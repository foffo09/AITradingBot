import asyncio
import time
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from config.hyperliquid_testnet import TestnetSettings
from config.providers import ProviderSettings
from src.broker.hyperliquid_testnet import HyperliquidTestnetBroker, TESTNET_URL
from src.broker.native import (AccountSnapshot, Book, BrokerRejected, BrokerUnavailable, NativeFill,
                               NativeOrder, NativePosition, NativeRequest, Rules)
from src.trading.native_engine import NativeEngine


def settings():
    return TestnetSettings(private_key="dummy-not-a-key", account_address="dummy-account")


class SimulatedBroker:
    """A broker-owned account: acknowledgements and fills are independently controlled."""
    network = "testnet"
    scope = "simulated-testnet-account"

    def __init__(self):
        self.cash = D("1000")
        self.positions = {}
        self.orders = {}
        self.fills = []
        self.submissions = []
        self.cancellations = []
        self.entry_behaviors = []
        self.exit_behaviors = []
        self.stop_behaviors = []
        self.cancel_blocked = False
        self.cancel_race = False
        self.read_failed = False
        self.publish_fills = True
        self.stale = False
        self.next_id = 1
        self.price = D("100")

    async def rules(self, symbol):
        return Rules(size_decimals=3)

    async def book(self, symbol):
        return Book(symbol=symbol, bid=self.price, ask=self.price, timestamp=time.time() - (100 if self.stale else 0))

    async def order(self, cloid):
        if self.read_failed:
            raise BrokerUnavailable("simulated outage")
        return self.orders.get(cloid)

    async def snapshot(self, since_ms):
        if self.read_failed:
            raise BrokerUnavailable("simulated outage")
        notional = sum((abs(p.quantity) * self.price for p in self.positions.values()), D(0))
        unrealized = sum(((self.price - p.entry) * p.quantity for p in self.positions.values()), D(0))
        return AccountSnapshot(equity=self.cash + unrealized, cash=self.cash, available=max(D(0), self.cash - notional),
            timestamp=time.time(), positions=list(self.positions.values()),
            open_orders=[o for o in self.orders.values() if o.status == "open"],
            fills=self.fills if self.publish_fills else [])

    def fill(self, cloid, quantity=None):
        order = self.orders[cloid]
        amount = order.remaining if quantity is None else min(quantity, order.remaining)
        previous = self.positions.get(order.symbol)
        old_quantity = previous.quantity if previous else D(0)
        entry = previous.entry if previous else self.price
        signed = amount if order.side == "buy" else -amount
        if order.reduce_only:
            if not old_quantity or old_quantity * signed >= 0:
                raise BrokerRejected("invalid reduce-only direction")
            amount = min(amount, abs(old_quantity))
            signed = amount if order.side == "buy" else -amount
        closing = min(abs(old_quantity), amount) if old_quantity * signed < 0 else D(0)
        pnl = (self.price - entry) * closing * (1 if old_quantity >= 0 else -1)
        fee = D("0.01")
        self.cash += pnl - fee
        new_quantity = old_quantity + signed
        if new_quantity:
            if old_quantity * signed >= 0:
                entry = (abs(old_quantity) * entry + amount * self.price) / abs(new_quantity)
            self.positions[order.symbol] = NativePosition(symbol=order.symbol, quantity=new_quantity, entry=entry, leverage=1)
        else:
            self.positions.pop(order.symbol, None)
        self.fills.append(NativeFill(id=f"fill-{len(self.fills)}", broker_id=order.broker_id, symbol=order.symbol,
            side=order.side, quantity=amount, price=self.price, fee=fee, realized_pnl=pnl, timestamp_ms=int(time.time() * 1000)))
        left = order.remaining - amount
        self.orders[cloid] = order.model_copy(update={"remaining": left, "status": "open" if left else "filled"})

    async def submit(self, request):
        assert (await self.rules(request.symbol)).quantity(request.quantity) == request.quantity
        self.submissions.append(request)
        queue = self.stop_behaviors if request.trigger else self.exit_behaviors if request.reduce_only else self.entry_behaviors
        behavior = queue.pop(0) if queue else "open" if request.trigger else "fill"
        if behavior == "timeout_before":
            raise BrokerUnavailable("ambiguous transport failure")
        order = NativeOrder(**request.model_dump(), broker_id=self.next_id, remaining=request.quantity, status="open")
        self.next_id += 1
        self.orders[request.cloid] = order
        if behavior == "reject":
            self.orders[request.cloid] = order.model_copy(update={"status": "rejected"})
            raise BrokerRejected("venue rejection")
        if behavior in {"fill", "timeout_after"}:
            self.fill(request.cloid)
        elif behavior in {"partial", "partial_terminal", "crash_after_partial"}:
            self.fill(request.cloid, (await self.rules(request.symbol)).quantity(request.quantity / 2))
            if behavior == "partial_terminal":
                self.orders[request.cloid] = self.orders[request.cloid].model_copy(update={"status": "canceled"})
        if behavior == "timeout_after":
            raise BrokerUnavailable("lost reply after fill")
        if behavior == "crash_after_partial":
            raise asyncio.CancelledError

    async def cancel(self, order):
        self.cancellations.append(order.broker_id)
        if self.cancel_blocked:
            raise BrokerUnavailable("cancel transport failure")
        cloid = next(key for key, value in self.orders.items() if value.broker_id == order.broker_id)
        if self.cancel_race and not order.reduce_only:
            self.fill(cloid)
            self.cancel_race = False
        elif self.orders[cloid].status == "open":
            self.orders[cloid] = self.orders[cloid].model_copy(update={"status": "canceled"})

    async def close(self):
        return None


