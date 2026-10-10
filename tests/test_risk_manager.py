import pytest

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager, RiskViolationError
from src.trading.paper_trader import PaperTrader


def test_invalid_quantity_is_blocked():
    settings = AppSettings(trading_mode="paper", alpaca_api_key="KEY", alpaca_secret_key="SECRET", paper_trading_enabled=True)
    manager = RiskManager(settings)

    with pytest.raises(RiskViolationError):
        manager.validate_order(side="buy", quantity=0, price=100, available_cash=1000)


def test_insufficient_capital_is_blocked():
    settings = AppSettings(trading_mode="paper", alpaca_api_key="KEY", alpaca_secret_key="SECRET", paper_trading_enabled=True)
    manager = RiskManager(settings)
    result = manager.validate_order(side="buy", quantity=1000, price=100, available_cash=5000)
    assert result.ok is False
    assert result.blocked_by in {"cash", "max_trade_fraction"}


def test_paper_mode_is_required_for_simulated_orders():
    settings = AppSettings(trading_mode="paper", alpaca_api_key="KEY", alpaca_secret_key="SECRET", paper_trading_enabled=False)
    trader = PaperTrader(settings=settings)

    with pytest.raises(PermissionError):
        trader.place_order(symbol="AAPL", side="buy", quantity=1, price=10, available_cash=1000)
