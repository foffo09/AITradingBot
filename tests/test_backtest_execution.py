import pandas as pd
import pytest

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine, backtest_input_key


def test_backtest_executes_after_signal_not_using_signal_bar_price():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True, initial_capital_eur=100, eur_usd_rate=1,
        risk_max_trade_fraction=0.2, commission_bps=0, slippage_bps=0,
    )
    data = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=7, freq="D", tz="UTC"),
        "open": [10, 10, 10, 12, 50, 13, 40],
        "close": [10, 10, 10, 12, 13, 9, 8],
    })
    result = BacktestEngine(settings).run(data, short_window=2, long_window=3, initial_capital=100)
    assert result.total_trades == 1
    trade = result.trade_history[0]
    assert trade["status"] == "closed"
    assert trade["opened_at"] == str(data["timestamp"].iloc[4])
    assert trade["entry_price"] == pytest.approx(50)
    assert trade["closed_at"] == str(data["timestamp"].iloc[6])
    assert trade["exit_price"] == pytest.approx(40)
    assert trade["net_pnl"] == pytest.approx(-4)
    assert result.losing_trades == 1


@pytest.mark.parametrize("invalid_price", [None, float("nan"), float("inf"), 0, -1])
def test_backtest_rejects_missing_or_invalid_prices(invalid_price):
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    data = pd.DataFrame({"open": [10, invalid_price], "close": [10, 11]})
    with pytest.raises(ValueError, match="must be present and positive"):
        BacktestEngine(settings).run(data)


def test_backtest_pnl_separates_gross_and_all_execution_costs():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True, initial_capital_eur=100, eur_usd_rate=1,
        risk_max_trade_fraction=0.2, commission_bps=100, spread_bps=100, slippage_bps=100,
    )
    data = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=7, freq="D", tz="UTC"),
        "open": [10, 10, 10, 12, 50, 13, 40],
        "close": [10, 10, 10, 12, 13, 9, 8],
    })
    result = BacktestEngine(settings).run(
        data, short_window=2, long_window=3, initial_capital=100,
    )
    trade = result.trade_history[0]
    assert trade["gross_pnl"] == pytest.approx(trade["quantity"] * (40 - 50))
    assert trade["net_pnl"] == pytest.approx(
        trade["gross_pnl"]
        - trade["entry_fee"]
        - trade["exit_fee"]
        - trade["entry_spread"]
        - trade["exit_spread"]
        - trade["entry_slippage"]
        - trade["exit_slippage"]
    )
    assert result.gross_pnl == pytest.approx(trade["gross_pnl"])
    assert result.net_pnl == pytest.approx(trade["net_pnl"])
    assert result.final_capital == pytest.approx(result.initial_capital + result.net_pnl)
    assert result.total_transaction_costs == pytest.approx(
        result.fees_paid + result.spread_paid + result.slippage_paid
    )
    closed_pnls = [
        trade["net_pnl"]
        for trade in result.trade_history
        if trade["status"] == "closed"
    ]
    winners = [pnl for pnl in closed_pnls if pnl > 0]
    losers = [pnl for pnl in closed_pnls if pnl < 0]
    assert result.average_profit_per_trade == (
        pytest.approx(sum(winners) / len(winners)) if winners else None
    )
    assert result.average_loss_per_trade == (
        pytest.approx(sum(losers) / len(losers)) if losers else None
    )
    assert result.profit_factor == (
        pytest.approx(sum(winners) / abs(sum(losers))) if losers else None
    )


def test_backtest_input_key_changes_with_data_source_or_parameters():
    data = pd.DataFrame({"open": [10, 11], "close": [10, 11]})
    parameters = {"short_window": 2, "long_window": 4}
    baseline = backtest_input_key(data, source="Alpaca", parameters=parameters)
    assert backtest_input_key(data.copy(), source="Alpaca", parameters=parameters) == baseline
    assert backtest_input_key(data, source="demo", parameters=parameters) != baseline
    assert backtest_input_key(
        data, source="Alpaca", parameters={**parameters, "short_window": 3}
    ) != baseline
    assert backtest_input_key(
        data.assign(close=[10, 12]), source="Alpaca", parameters=parameters
    ) != baseline


def test_backtest_rejects_insufficient_history_for_execution():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    data = pd.DataFrame({"open": [10, 11, 12], "close": [10, 11, 12]})
    with pytest.raises(ValueError, match="at least 5 bars"):
        BacktestEngine(settings).run(data, short_window=2, long_window=3)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (pd.DataFrame(), "data is empty"),
        (pd.DataFrame({"close": [10] * 5}), "must contain open and close"),
    ],
)
def test_backtest_rejects_empty_or_malformed_input(data, message):
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    with pytest.raises(ValueError, match=message):
        BacktestEngine(settings).run(data, short_window=2, long_window=3)


