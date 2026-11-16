"""Optional Windows terminal reader. No trading methods are exposed or called."""
from __future__ import annotations

import importlib
import math
from numbers import Integral, Real
import sys

import numpy as np
import pandas as pd

SOURCE = 'MetaTrader 5 terminal'


class MT5ReadError(ValueError):
    def __init__(self, reason: str, status: str = 'unavailable'):
        super().__init__(reason)
        self.status = status


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise MT5ReadError('Terminal returned a non-finite or unverifiable numeric value.')
    return float(value)


def _records(items, required_numbers):
    if not isinstance(items, (list, tuple)):
        raise MT5ReadError('Terminal collection unavailable.')
    result = []
    for item in items:
        record = item._asdict()
        for key in required_numbers:
            _number(record.get(key))
        for value in record.values():
            if isinstance(value, Real):
                _number(value)
        result.append(record)
    return result


def _demo_account(module, account):
    mode = getattr(account, 'trade_mode', None)
    expected = getattr(module, 'ACCOUNT_TRADE_MODE_DEMO', None)
    if (isinstance(mode, bool) or not isinstance(mode, Integral)
            or type(expected) is not int or mode != expected):
        raise MT5ReadError('Only a verified Demo terminal account is allowed; real or unknown accounts are blocked.')


class MT5ReadOnly:
    def __init__(self):
        self._module = None
        self._reason = 'Explicit terminal connection required.'

    def connect(self):
        if sys.platform != 'win32':
            self._reason = 'MetaTrader 5 is unsupported on this platform; Windows terminal required.'
            return
        self.close()
        try:
            module = importlib.import_module('MetaTrader5')
            if module.initialize(timeout=5000):
                self._module = module
                self._terminal()
                self._reason = 'Windows terminal read-only; account observation is not a broker timestamp.'
            else:
                module.shutdown()
                self._reason = 'Terminal initialization unavailable.'
        except Exception:
            self._reason = 'Verified Demo account or optional MetaTrader 5 terminal unavailable.'
            try:
                self.close()
            except Exception:
                self._reason = 'Demo verification failed and terminal cleanup was not confirmed.'

    # shortcut: native reads expose no timeout, isolate MT5 in a process before requiring a hard deadline.
    def _terminal(self):
        if self._module is None:
            raise MT5ReadError('Terminal not connected.')
        info = self._module.terminal_info()
        if info is None or getattr(info, 'connected', None) is not True:
            raise MT5ReadError('Terminal disconnected; cached values are not published.')
        _demo_account(self._module, self._module.account_info())
        return self._module

    def snapshot(self):
        if self._module is None:
            return {'connection': {'status': 'unsupported' if sys.platform != 'win32' else 'disconnected', 'reason': self._reason}, 'account': None, 'positions': [], 'orders': []}
        try:
            terminal = self._terminal()
            account = terminal.account_info()
            _demo_account(terminal, account)
            login = getattr(account, 'login', None)
            if isinstance(login, bool) or not isinstance(login, Integral) or login <= 0:
                raise MT5ReadError('Terminal account identity unavailable.')
            if not isinstance(account.server, str) or not account.server.strip():
                raise MT5ReadError('Terminal account server unavailable.')
            if not isinstance(account.currency, str) or not account.currency.strip():
                raise MT5ReadError('Terminal account currency unavailable.')
            cash, equity = _number(account.balance), _number(account.equity)
            positions = _records(terminal.positions_get(), ('volume', 'price_open', 'price_current', 'profit'))
            orders = _records(terminal.orders_get(), ('volume_initial', 'volume_current', 'price_open'))
            updated_at = pd.Timestamp.now(tz='UTC').isoformat()
            return {'connection': {'status': 'connected', 'reason': self._reason}, 'account': {'cash': cash, 'equity': equity, 'currency': account.currency, 'source': SOURCE, 'updated_at': updated_at}, 'positions': positions, 'orders': orders}
        except Exception:
            return {'connection': {'status': 'unavailable', 'reason': 'Terminal account or snapshot is not verifiable.'}, 'account': None, 'positions': [], 'orders': []}

    def latest_quote(self, symbol):
        try:
            tick = self._terminal().symbol_info_tick(symbol)
            if tick is None:
                raise MT5ReadError('Terminal quote unavailable; no historical-price fallback.')
            bid, ask = _number(tick.bid), _number(tick.ask)
            if bid <= 0 or ask <= 0 or bid > ask:
                raise MT5ReadError('Terminal bid/ask is invalid.')
            milliseconds = tick.time_msc
            if isinstance(milliseconds, bool) or not isinstance(milliseconds, Integral) or milliseconds <= 0:
                raise MT5ReadError('Terminal quote timestamp unavailable.')
            timestamp = pd.Timestamp(milliseconds, unit='ms', tz='UTC')
            age = (pd.Timestamp.now(tz='UTC') - timestamp).total_seconds()
            if not 0 <= age <= 120:
                raise MT5ReadError('Terminal quote is stale or in the future.', status='stale')
            return {'bid': bid, 'ask': ask, 'price': bid + (ask - bid) / 2, 'timestamp': timestamp.isoformat(), 'source': f'{SOURCE} tick'}
        except MT5ReadError:
            raise
        except Exception:
            raise MT5ReadError('Terminal quote unavailable; no historical-price fallback.') from None

    def market_data(self, symbol, interval):
        try:
            terminal = self._terminal()
            name = {'1Min': 'TIMEFRAME_M1', '5Min': 'TIMEFRAME_M5', '15Min': 'TIMEFRAME_M15', '1Hour': 'TIMEFRAME_H1', '1Day': 'TIMEFRAME_D1', '1Week': 'TIMEFRAME_W1'}[interval]
            rates = terminal.copy_rates_from_pos(symbol, getattr(terminal, name), 0, 200)
            if rates is None or not len(rates):
                raise MT5ReadError('Terminal bars unavailable.')
            data = pd.DataFrame(rates).rename(columns={'tick_volume': 'volume'})
            data['timestamp'] = pd.to_datetime(data['time'], unit='s', utc=True, errors='raise')
            timestamps = data['timestamp']
            values = data[['open', 'high', 'low', 'close', 'volume']]
            if any(pd.api.types.is_bool_dtype(dtype) for dtype in values.dtypes):
                raise MT5ReadError('Terminal bar prices and volume cannot be boolean.')
            if (
                timestamps.isna().any() or timestamps.duplicated().any()
                or not timestamps.is_monotonic_increasing
                or (timestamps > pd.Timestamp.now(tz='UTC')).any()
                or not np.isfinite(values.to_numpy(dtype=float)).all()
                or (data[['open', 'high', 'low', 'close']] <= 0).any().any()
                or (data['volume'] < 0).any()
                or (data['high'] < data[['open', 'close', 'low']].max(axis=1)).any()
                or (data['low'] > data[['open', 'close', 'high']].min(axis=1)).any()
            ):
                raise MT5ReadError('Terminal bars contain invalid OHLCV or timestamps.')
            data['is_synthetic'] = False
            data.attrs.update(source=f'{SOURCE} (broker bars; tick volume)', quality='real', volume_unit='ticks', interval=interval, fetched_at=pd.Timestamp.now(tz='UTC').isoformat())
            return data
        except MT5ReadError:
            raise
        except Exception:
            raise MT5ReadError('Terminal bars unavailable or malformed.') from None

    def close(self):
        module, self._module = self._module, None
        if module is not None:
            module.shutdown()
