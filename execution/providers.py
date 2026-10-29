from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from config.providers import ProviderSettings
from core.state import Market, ValidatedModel
from providers.common import ProviderUnavailable, error_code
from providers.crypto import CCXTData


class OrderIntent(ValidatedModel):
    client_order_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,32}$")
    venue: Literal["hyperliquid", "binance", "bybit", "alpaca", "ib"]
    market: Market
    symbol: str = Field(min_length=1, max_length=100)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)
    limit_price: float = Field(gt=0)
    quote_timestamp: float


class ExecutionProviders:
    """Prepared native transports. The dashboard uses its separate local-paper ledger."""

    def __init__(self, settings: ProviderSettings, journal: Path) -> None:
        self.settings, self.journal = settings, journal

    def capabilities(self) -> dict:
        s = self.settings
        return {
            "active_dashboard_execution": "local_paper",
            "native_orders_enabled": s.omega_enable_native_orders,
            "live_orders_enabled": False,
            "crypto_execution_network": s.crypto_execution_network,
            "alpaca_environment": "paper" if s.alpaca_paper else "live",
            "credentials_present": {
                "hyperliquid": bool(s.hyperliquid_private_key and s.hyperliquid_account_address),
                "binance": bool(s.binance_api_key and s.binance_secret_key),
                "bybit": bool(s.bybit_api_key and s.bybit_secret_key),
                "alpaca": bool(s.alpaca_api_key and s.alpaca_secret_key),
                "ib": bool(s.ib_enabled and s.ib_account),
            },
        }

    def check(self, intent: OrderIntent) -> None:
        s = self.settings
        if not s.omega_enable_native_orders:
            raise ProviderUnavailable("Native orders disabled; dashboard remains local paper")
        if not self.capabilities()["credentials_present"][intent.venue]:
            raise ProviderUnavailable("Credentials missing; use local paper")
        if not -5 <= time.time() - intent.quote_timestamp <= s.quote_max_age_seconds:
            raise ValueError("Order requires a fresh quote")
        live = ((intent.venue in {"hyperliquid", "binance", "bybit"} and s.crypto_execution_network == "mainnet")
                or (intent.venue == "alpaca" and not s.alpaca_paper)
                or (intent.venue == "ib" and not (s.secret("ib_account") or "").startswith("DU")))
        if live:
            raise ProviderUnavailable("Live native orders are prohibited; testnet/paper only")
        if intent.venue in {"hyperliquid", "binance", "bybit"} and intent.market != Market.CRYPTO_PERPS:
            raise ValueError("This crypto transport only supports perpetual contracts")
        if intent.venue == "alpaca" and intent.market not in {Market.OPTIONS_0DTE, Market.BIOTECH_CATALYST}:
            raise ValueError("Alpaca transport does not support futures or on-chain swaps")
        if intent.market in {Market.OPTIONS_0DTE, Market.COMMODITIES_FUT} and not intent.quantity.is_integer():
            raise ValueError("Contract quantity must be an integer")

    def reserve(self, intent: OrderIntent) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.journal) as db:
            db.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, venue TEXT, symbol TEXT, status TEXT, broker_id TEXT)")
            try:
                db.execute("INSERT INTO orders VALUES (?,?,?,?,?)", (intent.client_order_id, intent.venue, intent.symbol, "submitting", None))
            except sqlite3.IntegrityError:
                raise ProviderUnavailable("Request already journaled; reconcile at venue before retrying") from None

    async def submit(self, intent: OrderIntent):
        self.check(intent)
        self.reserve(intent)
        try:
            if intent.venue in {"binance", "bybit"}:
                exchange = CCXTData(intent.venue, self.settings).client(execution=True)
                try:
                    await exchange.load_markets()
                    contract = exchange.market(intent.symbol)
                    if not contract.get("swap"):
                        raise ValueError("A perpetual contract is required")
                    amount = float(exchange.amount_to_precision(intent.symbol, intent.quantity))
                    if amount <= 0 or abs(amount - intent.quantity) > 1e-12:
                        raise ValueError("Quantity does not match venue precision")
                    result = await exchange.create_order(intent.symbol, "limit", intent.side, amount, intent.limit_price,
                                                         {"clientOrderId": intent.client_order_id})
                finally:
                    await exchange.close()
            elif intent.venue == "hyperliquid":
                result = await asyncio.to_thread(self.hyperliquid_order, intent)
            elif intent.venue == "alpaca":
                result = await asyncio.to_thread(self.alpaca_order, intent)
            else:
                result = await self.ib_order(intent)
        except Exception as exc:
            # A write timeout is ambiguous. The persistent reservation prevents automatic duplicates.
            raise ProviderUnavailable(f"Native request requires reconciliation: {error_code(exc)}") from None
        with sqlite3.connect(self.journal) as db:
            broker_id = str(result.get("id", result.get("orderId", ""))) if isinstance(result, dict) else str(getattr(result, "id", ""))
            db.execute("UPDATE orders SET status=?, broker_id=? WHERE id=?", ("submitted", broker_id, intent.client_order_id))
        return result

    def hyperliquid_order(self, intent: OrderIntent):
        raise ProviderUnavailable("Legacy Hyperliquid writes disabled; use the reconciled testnet engine")

    def alpaca_order(self, intent: OrderIntent):
        if not self.settings.alpaca_paper:
            raise ProviderUnavailable("Live native orders are prohibited; paper only")
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest
        s = self.settings
        client = TradingClient(s.secret("alpaca_api_key"), s.secret("alpaca_secret_key"), paper=s.alpaca_paper)
        account = client.get_account()
        if str(account.status) not in {"ACTIVE", "AccountStatus.ACTIVE"} or account.trading_blocked:
            raise ProviderUnavailable("Alpaca account not active")
        if intent.market == Market.BIOTECH_CATALYST and not client.get_asset(intent.symbol).tradable:
            raise ProviderUnavailable("Asset not tradable")
        return client.submit_order(LimitOrderRequest(symbol=intent.symbol, qty=intent.quantity,
            side=OrderSide.BUY if intent.side == "buy" else OrderSide.SELL, time_in_force=TimeInForce.DAY,
            limit_price=intent.limit_price, client_order_id=intent.client_order_id))

    async def ib_order(self, intent: OrderIntent):
        if not (self.settings.secret("ib_account") or "").startswith("DU"):
            raise ProviderUnavailable("Live native orders are prohibited; paper account required")
        from ib_insync import IB, LimitOrder
        from providers.tradfi import IBData
        s, ib = self.settings, IB()
        kind = {Market.COMMODITIES_FUT: "future", Market.OPTIONS_0DTE: "option", Market.BIOTECH_CATALYST: "equity"}.get(intent.market)
        if kind is None:
            raise ValueError("Unsupported IB asset class")
        try:
            await ib.connectAsync(s.ib_host, s.ib_port, s.ib_client_id + 10, timeout=s.request_timeout_seconds, readonly=False)
            account = s.secret("ib_account")
            if account not in ib.managedAccounts():
                raise ProviderUnavailable("Configured IB account was not verified")
            contract = IBData(s, intent.symbol, kind).contract()
            if not await ib.qualifyContractsAsync(contract):
                raise ProviderUnavailable("IB contract not qualified")
            trade = ib.placeOrder(contract, LimitOrder(intent.side.upper(), intent.quantity, intent.limit_price,
                                                       account=account, orderRef=intent.client_order_id))
            await asyncio.wait_for(trade.statusEvent, timeout=s.request_timeout_seconds)
            return {"orderId": trade.order.orderId, "status": trade.orderStatus.status}
        finally:
            ib.disconnect()