def engine(tmp_path, broker):
    return NativeEngine(broker, settings(), tmp_path / "native.sqlite3")


def run(case):
    return asyncio.run(case)


def test_full_cycle_uses_broker_balances_fills_and_native_stop(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        cloid = await controller.on_signal("bar-1", 1, time.time())
        state = controller.status()
        assert state["account"]["cash"] == str(broker.cash) == "999.99"
        assert state["fill_count"] == 1 and state["orders"][0]["status"] == "filled"
        assert D(state["orders"][0]["filled_quantity"]) == broker.positions["BTC"].quantity
        assert broker.submissions[0].cloid == cloid and len(broker.submissions) == 2
        stop = broker.submissions[1]
        assert stop.reduce_only and stop.trigger == D("98.500")
        assert stop.quantity == broker.positions["BTC"].quantity
        await controller.tick()
        assert controller.status()["fill_count"] == 1
        await controller.close()
    run(case())


def test_acknowledgement_without_fill_does_not_change_account(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["open"]
        broker.cancel_blocked = True
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        assert controller.status()["account"]["cash"] == "1000"
        assert controller.status()["fill_count"] == 0 and not controller.snapshot.positions
        assert controller.status()["orders"][0]["status"] == "open"
        await controller.on_signal("bar-2", 1, time.time())
        assert len(broker.submissions) == 1
        await controller.close()
    run(case())


def test_partial_entry_cancels_remaining_and_protects_actual_fill(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["partial"]
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        entry, stop = broker.submissions
        assert broker.orders[entry.cloid].status == "canceled"
        assert broker.positions["BTC"].quantity == entry.quantity / 2 == stop.quantity
        assert D(controller.status()["orders"][0]["filled_quantity"]) == entry.quantity / 2
        await controller.close()
    run(case())


def test_rejection_is_terminal_and_signal_id_cannot_resubmit(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["reject"]
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        await controller.on_signal("bar-1", 1, time.time())
        assert len(broker.submissions) == 1 and controller.status()["orders"][0]["status"] == "rejected"
        assert not controller.snapshot.positions and controller.snapshot.cash == 1000
        await controller.close()
    run(case())


@pytest.mark.parametrize("cancel_race", [False, True])
def test_sell_signal_cancels_unfilled_entry_and_closes_racing_fill(tmp_path, cancel_race):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["open"]
        broker.cancel_blocked = True
        controller = engine(tmp_path, broker)
        await controller.on_signal("buy", 1, time.time())
        broker.cancel_blocked = False
        broker.cancel_race = cancel_race
        await controller.on_signal("sell", -1, time.time())
        assert broker.cancellations
        assert not controller.snapshot.positions and not controller.snapshot.open_orders
        assert not controller.store.exits()
        await controller.close()
    run(case())


def test_sell_target_survives_unknown_entry_restart_and_closes_late_fill(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["timeout_before"]
        controller = engine(tmp_path, broker)
        await controller.on_signal("buy", 1, time.time())
        await controller.on_signal("sell", -1, time.time())
        assert controller.store.exits()
        await controller.close()
        controller = engine(tmp_path, broker)
        request = broker.submissions[0]
        broker.orders[request.cloid] = NativeOrder(**request.model_dump(), broker_id=99,
                                                  remaining=request.quantity, status="open")
        broker.fill(request.cloid)
        await controller.tick()
        assert not controller.snapshot.positions and not controller.snapshot.open_orders
        assert not controller.store.exits()
        assert len([r for r in broker.submissions if not r.reduce_only]) == 1
        await controller.close()
    run(case())


@pytest.mark.parametrize("behavior", ["timeout_before", "timeout_after"])
def test_timeout_reconciles_or_halts_without_duplicate(tmp_path, behavior):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = [behavior]
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        await controller.close()
        restored = engine(tmp_path, broker)
        await restored.tick()
        await restored.on_signal("bar-1", 1, time.time())
        await restored.on_signal("bar-2", 1, time.time())
        assert len([r for r in broker.submissions if not r.reduce_only]) == 1
        if behavior == "timeout_after":
            assert restored.snapshot.positions and restored.status()["fill_count"] == 1
        else:
            assert restored.status()["orders"][0]["status"] == "unknown" and restored.status()["fill_count"] == 0
        await restored.close()
    run(case())


def test_restart_after_partial_write_recovers_position_without_resubmit(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["crash_after_partial"]
        controller = engine(tmp_path, broker)
        with pytest.raises(asyncio.CancelledError):
            await controller.on_signal("bar-1", 1, time.time())
        await controller.close()
        restored = engine(tmp_path, broker)
        await restored.tick()
        await restored.on_signal("bar-1", 1, time.time())
        assert len([r for r in broker.submissions if not r.reduce_only]) == 1
        assert restored.status()["fill_count"] == 1
        assert any(r.trigger for r in broker.submissions)
        assert restored.snapshot.cash == broker.cash
        await restored.close()
    run(case())


def test_cancel_racing_with_fill_uses_final_broker_quantity(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["partial"]
        broker.cancel_race = True
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        entry, stop = broker.submissions
        assert stop.quantity == entry.quantity == broker.positions["BTC"].quantity
        assert controller.status()["fill_count"] == 2
        await controller.close()
    run(case())


def test_cancel_pending_order_then_panic_confirms_flat_and_no_orders(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["partial"]
        broker.cancel_blocked = True
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        broker.cancel_blocked = False
        state = await controller.panic()
        assert state["panic_complete"] and not state["account"]["positions"] and not state["account"]["open_orders"]
        assert all(r.reduce_only for r in broker.submissions[1:])
        count = len(broker.submissions)
        await controller.on_signal("bar-2", 1, time.time())
        assert len(broker.submissions) == count
        await controller.close()
        restored = engine(tmp_path, broker)
        assert (await restored.tick())["panic_complete"]
        assert restored.store.get("locked_until") > time.time()
        await restored.close()
    run(case())


def test_partial_exit_keeps_persistent_target_not_repeated_halving(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        original = broker.positions["BTC"].quantity
        broker.exit_behaviors = ["partial_terminal"]
        await controller.partial_exit("exit-1")
        first_fill = (await broker.rules("BTC")).quantity(original / 4)
        assert broker.positions["BTC"].quantity == original - first_fill
        await controller.close()
        restored = engine(tmp_path, broker)
        await restored.tick()
        assert broker.positions["BTC"].quantity == original / 2
        await restored.partial_exit("exit-1")
        assert broker.positions["BTC"].quantity == original / 2
        assert all(r.reduce_only for r in broker.submissions[1:])
        await restored.close()
    run(case())


def test_native_stop_fill_updates_positions_and_cash_from_broker(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        stop = next(r for r in broker.submissions if r.trigger)
        broker.price = D("98")
        broker.fill(stop.cloid)
        state = await controller.tick()
        assert state["account"]["positions"] == [] and state["account"]["cash"] == str(broker.cash)
        assert state["fill_count"] == 2
        await controller.close()
    run(case())


def test_rejected_protection_requests_emergency_flatten(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.stop_behaviors = ["reject"]
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        assert controller.store.get("panic") and not broker.positions
        assert broker.submissions[-1].reduce_only and broker.submissions[-1].trigger is None
        await controller.close()
    run(case())


def test_unknown_exit_never_creates_second_close_after_restart(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        broker.exit_behaviors = ["timeout_before"]
        await controller.panic()
        await controller.close()
        restored = engine(tmp_path, broker)
        await restored.tick()
        await restored.panic()
        assert len([r for r in broker.submissions if r.reduce_only and r.trigger is None]) == 1
        assert not restored.status()["panic_complete"]
        await restored.close()
    run(case())


def test_risk_blocks_stale_books_low_balance_and_foreign_pending(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        broker.stale = True
        with pytest.raises(BrokerUnavailable):
            await controller.on_signal("stale", 1, time.time())
        assert not broker.submissions
        broker.stale = False
        broker.cash = D(1)
        assert await controller.on_signal("low", 1, time.time()) is None
        broker.cash = D(1000)
        broker.orders["foreign"] = NativeOrder(cloid=None, broker_id=99, symbol="BTC", side="buy", quantity=1,
            remaining=1, price=100, reduce_only=False, status="open")
        assert await controller.on_signal("foreign", 1, time.time()) is None
        assert not broker.submissions
        await controller.close()
    run(case())


def test_broker_read_outage_prevents_order_submission(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        broker.read_failed = True
        with pytest.raises(BrokerUnavailable):
            await controller.on_signal("bar-1", 1, time.time())
        assert not broker.submissions
        await controller.close()
    run(case())


def test_single_writer_and_account_scope_fence(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        with pytest.raises(RuntimeError, match="already"):
            engine(tmp_path, broker)
        await controller.close()
        broker.scope = "different-account"
        with pytest.raises(RuntimeError, match="different"):
            engine(tmp_path, broker)
    run(case())


def test_mainnet_blocked_at_engine_and_sdk_boundaries(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.network = "mainnet"
        with pytest.raises(ValueError, match="Mainnet"):
            engine(tmp_path, broker)
        adapter = HyperliquidTestnetBroker(settings())
        adapter._exchange = SimpleNamespace(base_url="https://api.hyperliquid.xyz", info=SimpleNamespace(base_url=TESTNET_URL))
        with pytest.raises(BrokerUnavailable, match="Mainnet"):
            await adapter.snapshot(0)
    run(case())


def test_provider_file_secrets_ignored_and_native_settings_environment_only(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("HYPERLIQUID_PRIVATE_KEY=file-secret\nOPENAI_API_KEY=file-secret\n")
    monkeypatch.delenv("HYPERLIQUID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CRYPTO_EXECUTION_NETWORK", "testnet")
    monkeypatch.delenv("HL_TESTNET_NETWORK", raising=False)
    assert ProviderSettings.from_env(path).hyperliquid_private_key is None
    assert TestnetSettings.from_env().private_key.get_secret_value() == ""
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "environment-secret")
    assert TestnetSettings.from_env().private_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(TestnetSettings.from_env())


def test_entry_risk_size_does_not_exceed_equity_or_usd_cap(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.cash = D(400)
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        entry = broker.submissions[0]
        assert entry.quantity * entry.price <= min(D(25), D(400) * D(".04"))
        await controller.close()
    run(case())


def test_broker_fills_lag_blocks_entries_even_after_next_reconciliation(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        broker.publish_fills = False
        await controller.on_signal("bar-1", 1, time.time())
        broker.fill(next(r.cloid for r in broker.submissions if r.trigger))
        await controller.tick()
        assert not controller.snapshot.positions and controller.incomplete_fills()
        count = len(broker.submissions)
        await controller.on_signal("bar-2", 1, time.time())
        assert len(broker.submissions) == count
        broker.publish_fills = True
        await controller.tick()
        assert not controller.incomplete_fills() and controller.status()["fill_count"] == 2
        await controller.close()
    run(case())


def test_cancel_failure_keeps_native_stop_and_panic_incomplete(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.entry_behaviors = ["partial"]
        broker.cancel_blocked = True
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        state = await controller.panic()
        assert not state["panic_complete"] and state["account"]["positions"]
        assert any(o.trigger and o.status == "open" for o in broker.orders.values())
        broker.cancel_blocked = False
        assert (await controller.tick())["panic_complete"]
        await controller.close()
    run(case())


def test_panic_reopens_zero_target_when_late_entry_fill_arrives(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        assert (await controller.panic())["panic_complete"]
        # A late venue fill is broker state, never an optimistic local position.
        request = NativeRequest(cloid="0x" + "b" * 32, symbol="BTC", side="buy", quantity=D(".1"), price=100)
        await broker.submit(request)
        assert broker.positions
        assert (await controller.tick())["panic_complete"]
        assert not broker.positions
        await controller.close()
    run(case())


def test_daily_loss_panic_does_not_extend_lock_on_every_poll(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.reconcile()
        broker.cash = D(949)
        assert (await controller.tick())["panic"]
        first_lock = controller.store.get("locked_until")
        await controller.tick()
        assert controller.store.get("locked_until") == first_lock
        with pytest.raises(BrokerUnavailable):
            await controller.resume()
        await controller.close()
    run(case())


def test_resume_requires_proven_flat_account_and_expired_lock(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.panic()
        controller.store.set("locked_until", time.time() - 1)
        await controller.resume()
        assert not controller.store.get("panic")
        await controller.on_signal("fresh-bar", 1, time.time())
        assert broker.positions
        await controller.close()
    run(case())


def test_read_only_reconcile_never_sends_native_protection(tmp_path):
    async def case():
        broker = SimulatedBroker()
        broker.positions["BTC"] = NativePosition(symbol="BTC", quantity=1, entry=100, leverage=1)
        controller = engine(tmp_path, broker)
        assert (await controller.reconcile())["account"]["positions"]
        assert broker.submissions == [] and broker.cancellations == []
        await controller.close()
    run(case())


def test_sdk_transport_fixed_endpoint_signed_order_stop_and_cancel(monkeypatch):
    async def case():
        calls = []
        adapter = HyperliquidTestnetBroker(settings())
        info = SimpleNamespace(base_url=TESTNET_URL, meta=lambda: {"universe": [{"name": "BTC", "szDecimals": 3}]})
        def update(leverage, symbol, is_cross):
            calls.append(("leverage", leverage, is_cross))
            return {"status": "ok"}
        def submit(*args, **kwargs):
            calls.append(("order", args, kwargs))
            return {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}
        def cancel(symbol, oid):
            calls.append(("cancel", symbol, oid))
            return {"status": "ok", "response": {"data": {"statuses": ["success"]}}}
        adapter._exchange = SimpleNamespace(base_url=TESTNET_URL, info=info, update_leverage=update, order=submit, cancel=cancel)
        request = NativeRequest(cloid="0x" + "a" * 32, symbol="BTC", side="buy", quantity=D(".1"), price=D("100.1"))
        await adapter.submit(request)
        stop = request.model_copy(update={"cloid": "0x" + "b" * 32, "side": "sell", "reduce_only": True, "trigger": D("98.5")})
        await adapter.submit(stop)
        assert calls[0] == ("leverage", 1, False)
        assert calls[1][1][-1] == {"limit": {"tif": "Ioc"}}
        assert calls[2][2]["reduce_only"] is True and calls[2][1][-1]["trigger"]["isMarket"]
        await adapter.cancel(NativeOrder(**stop.model_dump(), broker_id=1, remaining=stop.quantity, status="open"))
        assert calls[-1] == ("cancel", "BTC", 1)
    run(case())


def test_sdk_order_status_unknown_and_partial_parsers():
    raw = {"coin": "BTC", "side": "B", "limitPx": "100", "origSz": "1", "sz": ".5", "oid": 7,
           "reduceOnly": False, "cloid": "0x" + "a" * 32}
    parsed = HyperliquidTestnetBroker.parse_order(raw, "open")
    assert parsed.quantity == 1 and parsed.remaining == D(".5") and parsed.status == "open"
    assert HyperliquidTestnetBroker.parse_order(raw, "marginCanceled").status == "canceled"
    assert HyperliquidTestnetBroker.parse_order(raw, "scheduledCancel").status == "canceled"
    assert HyperliquidTestnetBroker.parse_order(raw, "tickRejected").status == "rejected"
    with pytest.raises(BrokerRejected):
        HyperliquidTestnetBroker._accepted({"status": "ok", "response": {"data": {"statuses": [{"error": "untrusted text"}]}}})


def test_sdk_write_failure_never_exposes_raw_secret_text(caplog):
    async def case():
        adapter = HyperliquidTestnetBroker(settings())
        adapter._exchange = SimpleNamespace(base_url=TESTNET_URL, info=SimpleNamespace(base_url=TESTNET_URL))
        def fail():
            raise RuntimeError("DO-NOT-LOG-SECRET")
        with pytest.raises(BrokerUnavailable) as error:
            await adapter._call(fail)
        assert "DO-NOT-LOG-SECRET" not in str(error.value) + caplog.text
    run(case())


def test_sdk_cancellation_waits_for_inflight_write():
    import threading
    async def case():
        started, finished = threading.Event(), threading.Event()
        adapter = HyperliquidTestnetBroker(settings())
        adapter._exchange = SimpleNamespace(base_url=TESTNET_URL, info=SimpleNamespace(base_url=TESTNET_URL))
        def write():
            started.set()
            time.sleep(.05)
            finished.set()
        task = asyncio.create_task(adapter._call(write))
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    run(case())


def test_legacy_live_flag_cannot_enable_mainnet(tmp_path):
    from execution.providers import ExecutionProviders, OrderIntent
    from providers.crypto import CCXTData
    config = ProviderSettings(omega_enable_native_orders=True, omega_enable_live_orders=True,
                             crypto_execution_network="mainnet", hyperliquid_private_key="dummy", hyperliquid_account_address="dummy")
    legacy = ExecutionProviders(config, tmp_path / "old.sqlite3")
    order = OrderIntent(client_order_id="test-request-01", venue="hyperliquid", market="CRYPTO_PERPS", symbol="BTC",
                        side="buy", quantity=1, limit_price=100, quote_timestamp=time.time())
    with pytest.raises(Exception, match="prohibited"):
        legacy.check(order)
    with pytest.raises(Exception, match="disabled"):
        legacy.hyperliquid_order(order)
    with pytest.raises(ValueError, match="Mainnet"):
        CCXTData("binance", config).client(execution=True)
    assert not legacy.capabilities()["live_orders_enabled"]


def test_runner_rejects_write_actions_without_explicit_testnet_flag(tmp_path):
    from src.hyperliquid_testnet_cli import execute
    args = SimpleNamespace(action="panic", trade_testnet=False)
    with pytest.raises(ValueError, match="trade-testnet"):
        run(execute(args))


def test_panic_outage_is_persisted_before_any_successful_broker_read(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        broker.read_failed = True
        with pytest.raises(BrokerUnavailable):
            await controller.panic()
        assert controller.store.get("panic") and controller.store.get("locked_until") > time.time()
        await controller.close()
        broker.read_failed = False
        restored = engine(tmp_path, broker)
        assert (await restored.tick())["panic_complete"]
        await restored.close()
    run(case())


def test_stale_book_during_panic_does_not_claim_liquidation(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        broker.stale = True
        with pytest.raises(BrokerUnavailable):
            await controller.panic()
        assert not controller.status()["panic_complete"] and broker.positions
        assert any(o.trigger and o.status == "open" for o in broker.orders.values())
        broker.stale = False
        assert (await controller.tick())["panic_complete"]
        await controller.close()
    run(case())


def test_rejected_exit_remains_pending_instead_of_reporting_flat(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        broker.exit_behaviors = ["reject"]
        state = await controller.panic()
        assert not state["panic_complete"] and state["pending_exits"] and broker.positions
        count = len(broker.submissions)
        await controller.tick()
        assert len(broker.submissions) == count
        assert any(o.trigger and o.status == "open" for o in broker.orders.values())
        await controller.close()
    run(case())


def test_secrets_not_written_to_native_journal_or_logs(tmp_path, caplog):
    async def case():
        broker = SimulatedBroker()
        config = TestnetSettings(private_key="PRIVATE-KEY-NEVER-PERSIST", account_address="ACCOUNT-NEVER-PERSIST")
        controller = NativeEngine(broker, config, tmp_path / "native.sqlite3")
        await controller.on_signal("bar-1", 1, time.time())
        await controller.close()
        data = b"".join(path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
        assert b"PRIVATE-KEY-NEVER-PERSIST" not in data and b"ACCOUNT-NEVER-PERSIST" not in data
        assert "PRIVATE-KEY-NEVER-PERSIST" not in caplog.text
    run(case())


def test_http_policy_blocks_mainnet_and_redirects(monkeypatch):
    import requests
    from src.broker.hyperliquid_testnet import TestnetSession
    calls = []
    def response(self, method, url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=302)
    monkeypatch.setattr(requests.Session, "request", response)
    with TestnetSession() as session:
        with pytest.raises(BrokerUnavailable, match="Non-testnet"):
            session.post("https://api.hyperliquid.xyz/exchange")
        assert calls == []
        with pytest.raises(BrokerUnavailable, match="redirects"):
            session.post(TESTNET_URL + "/exchange")
        assert calls[0]["allow_redirects"] is False


def test_engine_risk_interface_does_not_require_provider_credentials(tmp_path):
    from config.hyperliquid_testnet import TestnetRisk
    async def case():
        broker = SimulatedBroker()
        controller = NativeEngine(broker, TestnetRisk(), tmp_path / "native.sqlite3")
        await controller.on_signal("bar-1", 1, time.time())
        assert not hasattr(controller.settings, "private_key") and broker.positions
        await controller.close()
    run(case())


def test_missing_environment_credentials_cannot_create_bound_journal(tmp_path, monkeypatch):
    from src.hyperliquid_testnet_cli import execute
    for key in ("HYPERLIQUID_PRIVATE_KEY", "HYPERLIQUID_ACCOUNT_ADDRESS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CRYPTO_EXECUTION_NETWORK", "testnet")
    monkeypatch.delenv("HL_TESTNET_NETWORK", raising=False)
    path = tmp_path / "native.sqlite3"
    with pytest.raises(BrokerUnavailable, match="credentials"):
        run(execute(SimpleNamespace(action="status", trade_testnet=False, journal=path)))
    assert not path.exists()


def test_reduce_only_stop_can_shrink_to_actual_remaining_position(tmp_path):
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        await controller.partial_exit("exit-1")
        stop = next(r for r in broker.submissions if r.trigger)
        quantity = broker.positions["BTC"].quantity
        broker.orders[stop.cloid] = broker.orders[stop.cloid].model_copy(update={"quantity": quantity, "remaining": quantity})
        await controller.tick()
        assert not controller.store.get("panic") and len([r for r in broker.submissions if r.trigger]) == 1
        await controller.close()
    run(case())


def test_runner_uses_only_ordered_unique_closed_positive_candles():
    from src.hyperliquid_testnet_cli import closed_candles
    rows = [{"t": 2, "T": 3, "c": "100"}, {"t": 1, "T": 2, "c": "99"},
            {"t": 2, "T": 3, "c": "101"}, {"t": 4, "T": 5, "c": "102"}]
    closed = closed_candles(rows, 4)
    assert [(r["t"], r["c"]) for r in closed] == [(1, 99), (2, 101)]
    with pytest.raises(BrokerUnavailable):
        closed_candles([{"t": 1, "T": 2, "c": "NaN"}], 4)


def test_second_process_panic_request_blocks_entries_and_flattens(tmp_path):
    from src.trading.native_store import NativeStore
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        await controller.on_signal("bar-1", 1, time.time())
        NativeStore.queue_panic(tmp_path / "native.sqlite3", broker.scope)
        await controller.on_signal("bar-2", 1, time.time())
        assert not broker.positions and controller.status()["panic_complete"]
        assert len([r for r in broker.submissions if not r.reduce_only]) == 1
        await controller.close()
    run(case())


def test_cross_process_panic_rejects_wrong_account(tmp_path):
    from src.trading.native_store import NativeStore
    async def case():
        broker = SimulatedBroker()
        controller = engine(tmp_path, broker)
        with pytest.raises(RuntimeError, match="mismatch"):
            NativeStore.queue_panic(tmp_path / "native.sqlite3", "different-account")
        assert not controller.store.get("panic")
        await controller.close()
    run(case())
