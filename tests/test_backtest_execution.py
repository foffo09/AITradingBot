import pandas as pd
import pytest

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine


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


def test_backtest_rejects_missing_prices():
    settings = AppSettings(
        trading_mode="paper", alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        paper_trading_enabled=True,
    )
    data = pd.DataFrame({"open": [10, None], "close": [10, 11]})
    with pytest.raises(ValueError, match="must be present and positive"):
        BacktestEngine(settings).run(data)
