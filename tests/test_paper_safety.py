from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from alpaca.data.historical import StockHistoricalDataClient
from streamlit.testing.v1 import AppTest

from config.settings import AppSettings
import src.broker.alpaca_client as broker_module
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError
from src.data.market_data import generate_synthetic_market_data


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_local_demo_data_is_marked_synthetic():
    data = generate_synthetic_market_data("SPY", periods=40)
    assert data["is_synthetic"].all()
    assert (data["data_quality"] == "synthetic-demo").all()


def test_paper_order_requires_verified_active_paper_client(monkeypatch):
    calls = []

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def submit_order(self, request):
            calls.append(request)
            return {"id": "paper-order-id", "status": "accepted"}

        def get_account(self):
            return {"status": "ACTIVE", "trading_blocked": False}

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
    with pytest.raises(PermissionError, match="Verify the active Alpaca Paper account"):
        client.submit_order(
            symbol="AAPL",
            side="buy",
            quantity=1,
            client_order_id="ma-test-order",
        )
    assert calls == []
    assert client.verify_connection()["connected"] is True
    assert client.is_connected() is True
    result = client.submit_order(
        symbol="AAPL",
        side="buy",
        quantity=1,
        client_order_id="ma-test-order",
    )
    assert result["status"] == "accepted"
    assert len(calls) == 1
    assert calls[0].symbol == "AAPL"
    assert calls[0].qty == 1


def test_demo_mode_with_credentials_never_constructs_a_trading_client(monkeypatch):
    constructed = []

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    client = AlpacaClient(AppSettings(
        trading_mode="demo",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))
    assert constructed == []
    assert client.paper_client_configured is False
    with pytest.raises(PermissionError):
        client.submit_order(
            symbol="AAPL",
            side="buy",
            quantity=1,
            client_order_id="ma-demo-order",
        )


def test_paper_account_snapshot_does_not_invent_missing_values(monkeypatch):
    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def get_account(self):
            return {
                "status": "ACTIVE",
                "cash": None,
                "equity": None,
                "buying_power": None,
                "trading_blocked": False,
            }

        def get_all_positions(self):
            return []

        def get_orders(self, **kwargs):
            return []

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    )
    client = AlpacaClient(settings)
    snapshot = client.get_paper_snapshot()
    assert snapshot["account"]["cash"] is None
    assert snapshot["account"]["equity"] is None
    assert snapshot["positions"] == []
    assert snapshot["orders"] == []


def test_paper_orders_use_all_status_filter_and_include_order_history(monkeypatch):
    orders = [
        {"id": "open-order", "status": "new"},
        {"id": "filled-order", "status": "filled"},
    ]
    received_filters = []

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def get_account(self):
            return {"status": "ACTIVE", "trading_blocked": False}

        def get_all_positions(self):
            return []

        def get_orders(self, filter=None):
            received_filters.append(filter)
            return orders

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    snapshot = client.get_paper_snapshot()

    assert snapshot["orders"] == orders
    assert len(received_filters) == 1
    assert isinstance(received_filters[0], broker_module.GetOrdersRequest)
    assert received_filters[0].status == broker_module.QueryOrderStatus.ALL


def test_paper_order_fetch_failure_raises_clear_broker_error(monkeypatch):
    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def get_account(self):
            return {"status": "ACTIVE", "trading_blocked": False}

        def get_all_positions(self):
            return []

        def get_orders(self, filter=None):
            raise RuntimeError("order endpoint unavailable")

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    with pytest.raises(
        BrokerConnectionError,
        match="Unable to fetch orders: order endpoint unavailable",
    ):
        client.get_paper_snapshot()