@pytest.mark.parametrize(
    ("short_window", "long_window", "message"),
    [(2.5, 4, "must be integers"), (3, 3, "short_window must be smaller")],
)
def test_backtest_rejects_invalid_moving_average_windows(
    short_window, long_window, message,
):
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    data = pd.DataFrame({"open": [10] * 8, "close": [10] * 8})
    with pytest.raises(ValueError, match=message):
        BacktestEngine(settings).run(
            data, short_window=short_window, long_window=long_window,
        )


def test_open_position_is_marked_to_net_liquidation_value():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True, initial_capital_eur=100, eur_usd_rate=1,
        risk_max_trade_fraction=0.2, commission_bps=100, spread_bps=100, slippage_bps=100,
    )
    data = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=6, freq="D", tz="UTC"),
        "open": [10, 10, 10, 12, 50, 13],
        "close": [10, 10, 10, 12, 13, 9],
    })
    result = BacktestEngine(settings).run(
        data, short_window=2, long_window=3, initial_capital=100,
    )
    trade = result.trade_history[0]
    assert trade["status"] == "open"
    assert result.open_position_quantity == pytest.approx(trade["quantity"])
    assert result.unrealized_gross_pnl == pytest.approx(
        trade["quantity"] * (9 - trade["entry_market_price"])
    )
    assert trade["gross_pnl"] is None
    assert trade["net_pnl"] is None
    assert trade["unrealized_gross_pnl"] == pytest.approx(result.unrealized_gross_pnl)
    assert trade["unrealized_net_pnl"] == pytest.approx(result.unrealized_net_pnl)
    assert result.estimated_liquidation_costs > 0
    assert result.total_transaction_costs == pytest.approx(
        result.fees_paid + result.spread_paid + result.slippage_paid
        + result.estimated_liquidation_costs
    )
    assert result.final_capital == pytest.approx(result.equity_curve[-1])


def test_buy_and_hold_uses_same_period_and_execution_cost_model():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True, initial_capital_eur=100, eur_usd_rate=1,
        risk_max_trade_fraction=0.2, commission_bps=10, spread_bps=20, slippage_bps=30,
    )
    data = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=7, freq="D", tz="UTC"),
        "open": [10, 10, 10, 12, 50, 13, 40],
        "close": [10, 10, 10, 12, 13, 9, 8],
    })
    result = BacktestEngine(settings).run(
        data, short_window=2, long_window=3, initial_capital=100,
        periods_per_year=252, risk_free_rate_annual=0,
    )
    benchmark_quantity = 100 / (10.04 * 1.001)
    expected_benchmark_final = benchmark_quantity * 8 * (1 - 0.004) * (1 - 0.001)
    assert result.benchmark_final_capital == pytest.approx(expected_benchmark_final)
    assert result.benchmark_return_pct == pytest.approx(
        (result.benchmark_final_capital / result.initial_capital - 1) * 100
    )
    assert result.benchmark_total_transaction_costs == pytest.approx(
        result.benchmark_fees_paid + result.benchmark_spread_paid
        + result.benchmark_slippage_paid + result.benchmark_estimated_liquidation_costs
    )
    assert result.periods_per_year == 252
    assert result.risk_free_rate_annual == 0
    assert result.annualized_volatility_pct is not None
    assert result.benchmark_annualized_volatility_pct is not None
    assert result.sharpe_ratio is not None
    assert result.benchmark_sharpe_ratio is not None


def test_risk_metrics_are_unavailable_for_insufficient_or_flat_returns():
    assert BacktestEngine._risk_metrics(
        [100, 101], periods_per_year=252, risk_free_rate_annual=0,
    ) == (None, None)
    volatility, sharpe = BacktestEngine._risk_metrics(
        [100, 100, 100], periods_per_year=252, risk_free_rate_annual=0,
    )
    assert volatility is None
    assert sharpe is None


def test_risk_metrics_use_sample_volatility_and_explicit_annualization():
    volatility, sharpe = BacktestEngine._risk_metrics(
        [100, 110, 99], periods_per_year=252, risk_free_rate_annual=0,
    )
    expected_volatility = pd.Series([0.1, -0.1]).std(ddof=1) * (252 ** 0.5) * 100
    assert volatility == pytest.approx(expected_volatility)
    assert sharpe == pytest.approx(0)


@pytest.mark.parametrize(
    ("interval", "crypto", "expected"),
    [("1Day", False, 252), ("1Day", True, 365), ("1Hour", True, 8760)],
)
def test_period_annualization_is_explicit_for_market_frequency(interval, crypto, expected):
    assert BacktestEngine.periods_per_year_for_interval(interval, crypto=crypto) == expected


@pytest.mark.parametrize("rate", [-0.01, float("nan"), float("inf"), 1.1])
def test_backtest_rejects_invalid_annual_risk_free_rate(rate):
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    data = pd.DataFrame({"open": [10] * 5, "close": [10] * 5})
    with pytest.raises(ValueError, match="Annual risk-free rate"):
        BacktestEngine(settings).run(
            data, short_window=2, long_window=3, risk_free_rate_annual=rate,
        )
