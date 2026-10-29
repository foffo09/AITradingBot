"""Chart renderer with explicit data; no account, ledger or broker access."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.ui.presentation import finite_number, unique_orders


def plot_market_chart(
    data: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str,
    short_window: int,
    long_window: int,
    show_rsi: bool,
    paper_orders: list[dict] | None = None,
    latest_quote: dict | None = None,
    local_history: list[dict] | None = None,
) -> None:
    if data.empty or signals.empty:
        st.info("Grafico non disponibile: nessuna barra da visualizzare.")
        return
    if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(data.columns):
        st.warning("Grafico non disponibile: dati OHLCV incompleti.")
        return
    if pd.to_datetime(data["timestamp"], utc=True, errors="coerce").isna().any():
        st.warning("Grafico non disponibile: timestamp delle barre non validi.")
        return
    rows = 3 if show_rsi else 2
    heights = [0.65, 0.2, 0.15] if show_rsi else [0.75, 0.25]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=heights,
        subplot_titles=("Prezzo OHLC e medie mobili", "Volume", "RSI (14)" if show_rsi else None),
    )
    fig.add_trace(go.Candlestick(
        x=data["timestamp"], open=data["open"], high=data["high"], low=data["low"], close=data["close"],
        name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=signals["timestamp"], y=signals["short_ma"], mode="lines", name=f"MA breve ({short_window})",
        line={"color": "#ffca28", "width": 1.5},
    ), row=1, col=1)
    if latest_quote and finite_number(latest_quote.get("price")) is not None and float(latest_quote["price"]) > 0:
        fig.add_hline(
            y=float(latest_quote["price"]),
            line_dash="dot",
            line_color="#00e5ff",
            annotation_text=(
                f"Mid quote UTC {latest_quote.get('timestamp', 'n/d')} — non è una candela OHLC"
            ),
            annotation_position="top left",
            row=1,
            col=1,
        )
    fig.add_trace(go.Scatter(
        x=signals["timestamp"], y=signals["long_ma"], mode="lines", name=f"MA lunga ({long_window})",
        line={"color": "#42a5f5", "width": 1.5},
    ), row=1, col=1)

    buys = signals[signals["signal"] == 1]
    sells = signals[signals["signal"] == -1]
    for points, name, color, marker in (
        (buys, "Segnale acquisto", "#00c853", "triangle-up"),
        (sells, "Segnale uscita", "#ff1744", "triangle-down"),
    ):
        if not points.empty:
            fig.add_trace(go.Scatter(
                x=points["timestamp"], y=points["close"], mode="markers", name=name,
                marker={"symbol": marker, "color": color, "size": 10},
                text=points["signal_reason"], hovertemplate="%{x}<br>$%{y:.4f}<br>%{text}<extra></extra>",
            ), row=1, col=1)

    history = local_history or []
    if history:
        trade_rows = [item for item in history if item["symbol"] == symbol]
        for item in trade_rows:
            opened = pd.to_datetime(item["opened_at"], utc=True)
            fig.add_trace(go.Scatter(
                x=[opened], y=[item["entry_price"]], mode="markers", name="Entry simulazione",
                marker={"symbol": "star", "color": "#ab47bc", "size": 12},
                text=[item["entry_reason"]],
                hovertemplate="Entry simulazione<br>%{x}<br>$%{y:.4f}<br>%{text}<extra></extra>",
                showlegend=False,
            ), row=1, col=1)
            if item["closed_at"] and item["exit_price"] is not None:
                closed = pd.to_datetime(item["closed_at"], utc=True)
                fig.add_trace(go.Scatter(
                    x=[closed], y=[item["exit_price"]], mode="markers", name="Uscita simulazione",
                    marker={"symbol": "x", "color": "#ff9800", "size": 11},
                    text=[item["exit_reason"]],
                    hovertemplate="Uscita simulazione<br>%{x}<br>$%{y:.4f}<br>%{text}<extra></extra>",
                    showlegend=False,
                ), row=1, col=1)

    for order in unique_orders(paper_orders or []):
        if str(order.get("symbol", "")).upper() != symbol.upper():
            continue
        submitted_at = order.get("submitted_at") or order.get("created_at")
        submitted_time = pd.to_datetime(submitted_at, utc=True, errors="coerce")
        if submitted_at and not pd.isna(submitted_time):
            reference_index = (pd.to_datetime(data["timestamp"], utc=True) - submitted_time).abs().idxmin()
            reference_price = float(data.loc[reference_index, "close"])
            order_status = str(order.get("status", "unknown"))
            fig.add_trace(go.Scatter(
            x=[submitted_time],
            y=[reference_price],
            mode="markers",
            name="Ordine Paper (close barra di riferimento)",
            marker={"symbol": "square-open", "color": "#ffca28", "size": 11},
            text=[f"Ordine {order_status}; il prezzo mostrato è il close barra, non un fill."],
            hovertemplate="%{x}<br>%{text}<extra></extra>",
            showlegend=False,
            ), row=1, col=1)
        fill_price = finite_number(order.get("filled_avg_price"))
        fill_quantity = finite_number(order.get("filled_qty"))
        filled_at = pd.to_datetime(order.get("filled_at"), utc=True, errors="coerce")
        if (fill_price is not None and fill_price > 0 and fill_quantity is not None
                and fill_quantity > 0 and not pd.isna(filled_at)):
            fig.add_trace(go.Scatter(
            x=[pd.to_datetime(filled_at, utc=True)],
            y=[float(fill_price)],
            mode="markers",
            name="Fill Paper confermato",
            marker={"symbol": "circle", "color": "#00e676", "size": 11},
            text=[f"Quantità fill: {order.get('filled_qty', 'n/d')}"],
            hovertemplate="Fill Paper %{x}<br>$%{y:.4f}<br>%{text}<extra></extra>",
            showlegend=False,
            ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=data["timestamp"], y=data["volume"], name="Volume",
        marker_color="#78909c", opacity=0.65,
    ), row=2, col=1)
    if show_rsi:
        delta = data["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        relative_strength = gain / loss
        rsi = 100 - (100 / (1 + relative_strength))
        rsi = rsi.mask((gain == 0) & (loss == 0), 50)
        fig.add_trace(go.Scatter(
            x=data["timestamp"], y=rsi, mode="lines", name="RSI 14",
            line={"color": "#ce93d8"},
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef5350", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#26a69a", row=3, col=1)
        fig.update_yaxes(range=[0, 100], row=3, col=1)

    fig.update_layout(
        title=f"{symbol} · {'SYNTHETIC / DEMO' if data.attrs.get('quality') == 'synthetic' else 'Storico OHLC'}",
        height=760 if show_rsi else 650,
        template="plotly_dark",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font={"color": "#dce6ef"},
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 20, "r": 20, "t": 70, "b": 20},
    )
    st.plotly_chart(fig, use_container_width=True)
