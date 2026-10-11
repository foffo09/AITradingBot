import math
from datetime import datetime, timezone

import pytest

from src.simulation.ledger import (
    SimulationLedger,
    resolve_simulation_database_path,
)


def test_demo_database_uses_isolated_file_and_preserves_personal_ledger(tmp_path):
    project_root = tmp_path / "project"
    personal_database = project_root / "data" / "simulation.sqlite3"
    personal_database.parent.mkdir(parents=True)
    personal_database.write_bytes(b"personal ledger sentinel")
    demo_database = tmp_path / "LocalAppData" / "AITradingBot" / "demo" / "simulation.sqlite3"

    resolved_path = resolve_simulation_database_path(project_root, demo_database)
    ledger = SimulationLedger(resolved_path)

    assert resolved_path == demo_database.resolve()
    assert ledger.database_path == resolved_path
    assert resolved_path.is_file()
    assert personal_database.read_bytes() == b"personal ledger sentinel"


def test_default_database_path_remains_the_project_ledger(tmp_path):
    assert resolve_simulation_database_path(tmp_path) == (
        tmp_path / "data" / "simulation.sqlite3"
    ).resolve()


@pytest.mark.parametrize(
    ("configured_path", "message"),
    [
        ("", "path is required"),
        ("relative-demo.sqlite3", "absolute path"),
    ],
)
def test_demo_database_rejects_missing_or_relative_path(
    tmp_path, configured_path, message
):
    with pytest.raises(ValueError, match=message):
        resolve_simulation_database_path(tmp_path, configured_path)


def test_demo_database_rejects_personal_ledger_path(tmp_path):
    personal_database = tmp_path / "data" / "simulation.sqlite3"

    with pytest.raises(ValueError, match="personal simulation ledger"):
        resolve_simulation_database_path(tmp_path, personal_database)


def test_demo_database_rejects_directory_path(tmp_path):
    demo_directory = tmp_path / "demo-database"
    demo_directory.mkdir()

    with pytest.raises(ValueError, match="must be a file path"):
        resolve_simulation_database_path(tmp_path, demo_directory)


def make_ledger(path, rate=1.1):
    ledger = SimulationLedger(path)
    ledger.initialize_account(
        initial_eur=100,
        eur_usd_rate=rate,
        fx_source="test FX",
        fx_timestamp="2026-01-01",
    )
    return ledger


def buy(ledger, **kwargs):
    defaults = {
        "symbol": "AAPL",
        "quantity": 1,
        "market_price": 50,
        "commission_bps": 100,
        "slippage_bps": 100,
        "max_trade_fraction": 0.5,
        "max_exposure_fraction": 1.0,
        "daily_loss_limit_fraction": 0.1,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "test feed",
        "reason": "test entry",
        "idempotency_key": "buy-request-1",
    }
    defaults.update(kwargs)
    return ledger.buy(**defaults)


