"""Offline contracts for the Plotly figure handed to Streamlit."""
import pandas as pd
import pytest

from src.strategy.moving_average import MovingAverageStrategy
from src.ui.charts import plot_market_chart


@pytest.fixture
def market_data():
    data = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-05T14:30:00Z", periods=20, freq="min"),
        "open": range(100, 120), "high": range(102, 122),
        "low": range(99, 119), "close": range(101, 121),
        "volume": range(200, 220),
    })
    data.attrs.update(quality="real", source="isolated OHLCV fixture", interval="1Min")
    return data


@pytest.fixture
def rendered(monkeypatch):
    charts = []
    monkeypatch.setattr("streamlit.plotly_chart", lambda fig, **kwargs: charts.append((fig, kwargs)))
    return charts


def render(data, **kwargs):
    plot_market_chart(data, MovingAverageStrategy(2, 4).generate_signals(data),
                      kwargs.pop("symbol", "SPY"), 2, 4, kwargs.pop("show_rsi", False), **kwargs)


@pytest.mark.parametrize("interval, first_step", [("1Min", "minute"), ("1Day", "month")])
def test_chart_exposes_zoom_pan_and_time_navigation(market_data, rendered, interval, first_step):
    market_data.attrs["interval"] = interval
    render(market_data)
    fig, kwargs = rendered[0]
    assert kwargs["config"]["scrollZoom"] is True
    assert kwargs["config"]["displayModeBar"] is True
    controls = kwargs["config"]["modeBarButtons"][0]
    assert {"zoom2d", "pan2d", "zoomIn2d", "zoomOut2d", "resetScale2d"} <= set(controls)
    assert fig.layout.dragmode == "pan"
    assert fig.layout.xaxis.rangeslider.visible is False
    buttons = fig.layout.xaxis.rangeselector.buttons
    assert buttons[0].step == first_step
    assert buttons[-1].step == "all"
    assert fig.layout.hovermode == "x unified"
    assert fig.layout.hoverlabel.font.color
    assert fig.layout.legend.orientation == "h"
    assert fig.layout.height == 420


def test_chart_uses_compact_dark_theme_and_indigo_timeframe(market_data, rendered):
    render(market_data)
    fig, _ = rendered[0]
    assert fig.layout.height == 420
    assert fig.layout.paper_bgcolor == "#1e293b"
    assert fig.layout.plot_bgcolor == "#1e293b"
    assert fig.layout.xaxis.rangeselector.activecolor == "#7c3aed"


def test_chart_keeps_compact_height_with_optional_rsi(market_data, rendered):
    render(market_data, show_rsi=True)
    assert rendered[0][0].layout.height == 500


def test_zoom_survives_refresh_but_resets_for_symbol_or_interval(market_data, rendered):
    render(market_data)
    refreshed = market_data.copy()
    refreshed.loc[19, "close"] = 119
    render(refreshed, show_rsi=True)
    render(refreshed, symbol="AAPL")
    refreshed.attrs["interval"] = "5Min"
    render(refreshed)
    revisions = [fig.layout.uirevision for fig, _ in rendered]
    assert revisions[0] is not None
    assert revisions[0] == revisions[1]
    assert revisions[0] != revisions[2]
    assert revisions[0] != revisions[3]


def test_chart_uses_supplied_ohlcv_and_preserves_demo_label(market_data, rendered):
    render(market_data, show_rsi=True)
    fig, _ = rendered[0]
    candles = next(trace for trace in fig.data if trace.type == "candlestick")
    assert list(candles.open) == list(range(100, 120))
    assert list(candles.high) == list(range(102, 122))
    assert list(candles.low) == list(range(99, 119))
    assert list(candles.close) == list(range(101, 121))
    assert list(pd.to_datetime(candles.x, utc=True)) == list(market_data["timestamp"])
    volume = next(trace for trace in fig.data if trace.name == "Volume")
    assert list(volume.y) == list(range(200, 220))
    rsi = next(trace for trace in fig.data if trace.name == "RSI 14")
    assert list(rsi.y[14:]) == [100] * 6
    assert "Storico OHLC" in fig.layout.title.text
    market_data.attrs["quality"] = "synthetic"
    render(market_data)
    assert "SYNTHETIC / DEMO" in rendered[1][0].layout.title.text


def test_pending_order_is_reference_marker_and_only_confirmed_fill_uses_fill_price(market_data, rendered):
    timestamp = market_data["timestamp"].iloc[0]
    pending = {"id": "pending", "symbol": "SPY", "status": "accepted", "submitted_at": timestamp}
    filled = {"id": "filled", "symbol": "SPY", "status": "filled", "submitted_at": timestamp,
              "filled_at": timestamp, "filled_qty": "2", "filled_avg_price": "102.5"}
    render(market_data, paper_orders=[pending, filled])
    fig, _ = rendered[0]
    references = [trace for trace in fig.data if trace.name == "Ordine Paper (close barra di riferimento)"]
    fills = [trace for trace in fig.data if trace.name == "Fill Paper confermato"]
    assert len(references) == 2
    assert references[0].marker.symbol == "square-open"
    assert list(references[0].y) == [101]
    assert "non un fill" in references[0].text[0]
    assert len(fills) == 1
    assert list(fills[0].y) == [102.5]


def test_empty_chart_reports_unavailability_without_creating_data(monkeypatch, rendered):
    messages = []
    monkeypatch.setattr("streamlit.info", messages.append)
    plot_market_chart(pd.DataFrame(), pd.DataFrame(), "SPY", 2, 4, False)
    assert len(messages) == 1
    assert not rendered
