from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
import weakref
from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import AppSettings
from src.data.bar_timing import bar_timing
from src.data.instruments import INSTRUMENTS
from src.risk.risk_manager import RiskManager
from src.strategy.auto_selector import AutoSelectionResult, select_strategy
from src.strategy.moving_average import MovingAverageStrategy


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
                    strategy TEXT,
                    signal_timestamp_utc TEXT,
                    signal TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    side TEXT,
                    quantity REAL,
                    proposed_quantity REAL,
                    order_status TEXT,
                    reason TEXT NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS paper_automation_events_time "
                "ON paper_automation_events(timestamp_utc, id)"
            )
            columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(paper_automation_events)"
                ).fetchall()
            }
            if "strategy" not in columns:
                db.execute(
                    "ALTER TABLE paper_automation_events ADD COLUMN strategy TEXT"
                )
            if "proposed_quantity" not in columns:
                db.execute(
                    "ALTER TABLE paper_automation_events "
                    "ADD COLUMN proposed_quantity REAL"
                )

    def record(self, event: dict[str, Any]) -> None:
        with sqlite3.connect(self.database_path, timeout=10) as db:
            db.execute(
                """INSERT INTO paper_automation_events
                   (timestamp_utc, symbol, strategy, signal_timestamp_utc, signal, decision,
                    side, quantity, proposed_quantity, order_status, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(event["timestamp_utc"]),
                    str(event["symbol"]),
                    event.get("strategy"),
                    event.get("signal_timestamp_utc"),
                    str(event.get("signal", "n/d")),
                    str(event.get("decision", "unknown")),
                    event.get("side"),
                    event.get("quantity"),
                    event.get("proposed_quantity"),
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
                """SELECT timestamp_utc, symbol, strategy, signal_timestamp_utc, signal, decision,
                          side, quantity, proposed_quantity, order_status, reason
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
_AUTO_PARAMETER_CANDIDATES = (
    {"short_window": 5, "long_window": 10},
    {"short_window": 10, "long_window": 20},
    {"short_window": 20, "long_window": 50},
)
_AUTO_MARKET_DATA_CACHE: dict[
    tuple[weakref.ReferenceType[Any], str, str], tuple[float, pd.DataFrame, bool]
] = {}
_AUTO_MARKET_DATA_CACHE_LOCK = threading.RLock()
_AUTO_MARKET_DATA_CACHE_MAX_ENTRIES = 64


def _auto_market_data_cache_ttl(interval: str) -> float:
    return {
        "1Min": 30.0,
        "5Min": 60.0,
        "15Min": 120.0,
        "1Hour": 300.0,
        "1Day": 300.0,
        "1Week": 300.0,
    }.get(interval, 0.0)


def _get_auto_selection_data(
    broker: Any,
    *,
    symbol: str,
    interval: str,
) -> tuple[pd.DataFrame | None, bool]:
    key = (weakref.ref(broker), interval, symbol)
    now = time.monotonic()
    ttl = _auto_market_data_cache_ttl(interval)
    with _AUTO_MARKET_DATA_CACHE_LOCK:
        cached = _AUTO_MARKET_DATA_CACHE.get(key)
        if cached is not None and now - cached[0] < ttl:
            return cached[1].copy(), cached[2]

    availability = broker.get_instrument_availability(symbol)
    is_tradable = availability.get("paper_tradable") is True
    if not is_tradable:
        return None, False
    if interval == "1Week":
        period = "5Y"
    elif interval in {"1Min", "5Min", "15Min", "1Hour"}:
        period = "3M"
    else:
        period = "1Y"
    data = broker.get_market_data(
        symbol,
        timeframe=interval,
        period=period,
        limit=1_000,
    )
    if (
        not isinstance(data, pd.DataFrame)
        or data.empty
        or data.attrs.get("quality") != "real"
        or data.attrs.get("interval") != interval
    ):
        return None, False
    if len(data) > 1_000:
        data = data.tail(1_000).reset_index(drop=True)
    with _AUTO_MARKET_DATA_CACHE_LOCK:
        _AUTO_MARKET_DATA_CACHE[key] = (now, data.copy(), True)
        while len(_AUTO_MARKET_DATA_CACHE) > _AUTO_MARKET_DATA_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _AUTO_MARKET_DATA_CACHE,
                key=lambda cache_key: _AUTO_MARKET_DATA_CACHE[cache_key][0],
            )
            del _AUTO_MARKET_DATA_CACHE[oldest_key]
    return data, True


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
        parsed = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError, OverflowError) as exc:
        raise PaperAutomationError(f"{label} is invalid; automation is blocked.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def execute_auto_paper_cycle(
    *,
    broker: Any,
    settings: AppSettings,
    dry_run: bool = True,
    interval: str = "1Day",
    allowed_symbols: tuple[str, ...] | None = None,
    training_bars: int = 100,
    test_bars: int = 60,
) -> dict[str, Any]:
    """Select a walk-forward-validated asset and optionally route a Paper order."""
    if (
        settings.trading_mode != "paper"
        or not settings.paper_trading_enabled
        or getattr(broker, "paper_client_configured", False) is not True
        or getattr(broker, "paper_client_is_paper", False) is not True
    ):
        raise PaperAutomationError(
            "A dedicated Alpaca Paper client is required; Live and Demo are rejected."
        )
    verification = broker.verify_connection()
    if (
        verification.get("connected") is not True
        or verification.get("mode") != "paper"
        or broker.is_connected() is not True
    ):
        raise PaperAutomationError(
            "Alpaca Paper endpoint/account verification failed; no order was sent."
        )

    account = broker.get_account()
    if _text(_field(account, "status")) != "active":
        raise PaperAutomationError("Paper account is not active; automation is stopped.")
    if _field(account, "trading_blocked", False) or _field(account, "account_blocked", False):
        raise PaperAutomationError("Paper account trading is blocked; automation is stopped.")
    equity = _number(_field(account, "equity"), "Paper account equity")
    cash = _number(_field(account, "cash"), "Paper account cash")
    buying_power = _number(_field(account, "buying_power"), "Paper account buying power")
    previous_equity = _number(
        _field(account, "last_equity"), "Previous close equity"
    )
    if equity <= 0 or previous_equity <= 0 or cash < 0 or buying_power < 0:
        raise PaperAutomationError(
            "Paper account balances are invalid; automatic selection is blocked."
        )

    positions = broker.get_positions()
    orders = broker.get_orders()
    current_positions: dict[str, float] = {}
    for position in positions:
        symbol = str(_field(position, "symbol", "")).strip().upper()
        quantity = _number(_field(position, "qty"), "Current position quantity")
        if quantity < 0:
            raise PaperAutomationError(
                "Short positions are unsupported by the automatic selector."
            )
        current_positions[symbol] = quantity
    if not isinstance(orders, (list, tuple)):
        raise PaperAutomationError(
            "Paper orders could not be reconciled; automatic selection is blocked."
        )

    symbols = tuple(INSTRUMENTS) if allowed_symbols is None else tuple(
        str(symbol).strip().upper() for symbol in allowed_symbols
    )
    if not symbols or any(symbol not in INSTRUMENTS for symbol in symbols):
        raise PaperAutomationError(
            "The automatic selector accepts only non-empty subsets of supported assets."
        )
    if len(set(symbols)) != len(symbols):
        symbols = tuple(dict.fromkeys(symbols))

    asset_data: dict[str, pd.DataFrame] = {}
    asset_availability: dict[str, bool] = {}
    data_errors: list[str] = []
    for symbol in symbols:
        try:
            data, tradable = _get_auto_selection_data(
                broker, symbol=symbol, interval=interval
            )
        except (ValueError, RuntimeError) as exc:
            data, tradable = None, False
            data_errors.append(f"{symbol}: market data unavailable ({exc}).")
        asset_availability[symbol] = tradable
        if data is not None:
            asset_data[symbol] = data
        else:
            asset_data[symbol] = pd.DataFrame()

    selection: AutoSelectionResult = select_strategy(
        asset_data,
        asset_availability=asset_availability,
        interval=interval,
        parameter_candidates=_AUTO_PARAMETER_CANDIDATES,
        training_bars=training_bars,
        test_bars=test_bars,
        settings=settings,
        available_cash=min(cash, buying_power),
        current_positions=current_positions,
        pnl_today=equity - previous_equity,
    )
    if selection.status != "SELECTED":
        reason = selection.reason
        if data_errors:
            reason = f"{reason} {' '.join(data_errors)}"
        return {
            "status": "NO_TRADE",
            "symbol": selection.asset,
            "strategy": selection.strategy,
            "parameters": selection.parameters,
            "side": selection.side,
            "proposed_quantity": selection.proposed_quantity,
            "reason": reason,
            "selection_reason": selection.reason,
            "exclusions": selection.exclusions,
        }

    if (
        selection.asset not in asset_data
        or selection.strategy != "moving_average"
        or not selection.parameters
        or selection.side not in {"buy", "sell"}
        or selection.proposed_quantity is None
        or not math.isfinite(float(selection.proposed_quantity))
        or float(selection.proposed_quantity) <= 0
    ):
        raise PaperAutomationError(
            "The strategy selector returned an invalid decision; no order was sent."
        )
    execution = execute_paper_signal(
        broker=broker,
        settings=settings,
        symbol=selection.asset,
        market_data=asset_data[selection.asset],
        short_window=selection.parameters["short_window"],
        long_window=selection.parameters["long_window"],
        dry_run=dry_run,
    )
    return {
        **execution,
        "symbol": selection.asset,
        "strategy": selection.strategy,
        "parameters": dict(selection.parameters),
        "proposed_quantity": float(selection.proposed_quantity),
        "selection_reason": selection.reason,
        "reason": f"{selection.reason} {execution['reason']}",
        "exclusions": selection.exclusions,
    }


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
    as_of: datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Evaluate one fresh crossover and submit at most one verified paper order."""
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
    bar_intervals = {
        "1Min": (60, 600),
        "5Min": (300, 1200),
        "15Min": (900, 2700),
        "1Hour": (3600, 10_800),
        "1Day": (86_400, 345_600),
        "1Week": (604_800, 864_000),
    }
    interval_seconds = bar_intervals.get(interval)
    if interval_seconds is None:
        raise PaperAutomationError("Unsupported market-data interval; no order was sent.")
    timestamps = pd.to_datetime(
        market_data["timestamp"], utc=True, errors="coerce"
    )
    if (
        timestamps.isna().any()
        or not timestamps.is_monotonic_increasing
        or timestamps.duplicated().any()
    ):
        raise PaperAutomationError(
            "Market-data timestamps are invalid, duplicated, or out of order; automation is blocked."
        )
    try:
        decision_time = (
            pd.Timestamp.now(tz="UTC")
            if as_of is None
            else pd.Timestamp(as_of)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise PaperAutomationError(
            "Decision timestamp must be a valid timezone-aware date; automation is blocked."
        ) from exc
    if pd.isna(decision_time) or decision_time.tzinfo is None:
        raise PaperAutomationError(
            "Decision timestamp must be a valid timezone-aware date; automation is blocked."
        )
    decision_time = decision_time.tz_convert("UTC")

    signal_data = market_data.copy()
    signal_data["timestamp"] = timestamps
    forming_bar = False
    while not signal_data.empty:
        is_forming, timestamp_age, _ = bar_timing(
            symbol,
            interval,
            signal_data["timestamp"].iloc[-1],
            decision_time,
            interval_seconds[0],
        )
        if timestamp_age < 0:
            raise PaperAutomationError(
                "Market data contains a future timestamp; automation is blocked."
            )
        if not is_forming:
            break
        forming_bar = True
        signal_data = signal_data.iloc[:-1].copy()

    if signal_data.empty:
        bar_time = _utc_datetime(
            timestamps.iloc[-1], "Latest bar timestamp"
        )
        return {
            "status": "blocked",
            "reason": "No completed OHLC bar is available; automation is waiting.",
            "signal_timestamp": bar_time.isoformat(),
        }

    bar_time = _utc_datetime(
        signal_data["timestamp"].iloc[-1], "Latest completed bar timestamp"
    )
    _, completed_timestamp_age, completed_freshness_age = bar_timing(
        symbol,
        interval,
        signal_data["timestamp"].iloc[-1],
        decision_time,
        interval_seconds[0],
    )
    max_bar_age = interval_seconds[1]
    if (
        completed_timestamp_age < 0
        or completed_timestamp_age > max_bar_age
        or completed_freshness_age < -120
        or completed_freshness_age > max_bar_age
    ):
        raise PaperAutomationError("Market data is stale; automation is blocked.")

    verification = broker.verify_connection()
    if not verification.get("connected"):
        raise PaperAutomationError("Paper account verification failed; automation is stopped.")
    account = broker.get_account()
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
    if quote_age < -30 or quote_age > 120:
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

    if dry_run:
        return {
            "status": "preview",
            "signal": int(signal["signal"]),
            "reason": (
                "Paper order passed current broker and risk checks; dry-run mode "
                "did not call submit_order."
            ),
            "signal_timestamp": bar_time.isoformat(),
            "side": side,
            "quantity": order_quantity,
        }

    submitted = broker.submit_order(
        symbol=symbol,
        side=side,
        quantity=order_quantity,
        client_order_id=client_order_id,
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
