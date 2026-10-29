from __future__ import annotations

import pandas as pd
import pytest

from src.data.bar_timing import bar_timing


def test_nyse_daily_bar_is_forming_before_regular_session_close():
    forming, timestamp_age, freshness_age = bar_timing(
        "AAPL",
        "1Day",
        pd.Timestamp("2025-07-02T00:00:00Z"),
        pd.Timestamp("2025-07-02T19:59:00Z"),
        86_400,
    )

    assert forming
    assert timestamp_age == pytest.approx(19 * 60 * 60 + 59 * 60)
    assert freshness_age == pytest.approx(-60)


def test_nyse_daily_bar_is_complete_after_regular_session_close():
    forming, _, freshness_age = bar_timing(
        "SPY",
        "1Day",
        pd.Timestamp("2025-07-02T00:00:00Z"),
        pd.Timestamp("2025-07-02T20:01:00Z"),
        86_400,
    )

    assert not forming
    assert freshness_age == pytest.approx(60)


def test_nyse_early_close_uses_the_calendar_close_time():
    before_close, _, _ = bar_timing(
        "AAPL",
        "1Day",
        pd.Timestamp("2025-07-03T00:00:00Z"),
        pd.Timestamp("2025-07-03T16:59:00Z"),
        86_400,
    )
    after_close, _, freshness_age = bar_timing(
        "AAPL",
        "1Day",
        pd.Timestamp("2025-07-03T00:00:00Z"),
        pd.Timestamp("2025-07-03T17:01:00Z"),
        86_400,
    )

    assert before_close
    assert not after_close
    assert freshness_age == pytest.approx(60)


def test_crypto_daily_bar_uses_elapsed_time_not_equity_session_calendar():
    forming, timestamp_age, freshness_age = bar_timing(
        "BTC/USD",
        "1Day",
        pd.Timestamp("2025-07-02T00:00:00Z"),
        pd.Timestamp("2025-07-02T23:59:00Z"),
        86_400,
    )

    assert forming
    assert timestamp_age == pytest.approx(86_340)
    assert freshness_age == timestamp_age


def test_intraday_bar_keeps_elapsed_time_completion_rule():
    forming, _, _ = bar_timing(
        "AAPL",
        "1Min",
        pd.Timestamp("2025-07-02T12:00:00Z"),
        pd.Timestamp("2025-07-02T12:00:30Z"),
        60,
    )
    complete, _, _ = bar_timing(
        "AAPL",
        "1Min",
        pd.Timestamp("2025-07-02T12:00:00Z"),
        pd.Timestamp("2025-07-02T12:01:00Z"),
        60,
    )

    assert forming
    assert not complete


def test_daily_equity_timestamp_on_non_session_is_not_assumed_complete():
    forming, _, _ = bar_timing(
        "AAPL",
        "1Day",
        pd.Timestamp("2025-07-04T00:00:00Z"),
        pd.Timestamp("2025-07-07T15:00:00Z"),
        86_400,
    )

    assert forming


@pytest.mark.parametrize(
    ("bar_timestamp", "as_of"),
    [
        (None, pd.Timestamp("2025-07-02T20:01:00Z")),
        ("not-a-date", pd.Timestamp("2025-07-02T20:01:00Z")),
        (pd.Timestamp("2025-07-02T00:00:00Z"), None),
        (pd.Timestamp("2025-07-02T00:00:00Z"), "not-a-date"),
        (pd.Timestamp("2025-07-02"), pd.Timestamp("2025-07-02T20:01:00Z")),
    ],
)
def test_missing_invalid_or_naive_timestamps_are_rejected(bar_timestamp, as_of):
    with pytest.raises(ValueError):
        bar_timing("AAPL", "1Day", bar_timestamp, as_of, 86_400)
