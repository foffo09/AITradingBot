"""Same-origin desktop service. Broker access is explicitly opt-in and read-only."""
from __future__ import annotations

import math
import json
import tempfile
import os
from pathlib import Path
import secrets
import platform
import sqlite3
import threading
import time
from contextlib import contextmanager
from uuid import UUID
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.backtesting.walk_forward import walk_forward_evaluate
from src.broker.alpaca_client import AlpacaClient
from src.broker.mt5_readonly import MT5ReadError
from src.broker.mt5_process import MT5Process
from src.trading.offline_executor import OfflineExecutor, OfflineExecutionError
from src.data.instruments import INSTRUMENTS
from src.data.market_data import generate_demo_prices
from src.simulation.ledger import SimulationLedger, IdempotencyConflictError
from src.strategy.moving_average import MovingAverageStrategy
from src.strategy.trend import EMACrossoverStrategy
from src.strategy.engine import SignalProposal

from src.api.schemas import (
    Context, LocalContext, Interval, ErrorResponse, HealthResponse, IdentityResponse,
    ShutdownResponse, StateResponse, InstrumentsResponse, MarketResponse,
    TradeResponse, BacktestResponse, ProposalResponse, Preferences, PreferencesResponse,
    WalkForwardResponse, SystemResponse, WatchlistBody, WatchlistResponse, PendingTradeResponse,
    Mt5DiagnosticsResponse,
)
Positive = Annotated[float, Field(gt=0, le=1e12, strict=True, allow_inf_nan=False)]
COOKIE = 'aitradingbot_session'


class AccountInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: LocalContext
    initial_cash: Positive


class TradeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: LocalContext
    symbol: str
    side: Literal['buy', 'sell']
    idempotency_key: UUID
    quantity: Positive


class AutomationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: LocalContext
    command: Literal['start', 'pause', 'stop', 'cycle']
    request_id: UUID


class BacktestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: Context
    symbol: str
    short_window: Annotated[int, Field(ge=1, le=199, strict=True)] = 10
    long_window: Annotated[int, Field(ge=2, le=199, strict=True)] = 30


SERVICE_VERSION = '0.1.0'
# Same candidate grid the retired Streamlit dashboard used; selection happens on training slices only.
WALK_FORWARD_CANDIDATES = ({'short_window': 2, 'long_window': 4}, {'short_window': 3, 'long_window': 6}, {'short_window': 5, 'long_window': 10})
WALK_FORWARD_MIN_BARS = max(c['long_window'] for c in WALK_FORWARD_CANDIDATES) + 2
DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'SPY']
# Broker reads can take tens of seconds. Requests queued behind one would hold every worker
# thread of the shared pool and stall Demo too, so they wait briefly and then answer 503 busy.
BROKER_LOCK_WAIT_SECONDS = 2.0


class WalkForwardInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: Context
    symbol: str
    training_bars: Annotated[int, Field(ge=WALK_FORWARD_MIN_BARS, le=5000, strict=True)] | None = None
    test_bars: Annotated[int, Field(ge=WALK_FORWARD_MIN_BARS, le=5000, strict=True)] | None = None


def _symbol(symbol: str) -> str:
    if symbol not in INSTRUMENTS:
        raise HTTPException(422, 'Unknown instrument.')
    return symbol



def _indicators(data, currency):
    """Chart diagnostics reuse the causal strategy calculations, not UI formulas."""
    sma = MovingAverageStrategy().generate_signals(data)
    ema = EMACrossoverStrategy().generate_signals(data)
    result = []
    for identity, column, values, window, method in (
        ('sma10', 'short_ma', sma, 10, 'SMA'), ('sma30', 'long_ma', sma, 30, 'SMA'),
        ('ema9', 'short_ma', ema, 9, 'EMA'), ('ema21', 'long_ma', ema, 21, 'EMA'),
        ('ema50', 'ema50', ema, 50, 'EMA'), ('rsi14', 'rsi14', ema, 14, 'Wilder EWM'),
    ):
        result.append(dict(id=identity, label=identity.upper(), pane='rsi' if identity == 'rsi14' else 'price',
            unit='index' if identity == 'rsi14' else currency, method=method, parameters={'window': window},
            points=[{'time': int(pd.Timestamp(timestamp).timestamp()), 'value': float(value) if pd.notna(value) and math.isfinite(value) else None}
                for timestamp, value in zip(data['timestamp'], values[column])]))
    return result


