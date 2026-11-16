"""Same-origin desktop service. Broker access is explicitly opt-in and read-only."""
from __future__ import annotations

import math
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.broker.alpaca_client import AlpacaClient
from src.broker.mt5_readonly import MT5ReadOnly, MT5ReadError
from src.data.instruments import INSTRUMENTS
from src.data.market_data import generate_demo_prices
from src.simulation.ledger import SimulationLedger
from src.strategy.engine import SignalProposal

Context = Literal['demo', 'simulation', 'paper', 'mt5']
LocalContext = Literal['demo', 'simulation']
Interval = Literal['1Min', '5Min', '15Min', '1Hour', '1Day', '1Week']
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
    quantity: Positive


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
    mt5 = MT5ReadOnly()
    settings = AppSettings(trading_mode='demo', paper_trading_enabled=False)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

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

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse({'detail': 'Local storage unavailable; no account state was inferred.'}, status_code=503)

    @app.get('/api/v1/health')
    def health():
        return {'api_version': '1', 'status': 'ready'}

    @app.get('/api/v1/session')
    def session():
        response = JSONResponse(health())
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/api/v1')
        return response

    @app.get('/api/v1/identity')
    def identity():
        return {'pid': os.getpid(), 'instance_id': app.state.instance_id}

    @app.post('/api/v1/shutdown')
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
            'automation': {'state': 'stopped', 'reason': 'This service never submits broker orders.'},
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
                result.update(connection={'status': 'connected', 'reason': 'Alpaca Paper read-only; snapshot is not atomic.'}, account={**public_account, 'source': 'Alpaca Paper', 'updated_at': snap['updated_at']}, positions=snap['positions'], orders=snap['orders'])
            except Exception:
                result['connection'] = {'status': 'unavailable', 'reason': 'Paper snapshot unavailable; reconnect explicitly.'}
        elif context == 'mt5':
            result.update(mt5.snapshot())
        return result

    @app.get('/api/v1/state')
    def get_state(context: Context = 'demo'):
        with lock:
            return state(context)

    @app.get('/api/v1/instruments')
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

    @app.get('/api/v1/market')
    def market(context: Context = 'demo', symbol: str = 'AAPL', interval: Interval = '1Day'):
        _symbol(symbol)
        result = {'api_version': '1', 'context': context, 'symbol': symbol, 'interval': interval, 'status': 'unavailable', 'reason': 'Market data unavailable; no fallback.', 'source': None, 'as_of': None, 'bars': [], 'quote': None}
        with lock:
            try:
                data = frame(context, symbol, interval)
                if context == 'mt5':
                    result['quote'] = mt5.latest_quote(symbol)
                result.update(status='ready', reason='Synthetic data, not a broker price.' if context in paths else 'Historical bars; feed coverage and freshness require verification.', source=data.attrs['source'], as_of=data.attrs.get('fetched_at', pd.Timestamp.now(tz='UTC').isoformat()), bars=[{'time': int(pd.Timestamp(row.timestamp).timestamp()), **{key: float(getattr(row, key)) for key in ('open', 'high', 'low', 'close', 'volume')}} for row in data.itertuples()])
                if context == 'paper':
                    try:
                        result['quote'] = paper.get_latest_quote(symbol)
                    except Exception:
                        result['reason'] = 'Historical bars available; current quote unavailable.'
            except MT5ReadError as exc:
                result.update(status=exc.status, reason=str(exc), quote=None, bars=[])
            except Exception:
                result.update(status='unavailable', reason='Market data request failed; no fallback or cached values.', source=None, as_of=None, quote=None, bars=[])
        return result

    @app.post('/api/v1/local-account')
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

    @app.post('/api/v1/local-trades')
    def local_trade(body: TradeInput):
        _symbol(body.symbol)
        with lock:
            if not paths[body.context].exists() or ledger(body.context).account() is None:
                raise HTTPException(409, 'Initialize the local account explicitly first.')
            local = ledger(body.context)
            data = frame(body.context, body.symbol, '1Day')
            kwargs = dict(symbol=body.symbol, quantity=body.quantity, market_price=float(data.iloc[-1]['close']), commission_bps=settings.commission_bps, slippage_bps=settings.slippage_bps, spread_bps=settings.spread_bps, reason='Explicit local simulated trade', data_timestamp=data.iloc[-1]['timestamp'].isoformat(), data_source='synthetic-demo')
            try:
                if body.side == 'buy':
                    fill = local.buy(**kwargs, max_trade_fraction=settings.risk_max_trade_fraction, max_exposure_fraction=settings.risk_max_exposure_fraction, daily_loss_limit_fraction=settings.daily_loss_limit_pct, max_positions=settings.max_positions)
                else:
                    fill = local.sell(**kwargs)
            except ValueError:
                raise HTTPException(409, 'Simulated trade blocked by account, position or risk limits.') from None
            return {**state(body.context), 'fill': fill}

    @app.post('/api/v1/backtest')
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
        return {'api_version': '1', 'context': body.context, 'symbol': body.symbol, 'source': data.attrs['source'], 'metrics': result, 'trades': trades, 'equity': [{'time': int(pd.Timestamp(timestamp).timestamp()), 'value': value} for timestamp, value in zip(data['timestamp'], curve)]}

    @app.get('/api/v1/proposal')
    def proposal(context: Context = 'demo', symbol: str = 'AAPL', interval: Interval = '1Day'):
        _symbol(symbol)
        fallback = {**SignalProposal(symbol=symbol, reason='Risk snapshot and current market data are not verified for execution.').to_dict(), 'api_version': '1', 'contract_version': '1', 'context': context, 'interval': interval}
        with lock:
            try:
                from src.strategy.service import evaluate_proposal
                data = frame(context, symbol, interval)
                quote = paper.get_latest_quote(symbol) if context == 'paper' and paper else None
                result = evaluate_proposal(settings=paper.settings if context == 'paper' and paper else settings, bars=data, quote=quote, source=data.attrs['source'], as_of=pd.Timestamp.now(tz='UTC'), symbol=symbol, interval=interval, risk_snapshot=None, context=context)
                return {**result, 'api_version': '1', 'context': context}
            except ImportError:
                fallback['reason'] = 'Strategy service unavailable; no proposal can be verified.'
            except Exception:
                fallback['reason'] = 'Current market data or risk snapshot unavailable; no proposal can be verified.'
        return fallback

    @app.post('/api/v1/connections/paper')
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

    @app.post('/api/v1/connections/mt5')
    def connect_mt5():
        with lock:
            mt5.connect()
            return state('mt5')

    app.state.close = mt5.close
    if ui_dir is not None:
        ui = Path(ui_dir).resolve(strict=True)
        if not (ui / 'index.html').is_file():
            raise ValueError('UI directory must contain index.html.')
        app.mount('/', StaticFiles(directory=ui, html=True), name='ui')
    return app