def test_paper_dashboard_hides_previous_values_when_refresh_fails(
    monkeypatch, tmp_path,
):
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    paper_path = tmp_path / "paper" / "paper.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(paper_path))
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    snapshot_fetches = []

    class FakePaperBroker:
        paper_client_configured = True

        def __init__(self, runtime_settings):
            self.settings = runtime_settings

        def get_instrument_availability(self, symbol):
            return {
                "visible": True,
                "data_available": "mock",
                "paper_tradable": False,
                "message": "Mock test asset.",
            }

        def get_paper_snapshot(self):
            snapshot_fetches.append(None)
            if len(snapshot_fetches) > 1:
                raise BrokerConnectionError(
                    "Unable to fetch orders: order endpoint unavailable"
                )
            return {
                "account": {
                    "status": "ACTIVE",
                    "cash": "987654321",
                    "equity": "987654322",
                    "buying_power": "987654321",
                    "last_equity": "987654320",
                },
                "positions": [{"symbol": "STALE_POSITION"}],
                "orders": [{"id": "STALE_ORDER", "status": "filled"}],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    monkeypatch.setattr(broker_module, "AlpacaClient", FakePaperBroker)
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception

    next(
        button for button in app.button
        if button.label == "Verifica e aggiorna conto Alpaca Paper"
    ).click().run()
    assert app.session_state["paper_snapshot"]["orders"][0]["id"] == "STALE_ORDER"
    assert any("987,654,321" in metric.value for metric in app.metric)

    app.run()

    assert not app.exception
    assert app.session_state["paper_verified"] is False
    assert any(
        "Unable to fetch orders: order endpoint unavailable" in item.value
        for item in app.error
    )
    assert app.session_state.get("paper_snapshot") is None
    assert not any("987,654,321" in metric.value for metric in app.metric)


def test_asset_availability_includes_fractional_and_quantity_rules(monkeypatch):
    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

        def get_all_assets(self, request):
            return [SimpleNamespace(
                symbol="AAPL",
                tradable=True,
                fractionable=False,
                min_order_size=None,
                min_trade_increment=None,
            )]

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    availability = client.get_instrument_availability("AAPL")

    assert availability["paper_tradable"] is True
    assert availability["fractionable"] is False
    assert availability["min_order_size"] is None
    assert availability["min_trade_increment"] is None


def test_incremental_market_data_uses_bounded_request_and_keeps_ohlcv(monkeypatch):
    requests = []
    now = datetime.now(timezone.utc)
    fake_market_client = SimpleNamespace(
        get_stock_bars=lambda request: (
            requests.append(request)
            or SimpleNamespace(df=pd.DataFrame([{
                "timestamp": now,
                "o": 10.0,
                "h": 11.0,
                "l": 9.0,
                "c": 10.5,
                "v": 100,
            }]))
        )
    )

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(
        broker_module,
        "StockHistoricalDataClient",
        lambda **kwargs: fake_market_client,
    )
    monkeypatch.setattr(broker_module, "CryptoHistoricalDataClient", None)
    monkeypatch.setattr(broker_module, "StockBarsRequest", lambda **kwargs: kwargs)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    bars = client.get_market_data(
        "AAPL",
        timeframe="1Min",
        period="1M",
        limit=10,
        start_time=now - timedelta(minutes=2),
    )

    assert requests[0]["limit"] == 10
    assert requests[0]["start"] == now - timedelta(minutes=2)
    assert bars[["open", "high", "low", "close", "volume"]].iloc[0].tolist() == [
        10.0,
        11.0,
        9.0,
        10.5,
        100,
    ]
    assert bars.attrs["interval"] == "1Min"


def test_historical_market_data_uses_sdk_pagination_and_selected_period(
    monkeypatch,
):
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(broker_module, "datetime", FrozenDateTime)
    pages = [
        {
            "bars": {
                "AAPL": [{
                    "t": "2025-10-02T13:30:00Z",
                    "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100, "n": 1, "vw": 10,
                }],
            },
            "next_page_token": "next-page",
        },
        {
            "bars": {
                "AAPL": [{
                    "t": "2025-10-03T13:30:00Z",
                    "o": 10.5, "h": 12, "l": 10, "c": 11.5, "v": 200, "n": 2, "vw": 11,
                }],
            },
            "next_page_token": None,
        },
    ]
    requests = []
    historical_client = StockHistoricalDataClient(
        api_key="mock-key",
        secret_key="mock-secret",
    )

    def get_page(path, data):
        requests.append(dict(data))
        return pages[len(requests) - 1]

    monkeypatch.setattr(historical_client, "get", get_page)
    monkeypatch.setattr(
        broker_module,
        "StockHistoricalDataClient",
        lambda **kwargs: historical_client,
    )
    monkeypatch.setattr(broker_module, "CryptoHistoricalDataClient", None)
    monkeypatch.setattr(
        broker_module,
        "TradingClient",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    bars = client.get_market_data(
        "AAPL",
        timeframe="1Day",
        period="3M",
        limit=None,
    )

    assert len(requests) == 2
    assert requests[0]["page_token"] is None
    assert requests[1]["page_token"] == "next-page"
    assert requests[0]["start"] == (fixed_now - timedelta(days=93)).isoformat()
    assert bars["timestamp"].tolist() == [
        pd.Timestamp("2025-10-02T13:30:00Z"),
        pd.Timestamp("2025-10-03T13:30:00Z"),
    ]
    assert bars[["open", "high", "low", "close", "volume"]].values.tolist() == [
        [10.0, 11.0, 9.0, 10.5, 100.0],
        [10.5, 12.0, 10.0, 11.5, 200.0],
    ]
    assert bars.attrs["quality"] == "real"
    assert bars.attrs["source"].startswith("Dati storici reali Alpaca")


def test_empty_historical_response_is_an_explicit_error(monkeypatch):
    fake_market_client = SimpleNamespace(
        get_stock_bars=lambda request: SimpleNamespace(df=pd.DataFrame())
    )

    monkeypatch.setattr(broker_module, "TradingClient", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        broker_module,
        "StockHistoricalDataClient",
        lambda **kwargs: fake_market_client,
    )
    monkeypatch.setattr(broker_module, "CryptoHistoricalDataClient", None)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    with pytest.raises(BrokerConnectionError, match="No bars were returned"):
        client.get_market_data("AAPL", timeframe="1Day", period="3M", limit=None)


def test_invalid_ohlcv_response_is_reported_as_unavailable(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_market_client = SimpleNamespace(
        get_stock_bars=lambda request: SimpleNamespace(df=pd.DataFrame([{
            "timestamp": now,
            "o": 10.0,
            "h": 8.0,
            "l": 9.0,
            "c": 10.5,
            "v": 100,
        }]))
    )

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(
        broker_module,
        "StockHistoricalDataClient",
        lambda **kwargs: fake_market_client,
    )
    monkeypatch.setattr(broker_module, "CryptoHistoricalDataClient", None)
    monkeypatch.setattr(broker_module, "StockBarsRequest", lambda **kwargs: kwargs)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    with pytest.raises(BrokerConnectionError, match="invalid timestamps or OHLCV"):
        client.get_market_data("AAPL", timeframe="1Day", period="1M")


def test_market_data_timeout_is_converted_to_explicit_broker_error(monkeypatch):
    def timeout(request):
        raise TimeoutError("mock timeout")

    fake_market_client = SimpleNamespace(get_stock_bars=timeout)

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["paper"] is True

    monkeypatch.setattr(broker_module, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(
        broker_module,
        "StockHistoricalDataClient",
        lambda **kwargs: fake_market_client,
    )
    monkeypatch.setattr(broker_module, "CryptoHistoricalDataClient", None)
    monkeypatch.setattr(broker_module, "StockBarsRequest", lambda **kwargs: kwargs)
    client = AlpacaClient(AppSettings(
        trading_mode="paper",
        alpaca_api_key="local-test-key",
        alpaca_secret_key="local-test-secret",
        paper_trading_enabled=True,
    ))

    with pytest.raises(BrokerConnectionError, match="Market data unavailable"):
        client.get_market_data("AAPL", timeframe="1Day", period="1M")
