import numpy as np
import pandas as pd
import pytest

from src.strategy.trend import EMACrossoverStrategy


def test_crossovers_are_events_with_buy_sell_and_wait():
    prices = pd.DataFrame({"close": [10, 10, 10, 10, 9, 8, 12, 13, 7, 6]})
    result = EMACrossoverStrategy(2, 3, 4).generate_signals(prices)
    assert result["signal"].tolist() == [0, 0, 0, 0, -1, 0, 1, 0, -1, 0]
    assert "above" in result.loc[6, "signal_reason"]
    assert "below" in result.loc[8, "signal_reason"]
    assert pd.api.types.is_integer_dtype(result["signal"])


def test_default_parameters_and_full_warmup():
    strategy = EMACrossoverStrategy()
    assert (strategy.short_window, strategy.long_window, strategy.trend_window) == (9, 21, 50)
    assert strategy.warmup_bars == 51
    result = strategy.generate_signals(pd.DataFrame({"close": range(1, 52)}))
    assert result["ema50"].iloc[:49].isna().all()
    assert result["signal"].iloc[:50].eq(0).all()
    assert result["signal_reason"].iloc[:50].eq("insufficient data").all()
    for column, span in (("short_ma", 9), ("long_ma", 21), ("ema50", 50)):
        expected = result["close"].ewm(span=span, adjust=False, min_periods=span).mean()
        pd.testing.assert_series_equal(result[column], expected, check_names=False)


@pytest.mark.parametrize("mirror", [False, True])
def test_crossovers_on_wrong_side_of_trend_are_blocked(mirror):
    closes = [7, 7, 18, 10, 6, 7, 10, 10, 9, 19, 17, 13]
    if mirror:
        closes = [26 - price for price in closes]
    result = EMACrossoverStrategy(2, 3, 8).generate_signals(pd.DataFrame({"close": closes}))
    previous, latest = result.iloc[-2], result.iloc[-1]
    assert ((previous.short_ma >= previous.long_ma and latest.short_ma < latest.long_ma)
            if not mirror else
            (previous.short_ma <= previous.long_ma and latest.short_ma > latest.long_ma))
    assert latest.signal == 0
    assert "blocked by trend filter" in latest.signal_reason


def test_indicators_and_signals_are_prefix_invariant_and_input_is_preserved():
    data = pd.DataFrame({"close": [10, 9, 8, 11, 13, 7, 6, 12] * 4,
                         "volume": range(1, 33), "source": "fixture"})
    data.attrs = {"provider": "synthetic", "metadata": {"unit": "USD"}}
    original = data.copy(deep=True)
    strategy = EMACrossoverStrategy(2, 3, 4)
    full = strategy.generate_signals(data)
    for end in (1, 4, 8, 15, 31):
        pd.testing.assert_frame_equal(strategy.generate_signals(data.iloc[:end]), full.iloc[:end])
    pd.testing.assert_frame_equal(data, original)
    assert full.attrs == original.attrs
    pd.testing.assert_frame_equal(full[data.columns], original)


@pytest.mark.parametrize("windows", [(0, 3, 4), (-1, 3, 4), (2, 2, 4), (3, 2, 4),
                                     (2, 4, 3), (True, 3, 4), (2, False, 4),
                                     (2, 3, True), (2.0, 3, 4), (2, 3, "4")])
def test_invalid_windows_are_rejected(windows):
    with pytest.raises(ValueError):
        EMACrossoverStrategy(*windows)


@pytest.mark.parametrize("column,values", [
    ("close", [1, 0]), ("close", [1, -1]), ("close", [1, np.nan]),
    ("close", [1, np.inf]), ("close", ["1", "2"]), ("close", [True, False]),
    ("close", [1 + 1j, 2]), ("volume", [1, -1]), ("volume", [1, np.nan]),
    ("volume", [1, np.inf]), ("volume", ["1", "2"]), ("volume", [True, False]),
])
def test_invalid_prices_or_optional_volumes_are_rejected(column, values):
    data = pd.DataFrame({"close": [1, 2]})
    data[column] = values
    with pytest.raises(ValueError, match=column):
        EMACrossoverStrategy().generate_signals(data)


def test_empty_data_keeps_schema_and_missing_close_is_rejected():
    strategy = EMACrossoverStrategy()
    empty = strategy.generate_signals(pd.DataFrame({"close": pd.Series(dtype=float)}))
    assert empty.empty
    assert set(empty.columns) == {"close", "short_ma", "long_ma", "ema50", "rsi14", "signal", "signal_reason"}
    assert pd.api.types.is_integer_dtype(empty["signal"])
    with pytest.raises(ValueError, match="close"):
        strategy.generate_signals(pd.DataFrame())


def test_diagnostics_are_optional_and_do_not_filter_signals():
    strategy = EMACrossoverStrategy(2, 3, 4)
    prices = pd.DataFrame({"close": range(1, 31)})
    no_volume = strategy.generate_signals(prices)
    prices["volume"] = 0.0
    zero_volume = strategy.generate_signals(prices)
    pd.testing.assert_series_equal(no_volume["signal"], zero_volume["signal"])
    assert zero_volume["relative_volume"].isna().all()
    assert no_volume["rsi14"].iloc[:14].isna().all()
    assert no_volume["rsi14"].iloc[14:].eq(100).all()
    prices["close"] = 10
    prices["volume"] = 3
    flat = strategy.generate_signals(prices)
    assert flat["rsi14"].iloc[14:].eq(50).all()
    assert flat["relative_volume"].iloc[:19].isna().all()
    assert flat["relative_volume"].iloc[19:].eq(1).all()
    prices["close"] = range(30, 0, -1)
    falling = strategy.generate_signals(prices)
    assert falling["rsi14"].iloc[14:].eq(0).all()
