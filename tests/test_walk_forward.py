import math

import pandas as pd
import pytest

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.backtesting.walk_forward import walk_forward_evaluate


def market_series(periods=120):
    index = range(periods)
    close = [100 + position * 0.025 + 6 * math.sin(position * math.pi / 8) for position in index]
    open_prices = [close[0], *close[:-1]]
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC"),
        "open": open_prices,
        "close": close,
    })


def evaluator():
    settings = AppSettings(
        trading_mode="demo",
        paper_trading_enabled=True,
        auto_trade_enabled=False,
        initial_capital_eur=100,
        eur_usd_rate=1,
        risk_max_trade_fraction=0.25,
        commission_bps=10,
        spread_bps=20,
        slippage_bps=30,
    )
    return BacktestEngine(settings)


CANDIDATES = [
    {"short_window": 2, "long_window": 4},
    {"short_window": 3, "long_window": 6},
]


def run_walk_forward(data, **overrides):
    arguments = {
        "engine": evaluator(),
        "parameter_candidates": CANDIDATES,
        "training_bars": 40,
        "test_bars": 20,
        "step_bars": 20,
        "data_source": "Deterministic synthetic test series",
        "backtest_options": {
            "initial_capital": 100,
            "periods_per_year": 252,
            "risk_free_rate_annual": 0,
        },
    }
    arguments.update(overrides)
    return walk_forward_evaluate(data, **arguments)


def test_walk_forward_creates_chronological_disjoint_folds_and_costed_benchmarks():
    result = run_walk_forward(market_series())

    assert result.data_source == "Deterministic synthetic test series"
    assert result.selection_metric == "training net return after modeled costs"
    assert len(result.folds) == 4
    for fold in result.folds:
        assert fold.train_end == fold.test_start
        assert fold.test_end - fold.test_start == 20
        assert set(fold.selected_parameters) == {"short_window", "long_window"}
        assert fold.in_sample_result.initial_capital == 100
        assert fold.in_sample_result.total_trades == fold.in_sample_trades
        assert fold.in_sample_result.return_pct == pytest.approx(
            fold.in_sample_return_pct
        )
        assert fold.out_of_sample.initial_capital == 100
        assert fold.out_of_sample.benchmark_final_capital > 0
        assert fold.out_of_sample.benchmark_total_transaction_costs == pytest.approx(
            fold.out_of_sample.benchmark_fees_paid
            + fold.out_of_sample.benchmark_spread_paid
            + fold.out_of_sample.benchmark_slippage_paid
            + fold.out_of_sample.benchmark_estimated_liquidation_costs
        )
        assert fold.out_of_sample.benchmark_total_transaction_costs > 0
        assert fold.out_of_sample.total_transaction_costs == pytest.approx(
            fold.out_of_sample.fees_paid
            + fold.out_of_sample.spread_paid
            + fold.out_of_sample.slippage_paid
            + fold.out_of_sample.estimated_liquidation_costs
        )
    assert all(
        left.test_end == right.test_start
        for left, right in zip(result.folds, result.folds[1:])
    )


