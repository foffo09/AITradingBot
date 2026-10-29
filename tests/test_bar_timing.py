import pandas as pd
import pytest

from src.data.bar_timing import BarTimingError, select_completed_bars


def bars(times, now, interval="1Min", *, crypto=False, scope=None):
    frame = pd.DataFrame({"timestamp": pd.to_datetime(times, utc=True), "close": [100.0] * len(times)})
    frame.attrs.update(interval=interval, quality="real", bar_time_contract="alpaca-start-v1",
        fetched_at=now, bar_calendar="24/7" if crypto else "NYSE",
        session_scope=scope or ("continuous" if crypto else "all_sessions"))
    return frame


@pytest.mark.parametrize("start,now", [
    ("2026-03-06T14:30:00Z", "2026-03-06T14:31:30Z"),
    ("2026-03-09T13:30:00Z", "2026-03-09T13:31:30Z"),
    ("2026-10-30T13:30:00Z", "2026-10-30T13:31:30Z"),
    ("2026-11-02T14:30:00Z", "2026-11-02T14:31:30Z"),
])
def test_regular_open_tracks_new_york_dst(start, now):
    result = select_completed_bars(bars([start], now), "SPY", now)
    assert len(result) == 1
    assert pd.Timestamp(result.attrs["last_completed_at"]) == pd.Timestamp(start) + pd.Timedelta(minutes=1)


@pytest.mark.parametrize("date", ["2026-11-26", "2026-07-03", "2026-10-31"])
def test_holidays_and_weekends_never_authorize_equity_execution(date):
    now = date + "T16:00:00Z"
    frame = bars([date + "T15:58:00Z"], now)
    with pytest.raises(BarTimingError, match="session is closed"):
        select_completed_bars(frame, "SPY", now)


def test_early_close_daily_uses_session_close_instead_of_24_hours():
    now = "2026-11-27T18:00:30Z"
    frame = bars(["2026-11-27T05:00:00Z"], now, "1Day", scope="regular")
    result = select_completed_bars(frame, "SPY", now, require_market_open=False)
    assert len(result) == 1
    assert result.attrs["last_completed_at"] == "2026-11-27T18:00:00+00:00"
    with pytest.raises(BarTimingError, match="session is closed"):
        select_completed_bars(frame, "SPY", now)


def test_daily_regular_aggregate_waits_for_close_and_postclose_acquisition():
    frame = bars(["2026-10-28T04:00:00Z"], "2026-10-28T19:59:00Z", "1Day", scope="regular")
    assert select_completed_bars(frame, "SPY", "2026-10-28T19:59:30Z").empty
    assert select_completed_bars(frame, "SPY", "2026-10-28T20:01:00Z", require_market_open=False).empty
    frame.attrs["fetched_at"] = "2026-10-28T20:00:30Z"
    result = select_completed_bars(frame, "SPY", "2026-10-28T20:01:00Z", require_market_open=False)
    assert len(result) == 1


def test_incomplete_intervals_and_publication_margin_are_not_used():
    now = "2026-10-28T15:00:29Z"
    frame = bars(["2026-10-28T14:50:00Z", "2026-10-28T14:55:00Z"], now, "5Min")
    result = select_completed_bars(frame, "SPY", now)
    assert len(result) == 1 and result.attrs["excluded_incomplete"] == 1
    now = "2026-10-28T15:00:30Z"
    frame.attrs["fetched_at"] = now
    assert len(select_completed_bars(frame, "SPY", now)) == 2


def test_extended_hours_are_filtered_and_cannot_enable_execution():
    now = "2026-10-28T13:32:00Z"
    frame = bars(["2026-10-28T13:29:00Z", "2026-10-28T13:30:00Z"], now)
    result = select_completed_bars(frame, "SPY", now)
    assert len(result) == 1 and result.attrs["excluded_outside_session"] == 1
    with pytest.raises(BarTimingError, match="session is closed"):
        select_completed_bars(bars(["2026-10-28T20:29:00Z"], "2026-10-28T20:31:00Z"),
                              "SPY", "2026-10-28T20:31:00Z")


def test_early_close_rejects_bars_after_or_spanning_the_close():
    now = "2026-11-27T18:01:00Z"
    frame = bars(["2026-11-27T17:55:00Z", "2026-11-27T18:00:00Z"], now, "5Min")
    result = select_completed_bars(frame, "SPY", now, require_market_open=False)
    assert len(result) == 1 and result.attrs["excluded_outside_session"] == 1


def test_crypto_minute_bars_are_continuous_on_weekends():
    now = "2026-11-29T12:02:30Z"
    result = select_completed_bars(bars(["2026-11-29T12:01:00Z"], now, crypto=True), "BTC/USD", now)
    assert len(result) == 1


@pytest.mark.parametrize("problem", ["future", "duplicate", "unordered", "naive", "invalid", "stale",
    "contract", "fetched_future", "fetched_invalid", "unaligned", "zero_close", "nan_close"])
def test_invalid_or_ambiguous_bars_fail_closed(problem):
    now = "2026-10-28T15:00:30Z"
    frame = bars(["2026-10-28T14:58:00Z", "2026-10-28T14:59:00Z"], now)
    if problem == "future":
        frame.loc[1, "timestamp"] = pd.Timestamp(now) + pd.Timedelta(seconds=1)
    elif problem == "duplicate":
        frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    elif problem == "unordered":
        frame = frame.iloc[::-1]
    elif problem == "naive":
        frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    elif problem == "invalid":
        frame.loc[1, "timestamp"] = pd.NaT
    elif problem == "stale":
        frame["timestamp"] -= pd.Timedelta(hours=1)
    elif problem == "contract":
        frame.attrs.pop("bar_time_contract")
    elif problem == "fetched_future":
        frame.attrs["fetched_at"] = "2026-10-28T15:00:31Z"
    elif problem == "fetched_invalid":
        frame.attrs["fetched_at"] = None
    elif problem == "unaligned":
        frame["timestamp"] += pd.Timedelta(seconds=1)
    else:
        frame.loc[1, "close"] = 0 if problem == "zero_close" else float("nan")
    with pytest.raises(BarTimingError):
        select_completed_bars(frame, "SPY", now)


@pytest.mark.parametrize("interval,crypto", [("1Day", False), ("1Day", True), ("1Week", False)])
def test_unverified_raw_daily_and_weekly_aggregates_remain_display_only(interval, crypto):
    now = "2026-10-28T15:00:30Z"
    frame = bars(["2026-10-28T04:00:00Z"], now, interval, crypto=crypto)
    with pytest.raises(BarTimingError, match="unverified"):
        select_completed_bars(frame, "BTC/USD" if crypto else "SPY", now)


def test_calendar_failure_blocks_instead_of_falling_back_to_durations(monkeypatch):
    import src.data.bar_timing as timing
    now = "2026-10-28T15:00:30Z"
    timing._nyse_schedule.cache_clear()
    monkeypatch.setattr(timing, "mcal", None)
    with pytest.raises(BarTimingError, match="dependency is unavailable"):
        select_completed_bars(bars(["2026-10-28T14:58:00Z"], now), "SPY", now)
    timing._nyse_schedule.cache_clear()
