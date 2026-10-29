import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from config.settings import AppSettings
from src.broker import alpaca_client
from src.trading import paper_automation
from src.trading.paper_automation import (
    PaperAutomationError,
    PaperAutomationLog,
    execute_auto_paper_cycle,
    execute_paper_signal,
)


def make_data(*, quality="real", stale_seconds=90):
    now = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    frame = pd.DataFrame({
        "timestamp": pd.date_range(end=now, periods=6, freq="min"),
        "close": [4.0, 3.0, 2.0, 1.0, 2.0, 3.0],
    })
    frame.attrs["quality"] = quality
    frame.attrs["interval"] = "1Min"
    return frame


class FakePaperBroker:
    paper_client_configured = True

    def __init__(self):
        self.connected = True
        self.orders = []
        self.positions = []
        self.submitted = []

    def is_connected(self):
        return self.connected

    def verify_connection(self):
        self.connected = True
        return {"connected": True}

    def get_latest_quote(self, symbol):
        return {
            "symbol": symbol,
            "bid": 2.99,
            "ask": 3.01,
            "price": 3.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "mock paper-feed",
        }

    def get_instrument_availability(self, symbol):
        return {
            "paper_tradable": True,
            "fractionable": True,
            "min_order_size": "0.000001",
            "min_trade_increment": "0.000001",
        }

    def get_account(self):
        return {
            "status": "ACTIVE",
            "cash": "10000",
            "buying_power": "10000",
            "equity": "10000",
            "last_equity": "10000",
            "trading_blocked": False,
        }

    def get_positions(self):
        return self.positions

    def get_orders(self):
        return self.orders

    def submit_order(self, **kwargs):
        self.submitted.append(kwargs)
        order = {
            "symbol": kwargs["symbol"],
            "client_order_id": kwargs["client_order_id"],
            "status": "accepted",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        self.orders.append(order)
        return order


class FakeAutoPaperBroker(FakePaperBroker):
    paper_client_is_paper = True

    def __init__(self, *, stale_seconds=90):
        super().__init__()
        self.stale_seconds = stale_seconds
        self.requested_symbols = []

    def verify_connection(self):
        self.connected = True
        return {"connected": True, "mode": "paper"}

    def get_market_data(self, symbol, *, timeframe, period, limit):
        self.requested_symbols.append(symbol)
        data = make_data(stale_seconds=self.stale_seconds)
        data.attrs["interval"] = timeframe
        return data


def selected_decision(**overrides):
    decision = {
        "status": "SELECTED",
        "asset": "AAPL",
        "strategy": "moving_average",
        "parameters": {"short_window": 2, "long_window": 3},
        "side": "buy",
        "proposed_quantity": 10.0,
        "reason": "Validated on out-of-sample folds.",
        "exclusions": (),
    }
    decision.update(overrides)
    return type("Selection", (), decision)()


def make_settings(**overrides):
    values = {
        "trading_mode": "paper",
        "alpaca_api_key": "test-paper-key",
        "alpaca_secret_key": "test-paper-secret",
        "paper_trading_enabled": True,
        "initial_capital_eur": 100,
        "eur_usd_rate": 100,
        "risk_max_trade_fraction": 0.2,
        "risk_max_exposure_fraction": 0.5,
        "daily_loss_limit_pct": 0.05,
        "max_positions": 3,
        "paper_max_daily_orders": 5,
    }
    values.update(overrides)
    return AppSettings(**values)


def execute(broker, data=None, settings=None):
    return execute_paper_signal(
        broker=broker,
        settings=settings or make_settings(),
        symbol="AAPL",
        market_data=data if data is not None else make_data(),
        short_window=2,
        long_window=3,
    )


def test_fresh_buy_signal_submits_one_sized_paper_order():
    broker = FakePaperBroker()

    result = execute(broker)

    assert result["status"] == "submitted"
    assert result["side"] == "buy"
    assert result["quantity"] > 0
    assert result["quantity"] * 3.0 <= 2_000
    assert broker.submitted[0]["client_order_id"].startswith("ma-")
    assert len(broker.submitted) == 1

    repeated = execute(broker)
    assert repeated["status"] == "blocked"
    assert len(broker.submitted) == 1


def test_synthetic_and_stale_feeds_cannot_trigger_orders():
    broker = FakePaperBroker()
    with pytest.raises(PaperAutomationError, match="real market data"):
        execute(broker, data=make_data(quality="synthetic"))
    with pytest.raises(PaperAutomationError, match="stale"):
        execute(broker, data=make_data(stale_seconds=700))
    assert broker.submitted == []


def test_stale_or_crossed_quote_cannot_trigger_an_order():
    broker = FakePaperBroker()
    broker.get_latest_quote = lambda symbol: {
        "bid": 2.99,
        "ask": 3.01,
        "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    }
    with pytest.raises(PaperAutomationError, match="Latest quote is stale"):
        execute(broker)
    assert broker.submitted == []

    broker = FakePaperBroker()
    broker.get_latest_quote = lambda symbol: {
        "bid": 3.02,
        "ask": 3.01,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with pytest.raises(PaperAutomationError, match="bid/ask is invalid"):
        execute(broker)
    assert broker.submitted == []


def test_incomplete_current_bar_waits_before_generating_an_order():
    broker = FakePaperBroker()
    result = execute(broker, data=make_data(stale_seconds=10))
    assert result["status"] == "no_signal"
    assert "forming bar was ignored" in result["reason"]
    assert broker.submitted == []


def test_daily_equity_bar_before_session_close_waits_without_order():
    broker = FakePaperBroker()
    frame = pd.DataFrame({
        "timestamp": [pd.Timestamp("2025-07-02T00:00:00Z")],
        "close": [100.0],
    })
    frame.attrs.update({"quality": "real", "interval": "1Day"})

    result = execute_paper_signal(
        broker=broker,
        settings=make_settings(),
        symbol="AAPL",
        market_data=frame,
        short_window=2,
        long_window=3,
        as_of=pd.Timestamp("2025-07-02T19:00:00Z"),
    )

    assert result["status"] == "blocked"
    assert "No completed OHLC bar" in result["reason"]
    assert broker.submitted == []


def test_future_bar_timestamp_cannot_trigger_a_paper_order():
    broker = FakePaperBroker()
    frame = pd.DataFrame({
        "timestamp": pd.date_range(
            "2025-07-02T20:01:00Z", periods=6, freq="min"
        ),
        "close": [4.0, 3.0, 2.0, 1.0, 2.0, 3.0],
    })
    frame.attrs.update({"quality": "real", "interval": "1Min"})

    with pytest.raises(PaperAutomationError, match="future timestamp"):
        execute_paper_signal(
            broker=broker,
            settings=make_settings(),
            symbol="AAPL",
            market_data=frame,
            short_window=2,
            long_window=3,
            as_of=pd.Timestamp("2025-07-02T20:00:00Z"),
        )

    assert broker.submitted == []


def test_missing_market_data_cannot_trigger_a_paper_order():
    broker = FakePaperBroker()
    frame = pd.DataFrame(columns=["timestamp", "close"])
    frame.attrs.update({"quality": "real", "interval": "1Min"})

    with pytest.raises(PaperAutomationError, match="Fresh real market data"):
        execute(broker, data=frame)

    assert broker.submitted == []


def test_open_partial_order_blocks_another_order_for_the_symbol():
    broker = FakePaperBroker()
    broker.orders.append({
        "symbol": "AAPL",
        "status": "partially_filled",
        "client_order_id": "existing",
    })

    result = execute(broker)

    assert result["status"] == "blocked"
    assert "open paper order" in result["reason"]
    assert broker.submitted == []


def test_terminal_duplicate_order_and_ambiguous_submit_timeout_are_idempotent():
    broker = FakePaperBroker()
    data = make_data()
    first = execute(broker, data=data)
    assert first["status"] == "submitted"
    broker.orders[0]["status"] = "rejected"

    duplicate = execute(broker, data=data)

    assert duplicate["status"] == "duplicate"
    assert len(broker.submitted) == 1

    ambiguous_broker = FakePaperBroker()
    attempts = []

    def accept_then_timeout(**kwargs):
        attempts.append(kwargs)
        ambiguous_broker.orders.append({
            "symbol": kwargs["symbol"],
            "side": kwargs["side"],
            "client_order_id": kwargs["client_order_id"],
            "status": "accepted",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
        raise RuntimeError("simulated response timeout after broker acceptance")

    ambiguous_broker.submit_order = accept_then_timeout
    ambiguous_data = make_data()
    with pytest.raises(RuntimeError, match="response timeout"):
        execute(ambiguous_broker, data=ambiguous_data)
    retry = execute(ambiguous_broker, data=ambiguous_data)

    assert retry["status"] == "blocked"
    assert len(attempts) == 1


def test_disconnected_or_blocked_account_stops_before_strategy_or_order():
    broker = FakePaperBroker()
    broker.verify_connection = lambda: {"connected": False}
    with pytest.raises(PaperAutomationError, match="verification failed"):
        execute(broker)
    assert broker.submitted == []

    broker = FakePaperBroker()
    broker.get_account = lambda: {
        "status": "ACTIVE",
        "cash": "10000",
        "buying_power": "10000",
        "equity": "10000",
        "last_equity": "10000",
        "trading_blocked": True,
    }
    with pytest.raises(PaperAutomationError, match="trading is blocked"):
        execute(broker)
    assert broker.submitted == []


def test_daily_loss_limit_blocks_automatic_order():
    broker = FakePaperBroker()
    broker.get_account = lambda: {
        "status": "ACTIVE",
        "cash": "10000",
        "buying_power": "10000",
        "equity": "9400",
        "last_equity": "10000",
        "trading_blocked": False,
    }

    result = execute(broker)

    assert result["status"] == "blocked"
    assert "Daily loss limit" in result["reason"]
    assert broker.submitted == []


def test_daily_order_limit_blocks_new_paper_order():
    broker = FakePaperBroker()
    broker.orders = [
        {
            "symbol": f"OTHER{i}",
            "client_order_id": f"ma-existing-{i}",
            "status": "filled",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(5)
    ]

    result = execute(broker)

    assert result["status"] == "blocked"
    assert "daily paper-order limit" in result["reason"]
    assert broker.submitted == []


def test_total_portfolio_exposure_limit_blocks_a_new_symbol():
    broker = FakePaperBroker()
    broker.positions = [
        {"symbol": "MSFT", "qty": "100", "market_value": "4900"}
    ]

    result = execute(broker)

    assert result["status"] == "blocked"
    assert "portfolio exposure limit" in result["reason"]
    assert broker.submitted == []


def test_pending_buy_on_another_symbol_blocks_additional_exposure():
    broker = FakePaperBroker()
    broker.orders = [{
        "symbol": "MSFT",
        "side": "buy",
        "status": "accepted",
        "client_order_id": "ma-other-symbol",
    }]

    result = execute(broker)

    assert result["status"] == "blocked"
    assert "pending paper buy" in result["reason"]
    assert broker.submitted == []


def test_sell_signal_can_exit_position_without_available_cash():
    broker = FakePaperBroker()
    broker.positions = [{"symbol": "AAPL", "qty": "10", "market_value": "30"}]
    broker.get_account = lambda: {
        "status": "ACTIVE",
        "cash": "0",
        "buying_power": "0",
        "equity": "10000",
        "last_equity": None,
        "trading_blocked": False,
    }
    data = make_data()
    data["close"] = [1.0, 2.0, 3.0, 4.0, 3.0, 2.0]

    result = execute(broker, data=data)

    assert result["status"] == "submitted"
    assert result["side"] == "sell"
    assert result["quantity"] == 10
    assert broker.submitted[0]["side"] == "sell"


def test_unverified_and_demo_modes_cannot_submit():
    broker = FakePaperBroker()
    broker.connected = False
    with pytest.raises(PaperAutomationError, match="verified Alpaca Paper"):
        execute(broker)
    with pytest.raises(PaperAutomationError, match="Paper mode"):
        execute(broker, settings=make_settings(trading_mode="demo"))
    assert broker.submitted == []


def test_each_cycle_checks_account_positions_and_orders_even_without_a_signal():
    broker = FakePaperBroker()
    data = make_data()
    data["close"] = [5.0, 4.0, 3.0, 2.0, 2.1, 2.2]
    data.iloc[-1, data.columns.get_loc("timestamp")] = (
        datetime.now(timezone.utc) - timedelta(seconds=10)
    )
    calls = []
    broker.verify_connection = lambda: calls.append("verify") or {"connected": True}
    broker.get_account = lambda: calls.append("account") or {
        "status": "ACTIVE",
        "cash": "10000",
        "buying_power": "10000",
        "equity": "10000",
        "last_equity": "10000",
    }
    broker.get_positions = lambda: calls.append("positions") or []
    broker.get_orders = lambda: calls.append("orders") or []

    result = execute(broker, data=data)

    assert result["status"] == "no_signal"
    assert calls == ["verify", "account", "positions", "orders"]
    assert broker.submitted == []


def test_untradeable_asset_and_insufficient_minimum_quantity_are_blocked():
    broker = FakePaperBroker()
    broker.get_instrument_availability = lambda symbol: {
        "paper_tradable": False,
        "fractionable": False,
    }
    result = execute(broker)
    assert result["status"] == "blocked"
    assert "tradability is not verified" in result["reason"]
    assert broker.submitted == []

    broker = FakePaperBroker()
    broker.get_instrument_availability = lambda symbol: {
        "paper_tradable": True,
        "fractionable": False,
        "min_order_size": "1",
    }
    broker.get_account = lambda: {
        "status": "ACTIVE",
        "cash": "1",
        "buying_power": "1",
        "equity": "1",
        "last_equity": "1",
        "trading_blocked": False,
    }
    result = execute(broker, settings=make_settings(
        initial_capital_eur=1,
        eur_usd_rate=1,
        risk_max_trade_fraction=0.2,
    ))
    assert result["status"] == "blocked"
    assert "minimum order size" in result["reason"]
    assert broker.submitted == []


def test_nonfractionable_assets_round_down_to_whole_shares():
    broker = FakePaperBroker()
    broker.get_instrument_availability = lambda symbol: {
        "paper_tradable": True,
        "fractionable": False,
        "min_order_size": "1",
        "min_trade_increment": "0.001",
    }

    result = execute(broker)

    assert result["status"] == "submitted"
    assert result["quantity"] == math.floor(result["quantity"])
    assert broker.submitted[0]["quantity"] == result["quantity"]


def test_sell_order_uses_bid_and_available_position_quantity():
    broker = FakePaperBroker()
    broker.positions = [{
        "symbol": "AAPL",
        "qty": "10",
        "qty_available": "4",
        "market_value": "30",
    }]
    data = make_data()
    data["close"] = [1.0, 2.0, 3.0, 4.0, 3.0, 2.0]

    result = execute(broker, data=data)

    assert result["status"] == "submitted"
    assert result["quantity"] == 4
    assert result["quantity"] * 2.99 == pytest.approx(11.96)


def test_paper_automation_log_persists_decisions_without_credentials(tmp_path):
    database_path = tmp_path / "paper" / "automation.sqlite3"
    first_log = PaperAutomationLog(database_path)
    first_log.record({
        "timestamp_utc": "2026-10-11T10:00:00+00:00",
        "symbol": "AAPL",
        "strategy": "moving_average",
        "signal_timestamp_utc": "2026-10-11T09:59:00+00:00",
        "signal": 1,
        "decision": "blocked",
        "quantity": 10.0,
        "proposed_quantity": 12.0,
        "reason": "Order limit reached.",
    })

    reopened_log = PaperAutomationLog(Path(database_path))

    assert reopened_log.recent() == [{
        "timestamp_utc": "2026-10-11T10:00:00+00:00",
        "symbol": "AAPL",
        "strategy": "moving_average",
        "signal_timestamp_utc": "2026-10-11T09:59:00+00:00",
        "signal": "1",
        "decision": "blocked",
        "side": None,
        "quantity": 10.0,
        "proposed_quantity": 12.0,
        "order_status": None,
        "reason": "Order limit reached.",
    }]


def test_paper_automation_log_migrates_existing_event_table(tmp_path):
    database_path = tmp_path / "paper" / "existing.sqlite3"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as db:
        db.execute(
            """CREATE TABLE paper_automation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_timestamp_utc TEXT,
                signal TEXT NOT NULL,
                decision TEXT NOT NULL,
                side TEXT,
                quantity REAL,
                order_status TEXT,
                reason TEXT NOT NULL
            )"""
        )

    automation_log = PaperAutomationLog(database_path)
    automation_log.record({
        "timestamp_utc": "2026-10-11T10:00:00+00:00",
        "symbol": "AAPL",
        "strategy": "moving_average",
        "proposed_quantity": 3.0,
        "decision": "preview",
        "reason": "No order was sent.",
    })

    event = automation_log.recent()[0]
    assert event["strategy"] == "moving_average"
    assert event["proposed_quantity"] == 3.0
    assert event["quantity"] is None


def test_auto_cycle_uses_selected_asset_and_strategy_in_no_order_mode(monkeypatch):
    broker = FakeAutoPaperBroker()
    selector_calls = []
    executor_calls = []
    real_execute = paper_automation.execute_paper_signal

    def select(data, **kwargs):
        selector_calls.append((data, kwargs))
        return selected_decision()

    def execute(**kwargs):
        executor_calls.append(kwargs)
        return real_execute(**kwargs)

    monkeypatch.setattr(paper_automation, "select_strategy", select)
    monkeypatch.setattr(paper_automation, "execute_paper_signal", execute)

    result = execute_auto_paper_cycle(
        broker=broker,
        settings=make_settings(),
        allowed_symbols=("AAPL",),
        interval="1Min",
    )

    assert len(selector_calls) == 1
    assert selector_calls[0][0]["AAPL"].attrs["quality"] == "real"
    assert selector_calls[0][1]["asset_availability"] == {"AAPL": True}
    assert executor_calls[0]["symbol"] == "AAPL"
    assert executor_calls[0]["short_window"] == 2
    assert executor_calls[0]["long_window"] == 3
    assert executor_calls[0]["dry_run"] is True
    assert result["status"] == "preview"
    assert result["strategy"] == "moving_average"
    assert result["proposed_quantity"] == 10.0
    assert result["quantity"] > 0
    assert broker.submitted == []


def test_auto_cycle_no_trade_never_invokes_order_execution(monkeypatch):
    broker = FakeAutoPaperBroker()
    monkeypatch.setattr(
        paper_automation,
        "select_strategy",
        lambda *args, **kwargs: selected_decision(
            status="NO_TRADE",
            asset=None,
            strategy=None,
            parameters=None,
            side=None,
            proposed_quantity=None,
            reason="OOS criteria not met.",
        ),
    )
    monkeypatch.setattr(
        paper_automation,
        "execute_paper_signal",
        lambda **kwargs: pytest.fail("NO_TRADE must not reach execution."),
    )

    result = execute_auto_paper_cycle(
        broker=broker,
        settings=make_settings(),
        allowed_symbols=("AAPL",),
        interval="1Min",
    )

    assert result["status"] == "NO_TRADE"
    assert "OOS criteria not met" in result["reason"]
    assert broker.submitted == []


@pytest.mark.parametrize(
    ("broker", "decision", "settings", "reason"),
    [
        (
            FakeAutoPaperBroker(stale_seconds=700),
            selected_decision(),
            None,
            "stale",
        ),
        (
            FakeAutoPaperBroker(),
            selected_decision(proposed_quantity=math.nan),
            None,
            "invalid decision",
        ),
        (
            FakeAutoPaperBroker(),
            selected_decision(),
            SimpleNamespace(trading_mode="live", paper_trading_enabled=True),
            "Live and Demo are rejected",
        ),
    ],
)
def test_auto_cycle_blocks_stale_data_invalid_size_and_live(
    monkeypatch, broker, decision, settings, reason,
):
    monkeypatch.setattr(
        paper_automation,
        "select_strategy",
        lambda *args, **kwargs: decision,
    )

    with pytest.raises(PaperAutomationError, match=reason):
        execute_auto_paper_cycle(
            broker=broker,
            settings=settings or make_settings(),
            allowed_symbols=("AAPL",),
            interval="1Min",
        )
    assert broker.submitted == []


def test_auto_cycle_risk_limit_and_duplicate_orders_prevent_submission(monkeypatch):
    monkeypatch.setattr(
        paper_automation,
        "select_strategy",
        lambda *args, **kwargs: selected_decision(),
    )
    broker = FakeAutoPaperBroker()
    broker.get_account = lambda: {
        "status": "ACTIVE",
        "cash": "10000",
        "buying_power": "10000",
        "equity": "9000",
        "last_equity": "10000",
        "trading_blocked": False,
    }

    result = execute_auto_paper_cycle(
        broker=broker,
        settings=make_settings(),
        allowed_symbols=("AAPL",),
        interval="1Min",
        dry_run=False,
    )

    assert result["status"] == "blocked"
    assert "daily loss limit" in result["reason"].lower()
    assert broker.submitted == []

    broker = FakeAutoPaperBroker()
    broker.orders.append({"symbol": "AAPL", "status": "accepted"})
    result = execute_auto_paper_cycle(
        broker=broker,
        settings=make_settings(),
        allowed_symbols=("AAPL",),
        interval="1Min",
        dry_run=False,
    )

    assert result["status"] == "blocked"
    assert "open paper order" in result["reason"].lower()
    assert broker.submitted == []


def test_auto_cycle_requires_verified_paper_endpoint():
    broker = FakeAutoPaperBroker()
    broker.paper_client_is_paper = False

    with pytest.raises(PaperAutomationError, match="dedicated Alpaca Paper client"):
        execute_auto_paper_cycle(
            broker=broker,
            settings=make_settings(),
            allowed_symbols=("AAPL",),
            interval="1Min",
        )

    assert broker.submitted == []


def test_alpaca_trading_client_is_constructed_only_with_paper_endpoint(monkeypatch):
    initialized = []

    class MockTradingClient:
        def __init__(self, api_key, secret_key, *, paper):
            initialized.append(paper)

    monkeypatch.setattr(alpaca_client, "TradingClient", MockTradingClient)
    monkeypatch.setattr(alpaca_client, "StockHistoricalDataClient", None)
    monkeypatch.setattr(alpaca_client, "CryptoHistoricalDataClient", None)
    monkeypatch.setattr(alpaca_client, "configure_logging", lambda _: object())
    settings = make_settings()

    broker = alpaca_client.AlpacaClient(settings)

    assert initialized == [True]
    assert broker.paper_client_configured is True
    assert broker.paper_client_is_paper is True
    broker.settings.trading_mode = "live"
    assert broker.paper_client_configured is False
    assert broker.paper_client_is_paper is False
