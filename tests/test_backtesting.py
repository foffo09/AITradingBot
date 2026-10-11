import pandas as pd

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.data.market_data import generate_synthetic_market_data
from src.risk.risk_manager import RiskManager


def test_backtest_contains_drawdown_and_return_metrics():
    settings = AppSettings(trading_mode="paper", alpaca_api_key="KEY", alpaca_secret_key="SECRET", paper_trading_enabled=True)
    engine = BacktestEngine(settings=settings)
    data = generate_synthetic_market_data(periods=180)

    result = engine.run(data)
    assert result.final_capital >= 0
    assert result.total_trades >= 0
    assert result.max_drawdown_pct >= 0
    assert result.win_rate >= 0
    assert len(result.equity_curve) > 1


def test_drawdown_calculation_for_equity_curve():
    manager = RiskManager(AppSettings(trading_mode="paper", alpaca_api_key="KEY", alpaca_secret_key="SECRET", paper_trading_enabled=True))
    metrics = manager.compute_drawdown([100, 110, 95, 105, 90, 100])
    assert metrics["max_drawdown"] == 18.18
    assert metrics["peak"] == 110
    assert metrics["trough"] == 90
