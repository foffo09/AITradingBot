from __future__ import annotations

import math
from types import SimpleNamespace

import pandas as pd
import pytest

from config.settings import AppSettings
from src.strategy import auto_selector
from src.strategy.auto_selector import SelectionCriteria, select_strategy


CANDIDATES = (
    {"short_window": 2, "long_window": 4},
    {"short_window": 3, "long_window": 6},
)


def settings() -> AppSettings:
    return AppSettings(
        trading_mode="demo",
        paper_trading_enabled=True,
        auto_trade_enabled=False,
        initial_capital_eur=1_000,
        eur_usd_rate=1,
        risk_max_trade_fraction=0.2,
        risk_max_exposure_fraction=0.5,
        daily_loss_limit_pct=0.05,
        commission_bps=12,
        spread_bps=8,
        slippage_bps=5,
    )


def real_market_data(
    *,
    periods: int = 80,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    end = as_of or pd.Timestamp("2025-04-01T00:00:00Z")
    timestamps = pd.date_range(end=end - pd.Timedelta(days=2), periods=periods, freq="B")
    close = [100.0] * (periods - 2) + [80.0, 140.0]
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "open": close,
        "high": [price + 1 for price in close],
        "low": [price - 1 for price in close],
        "close": close,
        "volume": [1_000] * periods,
    })
    frame.attrs.update({"quality": "real", "interval": "1Day"})
    return frame


def stub_walk_forward(data, *, parameter_candidates, backtest_options, **kwargs):
    assert backtest_options["commission_bps"] == 12
    assert backtest_options["spread_bps"] == 8
    assert backtest_options["slippage_bps"] == 5
    assert tuple(parameter_candidates) == CANDIDATES
    short_candidate, long_candidate = parameter_candidates
    return SimpleNamespace(folds=[
        SimpleNamespace(
            selected_parameters=short_candidate,
            in_sample_return_pct=2.0,
            out_of_sample=SimpleNamespace(
                total_trades=2,
                return_pct=4.0,
                max_drawdown_pct=3.0,
                win_rate=50.0,
            ),
        ),
        SimpleNamespace(
            selected_parameters=short_candidate,
            in_sample_return_pct=3.0,
            out_of_sample=SimpleNamespace(
                total_trades=2,
                return_pct=6.0,
                max_drawdown_pct=5.0,
                win_rate=75.0,
            ),
        ),
        SimpleNamespace(
            selected_parameters=long_candidate,
            in_sample_return_pct=1.0,
            out_of_sample=SimpleNamespace(
                total_trades=2,
                return_pct=1.0,
                max_drawdown_pct=4.0,
                win_rate=50.0,
            ),
        ),
        SimpleNamespace(
            selected_parameters=short_candidate,
            in_sample_return_pct=4.0,
            out_of_sample=SimpleNamespace(
                total_trades=2,
                return_pct=5.0,
                max_drawdown_pct=2.0,
                win_rate=60.0,
            ),
        ),
    ])


def select(data: pd.DataFrame, *, criteria: SelectionCriteria | None = None):
    as_of = data["timestamp"].iloc[-1] + pd.Timedelta(days=2)
    return select_strategy(
        {"SPY": data},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        criteria=criteria,
        as_of=as_of,
    )


def test_selects_walk_forward_validated_ma_and_sizes_with_risk_manager(monkeypatch):
    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", stub_walk_forward)

    result = select(real_market_data())

    assert result.status == "SELECTED"
    assert result.asset == "SPY"
    assert result.strategy == "moving_average"
    assert result.parameters == {"short_window": 2, "long_window": 4}
    assert result.side == "buy"
    assert result.proposed_quantity == pytest.approx(200 / 140)
    assert result.evaluations[0].validation_folds == 3
    assert result.evaluations[0].oos_trades == 6
    assert result.evaluations[0].mean_oos_return_pct == pytest.approx(5.0)
    assert "rendimento medio netto +5.00%" in result.reason