def test_fx_initial_capital_costs_and_partial_close_math(tmp_path):
    ledger = make_ledger(tmp_path / "account.sqlite3", rate=1.1)
    assert ledger.account()["initial_cash"] == pytest.approx(110)
    result = buy(ledger)
    assert result["fill_price"] == pytest.approx(50.5)
    assert result["fee"] == pytest.approx(0.505)
    assert ledger.account()["cash"] == pytest.approx(58.995)

    closed = ledger.sell(
        symbol="AAPL",
        quantity=0.4,
        market_price=55,
        commission_bps=100,
        slippage_bps=100,
        data_timestamp=datetime.now(timezone.utc).isoformat(),
        data_source="test feed",
        reason="partial exit",
        idempotency_key="sell-request-1",
    )
    assert closed["net_pnl"] == pytest.approx(1.1602)
    summary = ledger.summary(commission_bps=100, slippage_bps=100)
    assert summary["realized_pnl"] == pytest.approx(1.1602)
    assert summary["closed_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["win_rate"] == pytest.approx(100)
    assert summary["open_positions"] == 1
    assert ledger.positions()[0]["quantity"] == pytest.approx(0.6)
    history = ledger.history()
    assert {row["status"] for row in history} == {"open", "closed"}
    closed_trade = next(row for row in history if row["status"] == "closed")
    assert closed_trade["gross_pnl"] == pytest.approx(2.0)
    assert closed_trade["net_pnl"] == pytest.approx(
        closed_trade["gross_pnl"]
        - closed_trade["entry_fee_alloc"]
        - closed_trade["exit_fee"]
        - closed_trade["entry_spread_alloc"]
        - closed_trade["exit_spread"]
        - closed_trade["entry_slippage_alloc"]
        - closed_trade["exit_slippage"]
    )
    assert summary["fx_source"] == "test FX"
    assert summary["return_pct"] == pytest.approx(summary["total_pnl"] / 110 * 100)


def test_cash_risk_short_and_stale_guard_inputs_are_validated(tmp_path):
    ledger = make_ledger(tmp_path / "cash.sqlite3")
    with pytest.raises(ValueError, match="stale or has a future timestamp"):
        buy(ledger, data_timestamp="2020-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="Insufficient simulation cash"):
        buy(ledger, quantity=2.1, max_trade_fraction=1, commission_bps=1000)
    with pytest.raises(ValueError, match="maximum per-trade"):
        buy(ledger, quantity=2, max_trade_fraction=0.5)
    buy(ledger, quantity=1, commission_bps=0, slippage_bps=0, max_trade_fraction=1)
    with pytest.raises(ValueError, match="short selling is disabled"):
        ledger.sell(
            symbol="AAPL", quantity=2, market_price=51, commission_bps=0,
                slippage_bps=0, data_timestamp=datetime.now(timezone.utc).isoformat(),
                data_source="test feed", reason="invalid short", idempotency_key="sell-too-much",
        )


def test_idempotency_and_persistence_across_instances(tmp_path):
    db_path = tmp_path / "persist.sqlite3"
    ledger = make_ledger(db_path, rate=1.2)
    first = buy(ledger, commission_bps=0, slippage_bps=0, max_trade_fraction=1)
    duplicate = buy(ledger, commission_bps=0, slippage_bps=0, max_trade_fraction=1)
    assert first["id"] == duplicate["id"]
    assert duplicate["duplicate"] is True

    restored = SimulationLedger(db_path)
    assert restored.account()["initial_eur"] == pytest.approx(100)
    assert restored.account()["cash"] == pytest.approx(70)
    assert len(restored.history()) == 1


def test_summary_handles_no_trades_and_profit_factor_zero_loss(tmp_path):
    ledger = make_ledger(tmp_path / "metrics.sqlite3")
    summary = ledger.summary(commission_bps=0, slippage_bps=0)
    assert summary["win_rate"] == 0
    assert summary["closed_trades"] == 0
    assert summary["profit_factor"] == 0
    buy(ledger, quantity=1, commission_bps=0, slippage_bps=0, max_trade_fraction=1)
    ledger.update_mark("AAPL", 60, "2026-01-02T12:00:00+00:00", "test feed")
    ledger.sell(
        symbol="AAPL", quantity=1, market_price=60, commission_bps=0,
        slippage_bps=0, data_timestamp=datetime.now(timezone.utc).isoformat(),
        data_source="test feed", reason="profit", idempotency_key="sell-profit",
    )
    summary = ledger.summary(commission_bps=0, slippage_bps=0)
    assert math.isinf(summary["profit_factor"])
    assert summary["average_win"] == pytest.approx(10)
    assert summary["max_drawdown_pct"] >= 0
    assert all("timestamp" in row and "equity" in row for row in summary["equity_curve"])


def test_spread_is_applied_to_both_execution_sides_and_reported(tmp_path):
    ledger = make_ledger(tmp_path / "spread.sqlite3")
    bought = buy(
        ledger, quantity=1, market_price=50, commission_bps=0, spread_bps=100,
        slippage_bps=0, max_trade_fraction=1,
    )
    assert bought["fill_price"] == pytest.approx(50.25)
    result = ledger.sell(
        symbol="AAPL", quantity=1, market_price=60, commission_bps=0,
        spread_bps=100, slippage_bps=0, data_timestamp=datetime.now(timezone.utc).isoformat(),
        data_source="test feed", reason="spread test", idempotency_key="sell-spread",
    )
    assert result["net_pnl"] == pytest.approx(9.45)
    summary = ledger.summary(commission_bps=0, slippage_bps=0, spread_bps=100)
    assert summary["spread"] == pytest.approx(0.55)


def test_daily_realized_loss_limit_blocks_new_entries(tmp_path):
    ledger = make_ledger(tmp_path / "daily-loss.sqlite3")
    buy(ledger, commission_bps=0, spread_bps=0, slippage_bps=0, max_trade_fraction=1)
    ledger.sell(
        symbol="AAPL", quantity=1, market_price=44, commission_bps=0,
        spread_bps=0, slippage_bps=0, data_timestamp=datetime.now(timezone.utc).isoformat(),
        data_source="test feed", reason="loss", idempotency_key="sell-loss",
    )
    with pytest.raises(ValueError, match="Daily loss limit reached"):
        buy(
            ledger, symbol="MSFT", quantity=1, market_price=10, commission_bps=0,
            spread_bps=0, slippage_bps=0, max_trade_fraction=1,
            daily_loss_limit_fraction=0.05, idempotency_key="buy-after-loss",
        )


def test_daily_loss_limit_includes_unrealized_losses(tmp_path):
    ledger = make_ledger(tmp_path / "daily-unrealized.sqlite3")
    buy(
        ledger, quantity=1, market_price=100, commission_bps=0, spread_bps=0,
        slippage_bps=0, max_trade_fraction=1, daily_loss_limit_fraction=0.05,
    )
    ledger.update_mark("AAPL", 90, datetime.now(timezone.utc).isoformat(), "test feed")
    with pytest.raises(ValueError, match="Daily loss limit reached"):
        buy(
            ledger, symbol="MSFT", quantity=1, market_price=5, commission_bps=0,
            spread_bps=0, slippage_bps=0, max_trade_fraction=1,
            daily_loss_limit_fraction=0.05, idempotency_key="buy-after-unrealized-loss",
        )


def test_reset_requires_new_explicit_account_parameters(tmp_path):
    ledger = make_ledger(tmp_path / "reset.sqlite3")
    buy(ledger, commission_bps=0, slippage_bps=0, max_trade_fraction=1)
    ledger.reset(
        initial_eur=75,
        eur_usd_rate=1.2,
        fx_source="user-confirmed",
        fx_timestamp="2026-02-01",
    )
    assert ledger.history() == []
    assert ledger.account()["cash"] == pytest.approx(90)
