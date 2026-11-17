"""Same-origin desktop service. Broker access is explicitly opt-in and read-only."""
from __future__ import annotations

import math
import json
import tempfile
import os
from pathlib import Path
import secrets
import sqlite3
import threading
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
    lock = threading.RLock()
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

    def check_preferences_path():
        if preferences_path.is_symlink() or (preferences_path.exists() and preferences_path.stat().st_nlink > 1):
            raise HTTPException(409, 'UI preference aliases are not allowed.')

    @app.get('/api/v1/preferences', response_model=PreferencesResponse)
    def get_preferences():
        with lock:
            check_preferences_path()
            stored = preferences_path.exists()
            if not stored:
                values = Preferences(theme='dark', density='comfortable', analysis_width=68)
            else:
                try:
                    with preferences_path.open('rb') as file:
                        raw = file.read(4097)
                    if len(raw) > 4096:
                        raise ValueError('Oversized preferences')
                    values = Preferences.model_validate(json.loads(raw.decode('utf-8')))
                except (ValueError, RecursionError):
                    raise HTTPException(503, 'UI preferences unavailable; stored values were not reset.') from None
            return {'api_version': '1', 'preferences': values, 'stored': stored}

    @app.post('/api/v1/preferences', response_model=PreferencesResponse)
    def save_preferences(body: Preferences):
        with lock:
            check_preferences_path()
            root.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(dir=root, prefix='ui-preferences-', suffix='.tmp')
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                    json.dump(body.model_dump(), file, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                check_preferences_path()
                os.replace(temporary, preferences_path)
            finally:
                temporary.unlink(missing_ok=True)
            return {'api_version': '1', 'preferences': body, 'stored': True}

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
        with lock:
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
            data.attrs.update(source='synthetic-demo', quality='synthetic', interval=interval)
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
        with lock:
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
        with lock:
            local = ledger(body.context)
            if local.account() is not None:
                raise HTTPException(409, 'Local account already initialized; reset is not available.')
            try:
                # USD input represented using identity conversion, explicitly not an FX quote.
                local.initialize_account(initial_eur=body.initial_cash, eur_usd_rate=1, fx_source='Local USD identity (no FX conversion)', fx_timestamp=pd.Timestamp.now(tz='UTC').isoformat())
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Local account already initialized.') from None
            return state(body.context)

    @app.post('/api/v1/local-trades', response_model=TradeResponse)
    def local_trade(body: TradeInput):
        _symbol(body.symbol)
        with lock:
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
        with lock:
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
        with lock:
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
        with lock:
            try:
                controls[body.context].command(body.command, str(body.request_id),
                    evaluate=lambda: proposal(body.context, 'AAPL', '1Day'))
            except OfflineExecutionError:
                raise HTTPException(409, 'Dry-run ownership or transition could not be verified; no retry was performed.') from None
            return state(body.context)

    @app.post('/api/v1/connections/paper', response_model=StateResponse)
    def connect_paper():
        nonlocal paper
        with lock:
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

    @app.post('/api/v1/connections/mt5', response_model=StateResponse)
    def connect_mt5():
        with lock:
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
