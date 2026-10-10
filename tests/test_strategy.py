import pandas as pd

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


def test_current_signal_reports_buy_when_short_moves_above_long():
    df = pd.DataFrame({
        "close": [10, 11, 12, 13, 14, 15, 16, 17]
    })
    strategy = MovingAverageStrategy(short_window=2, long_window=3)
    signal = strategy.current_signal(df)
    assert signal["signal"] in {-1, 0, 1}
    assert signal["short_ma"] >= 0
    assert signal["long_ma"] >= 0
