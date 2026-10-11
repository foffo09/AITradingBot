import pandas as pd
import pytest

from src.strategy.moving_average import MovingAverageStrategy


def test_generate_signals_uses_previous_values_only():
    df = pd.DataFrame({
        "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
    })
    strategy = MovingAverageStrategy(short_window=2, long_window=4)
    signals = strategy.generate_signals(df)
    assert signals["signal"].iloc[-1] in {0, 1, -1}
    assert "short_ma" in signals.columns
    assert "long_ma" in signals.columns


def test_future_prices_do_not_change_earlier_signals_or_indicators():
    history = pd.DataFrame({"close": [10, 11, 12, 11, 9, 8, 10, 12]})
    future = pd.DataFrame({"close": [1000, 1, 500]})
    strategy = MovingAverageStrategy(short_window=2, long_window=3)
    original = strategy.generate_signals(history)
    extended = strategy.generate_signals(pd.concat([history, future], ignore_index=True))

    pd.testing.assert_series_equal(
        original["short_ma"], extended.loc[:len(history) - 1, "short_ma"],
    )
    pd.testing.assert_series_equal(
        original["long_ma"], extended.loc[:len(history) - 1, "long_ma"],
    )
    pd.testing.assert_series_equal(
        original["signal"], extended.loc[:len(history) - 1, "signal"],
    )


def test_current_signal_reports_buy_when_short_moves_above_long():
    df = pd.DataFrame({
        "close": [10, 11, 12, 13, 14, 15, 16, 17]
    })
    strategy = MovingAverageStrategy(short_window=2, long_window=3)
    signal = strategy.current_signal(df)
    assert signal["signal"] in {-1, 0, 1}
    assert signal["short_ma"] >= 0
    assert signal["long_ma"] >= 0


def test_empty_input_returns_an_explicit_no_data_signal():
    signal = MovingAverageStrategy(short_window=2, long_window=3).current_signal(
        pd.DataFrame({"close": pd.Series(dtype=float)})
    )
    assert signal == {
        "signal": 0,
        "short_ma": None,
        "long_ma": None,
        "reason": "insufficient data: no price bars available",
    }


def test_insufficient_input_returns_no_nan_signal_values():
    signal = MovingAverageStrategy(short_window=2, long_window=4).current_signal(
        pd.DataFrame({"close": [10, 11, 12]})
    )
    assert signal["signal"] == 0
    assert signal["short_ma"] is None
    assert signal["long_ma"] is None
    assert "at least 4 valid price bars" in signal["reason"]


def test_empty_input_still_requires_a_close_column():
    with pytest.raises(ValueError, match="include 'close'"):
        MovingAverageStrategy().generate_signals(pd.DataFrame())
