"""Calendar eligibility for explicitly timestamped bars; no broker or clock access."""
from functools import lru_cache
import math

import pandas as pd

try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None


class BarTimingError(ValueError):
    pass


MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60}
MAX_AGE = {"1Min": 600, "5Min": 1200, "15Min": 2700, "1Hour": 10800, "1Day": 345600}
PUBLICATION_DELAY = pd.Timedelta(seconds=30)


def utc_timestamp(value, label):
    try:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed) or parsed.tzinfo is None:
            raise ValueError("Missing timezone or timestamp")
        return parsed.tz_convert("UTC")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BarTimingError(f"{label} is invalid or has no timezone; operation is blocked.") from exc


@lru_cache(maxsize=32)
def _nyse_schedule(start, end):
    if mcal is None:
        raise BarTimingError("Market calendar dependency is unavailable; operation is blocked.")
    try:
        return mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    except Exception as exc:
        raise BarTimingError("Market calendar cannot be verified; operation is blocked.") from exc


def select_completed_bars(data, symbol, now, *, require_market_open=True):
    """Select closed intervals fetched after publication delay, never infer feed finality.

    Raw stock daily/weekly aggregates may include extended hours. Without an
    explicit regular-session contract they remain display-only.
    """
    current = utc_timestamp(now, "Reference time")
    if data.empty or not {"timestamp", "close"}.issubset(data.columns):
        raise BarTimingError("No timestamped close bars are available.")
    interval = data.attrs.get("interval")
    if interval not in MAX_AGE:
        raise BarTimingError("Unsupported operational interval; weekly aggregation is unverified.")
    if data.attrs.get("bar_time_contract") != "alpaca-start-v1":
        raise BarTimingError("Bar timestamp contract is unverified; operation is blocked.")
    fetched = utc_timestamp(data.attrs.get("fetched_at"), "Data acquisition time")
    timestamps = pd.DatetimeIndex([utc_timestamp(value, "Bar timestamp") for value in data["timestamp"]])
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise BarTimingError("Duplicate or out-of-order bars are not operationally usable.")
    if fetched > current or (timestamps > current).any() or (timestamps > fetched).any():
        raise BarTimingError("Future bars or acquisition timestamps are not operationally usable.")
    if (current - timestamps[-1]).total_seconds() > MAX_AGE[interval]:
        raise BarTimingError("Market data is stale; latest available bar is too old.")
    try:
        closes = pd.to_numeric(data["close"], errors="raise")
        if not all(math.isfinite(float(value)) and float(value) > 0 for value in closes):
            raise ValueError("Invalid close")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BarTimingError("Invalid close prices; operation is blocked.") from exc

    crypto = "/" in symbol
    scope = data.attrs.get("session_scope")
    if crypto:
        if data.attrs.get("bar_calendar") != "24/7" or scope != "continuous":
            raise BarTimingError("Crypto session contract is unverified.")
        if interval == "1Day":
            raise BarTimingError("Crypto daily aggregation timezone is unverified; operation is blocked.")
        schedule = None
    else:
        if data.attrs.get("bar_calendar") != "NYSE" or scope not in {"regular", "all_sessions"}:
            raise BarTimingError("US equity session contract is unverified.")
        if interval == "1Day" and scope != "regular":
            raise BarTimingError("Raw daily bars may include extended hours; regular-session closure is unverified.")
        local = timestamps.tz_convert("America/New_York")
        today = current.tz_convert("America/New_York").date()
        schedule = _nyse_schedule(str(min(local.date)), str(today))
        today_key = pd.Timestamp(today)
        if require_market_open and (today_key not in schedule.index or not (
            schedule.loc[today_key, "market_open"] <= current < schedule.loc[today_key, "market_close"]
        )):
            raise BarTimingError("US regular market session is closed; extended-hours execution is unsupported.")

    selected, closed_at = [], []
    incomplete, outside = 0, 0
    cutoff = min(current, fetched) - PUBLICATION_DELAY
    for position, timestamp in enumerate(timestamps):
        if crypto:
            if timestamp != timestamp.floor(f"{MINUTES[interval]}min"):
                raise BarTimingError("Crypto bar is not aligned to its UTC interval.")
            end = timestamp + pd.Timedelta(minutes=MINUTES[interval])
        else:
            local_time = timestamp.tz_convert("America/New_York")
            day = pd.Timestamp(local_time.date())
            if day not in schedule.index:
                outside += 1
                continue
            opening, closing = schedule.loc[day, ["market_open", "market_close"]]
            if interval == "1Day":
                if local_time != local_time.normalize():
                    raise BarTimingError("Daily equity bar must start at midnight New York time.")
                end = closing
            else:
                if timestamp != timestamp.floor(f"{MINUTES[interval]}min"):
                    raise BarTimingError("Equity bar is not aligned to its interval.")
                end = timestamp + pd.Timedelta(minutes=MINUTES[interval])
                if timestamp < opening or end > closing:
                    outside += 1
                    continue
        if end <= cutoff:
            selected.append(position)
            closed_at.append(end)
        else:
            incomplete += 1
    result = data.iloc[selected].copy()
    result.attrs.update(data.attrs)
    result.attrs.update(excluded_incomplete=incomplete, excluded_outside_session=outside)
    if not result.empty:
        age = (current - timestamps[selected[-1]]).total_seconds()
        if age > MAX_AGE[interval]:
            raise BarTimingError("Market data is stale; latest completed bar is too old.")
        result.attrs["last_completed_at"] = closed_at[-1].isoformat()
    return result
