"""Optional Windows terminal reader. No trading methods are exposed or called."""
from __future__ import annotations

import importlib
import sys
import pandas as pd


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
            if module.initialize():
                self._module = module
                self._reason = 'Windows terminal read-only.'
            else:
                module.shutdown()
                self._reason = 'Terminal initialization unavailable.'
        except Exception:
            self._reason = 'Optional MetaTrader 5 module or terminal unavailable.'

    def snapshot(self):
        if self._module is None:
            return {'connection': {'status': 'unsupported' if sys.platform != 'win32' else 'disconnected', 'reason': self._reason}, 'account': None, 'positions': [], 'orders': []}
        try:
            account = self._module.account_info()
            positions = self._module.positions_get()
            orders = self._module.orders_get()
            if account is None or positions is None or orders is None:
                raise ValueError('Incomplete terminal snapshot')
            return {'connection': {'status': 'connected', 'reason': self._reason}, 'account': {'cash': account.balance, 'equity': account.equity, 'currency': account.currency, 'source': 'MetaTrader 5 terminal'}, 'positions': [item._asdict() for item in positions], 'orders': [item._asdict() for item in orders]}
        except Exception:
            return {'connection': {'status': 'unavailable', 'reason': 'Terminal snapshot unavailable.'}, 'account': None, 'positions': [], 'orders': []}

    def market_data(self, symbol, interval):
        if self._module is None:
            raise ValueError('Terminal not connected')
        name = {'1Min': 'TIMEFRAME_M1', '5Min': 'TIMEFRAME_M5', '15Min': 'TIMEFRAME_M15', '1Hour': 'TIMEFRAME_H1', '1Day': 'TIMEFRAME_D1', '1Week': 'TIMEFRAME_W1'}[interval]
        rates = self._module.copy_rates_from_pos(symbol, getattr(self._module, name), 0, 200)
        if rates is None or not len(rates):
            raise ValueError('Terminal bars unavailable')
        data = pd.DataFrame(rates).rename(columns={'tick_volume': 'volume'})
        data['timestamp'] = pd.to_datetime(data['time'], unit='s', utc=True)
        data.attrs.update(source='MetaTrader 5 terminal (broker bars; tick volume)', quality='real', interval=interval, fetched_at=pd.Timestamp.now(tz='UTC').isoformat())
        return data

    def close(self):
        if self._module is not None:
            self._module.shutdown()
            self._module = None
