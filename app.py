from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError
from src.data.fx_rates import fetch_eur_usd_rate
from src.data.instruments import CRYPTO_SYMBOLS, EQUITY_SYMBOLS, INSTRUMENTS
from src.data.market_data import generate_synthetic_market_data
from src.simulation.ledger import SimulationLedger
from src.strategy.moving_average import MovingAverageStrategy


st.set_page_config(page_title="AI Trading Bot | Simulazione", page_icon="📈", layout="wide")

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "simulation.sqlite3"
settings = AppSettings.from_env()
broker = AlpacaClient(settings)
ledger = SimulationLedger(DB_PATH)


def _freshness_limit(interval: str) -> timedelta:
    return {
        "1Min": timedelta(minutes=10),
        "5Min": timedelta(minutes=20),
        "15Min": timedelta(minutes=45),
        "1Hour": timedelta(hours=3),
        "1Day": timedelta(days=4),
        "1Week": timedelta(days=10),
    }[interval]


def _latest_timestamp(data: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(data["timestamp"].iloc[-1])


def _data_is_fresh(timestamp: object, interval: str) -> bool:
    parsed = pd.Timestamp(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return datetime.now(timezone.utc) - parsed.to_pydatetime() <= _freshness_limit(interval)


def _tradingview_url(symbol: str) -> str:
    if "/" in symbol:
        tv_symbol = f"BINANCE:{symbol.replace('/', '')}"
    elif symbol in {"SPY", "GLD"}:
        tv_symbol = f"AMEX:{symbol}"
    else:
        tv_symbol = f"NASDAQ:{symbol}"
    return f"https://www.tradingview.com/chart/?symbol={quote(tv_symbol, safe='')}"


@st.cache_data(ttl=300, show_spinner=False)
def _cached_asset_availability(symbol: str) -> dict:
    return broker.get_instrument_availability(symbol)


def _load_data(symbol: str, interval: str, period: str, demo: bool) -> tuple[pd.DataFrame, str]:
    if demo:
        if interval != "1Day":
            raise ValueError("La serie sintetica dimostrativa è giornaliera; seleziona 1Day.")
        periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "5Y": 1000}[period]
        result = generate_synthetic_market_data(symbol=symbol, periods=periods)
        result.attrs["source"] = "Serie sintetica locale (non sono prezzi reali)"
        result.attrs["quality"] = "synthetic"
        result.attrs["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return result, "Serie sintetica locale"
    result = broker.get_market_data(symbol, timeframe=interval, period=period)
    result.attrs["quality"] = "real"
    return result, str(result.attrs.get("source", "Alpaca market data"))


def _show_simulation_account(spread_bps: float) -> None:
    st.subheader("Conto di simulazione locale")
    account = ledger.account()
    if account is None:
        st.info("Il conto virtuale non è ancora inizializzato. È indipendente dal saldo Alpaca.")
        start_eur = st.number_input("Capitale iniziale (EUR)", min_value=1.0, value=100.0, step=10.0)
        col_fx, col_get = st.columns([2, 1])
        with col_fx:
            fx_input = st.number_input(
                "Tasso EUR/USD (serve per avviare il conto USD)",
                min_value=0.0,
                value=float(st.session_state.get("fx_rate", 0.0)),
                format="%.6f",
                help="Non viene inserito un cambio predefinito. Usa la fonte Frankfurter o inserisci un tasso noto.",
            )
            if fx_input > 0 and fx_input != float(st.session_state.get("fx_rate_recorded", 0.0)):
                st.session_state.fx_source = "Tasso inserito dall'utente"
                st.session_state.fx_timestamp = datetime.now(timezone.utc).isoformat()
        with col_get:
            st.write("")
            st.write("")
            if st.button("Recupera cambio EUR/USD"):
                try:
                    fx = fetch_eur_usd_rate()
                    st.session_state.fx_rate = float(fx["rate"])
                    st.session_state.fx_rate_recorded = float(fx["rate"])
                    st.session_state.fx_source = str(fx["source"])
                    st.session_state.fx_timestamp = str(fx["timestamp"])
                    st.success(f"Tasso {fx['rate']}: fonte {fx['source']}, data {fx['timestamp']}.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(f"{exc} Puoi inserire manualmente un tasso verificato.")
        if fx_input > 0 and st.button(f"Crea conto virtuale da {start_eur:.2f} EUR", type="primary"):
            source = str(st.session_state.get("fx_source", "Tasso inserito dall'utente"))
            timestamp = str(st.session_state.get("fx_timestamp", datetime.now(timezone.utc).isoformat()))
            ledger.initialize_account(
                initial_eur=float(start_eur),
                eur_usd_rate=float(fx_input),
                fx_source=source,
                fx_timestamp=timestamp,
            )
            st.rerun()
        elif fx_input <= 0:
            st.caption("Il cambio è necessario perché i titoli selezionati sono quotati in USD. Nessun tasso viene inventato.")
        return

    summary = ledger.summary(float(commission_bps), float(slippage_bps), spread_bps)
    st.caption(
        f"Saldo virtuale inizializzato con {account['initial_eur']:.2f} EUR × "
        f"{account['eur_usd_rate']:.6f} = {account['initial_cash']:.2f} USD. "
        f"Cambio: {account['fx_source']} · {account['fx_timestamp']}."
    )
    top = st.columns(4)
    top[0].metric("Capitale attuale netto*", f"${summary['current_capital']:,.2f}")
    top[1].metric("Cash disponibile", f"${summary['cash']:,.2f}")
    top[2].metric("Valore posizioni", f"${summary['market_value']:,.2f}")
    top[3].metric("P/L complessivo netto", f"${summary['total_pnl']:+,.2f}", f"{summary['return_pct']:+.2f}%")
    pnl = st.columns(4)
    pnl[0].metric("P/L realizzato", f"${summary['realized_pnl']:+,.2f}")
    pnl[1].metric("P/L non realizzato", f"${summary['unrealized_pnl']:+,.2f}")
    pnl[2].metric("Costi commissioni pagati", f"${summary['fees']:,.2f}")
    pnl[3].metric("Slippage stimato pagato", f"${summary['slippage']:,.2f}")
    st.metric("Spread stimato pagato", f"${summary['spread']:,.2f}")
    st.caption("*Il capitale attuale considera le posizioni al prezzo disponibile e il costo stimato di liquidazione. Dati del conto locale, non Alpaca.")

    perf = st.columns(6)
    perf[0].metric("Chiusure", summary["closed_trades"])
    perf[1].metric("Vincenti / perdenti", f"{summary['winning_trades']} / {summary['losing_trades']}")
    perf[2].metric("Win rate", f"{summary['win_rate']:.1f}%")
    perf[3].metric("Profitto medio", f"${summary['average_win']:.2f}")
    perf[4].metric("Perdita media", f"${summary['average_loss']:.2f}")
    profit_factor = summary["profit_factor"]
    perf[5].metric("Profit factor", "∞" if math.isinf(profit_factor) else f"{profit_factor:.2f}")
    st.metric("Massimo drawdown della curva salvata", f"{summary['max_drawdown_pct']:.2f}%")

    if summary["equity_curve"]:
        st.plotly_chart(
            go.Figure(go.Scatter(
                x=[item["timestamp"] for item in summary["equity_curve"]],
                y=[item["equity"] for item in summary["equity_curve"]],
                mode="lines",
                name="Capitale simulazione",
                line={"color": "#42a5f5"},
            )).update_layout(title="Curva del capitale — simulazione locale", xaxis_title="Data", yaxis_title="USD"),
            use_container_width=True,
        )
    st.caption("Profit factor = somma dei profitti netti realizzati / valore assoluto delle perdite nette realizzate.")

    positions = ledger.positions()
    st.markdown("**Posizioni aperte**")
    if positions:
        pos_frame = pd.DataFrame(positions).rename(columns={
            "symbol": "Strumento", "quantity": "Quantità", "average_entry": "Prezzo medio ingresso",
            "market_price": "Ultimo prezzo", "mark_timestamp": "Timestamp dato", "mark_source": "Fonte",
        })
        st.dataframe(pos_frame, use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna posizione aperta.")


def _plot_market_chart(
    data: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str,
    short_window: int,
    long_window: int,
    show_rsi: bool,
) -> None:
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

    history = ledger.history()
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

    fig.add_trace(go.Bar(
        x=data["timestamp"], y=data["volume"], name="Volume",
        marker_color="#78909c", opacity=0.65,
    ), row=2, col=1)
    if show_rsi:
        delta = data["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        relative_strength = gain / loss.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + relative_strength))
        fig.add_trace(go.Scatter(
            x=data["timestamp"], y=rsi, mode="lines", name="RSI 14",
            line={"color": "#ce93d8"},
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef5350", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#26a69a", row=3, col=1)
        fig.update_yaxes(range=[0, 100], row=3, col=1)

    fig.update_layout(
        height=760 if show_rsi else 650,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 20, "r": 20, "t": 70, "b": 20},
    )
    st.plotly_chart(fig, use_container_width=True)


st.title("AI Trading Bot — analisi e simulazione")
st.caption("Trading automatico disabilitato. Tutte le entry/uscite simulate sono registrate localmente; la dashboard non invia ordini.")

with st.sidebar:
    st.header("Strategia e rischio")
    short_window = st.number_input("Media mobile breve", min_value=2, max_value=100, value=settings.short_window)
    long_window = st.number_input("Media mobile lunga", min_value=3, max_value=300, value=settings.long_window)
    if short_window >= long_window:
        st.error("La media mobile breve deve essere minore di quella lunga.")
    max_trade_fraction = st.slider("Importo massimo per trade (% capitale)", 1, 50, int(settings.risk_max_trade_fraction * 100)) / 100
    max_exposure_fraction = st.slider("Esposizione massima (% capitale)", 1, 100, int(settings.risk_max_exposure_fraction * 100)) / 100
    daily_loss_fraction = st.slider("Blocco perdita giornaliera (%)", 0, 20, int(settings.daily_loss_limit_pct * 100)) / 100
    commission_bps = st.number_input("Commissione stimata (bps)", min_value=0.0, max_value=1000.0, value=float(settings.commission_bps))
    slippage_bps = st.number_input("Slippage stimato (bps)", min_value=0.0, max_value=1000.0, value=float(settings.slippage_bps))
    spread_bps = st.number_input("Spread stimato (bps)", min_value=0.0, max_value=1000.0, value=float(settings.spread_bps))
    st.caption("Questi limiti si applicano solo alla simulazione locale e al backtest.")
    st.success("Trading automatico: disattivato")

tab_markets, tab_sim, tab_backtest, tab_alpaca = st.tabs([
    "Mercati e strumenti", "Simulazione locale", "Backtesting", "Alpaca Paper (sola lettura)",
])

with tab_markets:
    st.header("Mercati e strumenti")
    categories = ["ETF e azioni"] + (["Criptovalute"] if st.session_state.get("paper_verified", False) else [])
    market_group = st.radio("Categoria", categories, horizontal=True, key="market_group")
    if not st.session_state.get("paper_verified", False):
        st.caption("Gli strumenti crypto sono mostrati solo dopo la verifica dell'account Paper nella scheda dedicata.")
    group_symbols = EQUITY_SYMBOLS if market_group == "ETF e azioni" else CRYPTO_SYMBOLS
    query = st.text_input("Cerca per ticker o nome")
    filtered_symbols = [
        symbol for symbol in group_symbols
        if query.casefold() in symbol.casefold()
        or query.casefold() in INSTRUMENTS[symbol]["name"].casefold()
        or query.casefold() in INSTRUMENTS[symbol]["description"].casefold()
    ]
    if not filtered_symbols:
        st.warning("Nessuno strumento corrisponde alla ricerca.")
        selected_symbol = None
    else:
        selected_symbol = st.selectbox("Strumento da analizzare", filtered_symbols)
        descriptor = INSTRUMENTS[selected_symbol]
        st.markdown(f"**{descriptor['name']}** — {descriptor['description']}")

    controls = st.columns(3)
    with controls[0]:
        interval = st.selectbox("Intervallo dati", ["1Min", "5Min", "15Min", "1Hour", "1Day", "1Week"], index=4)
    with controls[1]:
        period = st.selectbox("Periodo grafico", ["1M", "3M", "6M", "1Y", "5Y"], index=1)
    with controls[2]:
        demo_mode = st.checkbox("Usa serie sintetica demo", value=False, help="Attiva solo su richiesta; non rappresenta prezzi reali.")
    show_rsi = st.checkbox("Mostra RSI (14)", value=False)

    if selected_symbol:
        availability = _cached_asset_availability(selected_symbol)
        if (
            st.session_state.get("market_symbol") == selected_symbol
            and st.session_state.get("data_availability")
        ):
            availability = st.session_state.data_availability
        st.caption(
            f"Visibile nel catalogo: sì · Dati di mercato: {availability['data_available']} "
            f"· Negoziazione paper: {availability['paper_tradable']} · {availability['message']}"
        )
        load_col, refresh_col = st.columns([1, 1])
        with load_col:
            load_clicked = st.button("Carica dati / applica selezione", type="primary")
        with refresh_col:
            compare_symbols = st.multiselect(
                "Confronta strumenti (performance normalizzata)",
                list(group_symbols),
                default=[selected_symbol],
                max_selections=4,
            )
            compare_clicked = st.button("Carica confronto", disabled=not compare_symbols)

        if load_clicked:
            try:
                data, source = _load_data(selected_symbol, interval, period, demo_mode)
                if data.empty:
                    st.warning("La fonte non ha restituito dati per la selezione.")
                else:
                    latest_quote = None
                    quote_error = None
                    if not demo_mode:
                        try:
                            latest_quote = broker.get_latest_quote(selected_symbol)
                        except BrokerConnectionError as exc:
                            quote_error = str(exc)
                    st.session_state.market_frame = data
                    st.session_state.market_symbol = selected_symbol
                    st.session_state.market_interval = interval
                    st.session_state.market_period = period
                    st.session_state.market_source = source
                    st.session_state.market_quality = data.attrs.get("quality", "real")
                    st.session_state.market_quote = latest_quote
                    st.session_state.market_quote_error = quote_error
                    st.session_state.availability_checked = availability
                    st.session_state.data_availability = {
                        **availability,
                        "data_available": True,
                        "message": "Historical bars successfully returned; latest quote is checked separately.",
                    }
                    account = ledger.account()
                    if account is not None:
                        mark = latest_quote["price"] if latest_quote and latest_quote["price"] else float(data["close"].iloc[-1])
                        mark_timestamp = latest_quote["timestamp"] if latest_quote and latest_quote["price"] else str(_latest_timestamp(data))
                        mark_source = latest_quote["source"] if latest_quote and latest_quote["price"] else source + " — ultimo close barra"
                        ledger.update_mark(
                            selected_symbol, float(mark), str(mark_timestamp), mark_source,
                        )
            except (BrokerConnectionError, ValueError) as exc:
                st.error(f"Dati non caricati: {exc}")

        if compare_clicked:
            comparison_rows = []
            try:
                for compare_symbol in compare_symbols:
                    compare_data, compare_source = _load_data(compare_symbol, interval, period, demo_mode)
                    if compare_data.empty:
                        st.warning(f"Nessun dato disponibile per {compare_symbol}; escluso dal confronto.")
                        continue
                    start_price = float(compare_data["close"].iloc[0])
                    if start_price <= 0:
                        continue
                    comparison_rows.append(pd.DataFrame({
                        "timestamp": compare_data["timestamp"],
                        compare_symbol: (compare_data["close"] / start_price - 1) * 100,
                    }))
                if comparison_rows:
                    combined = comparison_rows[0]
                    for frame in comparison_rows[1:]:
                        combined = combined.merge(frame, on="timestamp", how="outer")
                    st.line_chart(combined.set_index("timestamp"))
                    st.caption(f"Confronto normalizzato (% dal primo prezzo del periodo). Fonte: {compare_source}.")
            except (BrokerConnectionError, ValueError) as exc:
                st.error(f"Confronto non disponibile: {exc}")

    if "market_frame" not in st.session_state:
        st.info("Seleziona uno strumento e carica i dati. La mancanza di dati reali non attiva automaticamente prezzi sintetici.")
    elif selected_symbol and st.session_state.market_symbol != selected_symbol:
        st.info("La selezione è cambiata: carica i dati aggiornati prima di analizzare o simulare questo strumento.")
    else:
        data = st.session_state.market_frame.copy()
        source = st.session_state.market_source
        quality = st.session_state.market_quality
        label = "SINTETICI — SOLO DEMO" if quality == "synthetic" else "DATI ALPACA — FEED IEX" if "IEX" in source else "DATI REALI ALPACA"
        st.info(f"{label} · Fonte: {source} · Ultima barra: {_latest_timestamp(data)}")
        if data.attrs.get("fetched_at"):
            st.caption(f"Scaricati il: {data.attrs['fetched_at']}")
        last = data.iloc[-1]
        latest_quote = st.session_state.get("market_quote")
        quote_cols = st.columns(3)
        if latest_quote and latest_quote.get("price"):
            quote_cols[0].metric("Ultima quotazione (mid bid/ask)", f"${float(latest_quote['price']):,.4f}")
            quote_cols[1].metric("Timestamp quotazione", str(latest_quote["timestamp"]))
            quote_cols[2].metric("Fonte quotazione", str(latest_quote["source"]))
            st.caption(f"Bid ${latest_quote['bid']:.4f} · Ask ${latest_quote['ask']:.4f}.")
        else:
            quote_cols[0].metric("Ultimo close della barra", f"${float(last['close']):,.4f}")
            quote_cols[1].metric("Timestamp ultima barra", str(_latest_timestamp(data)))
            quote_cols[2].metric("Fonte barra", source)
            if st.session_state.get("market_quote_error"):
                st.warning(f"Quotazione bid/ask non disponibile; mostrato il close della barra: {st.session_state.market_quote_error}")
        if len(data) > 0:
            st.caption(
                f"Periodo richiesto: {st.session_state.market_period} · Copertura restituita: "
                f"{data['timestamp'].iloc[0]} — {_latest_timestamp(data)}"
            )
        if quality == "synthetic":
            st.warning("Serie sintetica generata localmente: non è una quotazione o uno storico reale.")

        strategy = MovingAverageStrategy(int(short_window), int(long_window))
        signals = strategy.generate_signals(data)
        usable_signals = signals.dropna(subset=["short_ma", "long_ma"])
        if usable_signals.empty:
            st.warning("Dati insufficienti per calcolare le due medie mobili.")
        else:
            latest = usable_signals.iloc[-1]
            signal_text = "ACQUISTO" if int(latest["signal"]) == 1 else "USCITA" if int(latest["signal"]) == -1 else "NESSUN INCROCIO"
            st.subheader(f"Segnale strategia: {signal_text}")
            st.write(f"Motivazione: {latest['signal_reason']} · Generato sulla barra {latest['timestamp']}.")
            _plot_market_chart(data, signals, st.session_state.market_symbol, int(short_window), int(long_window), show_rsi)
        tv_col1, tv_col2 = st.columns(2)
        with tv_col1:
            st.link_button("Apri grafico su TradingView", _tradingview_url(st.session_state.market_symbol))
        with tv_col2:
            st.caption("TradingView è solo un link di analisi esterno e non è collegato all'esecuzione o al registro locale.")

with tab_sim:
    _show_simulation_account(float(spread_bps))
    account = ledger.account()
    data = st.session_state.get("market_frame")
    active_symbol = st.session_state.get("market_symbol")
    if account is not None:
        st.divider()
        st.subheader("Entry / uscita — simulazione locale")
        st.caption("I pulsanti registrano transazioni nel database locale. Non inviano ordini ad Alpaca.")
        positions = ledger.positions()
        held_position = next((pos for pos in positions if pos["symbol"] == active_symbol), None)
        stale_other_positions = [
            position for position in positions
            if position["symbol"] != active_symbol
            and (
                not position.get("mark_timestamp")
                or not _data_is_fresh(position["mark_timestamp"], st.session_state.get("market_interval", "1Day"))
            )
        ]
        quote = st.session_state.get("market_quote")
        order_timestamp = quote["timestamp"] if quote and quote.get("price") else (
            str(_latest_timestamp(data)) if data is not None else ""
        )
        fresh = bool(
            data is not None and active_symbol
            and st.session_state.get("market_symbol") == active_symbol
            and _data_is_fresh(order_timestamp, st.session_state.market_interval)
        )
        if data is None or not active_symbol:
            st.warning("Carica prima dati reali o attiva esplicitamente la modalità demo nella scheda Mercati.")
        elif not fresh:
            st.error("L'ultimo dato è obsoleto per l'intervallo selezionato: ordini locali bloccati.")
        else:
            price = float(quote["price"]) if quote and quote.get("price") else float(data["close"].iloc[-1])
            source_timestamp = order_timestamp
            source = str(quote["source"]) if quote and quote.get("price") else st.session_state.market_source + " — ultimo close barra"
            buy_tab, sell_tab = st.tabs(["Compra (long)", "Vendi posizione aperta"])
            with buy_tab:
                with st.form("local_sim_buy"):
                    qty = st.number_input("Quantità da acquistare", min_value=0.000001, value=0.01, format="%.6f")
                    reason = st.text_input("Motivo ingresso", value="Entry manuale utente")
                    buy_submit = st.form_submit_button(f"Conferma acquisto simulato — ${price:.4f}")
                if buy_submit:
                    request_id = st.session_state.setdefault("order_request_id", str(uuid.uuid4()))
                    try:
                        if stale_other_positions:
                            raise ValueError(
                                "Nuovi acquisti bloccati: aggiorna prima le quotazioni delle altre posizioni aperte."
                            )
                        result = ledger.buy(
                            symbol=active_symbol, quantity=float(qty), market_price=price,
                            commission_bps=float(commission_bps), spread_bps=float(spread_bps),
                            slippage_bps=float(slippage_bps),
                            max_trade_fraction=max_trade_fraction, max_exposure_fraction=max_exposure_fraction,
                            daily_loss_limit_fraction=daily_loss_fraction, data_timestamp=source_timestamp,
                            data_source=source, reason=reason,
                            max_data_age_seconds=_freshness_limit(st.session_state.market_interval).total_seconds(),
                            max_positions=settings.max_positions,
                            idempotency_key=request_id,
                        )
                        st.session_state.order_request_id = str(uuid.uuid4())
                        st.success("Acquisto registrato nella simulazione locale." if not result["duplicate"] else "Richiesta duplicata ignorata.")
                        st.rerun()
                    except (ValueError, RuntimeError) as exc:
                        st.error(f"Acquisto non registrato: {exc}")
            with sell_tab:
                if held_position is None:
                    st.info("Nessuna posizione aperta su questo strumento.")
                else:
                    with st.form("local_sim_sell"):
                        max_qty = float(held_position["quantity"])
                        sell_qty = st.number_input(
                            f"Quantità da vendere (massimo {max_qty:.6f})",
                            min_value=0.000001, max_value=max_qty, value=max_qty, format="%.6f",
                        )
                        sell_reason = st.text_input("Motivo uscita", value="Uscita manuale utente")
                        sell_submit = st.form_submit_button(f"Conferma vendita simulata — ${price:.4f}")
                    if sell_submit:
                        request_id = st.session_state.setdefault("order_request_id", str(uuid.uuid4()))
                        try:
                            result = ledger.sell(
                                symbol=active_symbol, quantity=float(sell_qty), market_price=price,
                                commission_bps=float(commission_bps), spread_bps=float(spread_bps),
                                slippage_bps=float(slippage_bps),
                                reason=sell_reason, data_timestamp=source_timestamp,
                                data_source=source,
                                max_data_age_seconds=_freshness_limit(st.session_state.market_interval).total_seconds(),
                                idempotency_key=request_id,
                            )
                            st.session_state.order_request_id = str(uuid.uuid4())
                            st.success(f"Vendita registrata localmente. P/L netto realizzato: ${result.get('net_pnl', 0):+.2f}")
                            st.rerun()
                        except (ValueError, RuntimeError) as exc:
                            st.error(f"Vendita non registrata: {exc}")

        st.divider()
        st.subheader("Storico completo delle operazioni")
        history = ledger.history()
        if history:
            history_frame = pd.DataFrame(history)
            filters = st.columns(3)
            with filters[0]:
                date_filter = st.date_input("Data apertura da", value=None)
            with filters[1]:
                symbol_filter = st.multiselect("Filtra strumenti", sorted(history_frame["symbol"].unique()))
            with filters[2]:
                status_filter = st.multiselect("Filtra stato", ["open", "closed", "cancelled"], default=["open", "closed"])
            if date_filter:
                history_frame = history_frame[
                    pd.to_datetime(history_frame["opened_at"], utc=True).dt.date >= date_filter
                ]
            if symbol_filter:
                history_frame = history_frame[history_frame["symbol"].isin(symbol_filter)]
            if status_filter:
                history_frame = history_frame[history_frame["status"].isin(status_filter)]
            history_frame["net_pnl_eur"] = history_frame["net_pnl"] / float(account["eur_usd_rate"])
            history_frame["return_pct"] = history_frame.apply(
                lambda row: (row["net_pnl"] / row["entry_invested"] * 100)
                if pd.notna(row["net_pnl"]) and row["entry_invested"] else None,
                axis=1,
            )
            history_frame = history_frame.rename(columns={
                "id": "ID posizione", "close_id": "ID chiusura", "symbol": "Strumento", "opened_at": "Apertura UTC",
                "closed_at": "Chiusura UTC", "direction": "Direzione", "quantity": "Quantità",
                "entry_price": "Prezzo ingresso", "exit_price": "Prezzo uscita",
                "entry_notional": "Valore entry", "entry_fee_alloc": "Commissione entry",
                "entry_invested": "Capitale impiegato entry",
                "exit_notional": "Valore uscita",
                "exit_fee": "Commissione uscita", "entry_spread_alloc": "Spread entry",
                "exit_spread": "Spread uscita", "entry_slippage_alloc": "Slippage entry",
                "exit_slippage": "Slippage uscita", "gross_pnl": "P/L lordo USD",
                "net_pnl": "P/L netto USD", "net_pnl_eur": "P/L netto EUR (FX iniziale)",
                "return_pct": "Rendimento % capitale impiegato", "entry_reason": "Motivo ingresso",
                "exit_reason": "Motivo uscita", "status": "Stato",
                "entry_data_source": "Fonte dati entry", "exit_data_source": "Fonte dati uscita",
                "exit_data_timestamp": "Timestamp dati uscita",
            })
            preferred = [
                "ID posizione", "ID chiusura", "Strumento", "Apertura UTC", "Chiusura UTC", "Direzione", "Quantità",
                "Prezzo ingresso", "Prezzo uscita", "Valore entry", "Valore uscita", "Commissione entry", "Commissione uscita",
                "Capitale impiegato entry", "Spread entry", "Spread uscita",
                "Slippage entry", "Slippage uscita", "P/L lordo USD", "P/L netto USD",
                "P/L netto EUR (FX iniziale)", "Rendimento % capitale impiegato",
                "Motivo ingresso", "Motivo uscita", "Stato", "Fonte dati entry",
                "Fonte dati uscita", "Timestamp dati uscita",
            ]
            st.dataframe(history_frame[[col for col in preferred if col in history_frame]], use_container_width=True, hide_index=True)
            st.caption("Il P/L netto EUR usa il cambio salvato all'inizializzazione del conto, non un cambio corrente. Le posizioni aperte non sono profitti realizzati.")
        else:
            st.info("Nessuna operazione registrata.")

        st.divider()
        reset_confirm = st.checkbox("Confermo di voler azzerare il conto virtuale e cancellare il relativo storico.")
        if st.button("Azzera simulazione locale", disabled=not reset_confirm, type="secondary"):
            ledger.reset(
                initial_eur=float(account["initial_eur"]),
                eur_usd_rate=float(account["eur_usd_rate"]),
                fx_source=str(account["fx_source"]),
                fx_timestamp=str(account["fx_timestamp"]),
            )
            st.rerun()

with tab_backtest:
    st.header("Backtesting — risultati separati")
    st.caption("Il backtest è separato dal conto simulato e dall'account Alpaca. Segnale calcolato alla chiusura della barra; esecuzione simulata all'apertura della barra successiva.")
    if "market_frame" not in st.session_state:
        st.info("Carica prima una serie storica nella scheda Mercati e strumenti.")
    else:
        data = st.session_state.market_frame
        backtest_capital = st.number_input("Capitale iniziale backtest (USD)", min_value=1.0, value=100.0, step=10.0)
        if st.button("Esegui backtest", type="primary"):
            try:
                engine = BacktestEngine(settings)
                result = engine.run(
                    data,
                    short_window=int(short_window),
                    long_window=int(long_window),
                    initial_capital=float(backtest_capital),
                    max_trade_fraction=max_trade_fraction,
                    daily_loss_limit_fraction=daily_loss_fraction,
                    commission_bps=float(commission_bps),
                    spread_bps=float(spread_bps),
                    slippage_bps=float(slippage_bps),
                )
                st.session_state.backtest_result = result.to_dict()
                st.session_state.backtest_source = st.session_state.market_source
            except ValueError as exc:
                st.error(f"Backtest non eseguito: {exc}")
        result = st.session_state.get("backtest_result")
        if result:
            st.info(f"Backtest su {st.session_state.get('backtest_source', 'fonte non registrata')}. Non è una previsione.")
            metrics = st.columns(4)
            metrics[0].metric("Capitale iniziale", f"${result['initial_capital']:.2f}")
            metrics[1].metric("Capitale finale mark-to-market", f"${result['final_capital']:.2f}")
            metrics[2].metric("Rendimento", f"{result['return_pct']:+.2f}%")
            metrics[3].metric("Drawdown massimo", f"{result['max_drawdown_pct']:.2f}%")
            stats = st.columns(4)
            stats[0].metric("Operazioni chiuse", result["total_trades"])
            stats[1].metric("Vincenti / perdenti", f"{result['winning_trades']} / {result['losing_trades']}")
            stats[2].metric("Win rate chiusi", f"{result['win_rate']:.1f}%")
            stats[3].metric(
                "Costi stimati",
                f"${result['fees_paid'] + result.get('slippage_paid', 0) + result.get('spread_paid', 0):.2f}",
            )
            st.plotly_chart(
                go.Figure(go.Scatter(y=result["equity_curve"], mode="lines", name="Equity backtest"))
                .update_layout(title="Curva capitale backtest (barre in ordine)", xaxis_title="Barra", yaxis_title="USD"),
                use_container_width=True,
            )
            if result.get("trade_history"):
                st.dataframe(pd.DataFrame(result["trade_history"]), use_container_width=True, hide_index=True)
            if result.get("open_position_quantity"):
                st.caption(f"Posizione finale ancora aperta: {result['open_position_quantity']:.6f}; valutata all'ultimo close e non contata come profitto realizzato.")
            st.caption("Commissioni e slippage sono stime configurabili. I risultati storici non garantiscono risultati futuri.")

with tab_alpaca:
    st.header("Alpaca Paper Trading — sola lettura")
    st.warning("Questa sezione legge soltanto account, posizioni e ordini esistenti. Non esistono pulsanti che inviano ordini.")
    st.caption("Account Paper Trading separato dal conto virtuale locale e dal backtest; saldo e risultati non vengono sommati.")
    if not broker.paper_client_configured:
        st.info("Client Paper Alpaca non configurato. Le credenziali mancanti non bloccano la simulazione locale.")
    elif st.button("Verifica connessione Paper"):
        status = broker.verify_connection()
        st.session_state.paper_verified = bool(status["connected"])
        if status["connected"]:
            st.success(status["message"])
        else:
            st.error(status["message"])
        st.rerun()
    if st.session_state.get("paper_verified", False) and st.button("Leggi posizioni e ordini Paper"):
        status = broker.verify_connection()
        st.session_state.paper_verified = bool(status["connected"])
        if not status["connected"]:
            st.error(status["message"])
        else:
            try:
                st.markdown("**Posizioni paper Alpaca (non incluse nel conto locale)**")
                paper_positions = broker.get_positions()
                st.dataframe(pd.DataFrame([item.model_dump() if hasattr(item, "model_dump") else item for item in paper_positions]), use_container_width=True)
                st.markdown("**Ordini paper Alpaca esistenti (sola lettura)**")
                paper_orders = broker.get_orders()
                st.dataframe(pd.DataFrame([item.model_dump() if hasattr(item, "model_dump") else item for item in paper_orders]), use_container_width=True)
            except Exception:
                st.error("Lettura account Paper non riuscita; dettagli sensibili non mostrati.")
