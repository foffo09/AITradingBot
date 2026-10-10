from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from config.settings import AppSettings
from src.utils.logging_config import configure_logging

try:
    from alpaca.data import CryptoHistoricalDataClient, StockHistoricalDataClient
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import (
        CryptoBarsRequest,
        CryptoLatestQuoteRequest,
        StockBarsRequest,
        StockLatestQuoteRequest,
    )
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest
except Exception:  # pragma: no cover - environment fallback
    CryptoHistoricalDataClient = None
    StockHistoricalDataClient = None
    StockBarsRequest = None
    CryptoBarsRequest = None
    CryptoLatestQuoteRequest = None
    StockLatestQuoteRequest = None
    TimeFrame = None
    TimeFrameUnit = None
    DataFeed = None
    TradingClient = None


class BrokerConnectionError(RuntimeError):
    """Raised when the broker cannot be reached or configured."""


class AlpacaClient:
    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings.from_env()
        self.logger = configure_logging(self.settings.log_level)
        self.client = None
        self.market_data_client = None
        self.crypto_data_client = None
        self._paper_connection_verified = False

        if TradingClient and self.settings.alpaca_api_key and self.settings.alpaca_secret_key:
            try:
                self.client = TradingClient(
                    self.settings.alpaca_api_key,
                    self.settings.alpaca_secret_key,
                    paper=True,
                )
            except Exception:  # pragma: no cover - defensive branch
                self.logger.warning("Failed to initialize the Alpaca Paper Trading client.")
                self.client = None

            try:
                if StockHistoricalDataClient:
                    self.market_data_client = StockHistoricalDataClient(
                        api_key=self.settings.alpaca_api_key,
                        secret_key=self.settings.alpaca_secret_key,
                    )
            except Exception:  # pragma: no cover - market-data availability is independent
                self.logger.warning("Failed to initialize the Alpaca stock-data client.")
                self.market_data_client = None

            try:
                if CryptoHistoricalDataClient:
                    self.crypto_data_client = CryptoHistoricalDataClient(
                        api_key=self.settings.alpaca_api_key,
                        secret_key=self.settings.alpaca_secret_key,
                    )
            except Exception:  # pragma: no cover - defensive branch
                self.logger.warning("Failed to initialize the Alpaca crypto-data client.")
                self.crypto_data_client = None

    def is_connected(self) -> bool:
        return self._paper_connection_verified

    @property
    def paper_client_configured(self) -> bool:
        return self.client is not None

    def verify_connection(self) -> dict[str, Any]:
        if self.client is None:
            self._paper_connection_verified = False
            return {
                "status": "demo",
                "connected": False,
                "message": "Paper credentials are unavailable; no Alpaca connection is verified. Demo data must be selected explicitly.",
                "mode": "demo",
            }
        try:
            self.client.get_account()
            self._paper_connection_verified = True
            return {
                "status": "connected",
                "connected": True,
                "message": "Connected to Alpaca Paper Trading.",
                "mode": "paper",
            }
        except Exception:  # pragma: no cover - preserves safe runtime behavior
            self._paper_connection_verified = False
            self.logger.warning("Alpaca Paper Trading account verification failed.")
            return {
                "status": "error",
                "connected": False,
                "message": "Paper account verification failed. Check local credentials and account status.",
                "mode": self.settings.trading_mode,
            }

    def get_account(self) -> dict[str, Any]:
        if self.client is None:
            return {
                "account_number": "demo",
                "mode": "demo",
                "cash": None,
                "equity": None,
                "currency": "USD",
                "status": "unavailable",
            }
        try:
            return self.client.get_account()
        except Exception as exc:  # pragma: no cover - defensive branch
            raise BrokerConnectionError(f"Unable to fetch account state: {self.describe_error(exc)}") from exc

    def get_positions(self) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        try:
            return self.client.get_all_positions()
        except Exception as exc:  # pragma: no cover
            raise BrokerConnectionError(f"Unable to fetch positions: {self.describe_error(exc)}") from exc

    def get_orders(self) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        try:
            return self.client.get_orders(status="all")
        except Exception as exc:  # pragma: no cover
            raise BrokerConnectionError(f"Unable to fetch orders: {self.describe_error(exc)}") from exc

    @staticmethod
    def _timeframe(interval: str) -> Any:
        frames = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
            "1Week": TimeFrame.Week,
        }
        try:
            return frames[interval]
        except KeyError as exc:
            raise ValueError(f"Unsupported interval: {interval}") from exc

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1Day",
        period: str = "3M",
        limit: int = 1000,
    ) -> pd.DataFrame:
        is_crypto = "/" in symbol
        client = self.crypto_data_client if is_crypto else self.market_data_client
        if client is None:
            raise BrokerConnectionError(
                "Alpaca credentials/data client are unavailable. Choose the explicitly labeled demo data option."
            )
        period_days = {"1M": 31, "3M": 93, "6M": 186, "1Y": 366, "5Y": 1827}
        if period not in period_days:
            raise ValueError(f"Unsupported chart period: {period}")
        start = datetime.now(timezone.utc) - timedelta(days=period_days[period])
        try:
            frame = self._timeframe(timeframe)
            interval_minutes = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 390, "1Week": 1950}[timeframe]
            market_days = period_days[period] if is_crypto else period_days[period] * 5 / 7
            hours_per_day = 24 if is_crypto else 6.5
            expected_bars = market_days * hours_per_day * 60 / interval_minutes
            request_limit = min(10_000, max(limit, int(expected_bars * 1.05)))
            if is_crypto:
                response = client.get_crypto_bars(
                    CryptoBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=frame,
                        start=start,
                        limit=request_limit,
                    )
                )
                source = "Alpaca Crypto data"
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=frame,
                    start=start,
                    limit=request_limit,
                    feed=DataFeed.IEX,
                )
                response = client.get_stock_bars(request)
                source = "Alpaca IEX (copertura venue parziale)"
            bars = response.df
            if bars is None or bars.empty:
                raise BrokerConnectionError(f"No bars were returned for {symbol} in the selected period.")
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.xs(symbol, level=0, drop_level=True)
            bars = bars.reset_index()
            if "timestamp" not in bars and "index" in bars:
                bars = bars.rename(columns={"index": "timestamp"})
            bars = bars.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            required = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required.issubset(bars.columns):
                raise BrokerConnectionError("Market-data response is missing required OHLCV fields.")
            bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
            bars["is_synthetic"] = False
            bars["data_quality"] = source
            bars.attrs["source"] = source
            bars.attrs["quality"] = "real"
            bars.attrs["fetched_at"] = datetime.now(timezone.utc).isoformat()
            bars.attrs["requested_start"] = start.isoformat()
            return bars.sort_values("timestamp").reset_index(drop=True)
        except BrokerConnectionError:
            raise
        except Exception as exc:  # pragma: no cover - requires broker/API failure
            self.logger.warning("Alpaca market-data request failed for %s.", symbol)
            raise BrokerConnectionError(
                f"Market data unavailable for {symbol}. Verify data entitlements and the selected period."
            ) from exc

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        is_crypto = "/" in symbol
        client = self.crypto_data_client if is_crypto else self.market_data_client
        if client is None:
            raise BrokerConnectionError("Alpaca quote client is unavailable.")
        try:
            if is_crypto:
                quotes = client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=symbol))
                source = "Alpaca Crypto latest quote"
            else:
                quotes = client.get_stock_latest_quote(
                    StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
                )
                source = "Alpaca IEX latest quote"
            quote = quotes.get(symbol)
            if quote is None:
                raise BrokerConnectionError(f"No latest quote was returned for {symbol}.")
            bid = float(quote.bid_price)
            ask = float(quote.ask_price)
            timestamp = pd.Timestamp(quote.timestamp)
            midpoint = (bid + ask) / 2 if bid > 0 and ask > 0 else None
            if midpoint is None:
                raise BrokerConnectionError(f"Alpaca returned no valid bid/ask for {symbol}.")
            return {
                "bid": bid,
                "ask": ask,
                "price": midpoint,
                "timestamp": timestamp.isoformat(),
                "source": source,
            }
        except BrokerConnectionError:
            raise
        except Exception as exc:  # pragma: no cover - requires broker/API failure
            self.logger.warning("Alpaca latest quote request failed for %s.", symbol)
            raise BrokerConnectionError(
                f"Latest quote unavailable for {symbol}; last historical bar may still be available."
            ) from exc

    def get_instrument_availability(self, symbol: str) -> dict[str, Any]:
        if self.client is None:
            return {
                "visible": True,
                "data_available": "unverified",
                "paper_tradable": "unverified",
                "message": "Paper credentials are not configured; availability cannot be verified.",
            }
        try:
            asset_class = AssetClass.CRYPTO if "/" in symbol else AssetClass.US_EQUITY
            assets = self.client.get_all_assets(
                GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=asset_class)
            )
            asset = next((item for item in assets if item.symbol == symbol), None)
            return {
                "visible": True,
                "data_available": "not tested",
                "paper_tradable": bool(getattr(asset, "tradable", False)) if asset else False,
                "message": "Active account asset." if asset else "Not present in the active paper-account asset list.",
            }
        except Exception:  # pragma: no cover - requires broker/API failure
            return {
                "visible": True,
                "data_available": "not tested",
                "paper_tradable": "unknown",
                "message": "Asset availability check failed; actual market-data access remains unverified.",
            }

    def submit_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.client is None:
            raise PermissionError("No Alpaca client available. This bot is in demo mode and cannot place live orders.")
        if not self.settings.paper_trading_enabled:
            raise PermissionError("Paper trading must be enabled before any order can be placed in paper mode.")
        raise PermissionError("This project never sends real orders. Simulated orders are handled by PaperTrader only.")

    def safe_account_summary(self) -> dict[str, Any]:
        account = self.get_account()
        return {
            "account_number": str(account.get("account_number", "demo")),
            "cash": str(account.get("cash", "100.00")),
            "equity": str(account.get("equity", "100.00")),
            "status": str(account.get("status", "demo")),
        }

    def describe_error(self, exc: Exception) -> str:
        message = str(exc)
        for secret in (self.settings.alpaca_api_key, self.settings.alpaca_secret_key):
            if secret:
                message = message.replace(secret, "<redacted>")
        return message
