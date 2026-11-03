from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from config.hyperliquid_testnet import TestnetRisk
from src.broker.native import (AccountSnapshot, Book, BrokerRejected, BrokerUnavailable,
                               NativeBroker, NativeOrder, NativeRequest)
from src.trading.native_store import NativeStore, TERMINAL


class NativeEngine:
    """Testnet-only long entries; exits and panic always reduce broker exposure."""

    def __init__(self, broker: NativeBroker, settings: TestnetRisk, journal: Path) -> None:
        if broker.network != "testnet" or settings.network != "testnet":
            raise ValueError("Mainnet execution is prohibited")
        self.broker = broker
        self.settings = TestnetRisk.model_validate({name: getattr(settings, name) for name in TestnetRisk.model_fields})
        self.store = NativeStore(journal, broker.scope)
        self.scope = broker.scope
        self.lock = asyncio.Lock()
        self.snapshot: AccountSnapshot | None = None
        self.reports: dict[str, NativeOrder | None] = {}

    def guard_network(self) -> None:
        if self.broker.network != "testnet" or self.broker.scope != self.scope:
            raise BrokerUnavailable("Broker network/account changed; execution prohibited")

    def cloid(self, purpose: str) -> str:
        return "0x" + hashlib.sha256((self.scope + ":testnet:" + purpose).encode()).hexdigest()[:32]

    def owned(self, order: NativeOrder) -> bool:
        return self.order_record(order) is not None

    def order_record(self, order: NativeOrder) -> dict | None:
        return next((row for row in self.store.orders() if row["cloid"] == order.cloid
                     or (order.broker_id is not None and row["broker_id"] == order.broker_id)), None)

    def unresolved(self, role: str | None = None) -> list[dict]:
        return [row for row in self.store.orders() if row["status"] not in TERMINAL and (role is None or row["role"] == role)]

    def pending_entry(self, symbol: str) -> bool:
        return any(NativeRequest.model_validate_json(row["request"]).symbol == symbol
                   for row in self.unresolved("entry"))

    async def sync(self) -> None:
        self.guard_network()
        reports = {}
        for row in self.unresolved():
            report = await self.broker.order(row["cloid"])
            if report is not None:
                request = NativeRequest.model_validate_json(row["request"])
                if (report.symbol != request.symbol or report.side != request.side
                        or report.reduce_only != request.reduce_only
                        or (report.quantity != request.quantity and not (request.reduce_only and report.quantity <= request.quantity))
                        or report.cloid not in {None, request.cloid}):
                    raise BrokerUnavailable("Broker order identity mismatch")
            reports[row["cloid"]] = report
        snapshot = AccountSnapshot.model_validate((await self.broker.snapshot(self.store.get("since_ms"))).model_dump())
        if not -5 <= time.time() - snapshot.timestamp <= 10:
            raise BrokerUnavailable("Stale broker account snapshot")
        self.store.record(snapshot, reports)
        self.snapshot, self.reports = snapshot, reports
        # Baseline belongs to the broker account, not to the configured order budget.
        today = datetime.now(timezone.utc).date().isoformat()
        baseline = Decimal(self.store.get("daily_equity", str(snapshot.equity)))
        if baseline > 0 and snapshot.equity <= baseline * Decimal("0.95"):
            self.store.latch_panic()
        if self.store.get("day") != today:
            self.store.set("day", today)
            self.store.set("daily_equity", str(snapshot.equity))
        if self.store.get("panic"):
            self.store.set("panic_complete", not snapshot.positions and not snapshot.open_orders and not self.unresolved() and not self.store.exits())

    async def fresh_book(self, symbol: str) -> Book:
        book = await self.broker.book(symbol)
        if book.symbol != symbol or book.bid > book.ask or not -5 <= time.time() - book.timestamp <= self.settings.quote_max_age:
            raise BrokerUnavailable("Fresh uncrossed testnet book required")
        return book

    async def place(self, purpose: str, role: str, request: NativeRequest) -> str:
        self.guard_network()
        if role == "entry" and self.store.get("panic"):
            raise BrokerUnavailable("Panic blocks entry submission")
        if self.store.find(request.cloid):
            return request.cloid
        # An existing broker cloid is adopted, never re-submitted (e.g. restored journal).
        existing = await self.broker.order(request.cloid)
        self.store.reserve(hashlib.sha256(purpose.encode()).hexdigest(), role, request)
        if existing is not None:
            self.store.status(request.cloid, "unknown")
            await self.sync()
            return request.cloid
        try:
            if role == "entry" and self.store.get("panic"):
                self.store.status(request.cloid, "rejected")
                raise BrokerRejected("Panic blocks entry submission")
            await self.broker.submit(request)
            self.store.status(request.cloid, "unknown")  # acknowledgement is not a fill
        except BrokerRejected:
            self.store.status(request.cloid, "rejected")
        except asyncio.CancelledError:
            self.store.status(request.cloid, "unknown")
            raise
        except Exception:
            self.store.status(request.cloid, "unknown")
        await self.sync()
        return request.cloid

    async def cancel_order(self, order: NativeOrder) -> None:
        self.guard_network()
        record = self.order_record(order)
        if record:
            self.store.status(record["cloid"], "cancel_pending")
        try:
            await self.broker.cancel(order)
        except BrokerUnavailable:
            # A fill may have raced with cancellation; only the next broker read decides.
            self.store.set("notice", "Cancellation requires broker reconciliation")
        await self.sync()

    def incomplete_fills(self) -> bool:
        return any(row["broker_id"] is not None and self.store.filled(row["broker_id"]) <
                   Decimal(self.store.get(f"expected:{row['broker_id']}", "0")) for row in self.store.orders())

    async def on_signal(self, signal_id: str, signal: int, signal_time: float) -> str | None:
        async with self.lock:
            if type(signal) is not int or signal not in {-1, 0, 1}:
                raise ValueError("Signal must be -1, 0 or 1")
            if not isinstance(signal_id, str) or not 1 <= len(signal_id) <= 200:
                raise ValueError("A stable bounded signal ID is required")
            await self.sync()
            purpose = "signal:" + signal_id
            identity = self.cloid(purpose)
            if self.store.find(identity):
                await self.protect()
                return identity
            if self.store.get("panic"):
                await self.drain()
                return None
            if signal == -1:
                self.store.exit_target(identity, self.settings.symbol, Decimal(0))
                await self.drain()
                return None
            if signal == 0:
                await self.protect()
                return None
            if (not -5 <= time.time() - signal_time <= 120 or self.store.get("locked_until", 0) > time.time()
                    or self.store.get("halted") or self.unresolved() or self.incomplete_fills()
                    or self.store.exits() or self.snapshot.positions or self.snapshot.open_orders):
                self.store.set("notice", "Entry blocked by risk/reconciliation gate")
                return None
            book = await self.fresh_book(self.settings.symbol)
            rules = await self.broker.rules(self.settings.symbol)
            limit = book.ask * Decimal("1.005")
            budget = min(self.settings.max_order_usd, self.snapshot.equity * self.settings.max_equity_fraction,
                         self.snapshot.available) / Decimal("1.01")
            quantity = rules.quantity(budget / limit)
            if quantity <= 0 or quantity * limit < rules.min_notional:
                self.store.set("notice", "Entry below broker minimum after risk sizing")
                return None
            request = NativeRequest(cloid=identity, symbol=self.settings.symbol, side="buy", quantity=quantity, price=limit)
            await self.place(purpose, "entry", request)
            await self.protect()
            return identity

    async def protect(self) -> None:
        if self.store.get("panic") or self.store.exits():
            await self.drain()
            return
        # IOC remainders/late open entries are canceled before sizing protection.
        for order in list(self.snapshot.open_orders):
            if not order.reduce_only and self.owned(order):
                await self.cancel_order(order)
        for position in list(self.snapshot.positions):
            if position.symbol != self.settings.symbol or position.quantity < 0 or position.leverage != 1:
                self.store.set("halted", "Unexpected position/leverage; dedicated long-only account required")
                continue
            stop = position.entry * (1 - self.settings.stop_fraction)
            book = await self.fresh_book(position.symbol)
            if book.bid <= stop:
                self.store.exit_target(self.cloid(f"stop-exit:{position.symbol}:{self.store.get('cycle:' + position.symbol)}"), position.symbol, Decimal(0))
                await self.drain()
                return
            candidates = [o for o in self.snapshot.open_orders if o.symbol == position.symbol and o.reduce_only
                          and o.side == "sell" and o.trigger is not None and self.owned(o)]
            if any(o.remaining >= position.quantity and stop <= o.trigger < position.entry for o in candidates):
                continue
            if any(row["role"] == "stop" and row["status"] == "unknown" for row in self.unresolved()):
                self.store.latch_panic()
                await self.drain()
                return
            purpose = f"stop:{position.symbol}:{self.store.get('cycle:' + position.symbol)}:{position.quantity}:{stop}"
            request = NativeRequest(cloid=self.cloid(purpose), symbol=position.symbol, side="sell", quantity=position.quantity,
                                    price=stop * Decimal("0.9"), reduce_only=True, trigger=stop)
            await self.place(purpose, "stop", request)
            row = self.store.find(request.cloid)
            if not any(p.symbol == position.symbol for p in self.snapshot.positions):
                continue
            if row["status"] != "open":
                self.store.latch_panic()
                self.store.set("halted", "Protective stop not confirmed; emergency flatten requested")
                await self.drain()
                return
        # No position may leave orphan reduce-only orders that affect a later entry.
        symbols = {p.symbol for p in self.snapshot.positions}
        for order in list(self.snapshot.open_orders):
            if order.symbol not in symbols and order.reduce_only and self.owned(order):
                await self.cancel_order(order)

    async def partial_exit(self, exit_id: str, fraction: Decimal = Decimal("0.5")) -> None:
        async with self.lock:
            if not fraction.is_finite() or not 0 < fraction <= 1:
                raise ValueError("Exit fraction must be in (0, 1]")
            await self.sync()
            position = next((p for p in self.snapshot.positions if p.symbol == self.settings.symbol), None)
            if position is None or position.quantity <= 0:
                return
            rules = await self.broker.rules(position.symbol)
            amount = rules.quantity(position.quantity * fraction)
            if amount <= 0:
                raise ValueError("Partial exit below quantity precision")
            identity = self.cloid("partial:" + exit_id)
            if any(target["symbol"] == position.symbol and target["id"] != identity for target in self.store.exits()):
                raise BrokerUnavailable("An existing exit target must be reconciled first")
            self.store.exit_target(identity, position.symbol, position.quantity - amount)
            await self.drain()
            if not self.store.exits():
                await self.protect()

    async def drain(self) -> None:
        panic = self.store.get("panic", False)
        if panic:
            self.store.set("panic_complete", False)
        for order in list(self.snapshot.open_orders):
            row = self.order_record(order)
            keep_stop = row and row["role"] == "stop" and any(p.symbol == order.symbol for p in self.snapshot.positions)
            if not keep_stop and (panic or self.owned(order)):
                await self.cancel_order(order)
        if any(not o.reduce_only for o in self.snapshot.open_orders):
            return
        if panic:
            for position in self.snapshot.positions:
                self.store.exit_target(self.cloid("panic:" + position.symbol), position.symbol, Decimal(0), reopen=True)
        for target in self.store.exits():
            position = next((p for p in self.snapshot.positions if p.symbol == target["symbol"]), None)
            quantity = abs(position.quantity) if position else Decimal(0)
            desired = Decimal(target["target"])
            if quantity <= desired:
                # A flat snapshot cannot rule out a late fill of an ambiguous entry.
                if not self.pending_entry(target["symbol"]):
                    self.store.finish_exit(target["id"])
                continue
            prior = [row for row in self.store.orders() if row["role"] == "exit:" + target["id"]]
            if any(row["role"].startswith("exit:") and NativeRequest.model_validate_json(row["request"]).symbol == target["symbol"]
                   for row in self.unresolved()):
                continue
            if any(row["status"] not in TERMINAL for row in prior) or (prior and prior[-1]["status"] == "rejected"):
                continue
            book = await self.fresh_book(position.symbol)
            buy = position.quantity < 0
            purpose = f"exit:{target['id']}:{len(prior)}"
            request = NativeRequest(cloid=self.cloid(purpose), symbol=position.symbol, side="buy" if buy else "sell",
                quantity=quantity - desired, price=book.ask * Decimal("1.005") if buy else book.bid * Decimal("0.995"), reduce_only=True)
            await self.place(purpose, "exit:" + target["id"], request)
            after = next((abs(p.quantity) for p in self.snapshot.positions if p.symbol == target["symbol"]), Decimal(0))
            if after <= desired and not self.pending_entry(target["symbol"]):
                self.store.finish_exit(target["id"])
        if not self.snapshot.positions:
            for order in list(self.snapshot.open_orders):
                if panic or self.owned(order):
                    await self.cancel_order(order)
        self.store.set("panic_complete", bool(panic and not self.snapshot.positions and not self.snapshot.open_orders
                                               and not self.unresolved() and not self.store.exits()))

    async def tick(self) -> dict:
        async with self.lock:
            await self.sync()
            await self.protect()
            return self.status()

    async def panic(self) -> dict:
        async with self.lock:
            self.store.latch_panic()  # durable before any network operation
            await self.sync()
            await self.drain()
            return self.status()

    async def cancel(self, cloid: str) -> None:
        async with self.lock:
            await self.sync()
            order = await self.broker.order(cloid)
            if order and order.status == "open":
                await self.cancel_order(order)
            await self.protect()

    async def resume(self) -> None:
        async with self.lock:
            await self.sync()
            if (self.store.get("locked_until", 0) > time.time() or self.snapshot.positions
                    or self.snapshot.open_orders or self.unresolved() or self.incomplete_fills()):
                raise BrokerUnavailable("Resume requires expired lock and reconciled flat account")
            self.store.set("panic", False)
            self.store.set("halted", None)
            self.store.set("panic_complete", False)

    def status(self) -> dict:
        return {"network": "testnet", "account": self.snapshot.model_dump(mode="json", exclude={"fills"}) if self.snapshot else None,
                "orders": [{"cloid": row["cloid"], "role": row["role"], "status": row["status"],
                            "filled_quantity": str(self.store.filled(row["broker_id"]))} for row in self.store.orders()],
                "fill_count": self.store.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0],
                "panic": self.store.get("panic", False), "panic_complete": self.store.get("panic_complete", False),
                "pending_exits": self.store.exits(),
                "notice": self.store.get("notice"), "halted": self.store.get("halted")}

    async def close(self) -> None:
        try:
            await self.broker.close()
        finally:
            self.store.close()

    async def reconcile(self) -> dict:
        """Read-only at the venue: do not place protection or send cancellation requests."""
        async with self.lock:
            await self.sync()
            return self.status()
