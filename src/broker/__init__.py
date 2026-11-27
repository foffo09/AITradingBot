"""Broker adapter package.

AlpacaClient is loaded lazily (PEP 562): importing src.broker.mt5_process inside the MT5 spawn worker
must not import the Alpaca SDK and pandas, whose cold start delayed every MT5 connection.
"""

__all__ = ["AlpacaClient"]


def __getattr__(name):
    if name == "AlpacaClient":
        from .alpaca_client import AlpacaClient
        return AlpacaClient
    raise AttributeError(name)