def create_local_app(*, data_dir: Path, port: int, ui_dir: Path | None = None) -> FastAPI:
    if not 1 <= port <= 65535:
        raise ValueError('The bound loopback port is required.')
    root = Path(data_dir).expanduser().resolve()
    if not Path(data_dir).is_absolute():
        raise ValueError('An absolute application data directory is required.')
    # Service-owned filenames never target legacy project or personal ledger paths.
    paths = {context: root / f'local-v1-{context}.sqlite3' for context in ('demo', 'simulation')}
    for path in paths.values():
        if path.is_symlink() or (path.exists() and path.stat().st_nlink > 1):
            raise ValueError('Application database aliases are not allowed.')
    token = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{port}'
    host = f'127.0.0.1:{port}'
    # One lock per context: a slow Paper/MT5 network read must not block the local Demo/Simulation ledgers.
    locks = {context: threading.RLock() for context in ('demo', 'simulation', 'paper', 'mt5')}
    preferences_lock = threading.Lock()

    @contextmanager
    def context_lock(context):
        lock = locks[context]
        if context in ('paper', 'mt5'):
            if not lock.acquire(timeout=BROKER_LOCK_WAIT_SECONDS):
                raise HTTPException(503, 'Broker read already in progress; retry shortly. No cached or fallback values.')
        else:
            lock.acquire()
        try:
            yield
        finally:
            lock.release()
    paper = None
    mt5 = MT5Process()
    controls = {context: OfflineExecutor(root, context) for context in ('demo', 'simulation', 'paper', 'mt5')}
    settings = AppSettings(trading_mode='demo', paper_trading_enabled=False)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None,
        responses={code: {'model': ErrorResponse} for code in (401, 403, 409, 422, 503)})

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        if request.headers.get('host') != host:
            return JSONResponse({'detail': 'Invalid local Host.'}, 403)
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return JSONResponse({'detail': 'Invalid local Origin.'}, 403)
        path = request.url.path
        if path.startswith('/api/'):
            bootstrap = path == '/api/v1/session'
            if bootstrap and supplied_origin is None and not (
                request.headers.get('sec-fetch-site') == 'same-origin'
                and request.headers.get('x-local-request') == '1'
            ):
                return JSONResponse({'detail': 'Same-origin session bootstrap required.'}, 403)
            if path not in {'/api/v1/health', '/api/v1/identity', '/api/v1/session'}:
                cookie = request.cookies.get(COOKIE, '')
                if not secrets.compare_digest(cookie, token):
                    return JSONResponse({'detail': 'Local session required.'}, 401)
            if request.method not in {'GET', 'HEAD'} and (
                supplied_origin != origin or request.headers.get('x-local-request') != '1'
            ):
                return JSONResponse({'detail': 'Explicit same-origin request required.'}, 403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': 'Invalid request parameters.'}, status_code=422)

    @app.exception_handler(ResponseValidationError)
    async def invalid_output(request, exc):
        # Validation errors may contain provider/account data: never echo or log them.
        return JSONResponse({'detail': 'Local response could not be verified; no state was inferred.'}, status_code=503)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse({'detail': 'Local storage unavailable; no account state was inferred.'}, status_code=503)

    preferences_path = root / 'local-v1-ui-preferences.json'
    watchlist_path = root / 'local-v1-watchlist.json'

    def check_alias(path, detail):
        if path.is_symlink() or (path.exists() and path.stat().st_nlink > 1):
            raise HTTPException(409, detail)

    def check_preferences_path():
        check_alias(preferences_path, 'UI preference aliases are not allowed.')

    def read_small_json(path):
        with path.open('rb') as file:
            raw = file.read(4097)
        if len(raw) > 4096:
            raise ValueError('Oversized local file')
        return json.loads(raw.decode('utf-8'))

    def write_json_atomically(path, data, prefix, check):
        check()
        root.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=root, prefix=prefix, suffix='.tmp')
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            check()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @app.get('/api/v1/preferences', response_model=PreferencesResponse)
    def get_preferences():
        with preferences_lock:
            check_preferences_path()
            stored = preferences_path.exists()
            if not stored:
                values = Preferences(theme='light', density='comfortable', analysis_width=68)
            else:
                try:
                    values = Preferences.model_validate(read_small_json(preferences_path))
                except (ValueError, RecursionError):
                    raise HTTPException(503, 'UI preferences unavailable; stored values were not reset.') from None
            return {'api_version': '1', 'preferences': values, 'stored': stored}

    @app.post('/api/v1/preferences', response_model=PreferencesResponse)
    def save_preferences(body: Preferences):
        with preferences_lock:
            write_json_atomically(preferences_path, body.model_dump(), 'ui-preferences-', check_preferences_path)
            return {'api_version': '1', 'preferences': body, 'stored': True}

    def check_watchlist_path():
        check_alias(watchlist_path, 'Watchlist aliases are not allowed.')

    def valid_watchlist(symbols):
        if len(set(symbols)) != len(symbols) or any(symbol not in INSTRUMENTS for symbol in symbols):
            raise HTTPException(422, 'Watchlist symbols must be unique known instruments.')
        return symbols

    @app.get('/api/v1/watchlist', response_model=WatchlistResponse)
    def get_watchlist():
        with preferences_lock:
            check_watchlist_path()
            if not watchlist_path.exists():
                return {'api_version': '1', 'symbols': DEFAULT_WATCHLIST, 'stored': False}
            try:
                symbols = WatchlistBody.model_validate(read_small_json(watchlist_path)).symbols
                valid_watchlist(symbols)
            except (ValueError, RecursionError, HTTPException):
                raise HTTPException(503, 'Watchlist unavailable; stored values were not reset.') from None
            return {'api_version': '1', 'symbols': symbols, 'stored': True}

    @app.post('/api/v1/watchlist', response_model=WatchlistResponse)
    def save_watchlist(body: WatchlistBody):
        with preferences_lock:
            symbols = valid_watchlist(body.symbols)
            write_json_atomically(watchlist_path, {'symbols': symbols}, 'watchlist-', check_watchlist_path)
            return {'api_version': '1', 'symbols': symbols, 'stored': True}

    @app.get('/api/v1/health', response_model=HealthResponse)
    def health():
        return {'api_version': '1', 'status': 'ready'}

    @app.get('/api/v1/session', response_model=HealthResponse)
    def session(response: Response):
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/api/v1')
        return health()

    @app.get('/api/v1/identity', response_model=IdentityResponse)
    def identity():
        return {'pid': os.getpid(), 'instance_id': app.state.instance_id}

    @app.post('/api/v1/shutdown', response_model=ShutdownResponse)
    def shutdown():
        callback = getattr(app.state, 'request_shutdown', None)
        if callback is None:
            raise HTTPException(409, 'Shutdown callback unavailable.')
        callback()
        return {'api_version': '1', 'status': 'stopping'}

    app.state.instance_id = secrets.token_hex(16)

    def ledger(context):
        path = paths[context]
        if path.is_symlink() or (path.exists() and path.stat().st_nlink > 1):
            raise HTTPException(409, 'Application database aliases are not allowed.')
        return SimulationLedger(path)

    def state(context):
        result = {
            'api_version': '1', 'context': context,
            'connection': {'status': 'disconnected', 'reason': 'Explicit connection required.'},
            'account': None, 'positions': [], 'orders': [], 'trades': [],
            'automation': controls[context].status(),
        }
        if context in paths:
            result['connection'] = {'status': 'local', 'reason': 'Local ledger; synthetic prices, USD.'}
            if paths[context].exists():
                local = ledger(context)
                account = local.account()
                if account is not None:
                    summary = local.summary(settings.commission_bps, settings.slippage_bps, settings.spread_bps)
                    for metric, count in (('win_rate', 'closed_trades'), ('average_win', 'winning_trades'), ('average_loss', 'losing_trades'), ('profit_factor', 'losing_trades')):
                        if not summary[count]:
                            summary[metric] = None
                    summary = {key: None if isinstance(value, float) and not math.isfinite(value) else value for key, value in summary.items()}
                    public_account = {key: value for key, value in {**account, **summary}.items() if key not in {'initial_eur', 'eur_usd_rate', 'fx_source', 'fx_timestamp'}}
                    result.update(account={**public_account, 'equity': summary['current_capital'], 'currency': 'USD', 'source': 'local-simulation'}, positions=local.positions(), trades=local.history())
        elif context == 'paper' and paper is not None:
            try:
                snap = paper.get_paper_snapshot()
                account = snap['account']
                if hasattr(account, 'model_dump'):
                    account = account.model_dump(mode='json')
                public_account = {key: account.get(key) for key in ('cash', 'equity', 'buying_power', 'last_equity', 'currency')}
                result.update(connection={'status': 'connected', 'reason': 'Alpaca Paper read-only; snapshot is not atomic.'}, account={**public_account, 'source': 'Alpaca Paper', 'updated_at': snap['updated_at']}, positions=jsonable_encoder(snap['positions']), orders=jsonable_encoder(snap['orders']))
            except Exception:
                result['connection'] = {'status': 'unavailable', 'reason': 'Paper snapshot unavailable; reconnect explicitly.'}
        elif context == 'mt5':
            result.update(mt5.snapshot())
        return result

    @app.get('/api/v1/state', response_model=StateResponse)
    def get_state(context: Context = 'demo'):
        with context_lock(context):
            return state(context)

    @app.get('/api/v1/instruments', response_model=InstrumentsResponse)
    def instruments():
        return {'api_version': '1', 'instruments': [{'symbol': symbol, 'name': info['name']} for symbol, info in INSTRUMENTS.items()]}

    def frame(context, symbol, interval):
        if context in paths:
            data = generate_demo_prices(symbol, periods=200)
            # Demo timestamps follow the requested interval; values remain explicitly fictitious.
            frequency = {'1Min': 'min', '5Min': '5min', '15Min': '15min', '1Hour': 'h', '1Day': 'D', '1Week': '7D'}[interval]
            data['timestamp'] = pd.date_range(end=pd.Timestamp.now(tz='UTC').floor('s'), periods=len(data), freq=frequency)
            data.attrs.update(source='synthetic-demo', quality='synthetic', interval=interval, price_digits=2)
            return data
        if context == 'paper' and paper is not None:
            return paper.get_market_data(symbol, timeframe=interval, limit=1000)
        if context == 'mt5':
            return mt5.market_data(symbol, interval)
        raise ValueError('Explicit connection required.')

    @app.get('/api/v1/market', response_model=MarketResponse)
    def market(context: Context = 'demo', symbol: str = 'AAPL', interval: Interval = '1Day'):
        _symbol(symbol)
        result = {'api_version': '1', 'context': context, 'symbol': symbol, 'interval': interval, 'status': 'unavailable', 'reason': 'Market data unavailable; no fallback.', 'source': None, 'as_of': None, 'bars': [], 'quote': None, 'metadata': {}, 'indicators': []}
        with context_lock(context):
            try:
                data = frame(context, symbol, interval)
                if context == 'mt5':
                    result['quote'] = mt5.latest_quote(symbol)
                result.update(status='ready', reason='Synthetic data, not a broker price.' if context in paths else 'Historical bars; feed coverage and freshness require verification.', metadata=dict(data.attrs), source=data.attrs['source'], as_of=data.attrs.get('fetched_at', pd.Timestamp.now(tz='UTC').isoformat()), bars=[{'time': int(pd.Timestamp(row.timestamp).timestamp()), **{key: float(getattr(row, key)) for key in ('open', 'high', 'low', 'close', 'volume')}} for row in data.itertuples()])
                result['indicators'] = _indicators(data, 'N/D' if context == 'mt5' else 'USD')
                if context == 'paper':
                    try:
                        result['quote'] = paper.get_latest_quote(symbol)
                    except Exception:
                        result['reason'] = 'Historical bars available; current quote unavailable.'
            except MT5ReadError as exc:
                result.update(status=exc.status, reason=str(exc), quote=None, bars=[], metadata={})
            except Exception:
                result.update(status='unavailable', reason='Market data request failed; no fallback or cached values.', source=None, as_of=None, quote=None, bars=[], metadata={})
        return result

    @app.post('/api/v1/local-account', response_model=StateResponse)
    def local_account(body: AccountInput):
        with context_lock(body.context):
            local = ledger(body.context)
            if local.account() is not None:
                raise HTTPException(409, 'Local account already initialized; reset is not available.')
            try:
                # USD input represented using identity conversion, explicitly not an FX quote.
                local.initialize_account(initial_eur=body.initial_cash, eur_usd_rate=1, fx_source='Local USD identity (no FX conversion)', fx_timestamp=pd.Timestamp.now(tz='UTC').isoformat())
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Local account already initialized.') from None
            return state(body.context)

    # An uncertain virtual trade is remembered by the service, not only by the browser: localStorage is
    # per-origin and the dynamic port changes it on every launch, which allowed a duplicate after restart.
    # The record is removed only by the client (DELETE) after it has *received* a definitive outcome:
    # clearing it server-side on commit lost it whenever that response never reached the UI.
    def pending_path(context):
        return root / f'local-v1-{context}-pending-trade.json'

    def check_pending_path(context):
        check_alias(pending_path(context), 'Pending trade aliases are not allowed.')

    def read_pending(context):
        check_pending_path(context)
        if not pending_path(context).exists():
            return None
        try:
            return TradeInput.model_validate(read_small_json(pending_path(context))).model_dump(mode='json')
        except (ValueError, RecursionError):
            raise HTTPException(503, 'Pending virtual trade record unreadable; nothing was reset or executed.') from None

    def clear_pending(context, key):
        pending = read_pending(context)
        if pending is not None and pending['idempotency_key'] == key:
            pending_path(context).unlink()

    @app.get('/api/v1/pending-trade', response_model=PendingTradeResponse)
    def get_pending_trade(context: LocalContext):
        with context_lock(context):
            return {'api_version': '1', 'context': context, 'pending': read_pending(context)}

    @app.put('/api/v1/pending-trade', response_model=PendingTradeResponse)
    def put_pending_trade(body: TradeInput):
        _symbol(body.symbol)
        with context_lock(body.context):
            pending, record = read_pending(body.context), body.model_dump(mode='json')
            if pending is not None and pending != record:
                raise HTTPException(409, 'Another uncertain virtual trade is pending; retry it first.', headers={'X-Request-Outcome': 'rejected'})
            write_json_atomically(pending_path(body.context), record, f'{body.context}-pending-', lambda: check_pending_path(body.context))
            return {'api_version': '1', 'context': body.context, 'pending': record}

    @app.delete('/api/v1/pending-trade', response_model=PendingTradeResponse)
    def delete_pending_trade(context: LocalContext, idempotency_key: UUID):
        with context_lock(context):
            clear_pending(context, str(idempotency_key))  # only the record with this key; idempotent
            return {'api_version': '1', 'context': context, 'pending': read_pending(context)}

    @app.post('/api/v1/local-trades', response_model=TradeResponse)
    def local_trade(body: TradeInput):
        _symbol(body.symbol)
        with context_lock(body.context):
            key = str(body.idempotency_key)
            pending = read_pending(body.context)
            if pending is not None and pending['idempotency_key'] != key:
                raise HTTPException(409, 'An uncertain virtual trade is pending; retry it with the same request first.', headers={'X-Request-Outcome': 'rejected'})
            if pending is not None and pending != body.model_dump(mode='json'):
                raise HTTPException(409, 'Request identity already belongs to another operation; verify history.')
            # The pending record stays until the client confirms it received this outcome (DELETE).
            return execute_local_trade(body)

    def execute_local_trade(body):
        if not paths[body.context].exists() or ledger(body.context).account() is None:
            raise HTTPException(409, 'Initialize the local account explicitly first.', headers={'X-Request-Outcome': 'rejected'})
        local = ledger(body.context)
        data = frame(body.context, body.symbol, '1Day')
        kwargs = dict(symbol=body.symbol, quantity=body.quantity, market_price=float(data.iloc[-1]['close']), commission_bps=settings.commission_bps, slippage_bps=settings.slippage_bps, spread_bps=settings.spread_bps, reason='Explicit local simulated trade', data_timestamp=data.iloc[-1]['timestamp'].isoformat(), data_source='synthetic-demo', idempotency_key=str(body.idempotency_key))
        try:
            if body.side == 'buy':
                fill = local.buy(**kwargs, max_trade_fraction=settings.risk_max_trade_fraction, max_exposure_fraction=settings.risk_max_exposure_fraction, daily_loss_limit_fraction=settings.daily_loss_limit_pct, max_positions=settings.max_positions)
            else:
                fill = local.sell(**kwargs)
        except IdempotencyConflictError:
            raise HTTPException(409, 'Request identity already belongs to another operation; verify history.') from None
        except ValueError:
            raise HTTPException(409, 'Simulated trade blocked by account, position or risk limits.', headers={'X-Request-Outcome': 'rejected'}) from None
        return {**state(body.context), 'fill': fill}

    @app.post('/api/v1/backtest', response_model=BacktestResponse)
    def backtest(body: BacktestInput):
        _symbol(body.symbol)
        if body.short_window >= body.long_window:
            raise HTTPException(422, 'Short window must be smaller than long window.')
        with context_lock(body.context):
            try:
                data = frame(body.context, body.symbol, '1Day')
                result = BacktestEngine(settings).run(data, short_window=body.short_window, long_window=body.long_window, periods_per_year=365 if '/' in body.symbol else 252).to_dict()
            except Exception:
                raise HTTPException(409, 'Backtest unavailable for the requested data and parameters.') from None
        trades = result.pop('trade_history')
        curve = result.pop('equity_curve')
        return {'api_version': '1', 'context': body.context, 'symbol': body.symbol, 'source': data.attrs['source'], 'strategy': 'sma', 'parameters': {'short_window': body.short_window, 'long_window': body.long_window}, 'interval': '1Day', 'sample': {'start': data.iloc[0]['timestamp'].isoformat(), 'end': data.iloc[-1]['timestamp'].isoformat(), 'bars': len(data)}, 'validation': {'kind': 'single_sample', 'out_of_sample': None}, 'metrics': result, 'trades': trades, 'equity': [{'time': int(pd.Timestamp(timestamp).timestamp()), 'value': value} for timestamp, value in zip(data['timestamp'], curve)]}

    @app.get('/api/v1/proposal', response_model=ProposalResponse)
    def proposal(context: Context = 'demo', symbol: str = 'AAPL', interval: Interval = '1Day'):
        _symbol(symbol)
        fallback = {**SignalProposal(symbol=symbol, reason='Risk snapshot and current market data are not verified for execution.').to_dict(), 'api_version': '1', 'contract_version': '1', 'context': context, 'interval': interval}
        with context_lock(context):
            try:
                from src.strategy.service import evaluate_proposal
                data = frame(context, symbol, interval)
                quote = paper.get_latest_quote(symbol) if context == 'paper' and paper else None
                result = evaluate_proposal(settings=paper.settings if context == 'paper' and paper else settings, bars=data, quote=quote, source=data.attrs['source'], as_of=pd.Timestamp.now(tz='UTC'), symbol=symbol, interval=interval, risk_snapshot=None, context=context)
                return {**fallback, **result, 'api_version': '1', 'context': context, 'symbol': symbol, 'interval': interval}
            except ImportError:
                fallback['reason'] = 'Strategy service unavailable; no proposal can be verified.'
            except Exception:
                fallback['reason'] = 'Current market data or risk snapshot unavailable; no proposal can be verified.'
        return fallback

    @app.post('/api/v1/automation', response_model=StateResponse)
    def automation(body: AutomationInput):
        with context_lock(body.context):
            try:
                controls[body.context].command(body.command, str(body.request_id),
                    evaluate=lambda: proposal(body.context, 'AAPL', '1Day'))
            except OfflineExecutionError:
                raise HTTPException(409, 'Dry-run ownership or transition could not be verified; no retry was performed.') from None
            return state(body.context)

    started = time.time()

    @app.get('/api/v1/system', response_model=SystemResponse)
    def system():
        contexts = {}
        for context, lock in locks.items():
            # Never wait behind a slow broker read: a held context lock is reported as busy.
            if not lock.acquire(blocking=False):
                contexts[context] = {'connection': 'busy', 'ledger': 'not_applicable', 'automation': 'N/D'}
                continue
            try:
                if context in paths:
                    connection, ledger_state = 'local', 'present' if paths[context].exists() else 'absent'
                elif context == 'paper':
                    connection, ledger_state = 'connected' if paper is not None else 'disconnected', 'not_applicable'
                else:
                    connection, ledger_state = mt5.state, 'not_applicable'
                contexts[context] = {'connection': connection, 'ledger': ledger_state, 'automation': str(controls[context].status().get('state', 'N/D'))}
            finally:
                lock.release()
        return {'api_version': '1', 'status': 'ready', 'service_version': SERVICE_VERSION,
                'python': platform.python_version(), 'platform': f'{platform.system()} {platform.machine()}',
                'started_at': pd.Timestamp(started, unit='s', tz='UTC').isoformat(),
                'uptime_seconds': round(time.time() - started, 1), 'order_submission': 'disabled', 'contexts': contexts}

    @app.post('/api/v1/walk-forward', response_model=WalkForwardResponse)
    def walk_forward(body: WalkForwardInput):
        _symbol(body.symbol)
        with context_lock(body.context):
            try:
                data = frame(body.context, body.symbol, '1Day').reset_index(drop=True)
            except Exception:
                raise HTTPException(409, 'Market data unavailable; walk-forward not run, no fallback.') from None
        rows = len(data)
        if rows < WALK_FORWARD_MIN_BARS * 2:
            raise HTTPException(409, f'Insufficient history: {WALK_FORWARD_MIN_BARS * 2} daily bars required, {rows} available.')
        training = body.training_bars or min(max(rows // 3, WALK_FORWARD_MIN_BARS), rows - WALK_FORWARD_MIN_BARS)
        test = body.test_bars or min(max(rows // 6, WALK_FORWARD_MIN_BARS), rows - training)
        if training + test > rows or test < WALK_FORWARD_MIN_BARS:
            raise HTTPException(422, f'Training ({training}) plus test ({test}) bars must fit the {rows} available daily bars, '
                                     f'with at least {WALK_FORWARD_MIN_BARS} bars each.')
        try:
            result = walk_forward_evaluate(data, engine=BacktestEngine(settings), parameter_candidates=WALK_FORWARD_CANDIDATES,
                training_bars=training, test_bars=test, data_source=data.attrs['source'],
                backtest_options={'periods_per_year': 365 if '/' in body.symbol else 252})
        except Exception:
            raise HTTPException(409, 'Walk-forward unavailable for the requested data and parameters.') from None
        stamp = lambda index: pd.Timestamp(data.iloc[index]['timestamp']).isoformat()
        window = lambda item: {'train_start': stamp(item.train_start), 'train_end': stamp(item.train_end - 1),
                               'test_start': stamp(item.test_start), 'test_end': stamp(item.test_end - 1)}
        def metrics(backtest):
            values = backtest.to_dict()
            values.pop('trade_history'); values.pop('equity_curve')
            return {key: None if isinstance(value, float) and not math.isfinite(value) else value for key, value in values.items()}
        return {'api_version': '1', 'context': body.context, 'symbol': body.symbol, 'source': result.data_source, 'strategy': 'sma',
                'interval': '1Day', 'sample': {'start': stamp(0), 'end': stamp(rows - 1), 'bars': rows},
                'candidates': list(WALK_FORWARD_CANDIDATES), 'selection_metric': result.selection_metric,
                'training_bars': result.training_bars, 'test_bars': result.test_bars, 'step_bars': result.step_bars,
                'folds': [{**window(fold), 'parameters': fold.selected_parameters, 'in_sample_return_pct': fold.in_sample_return_pct,
                           'in_sample_trades': fold.in_sample_trades, 'out_of_sample': metrics(fold.out_of_sample)} for fold in result.folds],
                'excluded': [{**window(item), 'reason': item.reason} for item in result.excluded_folds]}

    @app.post('/api/v1/connections/paper', response_model=StateResponse)
    def connect_paper():
        nonlocal paper
        with context_lock('paper'):
            paper = None
            key, secret = os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY')
            if not key or not secret:
                return {**state('paper'), 'connection': {'status': 'unavailable', 'reason': 'Paper credentials unavailable in process environment.'}}
            try:
                candidate = AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key=key, alpaca_secret_key=secret, paper_trading_enabled=False))
                # Harden the existing transport too; the desktop service cannot write to Paper.
                if getattr(candidate, 'client', None) is not None:
                    candidate.client._session.read_only = True
                if not candidate.verify_connection().get('connected'):
                    return {**state('paper'), 'connection': {'status': 'unavailable', 'reason': 'Paper account verification failed; no account values are published.'}}
                paper = candidate
            except Exception:
                return {**state('paper'), 'connection': {'status': 'unavailable', 'reason': 'Paper connection failed; no account values are published.'}}
            return state('paper')

    @app.get('/api/v1/diagnostics/mt5', response_model=Mt5DiagnosticsResponse)
    def mt5_diagnostics():
        # Phase, error type, MT5 code, worker interpreter and timings: no credentials, balances or account ids.
        with context_lock('mt5'):
            return {'api_version': '1', **mt5.diagnostics}

    @app.post('/api/v1/connections/mt5', response_model=StateResponse)
    def connect_mt5():
        with context_lock('mt5'):
            mt5.connect()
            return state('mt5')

    def close():
        try:
            mt5.close()
        finally:
            for control in controls.values():
                control.close()

    app.state.close = close
    if ui_dir is not None:
        ui = Path(ui_dir).resolve(strict=True)
        if not (ui / 'index.html').is_file():
            raise ValueError('UI directory must contain index.html.')
        app.mount('/', StaticFiles(directory=ui, html=True), name='ui')
    return app
