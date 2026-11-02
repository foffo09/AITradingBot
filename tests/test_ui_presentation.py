import pandas as pd
import pytest

from src.ui.presentation import data_status, finite_number, money, paper_metrics, signal_view, unique_orders


@pytest.mark.parametrize(("value", "expected"), [(0, 0), (-2, -2), ("1.25", 1.25),
    (None, None), ("invalid", None), (float("nan"), None), (float("inf"), None), (True, None)])
def test_money_keeps_zero_and_rejects_unavailable_values(value, expected):
    assert finite_number(value) == expected
    assert (money(value) == "N/D") == (expected is None)


def test_paper_metrics_use_only_broker_values_and_known_denominator():
    values = paper_metrics({"cash": "100", "equity": "150", "last_equity": "100", "buying_power": "110"},
                           [{"market_value": "50", "unrealized_pl": "10"}])
    assert values["cash"] == 100 and values["equity"] == 150
    assert values["daily_change"] == 50 and values["daily_percent"] == 50
    assert values["market_value"] == 50 and values["unrealized"] == 10
    assert paper_metrics({"equity": 100, "last_equity": 0}, [])["daily_percent"] is None
    assert paper_metrics({"equity": "bad", "last_equity": 100}, [])["daily_change"] is None
    assert paper_metrics({}, [])["market_value"] == 0
    assert paper_metrics({}, None)["market_value"] is None
    assert paper_metrics({}, [{"market_value": 1}, {}])["market_value"] is None
    assert paper_metrics({"equity": 1e308, "last_equity": -1e308}, [])["daily_change"] is None


def test_data_status_distinguishes_stale_future_invalid_and_synthetic():
    now = pd.Timestamp("2026-01-01T12:00:00Z")
    assert data_status(now, "1Min", "real", now)["state"] == "fresh"
    assert data_status(now + pd.Timedelta(seconds=1), "1Min", "real", now)["state"] == "future"
    assert data_status(now - pd.Timedelta(hours=1), "1Min", "real", now)["state"] == "stale"
    assert data_status(None, "1Min", "real", now)["state"] == "invalid"
    assert data_status("bad", "1Min", "real", now)["state"] == "invalid"
    assert data_status(now, "1Day", "synthetic", now)["label"] == "SYNTHETIC / DEMO"
    assert data_status(now, "1Day", None, now)["state"] == "unavailable"


def test_signal_view_distinguishes_technical_crossover_from_operational_permission():
    frame = pd.DataFrame({"timestamp": [pd.Timestamp.now(tz="UTC")], "close": [100],
                          "short_ma": [101], "long_ma": [100], "signal": [1]})
    view = signal_view(frame, "SPY", "1Day", "synthetic", 2, 4)
    assert view["direction"] == "ACQUISTO / BUY" and view["price"] == 100
    assert view["parameters"] == "SMA 2/4" and "stop" not in view
    frame["short_ma"] = None
    assert signal_view(frame, "SPY", "1Day", "synthetic", 2, 4)["state"] == "DATI INSUFFICIENTI"
    assert signal_view(frame.iloc[:0], "SPY", "1Day", "real", 2, 4)["state"] == "DATI INSUFFICIENTI"
    frame["timestamp"] = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
    assert "FUTURI" in signal_view(frame, "SPY", "1Day", "real", 2, 4)["state"]


def test_order_deduplication_uses_identifiers_without_collapsing_unknown_orders():
    order = {"id": "test-order", "status": "filled"}
    assert unique_orders([order, dict(order), {}, {}]) == [order, {}, {}]


def test_chart_rejects_empty_or_incomplete_data_without_accessing_a_ledger(monkeypatch):
    from src.ui.charts import plot_market_chart
    messages = []
    monkeypatch.setattr("streamlit.info", lambda text: messages.append(text))
    monkeypatch.setattr("streamlit.warning", lambda text: messages.append(text))
    def unexpected_chart(*args, **kwargs):
        pytest.fail("Invalid data must not be plotted")
    monkeypatch.setattr("streamlit.plotly_chart", unexpected_chart)
    signals = pd.DataFrame({"signal": [0]})
    for data in [pd.DataFrame(), pd.DataFrame({"close": [1]}), pd.DataFrame({
        "timestamp": ["invalid"], "open": [1], "high": [2], "low": [1], "close": [1], "volume": [1],
    })]:
        plot_market_chart(data, signals, "SPY", 2, 4, False)
    assert len(messages) == 3


def test_chart_requires_a_positive_confirmed_fill_and_deduplicates_orders(monkeypatch):
    from src.ui.charts import plot_market_chart
    from src.strategy.moving_average import MovingAverageStrategy

    now = pd.Timestamp("2026-01-01T12:00:00Z")
    data = pd.DataFrame({"timestamp": pd.date_range(end=now, periods=5, freq="min"),
                         "open": [100] * 5, "high": [101] * 5, "low": [99] * 5,
                         "close": [100] * 5, "volume": [1] * 5})
    signals = MovingAverageStrategy(2, 4).generate_signals(data)
    base = {"symbol": "SPY", "submitted_at": now, "filled_at": now,
            "filled_avg_price": "100", "status": "partially_filled"}
    confirmed = dict(base, id="confirmed", filled_qty="0.1")
    orders = [dict(base, id="unknown"), dict(base, id="zero", filled_qty="0"),
              dict(base, id="invalid", filled_qty="NaN"), confirmed, dict(confirmed)]
    figures = []
    monkeypatch.setattr("streamlit.plotly_chart", lambda figure, **kwargs: figures.append(figure))
    plot_market_chart(data, signals, "SPY", 2, 4, False, paper_orders=orders)
    traces = figures[0].data
    assert sum(trace.name == "Fill Paper confermato" for trace in traces) == 1
    assert sum(trace.name == "Ordine Paper (close barra di riferimento)" for trace in traces) == 4
