from __future__ import annotations

import math
import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine, backtest_input_key
from src.backtesting.walk_forward import walk_forward_evaluate
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError
from src.data.fx_rates import fetch_eur_usd_rate
from src.data.instruments import CRYPTO_SYMBOLS, EQUITY_SYMBOLS, INSTRUMENTS
from src.data.market_data import generate_synthetic_market_data
from src.data.bar_timing import BarTimingError, select_completed_bars
from src.simulation.ledger import SimulationLedger, resolve_simulation_database_path
from src.strategy.moving_average import MovingAverageStrategy
from src.ui.charts import plot_market_chart as _plot_market_chart
from src.ui.presentation import (data_status, finite_number, freshness_limit as _freshness_limit,
                                 money as _money_or_unavailable, paper_metrics, signal_view, unique_orders)
from src.trading.paper_automation import (
    PaperAutomationError,
    PaperAutomationLog,
    execute_paper_signal,
)


st.set_page_config(page_title="AI Trading Bot | Paper & Demo", page_icon="📈", layout="wide")
st.markdown(
    """
    <style>
    :root { color-scheme: dark; }
    .stApp { background: #0b0f14; color: #e6edf3; }
    [data-testid="stHeader"] { background: rgba(11, 15, 20, 0.92); }
    [data-testid="stSidebar"] { background: #111820; border-right: 1px solid #263342; }
    [data-testid="stMetric"] {
        background: #121a23; border: 1px solid #263342; border-radius: 10px;
        padding: 12px 14px;
    }
    [data-testid="stTabs"] button[role="tab"] { color: #b7c5d3; }
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: #69b7ff; border-bottom-color: #2785d8;
    }
    [data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {
        border: 1px solid #263342; border-radius: 8px; overflow: hidden;
    }
    div[data-testid="stAlert"] { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

ROOT = Path(__file__).resolve().parent
settings = AppSettings.from_env()
DEMO_DB_PATH_ENV = "AI_TRADINGBOT_DEMO_DB_PATH"
PAPER_DB_PATH_ENV = "AI_TRADINGBOT_PAPER_DB_PATH"
if settings.trading_mode == "demo" and DEMO_DB_PATH_ENV not in os.environ:
    if PAPER_DB_PATH_ENV in os.environ:
        raise RuntimeError(
            "Paper configuration was not available and runtime mode fell back to demo. "
            "Check local Paper setup or start the isolated demo launcher; no Paper/personal database was opened."
        )
    raise RuntimeError(
        "Demo mode requires an isolated database path. Start the app with .\\avvia_demo.ps1 "
        "or set AI_TRADINGBOT_DEMO_DB_PATH to an absolute path outside the personal ledger."
    )
if settings.trading_mode == "demo":
    DB_PATH = resolve_simulation_database_path(ROOT, os.environ[DEMO_DB_PATH_ENV])
elif settings.trading_mode == "paper":
    if PAPER_DB_PATH_ENV in os.environ:
        configured_paper_path = os.environ[PAPER_DB_PATH_ENV]
    else:
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError(
                "Paper mode requires AI_TRADINGBOT_PAPER_DB_PATH or LOCALAPPDATA "
                "to keep its database separate from the personal ledger."
            )
        configured_paper_path = str(
            Path(local_app_data) / "AITradingBot" / "paper" / "simulation.sqlite3"
        )
    DB_PATH = resolve_simulation_database_path(ROOT, configured_paper_path)
else:
    raise RuntimeError("Unsupported trading mode; start in demo or paper mode.")

other_mode = "paper" if settings.trading_mode == "demo" else "demo"
other_database_path = os.environ.get(PAPER_DB_PATH_ENV if other_mode == "paper" else DEMO_DB_PATH_ENV)
if not other_database_path and os.getenv("LOCALAPPDATA"):
    other_database_path = str(
        Path(os.environ["LOCALAPPDATA"]) / "AITradingBot" / other_mode / "simulation.sqlite3"
    )
if other_database_path:
    resolved_other_path = resolve_simulation_database_path(ROOT, other_database_path)
    if DB_PATH == resolved_other_path or (
        DB_PATH.exists() and resolved_other_path.exists() and DB_PATH.samefile(resolved_other_path)
    ):
        raise RuntimeError("Paper and demo modes must use separate database files.")

@st.cache_resource(show_spinner=False)
def _runtime_resources(session_id: str, database_path: str, _settings: AppSettings):
    del session_id
    return AlpacaClient(_settings), SimulationLedger(database_path)


@st.cache_resource(show_spinner=False)
def _paper_log_resource(database_path: str) -> PaperAutomationLog:
    return PaperAutomationLog(database_path)


broker, ledger = _runtime_resources(
    st.session_state.setdefault("_runtime_session_id", str(uuid.uuid4())),
    str(DB_PATH),
    settings,
)
paper_automation_log = (
    _paper_log_resource(str(DB_PATH)) if settings.trading_mode == "paper" else None
)
WALK_FORWARD_CANDIDATES = (
    {"short_window": 2, "long_window": 4},
    {"short_window": 3, "long_window": 6},
    {"short_window": 5, "long_window": 10},
)


def _latest_timestamp(data: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(data["timestamp"].iloc[-1])


def _data_is_fresh(timestamp: object, interval: str) -> bool:
    return data_status(timestamp, interval, "real")["state"] == "fresh"


def _tradingview_url(symbol: str) -> str:
    if "/" in symbol:
        tv_symbol = f"BINANCE:{symbol.replace('/', '')}"
    elif symbol in {"SPY", "GLD"}:
        tv_symbol = f"AMEX:{symbol}"
    else:
        tv_symbol = f"NASDAQ:{symbol}"
    return f"https://www.tradingview.com/chart/?symbol={quote(tv_symbol, safe='')}"


@st.cache_data(ttl=300, show_spinner=False)
def _cached_asset_availability(symbol: str, runtime_session_id: str) -> dict:
    del runtime_session_id
    return broker.get_instrument_availability(symbol)


def _load_data(symbol: str, interval: str, period: str, demo: bool) -> tuple[pd.DataFrame, str]:
    if demo:
        if interval != "1Day":
            raise ValueError("La serie sintetica dimostrativa è giornaliera; seleziona 1Day.")
        periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "5Y": 1000}[period]
        result = generate_synthetic_market_data(symbol=symbol, periods=periods)
        result.attrs["source"] = "Serie sintetica locale (non sono prezzi reali)"
        result.attrs["quality"] = "synthetic"
        result.attrs["interval"] = interval
        result.attrs["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return result, "Serie sintetica locale"
    result = broker.get_market_data(
        symbol, timeframe=interval, period=period, limit=None,
    )
    if result is None or result.empty:
        raise BrokerConnectionError("Nessuna barra disponibile per la selezione corrente.")
    result.attrs["quality"] = "real"
    result.attrs["interval"] = interval
    return result, str(result.attrs.get("source", "Alpaca market data"))


def _model_dict(item: object) -> dict:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {}


def _show_paper_snapshot(snapshot: dict) -> None:
    account = snapshot.get("account") or {}
    account = _model_dict(account)

    raw_positions = snapshot.get("positions")
    positions = [_model_dict(item) for item in raw_positions or []]
    orders = unique_orders([_model_dict(item) for item in snapshot.get("orders") or []])
    values = paper_metrics(account, positions if raw_positions is not None else None)
    equity, cash, buying_power = (values[name] for name in ("equity", "cash", "buying_power"))
    daily_change, daily_percent = values["daily_change"], values["daily_percent"]
    market_value, unrealized = values["market_value"], values["unrealized"]
    unavailable_message = "N/D — il broker non ha fornito un valore valido."

    account_metrics = st.columns(3)
    account_metrics[0].metric(
        "Saldo in contanti (Paper)",
        _money_or_unavailable(cash),
        help=(
            "N/D: Alpaca non ha restituito cash valido."
            if cash is None
            else "Cash riportato direttamente dal conto Alpaca Paper; non è il ledger locale."
        ),
    )
    account_metrics[1].metric(
        "Equity Alpaca Paper",
        _money_or_unavailable(equity),
        help=(
            "N/D: Alpaca non ha restituito equity valida."
            if equity is None
            else "Valore totale del conto restituito da Alpaca, distinto dal cash disponibile."
        ),
    )
    account_metrics[2].metric(
        "Liquidità utilizzabile (buying power)",
        _money_or_unavailable(buying_power),
        help=(
            "N/D: Alpaca non ha restituito buying power valido."
            if buying_power is None
            else "Buying power fornito da Alpaca. Non equivale sempre al saldo cash."
        ),
    )
    valuation = st.columns(3)
    valuation[0].metric(
        "Valore di mercato posizioni (Paper)",
        _money_or_unavailable(market_value),
        help=(
            "Somma del valore assoluto di mercato delle posizioni restituite. "
            "È N/D se almeno una posizione non include un valore valido."
        ),
    )
    valuation[1].metric(
        "P/L non realizzato Paper",
        _money_or_unavailable(unrealized),
        help=(
            "Somma del P/L non realizzato fornito dal broker. Non è calcolato "
            "da prezzi storici o dal ledger locale."
        ),
    )
    valuation[2].metric(
        "Variazione equity vs close precedente",
        _money_or_unavailable(daily_change),
        f"{daily_percent:+.2f}%" if daily_percent is not None else "N/D",
        help=(
            unavailable_message if daily_change is None
            else "Differenza equity - last_equity ricevuta da Alpaca; non è il solo P/L realizzato."
        ),
    )
    realized_reason = (
        "N/D — il riepilogo conto Alpaca non fornisce il P/L realizzato complessivo."
    )
    total_reason = (
        "N/D — non è disponibile un capitale iniziale affidabile del conto per "
        "calcolare il P/L totale."
    )
    pnl_metrics = st.columns(2)
    pnl_metrics[0].metric("P/L realizzato Paper", "N/D", help=realized_reason)
    pnl_metrics[1].metric("P/L totale Paper", "N/D", help=total_reason)
    st.caption(f"{realized_reason} {total_reason}")

    updated_at = snapshot.get("updated_at")
    if updated_at:
        try:
            update_time = pd.Timestamp(updated_at)
            if update_time.tzinfo is None:
                update_time = update_time.tz_localize("UTC")
            age_seconds = finite_number((datetime.now(timezone.utc) - update_time.tz_convert("UTC").to_pydatetime()).total_seconds())
            if age_seconds is None or age_seconds < 0:
                raise ValueError("Invalid snapshot timestamp")
            update_label = (
                f"Ultimo aggiornamento UTC: {updated_at} "
                f"({age_seconds:.0f} secondi fa)."
            )
            if age_seconds > 45:
                st.warning("Snapshot Paper non aggiornato da oltre 45 secondi.")
        except (TypeError, ValueError, OverflowError):
            update_label = f"Ultimo aggiornamento UTC: N/D — timestamp non valido ({updated_at})."
            st.warning("Timestamp dello snapshot non affidabile; non considerare il conto aggiornato.")
    else:
        update_label = "Ultimo aggiornamento UTC: N/D — timestamp assente."
    st.caption(
        f"Connessione verificata · Account Alpaca Paper: {account.get('status', 'N/D')} · "
        f"{update_label} Saldo e posizioni provengono dal broker, separati dal ledger locale e dal backtest."
    )
    position_col, orders_col = st.columns(2)
    with position_col:
        st.markdown("**Posizioni Paper**")
        if positions:
            position_rows = []
            fields = (
                ("symbol", "Strumento"),
                ("qty", "Quantità"),
                ("qty_available", "Quantità disponibile"),
                ("avg_entry_price", "Prezzo medio USD"),
                ("current_price", "Prezzo corrente USD"),
                ("market_value", "Valore di mercato USD"),
                ("unrealized_pl", "P/L non realizzato USD"),
            )
            for position in positions:
                row = {
                    label: (
                        position.get(source)
                        if position.get(source) is not None
                        else "N/D (campo non fornito dal broker)"
                    )
                    for source, label in fields
                }
                unrealized_percent = position.get("unrealized_plpc")
                if unrealized_percent is None:
                    row["P/L non realizzato %"] = "N/D (campo non fornito dal broker)"
                else:
                    try:
                        percent = float(unrealized_percent) * 100
                    except (TypeError, ValueError, OverflowError):
                        row["P/L non realizzato %"] = "N/D (campo non valido)"
                    else:
                        row["P/L non realizzato %"] = (
                            f"{percent:+.2f}%" if math.isfinite(percent)
                            else "N/D (campo non valido)"
                        )
                position_rows.append(row)
            st.dataframe(pd.DataFrame(position_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Nessuna posizione aperta." if raw_positions is not None else "Posizioni N/D: elenco non fornito dal broker.")
    with orders_col:
        st.markdown("**Ordini Paper recenti e pendenti**")
        if orders:
            terminal_states = {
                "filled", "canceled", "cancelled", "rejected", "expired", "replaced",
            }
            pending = [
                order for order in orders
                if str(order.get("status", "")).lower() not in terminal_states
            ]
            ordered = sorted(
                orders,
                key=lambda order: str(
                    order.get("submitted_at") or order.get("created_at") or ""
                ),
                reverse=True,
            )
            selected_orders = pending + [
                order for order in ordered if order not in pending
            ][:max(0, 10 - len(pending))]
            order_filter = st.selectbox("Filtro ordini Paper", ["Tutti", "Pendenti", "Con quantità eseguita", "Rifiutati/cancellati"], key="paper_order_filter")
            if order_filter == "Pendenti":
                selected_orders = pending
            elif order_filter == "Con quantità eseguita":
                selected_orders = [order for order in orders if (finite_number(order.get("filled_qty")) or 0) > 0]
            elif order_filter == "Rifiutati/cancellati":
                selected_orders = [order for order in orders if str(order.get("status", "")).lower() in {"rejected", "canceled", "cancelled"}]
            order_fields = (
                ("symbol", "Strumento"),
                ("side", "Lato"),
                ("qty", "Quantità richiesta"),
                ("filled_qty", "Quantità eseguita"),
                ("status", "Stato"),
                ("submitted_at", "Inviato UTC"),
                ("filled_at", "Eseguito UTC"),
            )
            order_rows = [
                {
                    label: (
                        order.get(source)
                        if order.get(source) is not None
                        else "N/D"
                    )
                    for source, label in order_fields
                }
                for order in selected_orders
            ]
            st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)
            st.caption(
                f"Ordini aperti/pending: {len(pending)} · mostrati anche gli ultimi "
                f"{max(0, len(selected_orders) - len(pending))} ordini recenti."
            )
            confirmed = [order for order in orders if (finite_number(order.get("filled_qty")) or 0) > 0
                         and (finite_number(order.get("filled_avg_price")) or 0) > 0
                         and not pd.isna(pd.to_datetime(order.get("filled_at"), utc=True, errors="coerce"))]
            if confirmed:
                st.markdown("**Esecuzioni confermate dal broker (anche parziali)**")
                st.dataframe(pd.DataFrame([{name: order.get(name, "N/D") for name in
                    ("symbol", "filled_qty", "filled_avg_price", "filled_at")} for order in confirmed]),
                    use_container_width=True, hide_index=True)
        else:
            st.caption("Nessun ordine restituito dall'account.")


@st.fragment(run_every="15s")
def _paper_account_monitor() -> None:
    st.subheader("Monitoraggio conto Alpaca Paper")
    if not broker.paper_client_configured or settings.trading_mode != "paper":
        st.info("Account Paper non configurato. Il ledger locale rimane disponibile in modalità demo.")
        return
    if not st.session_state.get("paper_verified", False):
        if st.button("Verifica e aggiorna conto Alpaca Paper", key="paper_verify_snapshot"):
            try:
                snapshot = broker.get_paper_snapshot()
                st.session_state.paper_verified = True
                st.session_state.paper_snapshot = snapshot
                st.session_state.paper_snapshot_error = None
            except BrokerConnectionError as exc:
                st.session_state.paper_verified = False
                st.session_state.pop("paper_snapshot", None)
                st.session_state.paper_snapshot_error = str(exc)
    elif st.session_state.get("paper_verified"):
        try:
            snapshot = broker.get_paper_snapshot()
            st.session_state.paper_snapshot = snapshot
            st.session_state.paper_snapshot_error = None
        except BrokerConnectionError as exc:
            st.session_state.paper_verified = False
            st.session_state.paper_automation_active = False
            st.session_state.pop("paper_snapshot", None)
            st.session_state.paper_snapshot_error = str(exc)
            st.error("Connessione Paper persa: automazione arrestata.")
    if st.session_state.get("paper_snapshot_error"):
        st.error(f"Stato Paper non disponibile: {st.session_state.paper_snapshot_error}")
    snapshot = st.session_state.get("paper_snapshot")
    if snapshot and st.session_state.get("paper_verified"):
        _show_paper_snapshot(snapshot)
    if st.session_state.get("paper_verified"):
        if st.button("Disconnetti monitor Paper", key="paper_disconnect"):
            st.session_state.paper_verified = False
            st.session_state.paper_automation_active = False
            st.session_state.pop("paper_snapshot", None)
            st.session_state.paper_snapshot_error = None
            st.rerun()
    st.caption(
        "Aggiornamento account, posizioni e ordini ogni 15 secondi mentre la dashboard è aperta. "
        "Se la richiesta fallisce, lo snapshot viene nascosto finché la connessione non viene riverificata."
    )


@st.fragment(run_every="15s")
def _live_quote_monitor(
    symbol: str,
    source_quality: str,
    data: pd.DataFrame,
    short_window: int,
    long_window: int,
    show_rsi: bool,
) -> None:
    if source_quality != "real":
        return
    try:
        current_data = st.session_state.get("market_frame")
        if (
            isinstance(current_data, pd.DataFrame)
            and st.session_state.get("market_symbol") == symbol
        ):
            interval = str(st.session_state.get("market_interval", ""))
            interval_seconds = {
                "1Min": 60,
                "5Min": 300,
                "15Min": 900,
                "1Hour": 3600,
                "1Day": 86_400,
                "1Week": 604_800,
            }.get(interval)
            if interval_seconds is not None and not current_data.empty:
                last_timestamp = pd.Timestamp(current_data["timestamp"].iloc[-1])
                incremental = broker.get_market_data(
                    symbol,
                    timeframe=interval,
                    period="1M",
                    limit=100,
                    start_time=(last_timestamp - timedelta(seconds=interval_seconds)).to_pydatetime(),
                )
                if not incremental.empty:
                    combined = pd.concat([current_data, incremental], ignore_index=True)
                    combined = combined.drop_duplicates("timestamp", keep="last")
                    combined = combined.sort_values("timestamp").tail(10_000).reset_index(drop=True)
                    combined.attrs.update(current_data.attrs)
                    combined.attrs["quality"] = "real"
                    combined.attrs["interval"] = interval
                    combined.attrs["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    st.session_state.market_frame = combined
                    current_data = combined
                st.session_state.market_incremental_error = None
    except BrokerConnectionError as exc:
        st.session_state.market_incremental_error = str(exc)
        st.warning(f"Aggiornamento incrementale OHLC non disponibile; storico già caricato mantenuto: {exc}")
    try:
        refreshed_at = st.session_state.get("market_quote_refreshed_at")
        quote = st.session_state.get("market_quote")
        if (
            not quote
            or not refreshed_at
            or (datetime.now(timezone.utc) - refreshed_at).total_seconds() >= 10
        ):
            quote = broker.get_latest_quote(symbol)
            st.session_state.market_quote_refreshed_at = datetime.now(timezone.utc)
        try:
            observed = pd.Timestamp(quote.get("timestamp"))
            if pd.isna(observed):
                raise ValueError("Missing quote timestamp")
        except (TypeError, ValueError, OverflowError):
            raise BrokerConnectionError("Timestamp quotazione non valido; storico mantenuto.") from None
        if observed.tzinfo is None:
            observed = observed.tz_localize("UTC")
        age = datetime.now(timezone.utc) - observed.tz_convert("UTC").to_pydatetime()
        if age > timedelta(minutes=2) or age < timedelta(0):
            quote = None
            st.session_state.market_quote = None
            st.session_state.pop("market_quote_refreshed_at", None)
            st.session_state.market_quote_error = (
                "La quotazione ha un timestamp futuro."
                if age < timedelta(0)
                else "La quotazione restituita dal feed è più vecchia di due minuti."
            )
            st.warning(f"Ultima quotazione scaduta o con timestamp futuro ({age.total_seconds() / 60:.1f} min).")
        else:
            st.session_state.market_quote = quote
            st.session_state.market_quote_error = None
            local_account = ledger.account()
            if local_account is not None:
                ledger.update_mark(
                    symbol,
                    float(quote["price"]),
                    str(quote["timestamp"]),
                    str(quote["source"]),
                )
            columns = st.columns(3)
            columns[0].metric("Quotazione aggiornata", f"${float(quote['price']):,.4f}")
            columns[1].metric("Timestamp quotazione UTC", str(quote["timestamp"]))
            columns[2].metric("Fonte feed", str(quote["source"]))
        latest_data = (
            current_data.copy()
            if isinstance(current_data, pd.DataFrame)
            else data.copy()
        )
        st.caption(
            f"Ultima barra OHLC disponibile: {_latest_timestamp(latest_data)} · "
            f"fonte: {st.session_state.get('market_source', 'n/d')}."
        )
        signals = MovingAverageStrategy(short_window, long_window).generate_signals(latest_data)
        paper_snapshot = st.session_state.get("paper_snapshot") or {}
        _plot_market_chart(
            latest_data,
            signals,
            symbol,
            short_window,
            long_window,
            show_rsi,
            paper_orders=[_model_dict(item) for item in paper_snapshot.get("orders") or []],
            latest_quote=quote,
            local_history=ledger.history(),
        )
    except BrokerConnectionError as exc:
        st.session_state.market_quote = None
        st.session_state.pop("market_quote_refreshed_at", None)
        st.session_state.market_quote_error = str(exc)
        st.warning(f"Feed quotazioni non disponibile; grafico storico invariato: {exc}")
        fallback_data = st.session_state.get("market_frame", data)
        signals = MovingAverageStrategy(short_window, long_window).generate_signals(fallback_data)
        snapshot = st.session_state.get("paper_snapshot") or {}
        _plot_market_chart(
            fallback_data,
            signals,
            symbol,
            short_window,
            long_window,
            show_rsi,
            paper_orders=[_model_dict(item) for item in snapshot.get("orders") or []],
            latest_quote=None,
            local_history=ledger.history(),
        )


@st.fragment(run_every="15s")
def _paper_automation_panel(
    symbol: str | None,
    interval: str | None,
    quality: str | None,
    market_data: pd.DataFrame | None,
    short_window: int,
    long_window: int,
    automation_settings: AppSettings,
    max_daily_orders: int,
) -> None:
    def record_event(event: dict) -> None:
        if paper_automation_log is None:
            st.error("Log Paper non disponibile fuori dalla modalità Alpaca Paper.")
            return
        try:
            paper_automation_log.record({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol or "N/D",
                "signal_timestamp_utc": event.get("signal_timestamp"),
                "signal": event.get("signal", event.get("side", "N/D")),
                "decision": event.get("status", "unknown"),
                "side": event.get("side"),
                "quantity": event.get("quantity"),
                "order_status": _model_dict(event.get("order", {})).get("status"),
                "reason": event.get("reason", ""),
            })
        except sqlite3.Error as exc:
            st.error(f"Impossibile salvare l'evento nel log locale Paper: {exc}")

    def show_history() -> None:
        if paper_automation_log is None:
            return
        try:
            history = paper_automation_log.recent(25)
        except sqlite3.Error as exc:
            st.error(f"Impossibile leggere il log locale Paper: {exc}")
            return
        if history:
            st.markdown("**Log locale persistente — attività recenti del bot**")
            decisions = st.multiselect("Filtra decisioni", sorted({row["decision"] for row in history}), key="paper_log_decisions")
            displayed = [row for row in history if not decisions or row["decision"] in decisions]
            frame = pd.DataFrame(displayed).fillna("N/D")
            st.caption("Ultimi 25 eventi locali. Timeframe, versione strategia e fonte non registrati nei vecchi eventi restano N/D; non vengono ricostruiti dai parametri correnti.")
            st.dataframe(
                frame,
                use_container_width=True,
                hide_index=True,
            )
            st.download_button("Scarica decisioni CSV (eventi mostrati)", frame.to_csv(index=False),
                               file_name="decisioni-paper.csv", mime="text/csv", key="paper_log_csv")

    current_market_data = st.session_state.get("market_frame")
    if (
        st.session_state.get("market_symbol") != symbol
        or st.session_state.get("market_quality") != quality
    ):
        current_market_data = None

    st.subheader("Automazione moving-average — solo Paper")
    st.caption(
        "Ogni ciclo valuta un segnale fresco, account, posizioni e ordini; un ordine inviato "
        "resta pending finché Alpaca non ne restituisce lo stato di fill. L'arresto ferma i "
        "cicli successivi ma non annulla ordini già inviati: gestiscili dal conto Paper. "
        "Il log locale registra timestamp, segnale, decisione, stato ordine e motivazione, "
        "senza credenziali."
    )
    active = bool(st.session_state.get("paper_automation_active", False))
    coordinated = getattr(broker, "paper_coordinator", None) is not None
    if not coordinated:
        st.warning("Invio Paper bloccato: esecutore esclusivo per conto non configurato. Il coordinamento distribuito non è supportato; l'anteprima DRY-RUN resta separata.")
    preview_requested = False
    if active:
        st.error("Automazione Paper ATTIVA per questa sessione.")
        if st.button("Arresto immediato", type="primary", key="paper_auto_stop"):
            st.session_state.paper_automation_active = False
            st.session_state.paper_auto_result = {
                "status": "stopped",
                "reason": "Arresto manuale.",
            }
            record_event(st.session_state.paper_auto_result)
            st.rerun()
    else:
        st.info("Automazione arrestata. L'attivazione richiede un'azione esplicita.")
        preview_requested = st.button(
            "Esegui anteprima DRY-RUN",
            disabled=(not broker.paper_client_configured or settings.trading_mode != "paper"
                      or not st.session_state.get("paper_verified", False) or quality != "real"
                      or current_market_data is None or symbol is None),
            help="Valuta account, dati e rischio una volta. Non avvia l'automazione e non invia ordini.",
            key="paper_auto_preview",
        )
        if st.button(
            "Avvia automazione Paper",
            type="primary",
            disabled=(
                not coordinated
                or not broker.paper_client_configured
                or settings.trading_mode != "paper"
                or not st.session_state.get("paper_verified", False)
                or quality != "real"
                or current_market_data is None
                or symbol is None
            ),
            key="paper_auto_start",
        ):
            st.session_state.paper_automation_active = True
            st.session_state.paper_auto_result = None
            active = True
    if not active and not preview_requested:
        if (
            settings.trading_mode != "paper"
            or not broker.paper_client_configured
        ):
            st.warning("Ordini automatici disabilitati: seleziona Paper con credenziali e account verificabili.")
        elif quality != "real":
            st.warning("Per l'automazione sono richiesti dati Alpaca reali; la serie sintetica è esclusa.")
        elif not st.session_state.get("paper_verified", False):
            st.warning("Verifica l'account Paper nella panoramica prima di avviare il bot.")
        show_history()
        return

    if (
        settings.trading_mode != "paper"
        or not broker.paper_client_configured
        or not st.session_state.get("paper_verified", False)
        or quality != "real"
        or current_market_data is None
        or symbol is None
        or interval is None
    ):
        st.session_state.paper_automation_active = False
        st.error("Prerequisito Paper/feed non valido: automazione arrestata senza inviare ordini.")
        show_history()
        return
    if short_window >= long_window:
        st.session_state.paper_automation_active = False
        st.error("Parametri medie mobili non validi: automazione arrestata.")
        show_history()
        return
    try:
        automation_data = current_market_data.copy()
        automation_data.attrs["quality"] = quality
        automation_data.attrs["interval"] = interval
        result = execute_paper_signal(
            broker=broker,
            settings=automation_settings,
            symbol=symbol,
            market_data=automation_data,
            short_window=short_window,
            long_window=long_window,
            max_daily_orders=max_daily_orders,
            dry_run=preview_requested,
        )
        if preview_requested:
            result["reason"] = "DRY-RUN — nessun ordine inviato. " + result["reason"]
        st.session_state.paper_auto_result = result
        if result.get("requires_stop"):
            st.session_state.paper_automation_active = False
            st.warning("Automazione arrestata: proprietà dell'esecutore o stato del conto non verificabile.")
        record_event(result)
        if result["status"] == "dry_run":
            st.success(f"DRY-RUN: {result['side']} {result['quantity']} · {result['symbol']}. Nessun ordine inviato; automazione arrestata.")
            st.caption(f"Riferimento {'ask' if result['side'] == 'buy' else 'bid'}: {result['reference_price']} USD · {result['reference_timestamp']}. Stop e target: N/D, non definiti dalla SMA.")
            st.caption(f"Controvalore teorico: {_money_or_unavailable(result['quantity'] * result['reference_price'])}. Rischio fino allo stop, target e costi effettivi broker: N/D. Il dimensionamento non è un rendimento garantito.")
        elif result["status"] == "submitted":
            order = _model_dict(result.get("order", {}))
            broker_status = order.get("status", "accepted/unknown")
            st.warning(
                f"Ordine Paper inviato ({result.get('side')} {result.get('quantity')}); "
                f"stato broker: {broker_status}. Nessun fill è presunto."
            )
        elif result["status"] == "no_signal":
            st.caption(f"Nessun incrocio operativo sull'ultima barra: {result['reason']}")
        else:
            st.info(f"Ciclo {result['status']}: {result['reason']}")
        st.caption(f"Ultimo ciclo UTC: {datetime.now(timezone.utc).isoformat()}")
    except (BrokerConnectionError, PaperAutomationError, ValueError, PermissionError) as exc:
        st.session_state.paper_automation_active = False
        st.session_state.paper_auto_result = {"status": "stopped", "reason": str(exc)}
        record_event(st.session_state.paper_auto_result)
        st.error(f"Automazione arrestata: {exc}")
    show_history()


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
    pnl[0].metric("P/L realizzato netto", f"${summary['realized_pnl']:+,.2f}")
    pnl[1].metric("P/L non realizzato netto", f"${summary['unrealized_pnl']:+,.2f}")
    pnl[2].metric("Commissioni pagate", f"${summary['fees']:,.2f}")
    pnl[3].metric("Slippage stimato pagato", f"${summary['slippage']:,.2f}")
    st.metric("Spread stimato pagato", f"${summary['spread']:,.2f}")
    today_utc = datetime.now(timezone.utc).date()
    realized_today = sum(
        float(item["net_pnl"])
        for item in ledger.history()
        if item["status"] == "closed"
        and item["closed_at"]
        and pd.Timestamp(item["closed_at"]).date() == today_utc
        and item["net_pnl"] is not None
    )
    st.metric("P/L realizzato oggi (UTC)", f"${realized_today:+,.2f}")
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
            )).update_layout(
                template="plotly_dark",
                paper_bgcolor="#0b0f14",
                plot_bgcolor="#0b0f14",
                title="Curva equity — simulazione locale",
                xaxis_title="Data",
                yaxis_title="USD",
            ),
            use_container_width=True,
        )
        curve_frame = pd.DataFrame(summary["equity_curve"])
        if len(curve_frame) > 1:
            curve_frame["timestamp"] = pd.to_datetime(curve_frame["timestamp"], utc=True)
            curve_frame = curve_frame.sort_values("timestamp").drop_duplicates(
                "timestamp", keep="last"
            )
            monthly_equity = (
                curve_frame.set_index("timestamp")["equity"].resample("ME").last().dropna()
            )
            if not monthly_equity.empty:
                monthly_returns = monthly_equity.pct_change() * 100
                first_month = monthly_equity.index[0]
                month_start = pd.Timestamp(
                    year=first_month.year,
                    month=first_month.month,
                    day=1,
                    tz="UTC",
                )
                previous = curve_frame[curve_frame["timestamp"] < month_start]
                first_base = (
                    float(previous.iloc[-1]["equity"])
                    if not previous.empty
                    else float(summary["initial_capital"])
                )
                monthly_returns.iloc[0] = (
                    (float(monthly_equity.iloc[0]) / first_base - 1) * 100
                    if first_base > 0
                    else float("nan")
                )
                monthly_frame = monthly_returns.rename("Rendimento equity %").reset_index()
                st.plotly_chart(
                    go.Figure(go.Bar(
                        x=monthly_frame["timestamp"],
                        y=monthly_frame["Rendimento equity %"],
                        marker_color=[
                            "#26a69a" if value >= 0 else "#ef5350"
                            for value in monthly_frame["Rendimento equity %"].fillna(0)
                        ],
                        name="Rendimento mensile",
                    )).update_layout(
                        template="plotly_dark",
                        paper_bgcolor="#0b0f14",
                        plot_bgcolor="#0b0f14",
                        title="Rendimento mensile / MTD equity — ledger locale",
                        xaxis_title="Mese",
                        yaxis_title="Variazione equity %",
                    ),
                    use_container_width=True,
                )
                st.caption(
                    "Rendimento mensile calcolato sulle equity mensili salvate; il mese corrente è "
                    "parziale (MTD). La curva locale include i prezzi segnati disponibili."
                )
            running_peak = curve_frame["equity"].cummax()
            drawdown = (curve_frame["equity"] / running_peak - 1) * 100
            st.plotly_chart(
                go.Figure(go.Scatter(
                    x=curve_frame["timestamp"],
                    y=drawdown,
                    fill="tozeroy",
                    name="Drawdown equity",
                    line={"color": "#ef5350"},
                )).update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    title="Drawdown — ledger locale",
                    yaxis_title="Drawdown %",
                ),
                use_container_width=True,
            )
    closed_history = [
        item for item in ledger.history()
        if item["status"] == "closed" and item["closed_at"] and item["net_pnl"] is not None
    ]
    if closed_history:
        trade_frame = pd.DataFrame(closed_history)
        trade_frame["closed_at"] = pd.to_datetime(trade_frame["closed_at"], utc=True)
        monthly_realized = (
            trade_frame.set_index("closed_at")["net_pnl"].resample("ME").sum().rename("P/L netto USD")
        )
        chart_columns = st.columns(2)
        with chart_columns[0]:
            st.plotly_chart(
                go.Figure(go.Bar(
                    x=monthly_realized.index,
                    y=monthly_realized.values,
                    name="P/L realizzato mensile",
                    marker_color=["#26a69a" if value >= 0 else "#ef5350" for value in monthly_realized],
                )).update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    title="P/L realizzato netto per mese",
                    xaxis_title="Mese",
                    yaxis_title="USD",
                ),
                use_container_width=True,
            )
        with chart_columns[1]:
            st.plotly_chart(
                go.Figure(go.Histogram(
                    x=trade_frame["net_pnl"],
                    marker_color="#42a5f5",
                    name="P/L netto per chiusura",
                )).update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    title="Distribuzione P/L netto per chiusura",
                    xaxis_title="P/L netto USD",
                    yaxis_title="Numero chiusure",
                ),
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




st.title("AI Trading Bot")
st.caption(
"Monitora il conto, l'andamento del mercato e le attività recenti. "
"Demo locale, backtest e Alpaca Paper restano contesti separati."
)
st.session_state.setdefault("paper_automation_active", False)
simulation_notice = st.session_state.pop("simulation_notice", None)
if simulation_notice:
    st.success(simulation_notice)

with st.sidebar:
    with st.expander("Impostazioni avanzate", expanded=False):
        st.header("Strategia e rischio")
        short_window = st.number_input(
            "Media mobile breve", min_value=2, max_value=100,
            value=settings.short_window,
            help="Numero di barre usate per la media più reattiva; non è una previsione.",
        )
        long_window = st.number_input(
            "Media mobile lunga", min_value=3, max_value=300,
            value=settings.long_window,
            help="Numero di barre usate per la media lenta; deve superare quella breve.",
        )
        if short_window >= long_window:
            st.error("La media mobile breve deve essere minore di quella lunga.")
        max_trade_fraction = st.slider(
            "Importo massimo per trade (% capitale)", 1, 50,
            int(settings.risk_max_trade_fraction * 100),
            help="Tetto nominale per ogni nuovo acquisto; applicato anche prima di ordini Paper automatici.",
        ) / 100
        max_exposure_fraction = st.slider(
            "Esposizione massima (% capitale)", 1, 100,
            int(settings.risk_max_exposure_fraction * 100),
            help="Limite al valore aggregato delle posizioni; non garantisce un prezzo di esecuzione.",
        ) / 100
        daily_loss_fraction = st.slider(
            "Blocco perdita giornaliera (%)", 0, 20,
            int(settings.daily_loss_limit_pct * 100),
            help="Blocca nuovi acquisti quando la perdita giornaliera raggiunge il limite.",
        ) / 100
        commission_bps = st.number_input("Commissione stimata (bps)", min_value=0.0, max_value=1000.0, value=float(settings.commission_bps))
        slippage_bps = st.number_input("Slippage stimato (bps)", min_value=0.0, max_value=1000.0, value=float(settings.slippage_bps))
        spread_bps = st.number_input("Spread stimato (bps)", min_value=0.0, max_value=1000.0, value=float(settings.spread_bps))
        paper_max_daily_orders = st.number_input(
            "Massimo ordini automatici paper al giorno",
            min_value=1,
            max_value=100,
            value=int(settings.paper_max_daily_orders),
            step=1,
        )
        st.caption("I limiti rischio vengono applicati a ledger locale, backtest e automazione Paper. Demo non può inviare ordini.")
        st.info(
            "Automazione Paper: attiva in questa sessione"
            if st.session_state.paper_automation_active
            else "Automazione Paper: arrestata"
        )

tab_overview, tab_sim, tab_backtest, tab_alpaca = st.tabs([
    "Dashboard", "Simulazione", "Backtest", "Alpaca Paper",
])

with tab_overview:
    st.subheader("Stato del sistema")
    mode_status = st.columns(4)
    mode_status[0].metric(
        "Modalità",
        "Alpaca Paper" if settings.trading_mode == "paper" else "Demo locale",
        help="Paper mostra i dati del conto Alpaca Paper; Demo usa un ledger locale isolato.",
    )
    mode_status[1].metric(
        "Connessione account",
        (
            "Verificata"
            if st.session_state.get("paper_verified", False)
            else "Errore"
            if st.session_state.get("paper_snapshot_error")
            else "Non verificata"
            if settings.trading_mode == "paper"
            else "N/D (Demo locale)"
        ),
        help=(
            st.session_state.get("paper_snapshot_error")
            or (
                "Stato restituito dall'ultima verifica dell'account Alpaca Paper."
                if settings.trading_mode == "paper"
                else "La modalità Demo locale non apre un conto broker."
            )
        ),
    )
    mode_status[2].metric(
        "Automazione",
        "Attiva" if st.session_state.paper_automation_active else "Arrestata",
        help="L'automazione è attivabile solo manualmente in Alpaca Paper.",
    )
    last_market_update = st.session_state.get("market_quote_refreshed_at")
    if last_market_update is None and st.session_state.get("market_frame") is not None:
        last_market_update = st.session_state.market_frame.attrs.get("fetched_at")
    mode_status[3].metric(
        "Aggiornamento dati",
        str(last_market_update) if last_market_update is not None else "N/D",
        help="Ora dell'ultimo aggiornamento dei dati di mercato disponibili in questa sessione.",
    )
    st.caption(
        "Per cambiare modalità riavvia con avvia_demo.ps1 o avvia_paper.ps1; "
        "Demo locale, simulazione e Alpaca Paper non condividono il capitale."
    )
    if settings.trading_mode == "paper":
        st.caption("Le metriche del conto Paper sono mostrate solo quando fornite dall'ultimo snapshot verificato.")
        st.caption("Origine: snapshot Alpaca Paper verificato. Nessuna metrica del ledger o del backtest viene sommata al conto.")
    else:
        local_account = ledger.account()
        if local_account is None:
            closed_trades = []
            st.info("Ledger Demo non inizializzato. Apri Simulazione per creare il conto virtuale.")
            local_metrics = st.columns(4)
            local_metrics[0].metric("Equity", "N/D")
            local_metrics[1].metric("P/L netto (dall'inizio)", "N/D", "N/D")
            local_metrics[2].metric("Operazioni chiuse", "N/D")
            local_metrics[3].metric("Win rate", "N/D", help="Numero di operazioni chiuse: N/D")
        else:
            overview = ledger.summary(float(commission_bps), float(slippage_bps), float(spread_bps))
            closed_trades = [
                trade for trade in ledger.history()
                if trade.get("status") == "closed" and trade.get("net_pnl") is not None
            ]
            closed_count = len(closed_trades)
            winning_count = sum(float(trade["net_pnl"]) > 0 for trade in closed_trades)
            initial_capital = float(local_account["initial_eur"]) * float(local_account["eur_usd_rate"])
            pnl_percent = (
                float(overview["total_pnl"]) / initial_capital * 100
                if initial_capital > 0 else None
            )
            local_metrics = st.columns(4)
            local_metrics[0].metric("Equity Demo", f"${overview['current_capital']:,.2f}")
            local_metrics[1].metric(
                "P/L netto (dall'inizio)",
                f"${overview['total_pnl']:+,.2f}",
                "N/D" if pnl_percent is None else f"{pnl_percent:+.2f}%",
            )
            local_metrics[2].metric("Operazioni chiuse (totale)", closed_count)
            local_metrics[3].metric(
                "Win rate",
                "N/D" if not closed_count else f"{winning_count / closed_count * 100:.1f}%",
                help=f"Operazioni chiuse considerate: {closed_count}",
            )
            st.caption("Origine: ledger locale, capitale virtuale. Il P/L dall'inizio non è il P/L di oggi; i costi applicati sono stime.")
            if closed_count < 30:
                st.caption(f"Campione statistico piccolo: {closed_count} operazioni chiuse; il win rate non è una previsione.")
    st.divider()
    _paper_account_monitor()

with tab_overview:
    st.subheader("Mercato")
    categories = ["ETF e azioni", "Criptovalute"]
    market_controls = st.columns(4)
    with market_controls[0]:
        market_group = st.selectbox("Categoria", categories, key="dashboard_market_group")
    group_symbols = EQUITY_SYMBOLS if market_group == "ETF e azioni" else CRYPTO_SYMBOLS
    demo_mode = st.checkbox(
        "Usa serie sintetica demo", value=False,
        help="Scelta esplicita: prezzi generati per provare l'app, non dati di mercato.",
    )
    if settings.trading_mode == "demo":
        st.caption("Per iniziare senza broker: attiva la serie sintetica, seleziona 1Day e premi Aggiorna dati. Il conto virtuale si crea nella scheda Simulazione.")
    with st.expander("Impostazioni avanzate"):
        query = st.text_input("Cerca per ticker o nome")
        show_rsi = st.checkbox("Mostra RSI (14)", value=False)
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
        with market_controls[1]:
            selected_symbol = st.selectbox("Strumento", filtered_symbols)
        descriptor = INSTRUMENTS[selected_symbol]
        st.caption(f"**{descriptor['name']}** — {descriptor['description']}")
    if not st.session_state.get("paper_verified", False):
        st.caption("Catalogo consultabile: disponibilità dei dati e negoziabilità Paper restano non verificate finché il broker non le conferma.")
    with market_controls[2]:
        interval = st.selectbox("Intervallo", ["1Min", "5Min", "15Min", "1Hour", "1Day", "1Week"], index=4)
    with market_controls[3]:
        period = st.selectbox("Periodo", ["1M", "3M", "6M", "1Y", "5Y"], index=1)
    current_market_request = (selected_symbol, interval, period, demo_mode)

    if selected_symbol:
        availability = _cached_asset_availability(
            selected_symbol,
            st.session_state["_runtime_session_id"],
        )
        if (
            st.session_state.get("market_symbol") == selected_symbol
            and st.session_state.get("data_availability")
        ):
            availability = st.session_state.data_availability
        if (
            st.session_state.get("market_symbol") == selected_symbol
            and st.session_state.get("market_quality") == "synthetic"
        ):
            market_availability_label = "Dati di mercato reali: non verificati (serie demo sintetica)"
            market_availability_message = "La serie sintetica non attesta la disponibilità di dati Alpaca."
        else:
            data_available = availability.get("data_available", "non verificato")
            market_availability_label = (
                "dati storici Alpaca ricevuti"
                if data_available is True
                else f"disponibilità dati: {data_available}"
            )
            market_availability_message = availability["message"]
        paper_tradability = availability.get("paper_tradable", "non verificato")
        tradability_label = (
            "negoziabile paper" if paper_tradability is True
            else "non negoziabile paper" if paper_tradability is False
            else f"negoziabilità paper: {paper_tradability}"
        )
        fractionable = availability.get("fractionable")
        fraction_label = (
            "sì" if fractionable is True else "no" if fractionable is False else "non verificato"
        )
        minimum_quantity = availability.get("min_order_size")
        quantity_increment = availability.get("min_trade_increment")
        with st.expander("Dettagli strumento e confronto"):
            st.caption(
                f"Visibile nel catalogo locale: sì · {market_availability_label} "
                f"· {tradability_label} · {market_availability_message}"
            )
            st.caption(
                f"Frazioni consentite: {fraction_label} · Quantità minima: "
                f"{minimum_quantity if minimum_quantity is not None else 'N/D'} · "
                f"Incremento: {quantity_increment if quantity_increment is not None else 'N/D'}. "
                "Una quotazione disponibile non garantisce che un ordine sia accettato."
            )
            compare_symbols = st.multiselect(
                "Confronta strumenti (performance normalizzata)",
                list(group_symbols),
                default=[selected_symbol],
                max_selections=4,
            )
            compare_clicked = st.button("Carica confronto", disabled=not compare_symbols)
        load_clicked = st.button("Aggiorna dati", type="primary")

        if load_clicked:
            for key in (
                "market_frame", "market_symbol", "market_interval", "market_period",
                "market_source", "market_quality", "market_quote", "market_quote_error",
                "market_quote_refreshed_at", "market_request", "backtest_result", "backtest_key",
            ):
                st.session_state.pop(key, None)
            try:
                data, source = _load_data(selected_symbol, interval, period, demo_mode)
                if data.empty:
                    st.session_state.market_load_error = "La fonte non ha restituito dati per la selezione."
                    st.session_state.market_error_request = current_market_request
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
                    st.session_state.market_quality = data.attrs.get("quality", "unavailable")
                    st.session_state.market_request = current_market_request
                    st.session_state.market_load_error = None
                    st.session_state.market_error_request = None
                    st.session_state.market_quote = latest_quote
                    st.session_state.market_quote_error = quote_error
                    st.session_state.market_quote_refreshed_at = (
                        datetime.now(timezone.utc) if latest_quote else None
                    )
                    st.session_state.availability_checked = availability
                    st.session_state.data_availability = {
                        **availability,
                        "data_available": availability["data_available"] if demo_mode else True,
                        "message": (
                            "Synthetic demo series selected; real market-data availability is not verified."
                            if demo_mode
                            else "Historical bars successfully returned; latest quote is checked separately."
                        ),
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
                st.session_state.market_load_error = str(exc)
                st.session_state.market_error_request = current_market_request
            st.rerun()

        if compare_clicked:
            comparison_rows = []
            comparison_sources = []
            try:
                for compare_symbol in compare_symbols:
                    compare_data, compare_source = _load_data(compare_symbol, interval, period, demo_mode)
                    if compare_data.empty:
                        st.warning(f"Nessun dato disponibile per {compare_symbol}; escluso dal confronto.")
                        continue
                    start_price = float(compare_data["close"].iloc[0])
                    if start_price <= 0:
                        continue
                    comparison_sources.append(
                        f"{compare_symbol}: {compare_source} "
                        f"({compare_data['timestamp'].iloc[0]} — {compare_data['timestamp'].iloc[-1]})"
                    )
                    comparison_rows.append(pd.DataFrame({
                        "timestamp": compare_data["timestamp"],
                        compare_symbol: (compare_data["close"] / start_price - 1) * 100,
                    }))
                if comparison_rows:
                    combined = comparison_rows[0]
                    for frame in comparison_rows[1:]:
                        combined = combined.merge(frame, on="timestamp", how="outer")
                    st.line_chart(combined.set_index("timestamp"))
                    st.caption(
                        "Confronto normalizzato (% dal primo prezzo del periodo). "
                        f"Fonti e copertura: {'; '.join(comparison_sources)}."
                    )
            except (BrokerConnectionError, ValueError) as exc:
                st.error(f"Confronto non disponibile: {exc}")

    market_data_current = (
        "market_frame" in st.session_state
        and st.session_state.get("market_request") == current_market_request
    )
    latest_signal_summary = None
    if not market_data_current:
        if st.session_state.get("market_error_request") == current_market_request:
            st.warning(f"Dati non disponibili per la selezione corrente: {st.session_state.market_load_error}")
        elif st.session_state.get("backtest_result"):
            st.info("La selezione dei dati è cambiata: il backtest precedente è nascosto. Carica la selezione corrente e riesegui il backtest.")
        elif "market_frame" in st.session_state:
            st.info("Strumento, intervallo, periodo o modalità cambiati: carica i dati aggiornati prima di analizzare o simulare.")
        else:
            st.info("Seleziona uno strumento e carica i dati. La mancanza di dati reali non attiva automaticamente prezzi sintetici.")
    else:
        data = st.session_state.market_frame.copy()
        source = st.session_state.market_source
        quality = st.session_state.market_quality
        label = (
            "SINTETICI - SOLO DEMO" if quality == "synthetic"
            else "DATI ALPACA - FEED IEX" if quality == "real" and "IEX" in source
            else "DATI REALI ALPACA" if quality == "real"
            else "FONTE DATI NON DISPONIBILE"
        )
        bar_timestamp_label = "Timestamp barra sintetica" if quality == "synthetic" else "Timestamp ultima barra"
        st.info(f"{label} · Fonte: {source} · {bar_timestamp_label}: {_latest_timestamp(data)}")
        quality_status = data_status(_latest_timestamp(data), interval, quality)
        st.caption(f"Qualità/freschezza: {quality_status['label']} · intervallo {interval}. Acquisizione e timestamp della barra sono informazioni diverse.")
        if quality == "real":
            try:
                completed = select_completed_bars(data, st.session_state.market_symbol,
                    datetime.now(timezone.utc), require_market_open=False)
                if completed.empty:
                    st.warning("Nessuna barra con chiusura temporale verificabile disponibile.")
                else:
                    st.caption(f"Ultima barra temporalmente conclusa: {completed['timestamp'].iloc[-1]} · fine intervallo UTC: {completed.attrs['last_completed_at']}. Non equivale a un segnale autorizzato; il feed può rettificare i dati.")
            except BarTimingError as exc:
                st.warning(f"Idoneità temporale operativa non verificata: {exc}")
        if data.attrs.get("fetched_at"):
            fetch_label = "Generata localmente il" if quality == "synthetic" else "Dati acquisiti il"
            st.caption(f"{fetch_label} (UTC): {data.attrs['fetched_at']}")
        if quality == "real" and not data.empty and not _data_is_fresh(
            _latest_timestamp(data), interval
        ):
            st.warning(
                "Le barre OHLC mostrate sono scadute per l'intervallo selezionato. "
                "Aggiorna i dati prima di usarli per una valutazione o un ordine simulato."
            )
        last = data.iloc[-1]
        latest_quote = st.session_state.get("market_quote")
        if quality == "real":
            if st.session_state.get("market_quote_error"):
                st.caption(f"Quotazione aggiornata non disponibile: {st.session_state.market_quote_error}")
        else:
            quote_cols = st.columns(3)
            quote_cols[0].metric("Ultimo close della barra", f"${float(last['close']):,.4f}")
            quote_cols[1].metric(bar_timestamp_label, str(_latest_timestamp(data)))
            quote_cols[2].metric("Fonte barra", source)
        if len(data) > 0:
            st.caption(
                f"Periodo richiesto: {st.session_state.market_period} · Copertura restituita: "
                f"{data['timestamp'].iloc[0]} — {_latest_timestamp(data)}"
            )
        if quality == "synthetic":
            st.warning("Serie sintetica generata localmente: non è una quotazione o uno storico reale.")

        try:
            strategy = MovingAverageStrategy(int(short_window), int(long_window))
            signals = strategy.generate_signals(data)
        except ValueError as exc:
            st.error(f"Strategia non disponibile: {exc}")
        else:
            if quality == "real":
                _live_quote_monitor(
                    st.session_state.market_symbol,
                    quality,
                    data,
                    int(short_window),
                    int(long_window),
                    show_rsi,
                )
            if quality == "real":
                data = st.session_state.get("market_frame", data).copy()
                signals = strategy.generate_signals(data)
            latest_signal_summary = signal_view(
                signals, st.session_state.market_symbol, interval, quality,
                int(short_window), int(long_window),
            )
            if latest_signal_summary["state"] == "DATI INSUFFICIENTI":
                st.warning("Dati insufficienti per calcolare le due medie mobili.")
            if quality != "real":
                _plot_market_chart(
                    data, signals, st.session_state.market_symbol,
                    int(short_window), int(long_window), show_rsi,
                    local_history=ledger.history(),
                )
        tv_col1, tv_col2 = st.columns(2)
        with tv_col1:
            st.link_button("Apri grafico su TradingView", _tradingview_url(st.session_state.market_symbol))
        with tv_col2:
            st.caption("TradingView è solo un link di analisi esterno e non è collegato all'esecuzione o al registro locale.")

    st.divider()
    st.subheader("Segnale tecnico (SMA crossover)")
    if latest_signal_summary is None:
        st.info("Segnale non disponibile per i dati correnti. Seleziona la fonte e premi Aggiorna dati.")
    else:
        view = latest_signal_summary
        st.markdown(f"**{view['state']}** · {view['symbol']} · {view['interval']} · {view['parameters']}")
        st.caption(f"Motivazione: {view['reason']}")
        if view["quality"] == "synthetic":
            st.warning("SYNTHETIC / DEMO — segnale dimostrativo, escluso dall'automazione Paper.")
        signal_columns = st.columns(3)
        signal_columns[0].metric("Close barra di riferimento", _money_or_unavailable(view["price"]),
                                help="Close storico della barra usata per il segnale; non è un fill né una quotazione corrente.")
        signal_columns[1].metric("SMA breve", _money_or_unavailable(view["short_ma"]))
        signal_columns[2].metric("SMA lunga", _money_or_unavailable(view["long_ma"]))
        st.caption(f"Timestamp barra UTC: {view['timestamp']}. La barra mostrata può essere in formazione; i controlli dell'automazione sono separati.")
        st.info("Un segnale tecnico non autorizza un ordine. Per una decisione operativa servono account, barra completata, quotazione e rischio verificati.")
        with st.expander("Dettagli del segnale e proposta teorica"):
            st.json(view)
            st.write("Ingresso di riferimento: close della barra, non prezzo garantito. Stop-loss, take-profit, rischio monetario e rapporto rischio/rendimento: N/D; la strategia SMA non definisce questi livelli.")
            st.write("Quantità operativa: N/D finché non viene completata una valutazione del conto e del rischio. Un'eventuale anteprima DRY-RUN non invia ordini.")
            st.caption("Le stime non garantiscono esecuzione: spread, slippage, gap e liquidità possono cambiare il risultato.")

    if st.session_state.get("paper_snapshot_error"):
        st.error(f"Alpaca Paper: {st.session_state.paper_snapshot_error}")

    st.divider()
    st.subheader("Attività")
    positions_col, orders_col = st.columns(2)
    if settings.trading_mode == "paper":
        activity_snapshot = st.session_state.get("paper_snapshot") or {}
        open_positions = [
            _model_dict(item) for item in activity_snapshot.get("positions") or []
        ]
        recent_orders = [
            _model_dict(item) for item in activity_snapshot.get("orders") or []
        ]
    else:
        open_positions = ledger.positions() if ledger.account() is not None else []
        recent_orders = []

    with positions_col:
        st.markdown("**Posizioni aperte**")
        if open_positions:
            positions_frame = pd.DataFrame(open_positions)
            position_columns = [
                column for column in (
                    "symbol", "qty", "quantity", "avg_entry_price", "current_price",
                    "market_value", "unrealized_pl", "unrealized_pnl",
                )
                if column in positions_frame.columns
            ]
            st.dataframe(
                positions_frame[position_columns] if position_columns else positions_frame,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nessuna posizione aperta disponibile.")

    with orders_col:
        st.markdown("**Ordini recenti**")
        if recent_orders:
            orders_frame = pd.DataFrame(recent_orders)
            order_columns = [
                column for column in (
                    "symbol", "side", "qty", "quantity", "type", "status",
                    "submitted_at", "filled_at", "filled_qty", "filled_avg_price",
                )
                if column in orders_frame.columns
            ]
            st.dataframe(
                orders_frame[order_columns].head(5) if order_columns else orders_frame.head(5),
                use_container_width=True,
                hide_index=True,
            )
        elif settings.trading_mode == "paper":
            st.info("Nessun ordine recente disponibile nell'ultimo snapshot.")
        else:
            st.info("Gli ordini sono gestiti nella scheda Simulazione.")

    st.markdown("**Ultime operazioni chiuse**")
    if settings.trading_mode == "paper":
        st.info("Storico delle operazioni chiuse: N/D.")
    else:
        if closed_trades:
            closed_frame = pd.DataFrame(closed_trades)
            closed_columns = [
                column for column in (
                    "symbol", "closed_at", "net_pnl", "net_pnl_eur",
                    "exit_reason", "status",
                )
                if column in closed_frame.columns
            ]
            st.dataframe(
                closed_frame[closed_columns].head(5),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nessuna operazione chiusa registrata.")

with tab_sim:
    _show_simulation_account(float(spread_bps))
    account = ledger.account()
    data = st.session_state.get("market_frame") if market_data_current else None
    active_symbol = st.session_state.get("market_symbol") if market_data_current else None
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
            st.warning("Carica prima dati reali o attiva esplicitamente la modalità demo nella Dashboard.")
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
                        st.session_state.simulation_notice = (
                            "Acquisto registrato nella simulazione locale."
                            if not result["duplicate"]
                            else "Richiesta duplicata ignorata."
                        )
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
                            st.session_state.simulation_notice = (
                                f"Vendita registrata localmente. P/L netto realizzato: "
                                f"${result.get('net_pnl', 0):+.2f}"
                            )
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
            st.caption("P/L lordo prima di commissioni, spread e slippage; P/L netto dopo tali costi. Il P/L netto EUR usa il cambio salvato all'inizializzazione del conto, non un cambio corrente. Le posizioni aperte non sono profitti realizzati.")
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
    if not market_data_current:
        st.info("Carica o riapplica la selezione corrente nella Dashboard prima del backtest.")
    else:
        data = st.session_state.market_frame
        backtest_capital = st.number_input("Capitale iniziale backtest (USD)", min_value=1.0, value=100.0, step=10.0)
        backtest_spread_bps = st.number_input(
            "Spread completo stimato per backtest (bps)",
            min_value=0.0,
            max_value=1000.0,
            value=max(10.0, float(settings.spread_bps)),
            help=(
                "Default conservativo di 10 bps (0,10%) di spread completo: circa "
                "5 bps all'ingresso e 5 bps all'uscita, circa 10 bps round trip sul "
                "controvalore. Adeguarlo allo spread tipico dello strumento. "
                "Zero impone esplicitamente un'ipotesi senza spread."
            ),
        )
        if "timestamp" in data.columns and not data.empty:
            st.info(
                f"Dati per il backtest: {st.session_state.market_source} · "
                f"{st.session_state.market_symbol} · {st.session_state.market_interval} · "
                f"{st.session_state.market_period} · {len(data)} barre · "
                f"{data['timestamp'].iloc[0]} — {data['timestamp'].iloc[-1]}."
            )
        backtest_parameters = {
            "short_window": int(short_window),
            "long_window": int(long_window),
            "initial_capital": float(backtest_capital),
            "max_trade_fraction": float(max_trade_fraction),
            "daily_loss_limit_fraction": float(daily_loss_fraction),
            "commission_bps": float(commission_bps),
            "spread_bps": float(backtest_spread_bps),
            "slippage_bps": float(slippage_bps),
            "market_request": current_market_request,
        }
        periods_per_year = BacktestEngine.periods_per_year_for_interval(
            str(st.session_state.market_interval),
            crypto=st.session_state.market_symbol in CRYPTO_SYMBOLS,
        )
        current_backtest_key = backtest_input_key(
            data,
            source=str(st.session_state.market_source),
            parameters=backtest_parameters,
        )
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
                    spread_bps=float(backtest_spread_bps),
                    slippage_bps=float(slippage_bps),
                    periods_per_year=periods_per_year,
                    risk_free_rate_annual=0.0,
                )
                st.session_state.backtest_result = result.to_dict()
                st.session_state.backtest_source = st.session_state.market_source
                st.session_state.backtest_key = current_backtest_key
            except ValueError as exc:
                st.error(f"Backtest non eseguito: {exc}")
        result = (
            st.session_state.get("backtest_result")
            if st.session_state.get("backtest_key") == current_backtest_key else None
        )
        if st.session_state.get("backtest_result") and result is None:
            st.info("Parametri o dati cambiati: riesegui il backtest per aggiornare i risultati.")
        if result:
            st.info(f"Backtest su {st.session_state.get('backtest_source', 'fonte non registrata')}. Non è una previsione.")
            metrics = st.columns(4)
            metrics[0].metric("Capitale iniziale", f"${result['initial_capital']:.2f}")
            metrics[1].metric(
                "Capitale finale (liquidazione netta stimata)",
                f"${result['final_capital']:.2f}",
            )
            metrics[2].metric(
                "Rendimento sul capitale",
                f"{result['return_pct']:+.2f}%",
                help="Variazione percentuale del capitale finale rispetto al capitale iniziale.",
            )
            metrics[3].metric(
                "Drawdown massimo",
                f"{result['max_drawdown_pct']:.2f}%",
                help="Massima discesa percentuale dal precedente picco della curva equity simulata.",
            )
            st.metric(
                "Profitto netto finale (include posizione aperta valutata)",
                f"${result['final_capital'] - result['initial_capital']:+.2f}",
                help=(
                    "Capitale finale meno capitale iniziale. Le posizioni ancora aperte "
                    "sono valutate al netto dei costi stimati di liquidazione."
                ),
            )
            benchmark_metrics = st.columns(5)
            benchmark_metrics[0].metric(
                "Buy & hold finale", f"${result['benchmark_final_capital']:.2f}"
            )
            benchmark_metrics[1].metric(
                "Buy & hold rendimento", f"{result['benchmark_return_pct']:+.2f}%"
            )
            benchmark_metrics[2].metric(
                "Drawdown buy & hold", f"{result['benchmark_max_drawdown_pct']:.2f}%"
            )
            benchmark_metrics[3].metric(
                "Volatilità annualizzata",
                "n/d" if result["annualized_volatility_pct"] is None
                else f"{result['annualized_volatility_pct']:.2f}%",
            )
            benchmark_metrics[4].metric(
                "Sharpe (rf 0%)",
                "n/d" if result["sharpe_ratio"] is None
                else f"{result['sharpe_ratio']:.2f}",
            )
            stats = st.columns(4)
            stats[0].metric("Operazioni chiuse", result["total_trades"])
            stats[1].metric("Vincenti / perdenti", f"{result['winning_trades']} / {result['losing_trades']}")
            stats[2].metric(
                "Win rate delle operazioni chiuse",
                "N/D" if result["win_rate"] is None
                else f"{result['win_rate']:.1f}%",
                help=f"Quota positiva su {result['total_trades']} trade chiusi; non è il rendimento del capitale.",
            )
            stats[3].metric("P/L lordo realizzato", f"${result['gross_pnl']:+.2f}")
            trade_metrics = st.columns(4)
            trade_metrics[0].metric(
                "Profitto medio netto per operazione",
                "N/D" if result["average_profit_per_trade"] is None
                else f"${result['average_profit_per_trade']:+.2f}",
            )
            trade_metrics[1].metric(
                "Perdita media netta per operazione",
                "N/D" if result["average_loss_per_trade"] is None
                else f"${result['average_loss_per_trade']:+.2f}",
            )
            trade_metrics[2].metric(
                "Profit factor netto",
                "N/D" if result["profit_factor"] is None
                else f"{result['profit_factor']:.2f}",
                help="Profitti netti dei trade vincenti divisi per il valore assoluto delle perdite nette.",
            )
            trade_metrics[3].metric("Operazioni chiuse", result["total_trades"])
            costs = st.columns(4)
            costs[0].metric("P/L netto realizzato", f"${result['net_pnl']:+.2f}")
            costs[1].metric("Commissioni", f"${result['fees_paid']:.2f}")
            costs[2].metric("Spread stimato", f"${result['spread_paid']:.2f}")
            costs[3].metric("Slippage stimato", f"${result['slippage_paid']:.2f}")
            comparison = st.columns(3)
            comparison[0].metric(
                "Volatilità buy & hold",
                "n/d" if result["benchmark_annualized_volatility_pct"] is None
                else f"{result['benchmark_annualized_volatility_pct']:.2f}%",
            )
            comparison[1].metric(
                "Sharpe buy & hold",
                "n/d" if result["benchmark_sharpe_ratio"] is None
                else f"{result['benchmark_sharpe_ratio']:.2f}",
            )
            comparison[2].metric(
                "Delta rendimento vs buy & hold",
                f"{result['return_pct'] - result['benchmark_return_pct']:+.2f}%",
            )
            total_costs = st.columns(2)
            total_costs[0].metric(
                "Costi totali strategia (incl. liquidazione stimata)",
                f"${result['total_transaction_costs']:.2f}",
            )
            total_costs[1].metric(
                "Costi totali buy & hold (incl. liquidazione stimata)",
                f"${result['benchmark_total_transaction_costs']:.2f}",
            )
            st.plotly_chart(
                go.Figure(go.Scatter(y=result["equity_curve"], mode="lines", name="Equity backtest"))
                .update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    title="Curva capitale backtest (barre in ordine)",
                    xaxis_title="Barra",
                    yaxis_title="USD",
                ),
                use_container_width=True,
            )
            if result.get("trade_history"):
                st.dataframe(pd.DataFrame(result["trade_history"]), use_container_width=True, hide_index=True)
            if result.get("open_position_quantity"):
                st.caption(
                    f"Posizione finale ancora aperta: {result['open_position_quantity']:.6f}; "
                    f"P/L non realizzato lordo ${result['unrealized_gross_pnl']:+.2f}, "
                    f"netto stimato ${result['unrealized_net_pnl']:+.2f}. "
                    f"Costi stimati per liquidarla: ${result['estimated_liquidation_costs']:.2f}."
                )
            st.caption(
                f"Sharpe/volatilità annualizzati assumendo {result['periods_per_year']} barre/anno "
                f"({ 'mercato crypto 365 giorni' if st.session_state.market_symbol in CRYPTO_SYMBOLS else '252 sessioni azionarie' }) "
                "per l'intervallo selezionato e tasso privo di rischio annuo 0%; sono stime su "
                "rendimenti barra-su-barra e non sono mostrate come significative se il campione "
                "è insufficiente. Benchmark e strategia entrano al primo open disponibile e sono "
                "valutati all'ultimo close al netto dei costi di liquidazione stimati. "
                "P/L realizzato esclude posizioni aperte. Il backtest è storico/simulato e non "
                "garantisce rendimenti futuri."
            )

    st.divider()
    st.subheader("Valutazione walk-forward — risultati fuori campione")
    st.warning(
        "Backtest in-sample ≠ performance fuori campione ≠ risultati futuri. "
        "Questa valutazione è separata dal backtest tradizionale e dal conto simulato."
    )
    st.caption(
        "La selezione sceglie il rendimento netto più alto tra tre coppie fisse "
        "(2/4, 3/6, 5/10), esclusivamente sul training di ciascun fold. "
        "Le finestre test sono cronologiche e non sovrapposte; parametri e capitale "
        "ripartono a ogni fold. Nessun ordine o scrittura al ledger."
    )
    if not market_data_current:
        st.info(
            "Walk-forward non disponibile: carica prima la selezione corrente. "
            "I risultati precedenti restano nascosti finché dati, simbolo e timeframe "
            "non corrispondono."
        )
    elif st.session_state.market_quality not in {"real", "synthetic"}:
        st.error("Walk-forward non eseguito: la fonte dei dati è indisponibile o non verificata.")
    else:
        wf_data = st.session_state.market_frame
        candidate_minimum = max(
            candidate["long_window"] for candidate in WALK_FORWARD_CANDIDATES
        ) + 2
        row_count = len(wf_data)
        if row_count < candidate_minimum * 2:
            st.warning(
                f"Campione insufficiente: servono almeno {candidate_minimum * 2} barre "
                f"(almeno {candidate_minimum} per training e test); disponibili {row_count}."
            )
        else:
            max_training_bars = row_count - candidate_minimum
            default_training_bars = min(
                max(row_count // 3, candidate_minimum), max_training_bars
            )
            stored_training_bars = st.session_state.get("walk_forward_training_bars")
            if stored_training_bars is not None and not (
                candidate_minimum <= stored_training_bars <= max_training_bars
            ):
                st.session_state.walk_forward_training_bars = default_training_bars
            training_bars = st.number_input(
                "Barre per training", min_value=candidate_minimum,
                max_value=max_training_bars, value=default_training_bars, step=1,
                key="walk_forward_training_bars",
            )
            max_test_bars = row_count - int(training_bars)
            default_test_bars = min(
                max(row_count // 6, candidate_minimum), max_test_bars
            )
            stored_test_bars = st.session_state.get("walk_forward_test_bars")
            if stored_test_bars is not None and not (
                candidate_minimum <= stored_test_bars <= max_test_bars
            ):
                st.session_state.walk_forward_test_bars = default_test_bars
            test_bars = st.number_input(
                "Barre per ciascun test fuori campione",
                min_value=candidate_minimum, max_value=max_test_bars,
                value=default_test_bars, step=1, key="walk_forward_test_bars",
            )
            step_bars = int(test_bars)
            walk_forward_options = {
                "initial_capital": float(backtest_capital),
                "max_trade_fraction": float(max_trade_fraction),
                "daily_loss_limit_fraction": float(daily_loss_fraction),
                "commission_bps": float(commission_bps),
                "spread_bps": float(backtest_spread_bps),
                "slippage_bps": float(slippage_bps),
                "periods_per_year": periods_per_year,
                "risk_free_rate_annual": 0.0,
            }
            walk_forward_parameters = {
                "symbol": st.session_state.market_symbol,
                "interval": st.session_state.market_interval,
                "period": st.session_state.market_period,
                "market_request": current_market_request,
                "quality": st.session_state.market_quality,
                "training_bars": int(training_bars),
                "test_bars": int(test_bars),
                "step_bars": step_bars,
                "candidates": WALK_FORWARD_CANDIDATES,
                **walk_forward_options,
            }
            current_walk_forward_key = backtest_input_key(
                wf_data,
                source=str(st.session_state.market_source),
                parameters=walk_forward_parameters,
            )
            if st.button("Esegui valutazione walk-forward", type="primary"):
                try:
                    walk_forward_result = walk_forward_evaluate(
                        wf_data,
                        engine=BacktestEngine(settings),
                        parameter_candidates=WALK_FORWARD_CANDIDATES,
                        training_bars=int(training_bars),
                        test_bars=int(test_bars),
                        step_bars=step_bars,
                        data_source=(
                            f"{st.session_state.market_quality}: "
                            f"{st.session_state.market_source}"
                        ),
                        backtest_options=walk_forward_options,
                    )
                    st.session_state.walk_forward_result = walk_forward_result
                    st.session_state.walk_forward_key = current_walk_forward_key
                except ValueError as exc:
                    st.error(f"Walk-forward non eseguito: {exc}")
            walk_forward_result = (
                st.session_state.get("walk_forward_result")
                if st.session_state.get("walk_forward_key") == current_walk_forward_key
                else None
            )
            if st.session_state.get("walk_forward_result") and walk_forward_result is None:
                st.info(
                    "Dati, parametri o costi cambiati: risultati walk-forward precedenti "
                    "nascosti. Esegui di nuovo la valutazione."
                )
            if walk_forward_result is not None:
                st.info(
                    f"Dati OOS: {st.session_state.market_quality} · "
                    f"{st.session_state.market_symbol} · {st.session_state.market_interval} · "
                    f"{st.session_state.market_period} · fonte: "
                    f"{st.session_state.market_source} · {len(wf_data)} barre · copertura "
                    f"{wf_data['timestamp'].iloc[0]} — {_latest_timestamp(wf_data)}. "
                    f"Selezione training: {walk_forward_result.selection_metric}."
                )
                counts = st.columns(2)
                counts[0].metric("Fold OOS validi", len(walk_forward_result.folds))
                counts[1].metric(
                    "Fold esclusi", len(walk_forward_result.excluded_folds)
                )
                st.caption(
                    f"Fold: training {walk_forward_result.training_bars} barre; test "
                    f"{walk_forward_result.test_bars} barre; passo {walk_forward_result.step_bars}. "
                    "Le barre test non si sovrappongono. Ogni fold riparte dal capitale iniziale "
                    "e non trasferisce posizioni o cash al fold seguente."
                )
                if walk_forward_result.folds:
                    def display_optional_metric(value: float | None, suffix: str = "") -> str:
                        if value is None:
                            return "n/d"
                        return f"{value:.2f}{suffix}"

                    for fold_number, fold in enumerate(walk_forward_result.folds, start=1):
                        train_start_date = pd.Timestamp(
                            wf_data.iloc[fold.train_start]["timestamp"]
                        ).strftime("%Y-%m-%d")
                        train_end_date = pd.Timestamp(
                            wf_data.iloc[fold.train_end - 1]["timestamp"]
                        ).strftime("%Y-%m-%d")
                        test_start_date = pd.Timestamp(
                            wf_data.iloc[fold.test_start]["timestamp"]
                        ).strftime("%Y-%m-%d")
                        test_end_date = pd.Timestamp(
                            wf_data.iloc[fold.test_end - 1]["timestamp"]
                        ).strftime("%Y-%m-%d")
                        oos = fold.out_of_sample
                        parameters = (
                            f"{fold.selected_parameters['short_window']}/"
                            f"{fold.selected_parameters['long_window']}"
                        )
                        st.markdown(
                            f"**Fold {fold_number}** · Training: {train_start_date} – "
                            f"{train_end_date} · Test OOS: {test_start_date} – {test_end_date}"
                        )
                        summary_columns = st.columns(4)
                        summary_columns[0].metric(
                            "MA scelte (training)",
                            parameters,
                        )
                        summary_columns[1].metric(
                            "Rendimento strategia OOS",
                            f"{oos.return_pct:+.2f}%",
                        )
                        summary_columns[2].metric(
                            "Rendimento buy & hold OOS",
                            f"{oos.benchmark_return_pct:+.2f}%",
                        )
                        summary_columns[3].metric(
                            "Delta vs benchmark",
                            f"{oos.return_pct - oos.benchmark_return_pct:+.2f} p.p.",
                        )
                        train = fold.in_sample_result
                        with st.expander(f"Metriche training e OOS — fold {fold_number}"):
                            st.markdown("**Training in-sample (usato solo per selezionare i parametri)**")
                            train_metrics = st.columns(4)
                            train_metrics[0].metric("Rendimento netto training", f"{train.return_pct:+.2f}%")
                            train_metrics[1].metric("Buy & hold training", f"{train.benchmark_return_pct:+.2f}%")
                            train_metrics[2].metric("Operazioni training", train.total_trades)
                            train_metrics[3].metric(
                                "Win rate training",
                                display_optional_metric(train.win_rate, "%"),
                            )
                            train_trade_metrics = st.columns(4)
                            train_trade_metrics[0].metric(
                                "Profitto medio training",
                                display_optional_metric(train.average_profit_per_trade, " USD"),
                            )
                            train_trade_metrics[1].metric(
                                "Perdita media training",
                                display_optional_metric(train.average_loss_per_trade, " USD"),
                            )
                            train_trade_metrics[2].metric(
                                "Profit factor training",
                                display_optional_metric(train.profit_factor),
                            )
                            train_trade_metrics[3].metric(
                                "Drawdown massimo training",
                                f"{train.max_drawdown_pct:.2f}%",
                            )
                            train_risk = st.columns(4)
                            train_risk[0].metric(
                                "Sharpe training (rf 0%)",
                                display_optional_metric(train.sharpe_ratio),
                            )
                            train_risk[1].metric(
                                "Volatilità annualizzata training",
                                display_optional_metric(
                                    train.annualized_volatility_pct, "%"
                                ),
                            )
                            train_risk[2].metric(
                                "Costi totali training",
                                f"${train.total_transaction_costs:.4f}",
                            )
                            train_risk[3].metric(
                                "Costi totali buy & hold training",
                                f"${train.benchmark_total_transaction_costs:.4f}",
                            )
                            st.markdown("**Test fuori campione (OOS)**")
                            oos_metrics = st.columns(4)
                            oos_metrics[0].metric("Rendimento netto OOS", f"{oos.return_pct:+.2f}%")
                            oos_metrics[1].metric("Buy & hold OOS", f"{oos.benchmark_return_pct:+.2f}%")
                            oos_metrics[2].metric("Operazioni OOS", oos.total_trades)
                            oos_metrics[3].metric(
                                "Win rate OOS",
                                display_optional_metric(oos.win_rate, "%"),
                            )
                            oos_trade_metrics = st.columns(4)
                            oos_trade_metrics[0].metric(
                                "Profitto medio OOS",
                                display_optional_metric(oos.average_profit_per_trade, " USD"),
                            )
                            oos_trade_metrics[1].metric(
                                "Perdita media OOS",
                                display_optional_metric(oos.average_loss_per_trade, " USD"),
                            )
                            oos_trade_metrics[2].metric(
                                "Profit factor OOS",
                                display_optional_metric(oos.profit_factor),
                            )
                            oos_trade_metrics[3].metric(
                                "Drawdown massimo OOS",
                                f"{oos.max_drawdown_pct:.2f}%",
                            )
                        with st.expander(f"Rischio e costi — fold {fold_number}"):
                            risk_columns = st.columns(4)
                            risk_columns[0].metric(
                                "Drawdown strategia OOS",
                                f"{oos.max_drawdown_pct:.2f}%",
                            )
                            risk_columns[1].metric(
                                "Drawdown buy & hold OOS",
                                f"{oos.benchmark_max_drawdown_pct:.2f}%",
                            )
                            risk_columns[2].metric(
                                "Costi strategia OOS",
                                f"${oos.total_transaction_costs:.4f}",
                            )
                            risk_columns[3].metric(
                                "Costi buy & hold OOS",
                                f"${oos.benchmark_total_transaction_costs:.4f}",
                            )
                            st.caption(
                                "Costi USD (commissioni / spread / slippage) — strategia: "
                                f"{oos.fees_paid:.4f} / {oos.spread_paid:.4f} / "
                                f"{oos.slippage_paid:.4f}; buy & hold: "
                                f"{oos.benchmark_fees_paid:.4f} / "
                                f"{oos.benchmark_spread_paid:.4f} / "
                                f"{oos.benchmark_slippage_paid:.4f}."
                            )
                            metric_columns = st.columns(4)
                            metric_columns[0].metric(
                                "Volatilità strategia ann.",
                                display_optional_metric(
                                    oos.annualized_volatility_pct, "%"
                                ),
                            )
                            metric_columns[1].metric(
                                "Sharpe strategia (rf 0%)",
                                display_optional_metric(oos.sharpe_ratio),
                            )
                            metric_columns[2].metric(
                                "Volatilità benchmark ann.",
                                display_optional_metric(
                                    oos.benchmark_annualized_volatility_pct, "%"
                                ),
                            )
                            metric_columns[3].metric(
                                "Sharpe buy & hold (rf 0%)",
                                display_optional_metric(oos.benchmark_sharpe_ratio),
                            )
                    st.caption(
                        "I valori OOS di ogni fold sono valutati separatamente con lo stesso "
                        "capitale iniziale e costi configurati del backtest. Volatilità annualizzata "
                        "assumendo 252 barre/anno; Sharpe con tasso privo di rischio annuo 0%. "
                        "Sharpe/volatilità n/d quando il campione è insufficiente o la volatilità "
                        "è nulla; non vengono sostituiti con zero."
                    )
                    st.warning(
                        "Aggregato OOS non calcolato: i fold riavviano il capitale e azzerano "
                        "le posizioni, quindi concatenare i rendimenti implicherebbe una "
                        "continuità di portafoglio non modellata. Confronta i fold singolarmente."
                    )
                for exclusion in walk_forward_result.excluded_folds:
                    st.error(
                        f"Fold escluso (train [{exclusion.train_start}, {exclusion.train_end}), "
                        f"test [{exclusion.test_start}, {exclusion.test_end})): "
                        f"{exclusion.reason}"
                    )
                if not walk_forward_result.folds and walk_forward_result.excluded_folds:
                    st.warning("Nessun fold valido; controlla i motivi di esclusione sopra.")
                st.caption(
                    "Campione OOS derivato da barre storiche della fonte selezionata; i dati "
                    "sintetici restano marcati come synthetic e non rappresentano prezzi reali. "
                    "I risultati storici non garantiscono performance future."
                )

with tab_alpaca:
    st.header("Account e automazione Alpaca Paper")
    st.caption(
        "Il broker di trading viene costruito esclusivamente con paper=True. "
        "La demo sintetica e il backtest non possono attivare ordini."
    )
    if not broker.paper_client_configured or settings.trading_mode != "paper":
        st.error(
            "Invio paper indisponibile: configura credenziali paper valide in .env e "
            "avvia TRADING_MODE=paper. La modalità demo rimane solo locale."
        )
    elif not st.session_state.get("paper_verified", False):
        st.warning("Verifica prima il conto Paper nella scheda Panoramica.")
    else:
        st.success("Account paper verificato in questa sessione.")

    current_data = (
        st.session_state.get("market_frame")
        if market_data_current
        else None
    )
    current_quality = (
        st.session_state.get("market_quality")
        if market_data_current
        else None
    )
    current_symbol = st.session_state.get("market_symbol") if market_data_current else None
    current_interval = st.session_state.get("market_interval") if market_data_current else None
    automation_settings = replace(
        settings,
        risk_max_trade_fraction=float(max_trade_fraction),
        risk_max_exposure_fraction=float(max_exposure_fraction),
        daily_loss_limit_pct=float(daily_loss_fraction),
        paper_max_daily_orders=int(paper_max_daily_orders),
    )
    _paper_automation_panel(
        current_symbol,
        current_interval,
        current_quality,
        current_data,
        int(short_window),
        int(long_window),
        automation_settings,
        int(paper_max_daily_orders),
    )
