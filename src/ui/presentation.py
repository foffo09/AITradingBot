"""Pure presentation rules: provenance, unavailable values and technical states."""
import math
from datetime import timedelta

import pandas as pd


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def money(value):
    number = finite_number(value)
    return "N/D" if number is None else f"${number:,.2f}"


def paper_metrics(account, positions):
    result = {name: finite_number(account.get(name)) for name in ("cash", "equity", "buying_power", "last_equity")}
    equity, previous = result["equity"], result["last_equity"]
    change = finite_number(equity - previous) if equity is not None and previous is not None else None
    result["daily_change"] = change
    result["daily_percent"] = finite_number(change / previous * 100) if change is not None and previous > 0 else None
    for field, target, absolute in [("market_value", "market_value", True), ("unrealized_pl", "unrealized", False)]:
        values = [finite_number(p.get(field)) for p in positions] if positions is not None else [None]
        result[target] = (
            finite_number(sum(abs(v) if absolute else v for v in values))
            if all(v is not None for v in values) else None
        )
    return result


def freshness_limit(interval):
    return {
        "1Min": timedelta(minutes=10), "5Min": timedelta(minutes=20),
        "15Min": timedelta(minutes=45), "1Hour": timedelta(hours=3),
        "1Day": timedelta(days=4), "1Week": timedelta(days=10),
    }[interval]


def data_status(timestamp, interval, quality, now=None):
    if quality == "synthetic":
        return {"state": "synthetic", "label": "SYNTHETIC / DEMO", "age_seconds": None}
    if quality != "real":
        return {"state": "unavailable", "label": "DATI NON DISPONIBILI", "age_seconds": None}
    try:
        observed = pd.Timestamp(timestamp)
        if pd.isna(observed):
            raise ValueError("Missing timestamp")
        observed = observed.tz_localize("UTC") if observed.tzinfo is None else observed.tz_convert("UTC")
        current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        if pd.isna(current):
            raise ValueError("Missing reference time")
        current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
        age = (current - observed).total_seconds()
    except (ValueError, TypeError, OverflowError):
        return {"state": "invalid", "label": "TIMESTAMP NON VALIDO", "age_seconds": None}
    if age < 0:
        return {"state": "future", "label": "DATI FUTURI — NON UTILIZZABILI", "age_seconds": age}
    if age > freshness_limit(interval).total_seconds():
        return {"state": "stale", "label": "DATI OBSOLETI", "age_seconds": age}
    return {"state": "fresh", "label": "DATI AGGIORNATI", "age_seconds": age}


def signal_view(signals, symbol, interval, quality, short_window, long_window):
    view = {"symbol": symbol, "interval": interval, "quality": quality,
            "parameters": f"SMA {short_window}/{long_window}", "direction": "N/D",
            "timestamp": None, "price": None, "short_ma": None, "long_ma": None,
            "state": "DATI INSUFFICIENTI", "reason": "Carica abbastanza barre per entrambe le medie."}
    if signals.empty:
        return view
    row = signals.iloc[-1]
    view.update(timestamp=str(row.get("timestamp", "N/D")), price=finite_number(row.get("close")),
                short_ma=finite_number(row.get("short_ma")), long_ma=finite_number(row.get("long_ma")))
    if view["short_ma"] is not None and view["long_ma"] is not None:
        direction = {1: "ACQUISTO / BUY", -1: "USCITA / EXIT"}.get(row.get("signal"), "NESSUN SEGNALE")
        reasons = {1: "La SMA breve ha incrociato dal basso la SMA lunga.",
                   -1: "La SMA breve ha incrociato dall'alto la SMA lunga."}
        view.update(direction=direction, state=direction,
                    reason=reasons.get(row.get("signal"), "Nessun nuovo incrocio sull'ultima barra."))
    status = data_status(row.get("timestamp"), interval, quality)
    if status["state"] not in {"fresh", "synthetic"}:
        view.update(state=status["label"], reason="Il segnale storico non è utilizzabile con questi dati.")
    return view


def unique_orders(orders):
    result, seen = [], set()
    for order in orders:
        identity = order.get("id") or order.get("client_order_id")
        if identity is not None:
            identity = str(identity)
            if identity in seen:
                continue
            seen.add(identity)
        result.append(order)
    return result
