from __future__ import annotations

import asyncio
import hashlib
import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from urllib.parse import urlparse

import requests

from config.hyperliquid_testnet import TestnetSettings
from src.broker.native import (AccountSnapshot, Book, BrokerRejected, BrokerUnavailable,
                               NativeFill, NativeOrder, NativePosition, NativeRequest, Rules)


TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


class TestnetSession(requests.Session):
    __test__ = False

    def request(self, method, url, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.hyperliquid-testnet.xyz":
            raise BrokerUnavailable("Non-testnet HTTP destination prohibited")
        kwargs["allow_redirects"] = False
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            raise BrokerUnavailable("Testnet HTTP redirects are prohibited")
        return response


class HyperliquidTestnetBroker:
    network = "testnet"

    def __init__(self, settings: TestnetSettings) -> None:
        if settings.network != "testnet":
            raise ValueError("Mainnet execution is prohibited")
        if not settings.private_key.get_secret_value() or not settings.account_address.get_secret_value():
            raise BrokerUnavailable("Testnet credentials are required in process environment")
        self.settings = settings
        self.scope = hashlib.sha256(("hyperliquid-testnet:" + settings.account_address.get_secret_value().lower()).encode()).hexdigest()
        self._exchange = None
        self._rules: dict[str, Rules] = {}
        self._lock = asyncio.Lock()

    def _connect(self) -> None:
        if self._exchange is None:
            try:
                from eth_account import Account
                from hyperliquid.exchange import Exchange
                key = self.settings.private_key.get_secret_value()
                address = self.settings.account_address.get_secret_value()
                if not key or not address:
                    raise ValueError("Credentials missing")
                self._exchange = Exchange(Account.from_key(key), TESTNET_URL, account_address=address, timeout=self.settings.timeout)
                for api in (self._exchange, self._exchange.info):
                    session = TestnetSession()
                    session.headers.update(api.session.headers)
                    api.session.close()
                    api.session = session
            except Exception:
                raise BrokerUnavailable("Cannot initialize testnet SDK; check environment credentials/connectivity") from None
        self._assert_testnet()

    def _assert_testnet(self) -> None:
        if (self.network != "testnet" or self._exchange.base_url != TESTNET_URL
                or self._exchange.info.base_url != TESTNET_URL):
            raise BrokerUnavailable("Mainnet or custom endpoint is prohibited")

    async def _call(self, operation, *args):
        # Serializing reads and writes also avoids SDK nonce races between concurrent actions.
        async with self._lock:
            try:
                await asyncio.to_thread(self._connect)
                self._assert_testnet()
                operation_task = asyncio.create_task(asyncio.to_thread(operation, *args))
                try:
                    return await asyncio.shield(operation_task)
                except asyncio.CancelledError:
                    # Do not release the engine's process lock while a signed write is still running.
                    try:
                        await operation_task
                    finally:
                        raise asyncio.CancelledError
            except (BrokerUnavailable, BrokerRejected):
                raise
            except Exception:
                raise BrokerUnavailable("Testnet request failed; reconcile before any further write") from None

    @staticmethod
    def parse_order(payload: dict, status: str) -> NativeOrder:
        normalized = status if status in {"open", "filled", "canceled", "rejected", "triggered"} else (
            "rejected" if status.endswith("Rejected") else "canceled" if status.endswith("Canceled") or status == "scheduledCancel" else "unknown")
        raw_quantity = payload.get("origSz") or payload["sz"]
        return NativeOrder(cloid=payload.get("cloid"), broker_id=payload["oid"], symbol=payload["coin"],
            side="buy" if payload["side"] == "B" else "sell", quantity=raw_quantity, remaining=payload["sz"],
            price=payload["limitPx"], reduce_only=payload.get("reduceOnly", False),
            trigger=payload.get("triggerPx") if payload.get("isTrigger") else None, status=normalized)

    async def order(self, cloid: str) -> NativeOrder | None:
        def read():
            from hyperliquid.utils.types import Cloid
            result = self._exchange.info.query_order_by_cloid(self.settings.account_address.get_secret_value(), Cloid.from_str(cloid))
            if result.get("status") == "unknownOid":
                return None
            return self.parse_order(result["order"]["order"], result["order"]["status"])
        return await self._call(read)

    async def snapshot(self, since_ms: int) -> AccountSnapshot:
        def read():
            info, address = self._exchange.info, self.settings.account_address.get_secret_value()
            fills, seen, start = [], set(), since_ms
            for _ in range(100):
                page = info.user_fills_by_time(address, start, aggregate_by_time=False)
                for row in page:
                    identity = f"{row['coin']}:{row['oid']}:{row['tid']}"
                    if identity not in seen:
                        seen.add(identity)
                        fills.append(NativeFill(id=identity, broker_id=row["oid"], symbol=row["coin"],
                            side="buy" if row["side"] == "B" else "sell", quantity=row["sz"], price=row["px"],
                            fee=row["fee"], realized_pnl=row["closedPnl"], timestamp_ms=row["time"]))
                if len(page) < 2000:
                    break
                next_start = max(row["time"] for row in page)
                if next_start <= start:
                    raise BrokerUnavailable("Fill pagination saturated; manual reconciliation required")
                start = next_start
            else:
                raise BrokerUnavailable("Fill pagination limit; manual reconciliation required")
            orders = [self.parse_order(row, "open") for row in info.frontend_open_orders(address)]
            account = info.user_state(address)
            summary = account["marginSummary"]
            positions = [NativePosition(symbol=p["position"]["coin"], quantity=p["position"]["szi"],
                entry=p["position"]["entryPx"], leverage=p["position"]["leverage"]["value"])
                for p in account["assetPositions"] if Decimal(p["position"]["szi"]) != 0]
            return AccountSnapshot(equity=summary["accountValue"], cash=summary["totalRawUsd"],
                available=account["withdrawable"], timestamp=time.time(), positions=positions, open_orders=orders, fills=fills)
        return await self._call(read)

    async def rules(self, symbol: str) -> Rules:
        def read():
            if symbol not in self._rules:
                for row in self._exchange.info.meta()["universe"]:
                    self._rules[row["name"]] = Rules(size_decimals=row["szDecimals"])
            if symbol not in self._rules:
                raise BrokerUnavailable("Unknown testnet perpetual")
            return self._rules[symbol]
        return await self._call(read)

    async def book(self, symbol: str) -> Book:
        def read():
            data = self._exchange.info.l2_snapshot(symbol)
            return Book(symbol=symbol, bid=data["levels"][0][0]["px"], ask=data["levels"][1][0]["px"], timestamp=data["time"] / 1000)
        return await self._call(read)

    @staticmethod
    def price(value: Decimal, rules: Rules, buy: bool) -> Decimal:
        step = max(Decimal(1).scaleb(value.adjusted() - 4), Decimal(1).scaleb(-(6 - rules.size_decimals)))
        return value.quantize(step, rounding=ROUND_CEILING if buy else ROUND_FLOOR)

    @staticmethod
    def _accepted(result: dict) -> None:
        if result.get("status") != "ok":
            raise BrokerRejected("Testnet rejected request")
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        if not statuses or any(isinstance(row, dict) and "error" in row for row in statuses):
            raise BrokerRejected("Testnet rejected request")

    async def submit(self, request: NativeRequest) -> None:
        request = NativeRequest.model_validate(request.model_dump())
        if (request.trigger is not None and not request.reduce_only) or (request.side == "sell" and not request.reduce_only):
            raise ValueError("Only long entries and reduce-only protection/exits are supported")
        rules = await self.rules(request.symbol)
        if rules.quantity(request.quantity) != request.quantity:
            raise ValueError("Quantity violates testnet precision")
        def write():
            from hyperliquid.utils.types import Cloid
            if not request.reduce_only:
                result = self._exchange.update_leverage(1, request.symbol, is_cross=False)
                if result.get("status") != "ok":
                    raise BrokerRejected("Cannot enforce isolated 1x leverage")
            buy = request.side == "buy"
            kind = ({"trigger": {"triggerPx": float(self.price(request.trigger, rules, not buy)), "isMarket": True, "tpsl": "sl"}}
                    if request.trigger else {"limit": {"tif": "Ioc"}})
            self._accepted(self._exchange.order(request.symbol, buy, float(request.quantity), float(self.price(request.price, rules, buy)),
                                               kind, reduce_only=request.reduce_only, cloid=Cloid.from_str(request.cloid)))
        await self._call(write)

    async def cancel(self, order: NativeOrder) -> None:
        def write():
            if order.broker_id is None:
                raise BrokerUnavailable("Cannot cancel an order without broker identity")
            result = self._exchange.cancel(order.symbol, order.broker_id)
            self._accepted(result)
        await self._call(write)

    async def candles(self, symbol: str):
        def read():
            now = int(time.time() * 1000)
            return self._exchange.info.candles_snapshot(symbol, "1m", now - 120 * 60000, now)
        return await self._call(read)

    async def close(self) -> None:
        if self._exchange is not None:
            self._exchange.session.close()
            self._exchange.info.session.close()
