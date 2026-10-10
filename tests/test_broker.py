from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError


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
