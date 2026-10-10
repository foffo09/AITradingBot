import pytest

from config.settings import AppSettings
import src.broker.alpaca_client as broker_module
from src.broker.alpaca_client import AlpacaClient
from src.data.market_data import generate_synthetic_market_data


def test_local_demo_data_is_marked_synthetic():
    data = generate_synthetic_market_data("SPY", periods=40)
    assert data["is_synthetic"].all()
    assert (data["data_quality"] == "synthetic-demo").all()


def test_submit_order_never_delegates_to_alpaca(monkeypatch):
    calls = []

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def submit_order(self, *args, **kwargs):
            calls.append("submitted")
            raise AssertionError("Alpaca order submission must never be called.")

        def get_account(self):
            return object()

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    )
    client = AlpacaClient(settings)
    assert client.paper_client_configured is True
    assert client.is_connected() is False
    with pytest.raises(PermissionError, match="never sends real orders"):
        client.submit_order(symbol="AAPL")
    assert calls == []
    assert client.verify_connection()["connected"] is True
    assert client.is_connected() is True
