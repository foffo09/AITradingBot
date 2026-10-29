from __future__ import annotations

import hashlib
import math
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager
from src.data.bar_timing import BarTimingError, select_completed_bars, utc_timestamp
from src.strategy.moving_average import MovingAverageStrategy
from src.trading.paper_coordinator import PaperAccountCoordinator, PaperCoordinationError


class PaperAutomationError(RuntimeError):
    """Raised when paper automation cannot safely evaluate or route a signal."""


class PaperAutomationLog:
    """Persistent, credential-free decision log in the isolated Paper database."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=10) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS paper_automation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal_timestamp_utc TEXT,
                    signal TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    side TEXT,
                    quantity REAL,
                    order_status TEXT,
                    reason TEXT NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS paper_automation_events_time "
                "ON paper_automation_events(timestamp_utc, id)"
            )

    def record(self, event: dict[str, Any]) -> None:
        with sqlite3.connect(self.database_path, timeout=10) as db:
            db.execute(
                """INSERT INTO paper_automation_events
                   (timestamp_utc, symbol, signal_timestamp_utc, signal, decision,
                    side, quantity, order_status, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(event["timestamp_utc"]),
                    str(event["symbol"]),
                    event.get("signal_timestamp_utc"),
                    str(event.get("signal", "n/d")),
                    str(event.get("decision", "unknown")),
                    event.get("side"),
                    event.get("quantity"),
                    event.get("order_status"),
                    str(event.get("reason", "")),
                ),
            )

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("Paper automation log limit must be positive.")
        with sqlite3.connect(self.database_path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT timestamp_utc, symbol, signal_timestamp_utc, signal, decision,
                          side, quantity, order_status, reason
                   FROM paper_automation_events
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


_TERMINAL_ORDER_STATES = {
    "filled",
    "canceled",
    "cancelled",
    "rejected",
    "expired",
    "replaced",
}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PaperAutomationError(f"{label} is unavailable or invalid; automation is blocked.") from exc
    if not math.isfinite(result):
        raise PaperAutomationError(f"{label} is unavailable or invalid; automation is blocked.")
    return result


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _utc_datetime(value: Any, label: str) -> datetime:
    try:
        return utc_timestamp(value, label).to_pydatetime()
    except BarTimingError as exc:
        raise PaperAutomationError(str(exc)) from exc


def _order_id(symbol: str, timestamp: str, side: str) -> str:
    digest = hashlib.sha256(f"{symbol}|{timestamp}|{side}".encode("utf-8")).hexdigest()[:40]
    return f"ma-{digest}"


def _order_is_open(order: Any) -> bool:
    return _text(_field(order, "status")) not in _TERMINAL_ORDER_STATES


def _quantity_step(asset: dict[str, Any], symbol: str) -> Decimal:
    if "/" not in symbol and asset.get("fractionable") is False:
        return Decimal("1")
    raw_increment = asset.get("min_trade_increment")
    if raw_increment is not None:
        try:
            increment = Decimal(str(raw_increment))
        except InvalidOperation as exc:
            raise PaperAutomationError(
                "Broker quantity increment is invalid; automation is blocked."
            ) from exc
        if not increment.is_finite() or increment <= 0:
            raise PaperAutomationError(
                "Broker quantity increment is invalid; automation is blocked."
            )
        return increment
    if asset.get("fractionable") is True and "/" not in symbol:
        return Decimal("0.000001")
    return Decimal("1")


def _rounded_quantity(quantity: float, increment: Decimal) -> float:
    try:
        raw_quantity = Decimal(str(quantity))
        steps = (raw_quantity / increment).to_integral_value(rounding=ROUND_DOWN)
        return float(steps * increment)
    except (InvalidOperation, ZeroDivisionError, OverflowError) as exc:
        raise PaperAutomationError(
            "Order quantity cannot be represented at the broker's allowed increment."
        ) from exc


def execute_paper_signal(
    *,
    broker: Any,
    settings: AppSettings,
    symbol: str,
    market_data: pd.DataFrame,
    short_window: int,
    long_window: int,
    max_daily_orders: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Serialize operational evaluation; preview never obtains a submit permit."""
    arguments = dict(broker=broker, settings=settings, symbol=symbol, market_data=market_data,
                     short_window=short_window, long_window=long_window,
                     max_daily_orders=max_daily_orders, dry_run=dry_run)
    if dry_run:
        return _evaluate_paper_signal(**arguments)
    if settings.trading_mode != "paper" or not broker.is_connected():
        raise PaperAutomationError("Paper mode and a verified Alpaca Paper connection are required.")
    coordinator = getattr(broker, "paper_coordinator", None)
    if not isinstance(coordinator, PaperAccountCoordinator):
        raise PaperAutomationError("Paper account coordination is not configured; operational execution is disabled.")
    try:
        with coordinator.acquire() as lease:
            return _evaluate_paper_signal(**arguments, _lease=lease)
    except PaperCoordinationError as exc:
        return {"status": "blocked", "reason": str(exc), "requires_stop": True}


def _evaluate_paper_signal(*, broker, settings, symbol, market_data, short_window,
                           long_window, max_daily_orders, dry_run, _lease=None):
    if settings.trading_mode != "paper" or not settings.paper_trading_enabled:
        raise PaperAutomationError("Paper mode is not enabled; no order was sent.")
    if not broker.paper_client_configured or not broker.is_connected():
        raise PaperAutomationError("A verified Alpaca Paper connection is required; no order was sent.")
    if market_data.empty or market_data.attrs.get("quality") != "real":
        raise PaperAutomationError("Fresh real market data is required; synthetic data cannot trigger orders.")
    if not {"timestamp", "close"}.issubset(market_data.columns):
        raise PaperAutomationError("Market data is incomplete; no order was sent.")

    symbol = symbol.strip().upper()
    interval = str(market_data.attrs.get("interval", "1Day"))
    try:
        signal_data = select_completed_bars(market_data, symbol, datetime.now(timezone.utc))
    except BarTimingError as exc:
        raise PaperAutomationError(str(exc)) from exc
    if signal_data.empty:
        return {"status": "blocked", "reason": "No completed OHLC bar is available; automation is waiting."}
    forming_bar = signal_data.attrs["excluded_incomplete"] > 0
    bar_time = _utc_datetime(signal_data["timestamp"].iloc[-1], "Latest completed bar timestamp")

    verification = broker.verify_connection()
    if not verification.get("connected"):
        raise PaperAutomationError("Paper account verification failed; automation is stopped.")
    account = broker.get_account()
    if _lease is not None:
        _lease.assert_account(str(_field(account, "id") or ""))
    if _text(_field(account, "status")) != "active":
        raise PaperAutomationError("Paper account is not active; automation is stopped.")
    if _field(account, "trading_blocked", False) or _field(account, "account_blocked", False):
        raise PaperAutomationError("Paper account trading is blocked; automation is stopped.")
    positions = broker.get_positions()
    orders = broker.get_orders()

    strategy = MovingAverageStrategy(short_window, long_window)
    signal = strategy.current_signal(signal_data)
    if signal["signal"] not in {-1, 1}:
        return {
            "status": "no_signal",
            "signal": 0,
            "reason": (
                f"No crossover on the latest completed bar; the forming bar was ignored. "
                f"{signal['reason']}"
                if forming_bar
                else str(signal["reason"])
            ),
            "signal_timestamp": bar_time.isoformat(),
        }
    side = "buy" if signal["signal"] == 1 else "sell"

    asset = broker.get_instrument_availability(symbol)
    if asset.get("paper_tradable") is not True:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "Broker asset tradability is not verified; no paper order was sent.",
            "signal_timestamp": bar_time.isoformat(),
        }

    quote = broker.get_latest_quote(symbol)
    quote_time = _utc_datetime(quote.get("timestamp"), "Latest quote timestamp")
    quote_age = (datetime.now(timezone.utc) - quote_time).total_seconds()
    if quote_age < 0 or quote_age > 120:
        raise PaperAutomationError("Latest quote is stale; automation is blocked.")
    bid = _number(quote.get("bid"), "Latest quote bid")
    ask = _number(quote.get("ask"), "Latest quote ask")
    if bid <= 0 or ask <= 0 or bid > ask:
        raise PaperAutomationError("Latest quote bid/ask is invalid; no order was sent.")
    price = ask if side == "buy" else bid
    equity = _number(_field(account, "equity"), "Paper account equity")
    if side == "buy":
        buying_power = _number(_field(account, "buying_power"), "Paper account buying power")
        cash = _number(_field(account, "cash"), "Paper account cash")
    else:
        try:
            buying_power = max(0.0, float(_field(account, "buying_power", 0) or 0))
            cash = max(0.0, float(_field(account, "cash", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            buying_power = 0.0
            cash = 0.0
    previous_equity_value = _field(account, "last_equity")
    last_equity = (
        _number(previous_equity_value, "Previous close equity")
        if previous_equity_value is not None
        else None
    )
    if equity <= 0:
        raise PaperAutomationError("Paper account has no positive equity.")
    if side == "buy" and min(buying_power, cash) <= 0:
        raise PaperAutomationError("Paper account has no positive cash and buying power.")
    if side == "buy" and (last_equity is None or last_equity <= 0):
        raise PaperAutomationError("Previous close equity is invalid; daily loss cannot be checked.")

    now = datetime.now(timezone.utc)
    automated_today = 0
    for order in orders:
        order_timestamp = _field(order, "submitted_at") or _field(order, "created_at")
        client_id = str(_field(order, "client_order_id", ""))
        if order_timestamp:
            submitted = _utc_datetime(order_timestamp, "Order timestamp")
            if submitted.date() == now.date() and client_id.startswith("ma-"):
                automated_today += 1
        if _order_is_open(order):
            order_symbol = str(_field(order, "symbol", "")).upper()
            order_side = _text(_field(order, "side"))
            if order_symbol == symbol or (side == "buy" and order_side == "buy"):
                return {
                    "status": "blocked",
                    "signal": int(signal["signal"]),
                    "reason": (
                        "An open paper order already exists for this symbol."
                        if order_symbol == symbol
                        else "A pending paper buy order must be reconciled before another buy."
                    ),
                    "signal_timestamp": bar_time.isoformat(),
                }

    daily_limit = settings.paper_max_daily_orders if max_daily_orders is None else max_daily_orders
    if daily_limit <= 0:
        raise PaperAutomationError("Maximum daily paper orders must be positive.")
    if automated_today >= daily_limit:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "The configured daily paper-order limit has been reached.",
            "signal_timestamp": bar_time.isoformat(),
        }

    position = next(
        (item for item in positions if str(_field(item, "symbol", "")).upper() == symbol),
        None,
    )
    current_quantity = _number(_field(position, "qty", 0), "Current position quantity") if position else 0.0
    if side == "buy" and position is not None:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "A buy signal cannot add to an existing position.",
            "signal_timestamp": bar_time.isoformat(),
        }
    if side == "sell" and current_quantity <= 0:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "A sell signal has no open long position to close.",
            "signal_timestamp": bar_time.isoformat(),
        }
    if side == "buy" and len(positions) >= settings.max_positions:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "The configured maximum number of paper positions is reached.",
            "signal_timestamp": bar_time.isoformat(),
        }

    total_exposure = 0.0
    if side == "buy":
        position_values = []
        for item in positions:
            market_value = _field(item, "market_value")
            if market_value is None:
                position_price = price if str(_field(item, "symbol", "")).upper() == symbol else None
                if position_price is None:
                    raise PaperAutomationError(
                        "Portfolio exposure is incomplete; automation is blocked."
                    )
                market_value = _number(_field(item, "qty"), "Position quantity") * position_price
            position_values.append(_number(market_value, "Position market value"))
        total_exposure = sum(abs(value) for value in position_values)

    order_quantity = (
        RiskManager(replace(settings, initial_capital_eur=equity / settings.eur_usd_rate))
        .calculate_position_size(min(cash, buying_power), price)
        if side == "buy"
        else current_quantity
    )
    quantity_step = _quantity_step(asset, symbol)
    order_quantity = _rounded_quantity(order_quantity, quantity_step)
    if side == "sell" and position is not None:
        available_to_sell = _field(position, "qty_available")
        if available_to_sell is not None:
            order_quantity = min(
                order_quantity,
                _rounded_quantity(
                    _number(available_to_sell, "Available position quantity"),
                    quantity_step,
                ),
            )
    minimum_order_size_value = asset.get("min_order_size")
    minimum_order_size = (
        _number(minimum_order_size_value, "Broker minimum order size")
        if minimum_order_size_value is not None
        else 0.0
    )
    if order_quantity <= 0 or order_quantity < minimum_order_size:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": (
                "Calculated quantity is below the broker's minimum order size or "
                "allowed increment; no paper order was sent."
            ),
            "signal_timestamp": bar_time.isoformat(),
        }
    risk_settings = replace(settings, initial_capital_eur=equity / settings.eur_usd_rate)
    risk = RiskManager(risk_settings)
    result = risk.validate_order(
        side=side,
        quantity=order_quantity,
        price=price,
        available_cash=max(0.0, min(cash, buying_power)),
        current_position=current_quantity,
        symbol=symbol,
        pnl_today=equity - last_equity if last_equity is not None else 0.0,
    )
    if not result.ok:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": result.reason,
            "signal_timestamp": bar_time.isoformat(),
        }
    if side == "buy" and total_exposure + result.notional > equity * settings.risk_max_exposure_fraction:
        return {
            "status": "blocked",
            "signal": int(signal["signal"]),
            "reason": "The order would exceed the portfolio exposure limit.",
            "signal_timestamp": bar_time.isoformat(),
        }

    client_order_id = _order_id(symbol, bar_time.isoformat(), side)
    existing = next(
        (item for item in orders if _field(item, "client_order_id") == client_order_id),
        None,
    )
    if existing is not None:
        return {
            "status": "duplicate",
            "signal": int(signal["signal"]),
            "reason": "This signal already has a broker order record.",
            "order": existing,
            "signal_timestamp": bar_time.isoformat(),
        }

    def validate_submission_time():
        current = datetime.now(timezone.utc)
        try:
            latest = select_completed_bars(market_data, symbol, current)
        except BarTimingError as exc:
            raise PaperAutomationError(str(exc)) from exc
        if latest.empty or _utc_datetime(latest["timestamp"].iloc[-1], "Latest bar") != bar_time:
            raise PaperAutomationError("Completed bar changed during evaluation; reevaluate before submitting.")
        if not 0 <= (current - quote_time).total_seconds() <= 120:
            raise PaperAutomationError("Latest quote expired during evaluation; no order was sent.")

    validate_submission_time()
    if dry_run:
        return {
            "status": "dry_run", "signal": int(signal["signal"]), "side": side,
            "quantity": order_quantity, "symbol": symbol, "interval": interval,
            "reference_price": price, "reference_timestamp": quote_time.isoformat(),
            "client_order_id": client_order_id, "signal_timestamp": bar_time.isoformat(),
            "reason": "Controlli completati; anteprima senza invio. Prezzo e quantità non sono un fill.",
        }

    if _lease is None:
        raise PaperAutomationError("Paper execution requires an exclusive account owner.")
    _lease.submission_check = validate_submission_time
    _lease.reconcile_unfilled(orders)
    _lease.reserve(client_order_id)
    submitted = broker.submit_order(
        symbol=symbol,
        side=side,
        quantity=order_quantity,
        client_order_id=client_order_id,
        _execution_lease=_lease,
    )
    return {
        "status": "submitted",
        "signal": int(signal["signal"]),
        "reason": str(signal["reason"]),
        "signal_timestamp": bar_time.isoformat(),
        "side": side,
        "quantity": order_quantity,
        "order": submitted,
    }
