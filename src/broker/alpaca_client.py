from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from config.settings import AppSettings
from src.utils.logging_config import configure_logging
from src.trading.paper_coordinator import PaperAccountCoordinator, PaperExecutionLease

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
    from alpaca.trading.enums import (
        AssetClass,
        AssetStatus,
        OrderSide,
        OrderType,
        QueryOrderStatus,
        TimeInForce,
    )
    from alpaca.trading.requests import GetAssetsRequest, GetOrdersRequest, MarketOrderRequest
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
    OrderSide = None
    OrderType = None
    TimeInForce = None
    QueryOrderStatus = None
    GetOrdersRequest = None
    MarketOrderRequest = None


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
        self._paper_client_is_paper = False
        self._verified_account = None

        if (
            self.settings.trading_mode == "paper"
            and TradingClient
            and self.settings.alpaca_api_key
            and self.settings.alpaca_secret_key
        ):
            try:
                self.client = TradingClient(
                    self.settings.alpaca_api_key,
                    self.settings.alpaca_secret_key,
                    paper=True,
                )
                self._paper_client_is_paper = True
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
    def paper_coordinator(self):
        if self.settings.paper_execution_scope != "single_host" or not self._paper_connection_verified:
            return None
        account = self._verified_account
        identity = account.get("id") if isinstance(account, dict) else getattr(account, "id", None)
        if not identity:
            return None
        return PaperAccountCoordinator(self.settings.paper_coordinator_directory, str(identity))

    @property
    def paper_client_configured(self) -> bool:
        return self.client is not None

    def verify_connection(self) -> dict[str, Any]:
        if (
            self.client is None
            or self.settings.trading_mode != "paper"
            or not self.settings.paper_trading_enabled
            or not self._paper_client_is_paper
        ):
            self._paper_connection_verified = False
            self._verified_account = None
            return {
                "status": "demo",
                "connected": False,
                "message": "A dedicated Alpaca Paper client is unavailable; no account connection is verified.",
                "mode": "demo",
            }
        try:
            account = self.client.get_account()
            account_status = getattr(account, "status", None)
            if isinstance(account, dict):
                account_status = account.get("status")
            account_status = str(getattr(account_status, "value", account_status) or "").lower()
            trading_blocked = (
                account.get("trading_blocked", False)
                if isinstance(account, dict)
                else getattr(account, "trading_blocked", False)
            )
            account_blocked = (
                account.get("account_blocked", False)
                if isinstance(account, dict)
                else getattr(account, "account_blocked", False)
            )
            if account_status != "active" or trading_blocked or account_blocked:
                raise BrokerConnectionError("Alpaca Paper account is not active and unblocked.")
            self._paper_connection_verified = True
            self._verified_account = account
            return {
                "status": "connected",
                "connected": True,
                "message": "Connected to Alpaca Paper Trading.",
                "mode": "paper",
            }
        except Exception:  # pragma: no cover - preserves safe runtime behavior
            self._paper_connection_verified = False
            self._verified_account = None
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
            self._paper_connection_verified = False
            self._verified_account = None
            raise BrokerConnectionError(f"Unable to fetch account state: {self.describe_error(exc)}") from exc

    def get_positions(self) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        try:
            return self.client.get_all_positions()
        except Exception as exc:  # pragma: no cover
            self._paper_connection_verified = False
            self._verified_account = None
            raise BrokerConnectionError(f"Unable to fetch positions: {self.describe_error(exc)}") from exc

    def get_orders(self) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        if GetOrdersRequest is None or QueryOrderStatus is None:
            raise BrokerConnectionError(
                "Alpaca order-query support is unavailable in the installed SDK."
            )
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500)
            orders = self.client.get_orders(filter=request)
            if len(orders) >= 500:
                raise BrokerConnectionError("Order history may be truncated; automation is blocked.")
            return orders
        except Exception as exc:  # pragma: no cover
            self._paper_connection_verified = False
            self._verified_account = None
            raise BrokerConnectionError(f"Unable to fetch orders: {self.describe_error(exc)}") from exc

    def get_paper_snapshot(self) -> dict[str, Any]:
        status = self.verify_connection()
        if not status["connected"]:
            raise BrokerConnectionError(status["message"])
        try:
            positions = self.get_positions()
            orders = self.get_orders()
        except BrokerConnectionError:
            self._paper_connection_verified = False
            self._verified_account = None
            raise
        account = self._verified_account
        if hasattr(account, "model_dump"):
            account = account.model_dump(mode="json")
        return {
            "account": account,
            "positions": positions,
            "orders": orders,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

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
        limit: int | None = 1000,
        start_time: datetime | None = None,
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
        if limit is not None and limit <= 0:
            raise ValueError("Market-data limit must be positive.")
        if start_time is None:
            start = datetime.now(timezone.utc) - timedelta(days=period_days[period])
        else:
            start = pd.Timestamp(start_time).to_pydatetime()
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            else:
                start = start.astimezone(timezone.utc)
            if start > datetime.now(timezone.utc):
                raise ValueError("Incremental market-data start cannot be in the future.")
        try:
            frame = self._timeframe(timeframe)
            interval_minutes = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 390, "1Week": 1950}[timeframe]
            market_days = period_days[period] if is_crypto else period_days[period] * 5 / 7
            hours_per_day = 24 if is_crypto else 6.5
            expected_bars = market_days * hours_per_day * 60 / interval_minutes
            request_limit = None
            if limit is not None:
                request_limit = (
                    min(10_000, max(1, limit))
                    if start_time is not None
                    else min(10_000, max(limit, int(expected_bars * 1.05)))
                )
            if is_crypto:
                response = client.get_crypto_bars(
                    CryptoBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=frame,
                        start=start,
                        limit=request_limit,
                    )
                )
                source = "Dati storici reali Alpaca Crypto"
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=frame,
                    start=start,
                    limit=request_limit,
                    feed=DataFeed.IEX,
                )
                response = client.get_stock_bars(request)
                source = "Dati storici reali Alpaca IEX (copertura venue parziale)"
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
            numeric_columns = ["open", "high", "low", "close", "volume"]
            bars[numeric_columns] = bars[numeric_columns].apply(
                pd.to_numeric, errors="coerce"
            )
            numeric_values = bars[numeric_columns].to_numpy(dtype=float)
            if (
                bars["timestamp"].isna().any()
                or bars["timestamp"].duplicated().any()
                or not all(math.isfinite(float(value)) for value in numeric_values.flat)
                or (bars[["open", "high", "low", "close"]] <= 0).any().any()
                or (bars["volume"] < 0).any()
                or (
                    bars["high"]
                    < bars[["open", "close", "low"]].max(axis=1)
                ).any()
                or (
                    bars["low"]
                    > bars[["open", "close", "high"]].min(axis=1)
                ).any()
            ):
                raise BrokerConnectionError(
                    "Market-data response contains invalid timestamps or OHLCV values."
                )
            bars["is_synthetic"] = False
            bars["data_quality"] = source
            bars.attrs["source"] = source
            bars.attrs["quality"] = "real"
            bars.attrs["interval"] = timeframe
            bars.attrs["bar_time_contract"] = "alpaca-start-v1"
            bars.attrs["bar_calendar"] = "24/7" if is_crypto else "NYSE"
            bars.attrs["session_scope"] = "continuous" if is_crypto else "all_sessions"
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
            if (
                not math.isfinite(bid)
                or not math.isfinite(ask)
                or bid <= 0
                or ask <= 0
                or bid > ask
            ):
                raise BrokerConnectionError(f"Alpaca returned no valid bid/ask for {symbol}.")
            midpoint = (bid + ask) / 2
            if pd.isna(timestamp):
                raise BrokerConnectionError(f"Alpaca returned no valid quote timestamp for {symbol}.")
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
                "fractionable": None,
                "min_order_size": None,
                "min_trade_increment": None,
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
                "fractionable": getattr(asset, "fractionable", None) if asset else None,
                "min_order_size": getattr(asset, "min_order_size", None) if asset else None,
                "min_trade_increment": (
                    getattr(asset, "min_trade_increment", None) if asset else None
                ),
                "message": "Active account asset." if asset else "Not present in the active paper-account asset list.",
            }
        except Exception:  # pragma: no cover - requires broker/API failure
            return {
                "visible": True,
                "data_available": "not tested",
                "paper_tradable": "unknown",
                "fractionable": None,
                "min_order_size": None,
                "min_trade_increment": None,
                "message": "Asset availability check failed; actual market-data access remains unverified.",
            }

    def submit_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if (
            self.client is None
            or self.settings.trading_mode != "paper"
            or not self.settings.paper_trading_enabled
            or not self._paper_client_is_paper
        ):
            raise PermissionError("Only the dedicated Alpaca Paper client may submit orders.")
        if not self._paper_connection_verified:
            raise PermissionError("Verify the active Alpaca Paper account before submitting an order.")
        lease = kwargs.pop("_execution_lease", None)
        coordinator = self.paper_coordinator
        if (coordinator is None or not isinstance(lease, PaperExecutionLease)
                or lease.directory != coordinator.directory.resolve() or lease.scope != coordinator.scope):
            raise PermissionError("Exclusive Paper account execution is required; direct submission is disabled.")
        if MarketOrderRequest is None or OrderSide is None or OrderType is None or TimeInForce is None:
            raise BrokerConnectionError("Alpaca market-order support is unavailable in the installed SDK.")
        if args:
            raise TypeError("Paper order submission accepts named order fields only.")

        symbol = str(kwargs.get("symbol", "")).strip().upper()
        side = str(kwargs.get("side", "")).strip().lower()
        client_order_id = str(kwargs.get("client_order_id", "")).strip()
        if not symbol or side not in {"buy", "sell"} or not client_order_id:
            raise ValueError("Symbol, valid side, and idempotent client order ID are required.")
        try:
            quantity = float(kwargs.get("quantity"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Order quantity must be a finite positive number.") from exc
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("Order quantity must be a finite positive number.")

        try:
            account = self.client.get_account()
        except Exception as exc:
            self._paper_connection_verified = False
            self._verified_account = None
            raise BrokerConnectionError(
                f"Unable to reverify the Alpaca Paper account before submission: {self.describe_error(exc)}"
            ) from exc
        account_status = getattr(account, "status", None)
        trading_blocked = getattr(account, "trading_blocked", False)
        account_blocked = getattr(account, "account_blocked", False)
        if isinstance(account, dict):
            account_status = account.get("status")
            trading_blocked = account.get("trading_blocked", False)
            account_blocked = account.get("account_blocked", False)
        account_status = str(getattr(account_status, "value", account_status) or "").lower()
        if account_status != "active" or trading_blocked or account_blocked:
            self._paper_connection_verified = False
            self._verified_account = None
            raise PermissionError("Active, unblocked Alpaca Paper account verification is required.")

        identity = account.get("id") if isinstance(account, dict) else getattr(account, "id", None)
        lease.authorize_submission(client_order_id, str(identity or ""))

        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC if "/" in symbol else TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        try:
            order = self.client.submit_order(request)
        except Exception as exc:
            self._paper_connection_verified = False
            self._verified_account = None
            raise BrokerConnectionError(
                f"Alpaca Paper order request failed: {self.describe_error(exc)}"
            ) from exc
        if hasattr(order, "model_dump"):
            return order.model_dump(mode="json")
        if isinstance(order, dict):
            return dict(order)
        raise BrokerConnectionError("Alpaca Paper returned an unrecognized order response.")

    def safe_account_summary(self) -> dict[str, Any]:
        account = self.get_account()
        if hasattr(account, "model_dump"):
            account = account.model_dump()
        if not isinstance(account, dict):
            account = {}
        return {
            "account_number": "configured" if account.get("account_number") else None,
            "cash": account.get("cash"),
            "equity": account.get("equity"),
            "buying_power": account.get("buying_power"),
            "last_equity": account.get("last_equity"),
            "status": str(account.get("status")) if account.get("status") is not None else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def describe_error(self, exc: Exception) -> str:
        message = str(exc)
        for secret in (self.settings.alpaca_api_key, self.settings.alpaca_secret_key):
            if secret:
                message = message.replace(secret, "<redacted>")
        return message