def test_future_test_prices_cannot_change_first_fold_parameter_selection():
    baseline_data = market_series()
    changed_future = baseline_data.copy()
    changed_future.loc[40:59, ["open", "close"]] = (
        200 - changed_future.loc[40:59, ["open", "close"]]
    )

    baseline = run_walk_forward(baseline_data).folds[0]
    changed = run_walk_forward(changed_future).folds[0]

    assert baseline.train_start == changed.train_start == 0
    assert baseline.train_end == changed.train_end == 40
    assert baseline.selected_parameters == changed.selected_parameters
    assert baseline.in_sample_return_pct == pytest.approx(changed.in_sample_return_pct)
    assert baseline.out_of_sample.return_pct != pytest.approx(
        changed.out_of_sample.return_pct
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_price", "prices must be present"),
        ("infinite_price", "prices must be present"),
        ("zero_price", "prices must be present"),
        ("duplicate_index", "strictly increasing, unique index"),
        ("unordered_index", "strictly increasing, unique index"),
        ("duplicate_timestamp", "timestamps must be valid"),
        ("unordered_timestamp", "timestamps must be valid"),
    ],
)
def test_walk_forward_rejects_missing_duplicate_and_unordered_data(mutation, message):
    data = market_series()
    if mutation == "missing_price":
        data.loc[10, "close"] = float("nan")
    elif mutation == "infinite_price":
        data.loc[10, "close"] = float("inf")
    elif mutation == "zero_price":
        data.loc[10, "close"] = 0
    elif mutation == "duplicate_index":
        data.index = [*range(60), *range(59, 119)]
    elif mutation == "unordered_index":
        data = data.iloc[::-1]
    elif mutation == "duplicate_timestamp":
        data.loc[10, "timestamp"] = data.loc[9, "timestamp"]
    else:
        data.loc[10, "timestamp"], data.loc[11, "timestamp"] = (
            data.loc[11, "timestamp"],
            data.loc[10, "timestamp"],
        )

    with pytest.raises(ValueError, match=message):
        run_walk_forward(data)


def test_walk_forward_rejects_empty_input():
    with pytest.raises(ValueError, match="non-empty dataframe"):
        run_walk_forward(pd.DataFrame())


def test_walk_forward_rejects_insufficient_samples_and_overlapping_tests():
    with pytest.raises(ValueError, match="Insufficient data"):
        run_walk_forward(market_series(59))
    with pytest.raises(ValueError, match="must be at least test_bars"):
        run_walk_forward(market_series(), step_bars=10)


def test_walk_forward_rejects_missing_data_source_and_invalid_candidates():
    with pytest.raises(ValueError, match="data source label"):
        run_walk_forward(market_series(), data_source=" ")
    with pytest.raises(ValueError, match="short_window must be smaller"):
        run_walk_forward(
            market_series(), parameter_candidates=[{"short_window": 4, "long_window": 4}]
        )
    with pytest.raises(ValueError, match="positive integer"):
        run_walk_forward(
            market_series(), parameter_candidates=[{"short_window": 2.5, "long_window": 4}]
        )


def test_failed_fold_is_reported_as_excluded_with_its_reason():
    class RejectTestFoldEngine:
        def run(self, data, **kwargs):
            if data.index[0] >= 40:
                raise ValueError("deterministic test-fold rejection")
            return evaluator().run(data, **kwargs)

    result = run_walk_forward(
        market_series(),
        engine=RejectTestFoldEngine(),
    )

    assert result.folds == []
    assert len(result.excluded_folds) == 4
    assert all(
        exclusion.reason == "deterministic test-fold rejection"
        for exclusion in result.excluded_folds
    )


def test_constant_equity_and_no_trade_period_have_unavailable_risk_metrics():
    settings = AppSettings(
        trading_mode="demo",
        paper_trading_enabled=True,
        auto_trade_enabled=False,
        initial_capital_eur=100,
        eur_usd_rate=1,
        risk_max_trade_fraction=0.25,
        commission_bps=0,
        spread_bps=0,
        slippage_bps=0,
    )
    data = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=12, freq="D", tz="UTC"),
        "open": [100] * 12,
        "close": [100] * 12,
    })
    result = BacktestEngine(settings).run(
        data,
        short_window=2,
        long_window=4,
        initial_capital=100,
        periods_per_year=252,
    )
    assert result.total_trades == 0
    assert result.return_pct == 0
    assert result.annualized_volatility_pct is None
    assert result.sharpe_ratio is None
    assert result.benchmark_annualized_volatility_pct is None
    assert result.benchmark_sharpe_ratio is None
    assert result.win_rate is None
    assert result.average_profit_per_trade is None
    assert result.average_loss_per_trade is None
    assert result.profit_factor is None
