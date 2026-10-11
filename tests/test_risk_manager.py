import pytest

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient
from src.risk.risk_manager import RiskManager, RiskViolationError
from src.trading.paper_trader import PaperTrader


def make_settings(**overrides):
    values = {
        "trading_mode": "demo",
        "paper_trading_enabled": True,
        "alpaca_api_key": "test-key",
        "alpaca_secret_key": "test-secret",
        "initial_capital_eur": 100,
        "eur_usd_rate": 1,
        "risk_max_trade_fraction": 0.5,
        "risk_max_exposure_fraction": 0.8,
        "daily_loss_limit_pct": 0.05,
    }
    values.update(overrides)
    return AppSettings(**values)


def test_invalid_quantity_is_blocked():
    manager = RiskManager(make_settings())

    with pytest.raises(RiskViolationError):
        manager.validate_order(side="buy", quantity=0, price=100, available_cash=1000)


def test_insufficient_capital_is_blocked():
    manager = RiskManager(make_settings(risk_max_trade_fraction=1))
    result = manager.validate_order(side="buy", quantity=1, price=10, available_cash=5)
    assert result.ok is False
    assert result.blocked_by == "cash"


def test_valid_buy_is_approved():
    result = RiskManager(make_settings()).validate_order(
        side="buy", quantity=2, price=10, available_cash=50, symbol="AAPL"
    )
    assert result.ok is True
    assert result.notional == 20
    assert result.reason == "BUY 2.0 AAPL"


@pytest.mark.parametrize(
    ("side", "quantity", "position", "expected"),
    [
        ("sell", 2, 5, True),
        ("sell", 5, 5, True),
    ],
)
def test_partial_and_full_long_sales_are_approved(side, quantity, position, expected):
    result = RiskManager(make_settings(risk_max_trade_fraction=0.01)).validate_order(
        side=side,
        quantity=quantity,
        price=100,
        available_cash=0,
        current_position=position,
    )
    assert result.ok is expected
    assert result.blocked_by == ""


def test_sale_can_reduce_position_even_when_existing_exposure_exceeds_limit():
    result = RiskManager(make_settings(risk_max_exposure_fraction=0.1)).validate_order(
        side="sell", quantity=1, price=100, available_cash=0, current_position=10
    )
    assert result.ok is True


def test_sale_larger_than_long_position_is_rejected_without_shorting():
    result = RiskManager(make_settings()).validate_order(
        side="sell", quantity=1.1, price=10, available_cash=100, current_position=1
    )
    assert result.ok is False
    assert result.blocked_by == "position"
    assert "short selling is disabled" in result.reason


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf"), float("-inf"), None])
@pytest.mark.parametrize("field", ["quantity", "price"])
def test_invalid_order_quantity_and_price_are_rejected(invalid, field):
    values = {"quantity": 1, "price": 10}
    values[field] = invalid
    with pytest.raises(RiskViolationError, match="finite|positive"):
        RiskManager(make_settings()).validate_order(
            side="buy", available_cash=100, **values
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("available_cash", float("nan")),
        ("available_cash", float("inf")),
        ("available_cash", -1),
        ("current_position", float("nan")),
        ("current_position", float("inf")),
        ("current_position", -1),
        ("pnl_today", float("nan")),
        ("pnl_today", float("inf")),
    ],
)
def test_invalid_cash_position_and_daily_pnl_are_rejected(field, value):
    arguments = {
        "side": "buy",
        "quantity": 1,
        "price": 1,
        "available_cash": 100,
    }
    arguments[field] = value
    with pytest.raises(RiskViolationError):
        RiskManager(make_settings()).validate_order(**arguments)


def test_exposure_limit_blocks_new_buy():
    manager = RiskManager(make_settings(risk_max_exposure_fraction=0.2))
    result = manager.validate_order(
        side="buy", quantity=3, price=10, available_cash=100
    )
    assert result.ok is False
    assert result.blocked_by == "max_exposure_fraction"
    assert result.notional == 30


def test_daily_loss_limit_blocks_buys_but_allows_risk_reducing_sales():
    manager = RiskManager(make_settings())
    blocked = manager.validate_order(
        side="buy", quantity=1, price=1, available_cash=100, pnl_today=-5
    )
    allowed_sale = manager.validate_order(
        side="sell", quantity=1, price=1, available_cash=0,
        current_position=1, pnl_today=-5,
    )
    assert blocked.ok is False
    assert blocked.blocked_by == "daily_loss_limit"
    assert allowed_sale.ok is True
    assert manager.check_daily_loss_limit(-4.99) is True
    assert manager.check_daily_loss_limit(-5) is False


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), None])
def test_daily_loss_limit_rejects_non_finite_values(invalid):
    with pytest.raises(RiskViolationError, match="finite"):
        RiskManager(make_settings()).check_daily_loss_limit(invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1])
def test_drawdown_rejects_invalid_equity(invalid):
    with pytest.raises(RiskViolationError):
        RiskManager(make_settings()).compute_drawdown([100, invalid])


def test_paper_trader_does_not_send_orders_to_broker(monkeypatch):
    submitted = []
    monkeypatch.setattr(AlpacaClient, "submit_order", lambda *args, **kwargs: submitted.append(True))
    trader = PaperTrader(settings=make_settings())
    result = trader.place_order(
        symbol="AAPL", side="buy", quantity=1, price=10, available_cash=100
    )
    assert result["status"] == "simulated"
    assert submitted == []


def test_paper_trader_blocks_new_buy_at_daily_loss_limit():
    trader = PaperTrader(settings=make_settings())
    with pytest.raises(RiskViolationError, match="Daily loss limit"):
        trader.place_order(
            symbol="AAPL", side="buy", quantity=1, price=10,
            available_cash=100, pnl_today=-5,
        )


def test_position_sizing_rejects_invalid_inputs():
    manager = RiskManager(make_settings())
    for cash, price in ((float("nan"), 10), (100, float("inf")), (-1, 10), (100, 0)):
        with pytest.raises(RiskViolationError):
            manager.calculate_position_size(cash, price)


def test_paper_mode_is_required_for_simulated_orders():
    settings = make_settings(trading_mode="paper", paper_trading_enabled=False)
    trader = PaperTrader(settings=settings)

    with pytest.raises(PermissionError):
        trader.place_order(symbol="AAPL", side="buy", quantity=1, price=10, available_cash=1000)
