from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError

import pytest
from types import SimpleNamespace


@pytest.mark.parametrize("count", [2, 500])
def test_order_history_uses_explicit_limit_and_blocks_saturation(count):
    client = AlpacaClient(AppSettings(trading_mode="demo"))
    orders = [{"id": f"test-order-{i}"} for i in range(count)]
    requests = []
    def get_orders(filter):
        requests.append(filter)
        return orders
    client.client = SimpleNamespace(get_orders=get_orders)
    if count == 500:
        with pytest.raises(BrokerConnectionError, match="truncated"):
            client.get_orders()
    else:
        assert client.get_orders() == orders
    assert requests[0].limit == 500


def test_demo_mode_without_api_keys():
    settings = AppSettings(trading_mode="demo", alpaca_api_key=None, alpaca_secret_key=None, paper_trading_enabled=True)
    client = AlpacaClient(settings)
    status = client.verify_connection()
    assert status["status"] == "demo"
    assert client.get_account()["mode"] == "demo"


def test_broker_error_handling_for_missing_credentials():
    client = AlpacaClient(AppSettings(trading_mode="demo", alpaca_api_key=None, alpaca_secret_key=None, paper_trading_enabled=True))
    try:
        client.get_market_data("AAPL", limit=5)
    except BrokerConnectionError as exc:
        assert "Choose the explicitly labeled demo data option" in str(exc)
    else:
        raise AssertionError("Missing real market-data credentials must not silently fabricate bars.")
