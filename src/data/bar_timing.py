from __future__ import annotations

import pandas as pd
import pandas_market_calendars as mcal

from src.data.instruments import INSTRUMENTS


_NYSE_CALENDAR = mcal.get_calendar("NYSE")


def bar_timing(
    symbol: str,
    interval: str,
    bar_timestamp: object,
    as_of: object,
    minimum_age_seconds: int,
) -> tuple[bool, float, float]:
    """Return (is_forming, timestamp_age_seconds, freshness_age_seconds)."""
    if bar_timestamp is None or as_of is None:
        raise ValueError("Bar and decision timestamps are required.")

    try:
        bar_time = pd.Timestamp(bar_timestamp)
        now = pd.Timestamp(as_of)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Bar and decision timestamps must be valid dates.") from exc

    if pd.isna(bar_time) or pd.isna(now):
        raise ValueError("Bar and decision timestamps must be valid dates.")

    if bar_time.tzinfo is None or now.tzinfo is None:
        raise ValueError("Bar and decision timestamps must include a timezone.")

    bar_time = bar_time.tz_convert("UTC")
    now = now.tz_convert("UTC")
    timestamp_age = (now - bar_time).total_seconds()

    instrument = INSTRUMENTS.get(symbol.strip().upper(), {})

    # Daily US stocks and ETFs use the actual NYSE session close.
    if interval == "1Day" and instrument.get("kind") == "equity":
        session_date = bar_time.date()
        schedule = _NYSE_CALENDAR.schedule(
            start_date=session_date,
            end_date=session_date,
        )

        if schedule.empty:
            return True, timestamp_age, timestamp_age

        market_close = pd.Timestamp(
            schedule.iloc[0]["market_close"]
        ).tz_convert("UTC")

        is_forming = now < market_close
        freshness_age = (now - market_close).total_seconds()

        return is_forming, timestamp_age, freshness_age

    # Intraday bars, crypto daily bars, weekly bars and non-session
    # timestamps retain the existing elapsed-time rules.
    return (
        timestamp_age < minimum_age_seconds,
        timestamp_age,
        timestamp_age,
    )