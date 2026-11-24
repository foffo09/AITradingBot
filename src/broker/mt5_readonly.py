"""Optional Windows terminal reader. No trading methods are exposed or called."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
import math
from numbers import Integral, Real
import subprocess
import sys
import time

# numpy/pandas are imported only where bars are parsed: the reader runs in a spawn worker whose
# start-up time is on the critical path of every connection (see docs/MT5_CONNECTION_FIX_REPORT.md).

SOURCE = 'MetaTrader 5 terminal'
INITIALIZE_TIMEOUT_MS = 5000
_TERMINAL_IMAGES = ('terminal64.exe', 'terminal.exe')


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


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _last_error(module):
    """MT5's own (code, description) for the last failure; the description holds no credentials."""
    try:
        code, message = module.last_error()
        return [int(code), str(message)[:120]]
    except Exception:
        return None


def _terminal_running():
    """True/False from the process list; None when it cannot be determined (then not enforced)."""
    try:
        listing = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None
    return any(f'"{image}"' in listing for image in _TERMINAL_IMAGES)


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
        """Connect read-only and report the outcome of every phase (status, phase, reason, MT5 code, time)."""
        started = time.monotonic()

        def outcome(status, phase, reason, mt5_error=None):
            self._reason = reason
            return {'status': status, 'phase': phase, 'reason': reason, 'mt5_error': mt5_error,
                    'elapsed_ms': round((time.monotonic() - started) * 1000)}

        if sys.platform != 'win32':
            return outcome('unsupported', 'platform', 'MetaTrader 5 is unsupported on this platform; Windows terminal required.')
        self.close()
        try:
            module = importlib.import_module('MetaTrader5')
        except Exception as error:
            return outcome('unavailable', 'import', f'MetaTrader5 package not importable by the service interpreter ({type(error).__name__}); '
                                                    'install packaging/backend/requirements-mt5.txt in the same environment.')
        # The app never launches the terminal: initialize() would start it inside the desktop app's job
        # object, and closing the app would then also close the user's terminal.
        if _terminal_running() is False:
            return outcome('unavailable', 'terminal_not_running', 'MetaTrader 5 terminal is not running: open it and sign in to a Demo account, then connect again.')
        phase = 'initialize'
        try:
            if not module.initialize(timeout=INITIALIZE_TIMEOUT_MS):
                error = _last_error(module)
                module.shutdown()
                detail = f' (MT5 {error[0]}: {error[1]})' if error else ''
                return outcome('unavailable', phase, f'Terminal initialization failed{detail}.', error)
            self._module = module
            phase = 'terminal_info'
            info = module.terminal_info()
            if info is None or getattr(info, 'connected', None) is not True:
                raise MT5ReadError('Terminal is not connected to its trade server.')
            phase = 'account'
            _demo_account(module, module.account_info())
        except Exception as error:
            reason = str(error) if isinstance(error, MT5ReadError) else f'{phase} failed ({type(error).__name__}).'
            mt5_error = _last_error(module)
            try:
                self.close()
            except Exception:
                reason += ' Terminal cleanup was not confirmed.'
            return outcome('unavailable', phase, reason, mt5_error)
        return outcome('connected', 'connected', 'Windows terminal read-only; account observation is not a broker timestamp.')

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
            # Optional fields stay None (N/D) when the terminal does not provide a finite value.
            def optional(name):
                value = getattr(account, name, None)
                return float(value) if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) else None
            details = {name: optional(name) for name in ('profit', 'margin', 'margin_free', 'margin_level')}
            return {'connection': {'status': 'connected', 'reason': self._reason},
                    'account': {'cash': cash, 'balance': cash, 'equity': equity, **details, 'currency': account.currency,
                                'server': account.server, 'source': SOURCE, 'updated_at': _now_iso()},
                    'positions': positions, 'orders': orders}
        except Exception:
            return {'connection': {'status': 'unavailable', 'reason': 'Terminal account or snapshot is not verifiable.'}, 'account': None, 'positions': [], 'orders': []}

    def latest_quote(self, symbol):
        import pandas as pd
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
        import numpy as np
        import pandas as pd
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