def test_returns_no_trade_when_oos_candidate_fails_explicit_criteria(monkeypatch):
    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", stub_walk_forward)

    result = select(
        real_market_data(),
        criteria=SelectionCriteria(min_mean_oos_return_pct=5.0),
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert "Nessun candidato" in result.reason


def test_returns_no_trade_when_any_oos_fold_exceeds_drawdown_limit(monkeypatch):
    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", stub_walk_forward)

    result = select(
        real_market_data(),
        criteria=SelectionCriteria(max_oos_drawdown_pct=4.0),
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert "Nessun candidato" in result.reason


def test_rejects_insufficient_history_without_running_walk_forward(monkeypatch):
    monkeypatch.setattr(
        auto_selector,
        "walk_forward_evaluate",
        lambda *args, **kwargs: pytest.fail("Walk-forward must not run on stale/short data."),
    )

    result = select(real_market_data(periods=12))

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert any("dati insufficienti" in item for item in result.exclusions)


def test_daily_equity_forming_bar_is_excluded_from_selector():
    frame = real_market_data(
        periods=2,
        as_of=pd.Timestamp("2025-07-04T00:00:00Z"),
    ).tail(1).reset_index(drop=True)
    result = select_strategy(
        {"AAPL": frame},
        asset_availability={"AAPL": True},
        interval="1Day",
        parameter_candidates=({"short_window": 1, "long_window": 2},),
        training_bars=4,
        test_bars=4,
        settings=settings(),
        available_cash=1_000,
        as_of=pd.Timestamp("2025-07-02T19:00:00Z"),
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert any("nessuna barra completata" in item for item in result.exclusions)


def test_selector_rejects_future_bar_timestamp():
    frame = real_market_data(
        periods=2,
        as_of=pd.Timestamp("2025-07-04T00:00:00Z"),
    ).tail(1).reset_index(drop=True)
    frame.loc[0, "timestamp"] = pd.Timestamp("2025-07-02T20:01:00Z")
    result = select_strategy(
        {"AAPL": frame},
        asset_availability={"AAPL": True},
        interval="1Day",
        parameter_candidates=({"short_window": 1, "long_window": 2},),
        training_bars=4,
        test_bars=4,
        settings=settings(),
        available_cash=1_000,
        as_of=pd.Timestamp("2025-07-02T19:59:00Z"),
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert any("timestamp dell'ultima barra nel futuro" in item for item in result.exclusions)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda frame: frame.attrs.update(quality="synthetic"), "dati storici reali"),
        (
            lambda frame: frame.__setitem__(
                "timestamp",
                pd.date_range("2020-01-01", periods=len(frame), freq="D", tz="UTC"),
            ),
            "dati obsoleti",
        ),
    ],
)
def test_excludes_non_real_or_stale_asset_data(mutate, reason):
    frame = real_market_data()
    mutate(frame)

    result = select_strategy(
        {"SPY": frame},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        as_of=pd.Timestamp("2025-04-03T00:00:00Z"),
    )

    assert result.status == "NO_TRADE"
    assert any(reason in item for item in result.exclusions)


def test_returns_no_trade_when_strategy_has_no_current_crossover(monkeypatch):
    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", stub_walk_forward)
    frame = real_market_data()
    frame["close"] = 100.0
    frame["open"] = 100.0

    result = select(frame)

    assert result.status == "NO_TRADE"
    assert result.asset == "SPY"
    assert result.parameters == {"short_window": 2, "long_window": 4}
    assert result.proposed_quantity is None
    assert "nessun incrocio operativo" in result.reason


def test_risk_manager_blocks_quantity_proposal_when_daily_limit_is_hit(monkeypatch):
    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", stub_walk_forward)
    frame = real_market_data()
    as_of = frame["timestamp"].iloc[-1] + pd.Timedelta(days=2)

    result = select_strategy(
        {"SPY": frame},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        pnl_today=-100,
        as_of=as_of,
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert "daily loss limit" in result.reason.lower()


def test_unsupported_and_unverified_assets_are_excluded():
    frame = real_market_data()
    result = select_strategy(
        {"NOT-A-SUPPORTED-ASSET": frame, "SPY": frame},
        asset_availability={"SPY": False},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        as_of=frame["timestamp"].iloc[-1] + pd.Timedelta(days=2),
    )

    assert result.status == "NO_TRADE"
    assert any("non presente nel catalogo" in item for item in result.exclusions)
    assert any("negoziabilità non verificata" in item for item in result.exclusions)


def test_real_walk_forward_evaluator_supplies_costed_oos_evidence():
    as_of = pd.Timestamp("2025-04-01T00:00:00Z")
    frame = real_market_data(periods=140, as_of=as_of)
    index = range(len(frame))
    close = [
        100 + position * 0.025 + 6 * math.sin(position * math.pi / 8)
        for position in index
    ]
    frame["close"] = close
    frame["open"] = [close[0], *close[:-1]]
    result = select_strategy(
        {"SPY": frame},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=50,
        test_bars=20,
        settings=settings(),
        available_cash=1_000,
        criteria=SelectionCriteria(min_oos_trades=10_000),
        as_of=as_of,
    )

    assert result.status == "NO_TRADE"
    assert result.evaluations
    assert all(evaluation.validation_folds > 0 for evaluation in result.evaluations)
    assert result.proposed_quantity is None


def test_walk_forward_result_is_reused_only_for_identical_fresh_data(monkeypatch):
    calls = []

    def counted_walk_forward(*args, **kwargs):
        calls.append(1)
        return stub_walk_forward(*args, **kwargs)

    monkeypatch.setattr(auto_selector, "walk_forward_evaluate", counted_walk_forward)
    frame = real_market_data(as_of=pd.Timestamp("2025-05-15T00:00:00Z"))
    decision_time = frame["timestamp"].iloc[-1] + pd.Timedelta(days=2)

    first = select_strategy(
        {"SPY": frame},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        as_of=decision_time,
    )
    second = select_strategy(
        {"SPY": frame.copy()},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=settings(),
        available_cash=1_000,
        as_of=decision_time,
    )

    assert first.status == second.status == "SELECTED"
    assert len(calls) == 1


def test_live_mode_is_never_eligible_for_strategy_selection(monkeypatch):
    monkeypatch.setattr(
        auto_selector,
        "walk_forward_evaluate",
        lambda *args, **kwargs: pytest.fail("Live mode must not evaluate candidates."),
    )
    live_settings = settings()
    live_settings.trading_mode = "live"
    frame = real_market_data()

    result = select_strategy(
        {"SPY": frame},
        asset_availability={"SPY": True},
        interval="1Day",
        parameter_candidates=CANDIDATES,
        training_bars=20,
        test_bars=10,
        settings=live_settings,
        available_cash=1_000,
        as_of=frame["timestamp"].iloc[-1] + pd.Timedelta(days=2),
    )

    assert result.status == "NO_TRADE"
    assert result.proposed_quantity is None
    assert "solo in modalità Demo o Alpaca Paper" in result.reason
