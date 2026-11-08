from __future__ import annotations

from numbers import Integral

import numpy as np
import pandas as pd


class EMACrossoverStrategy:
    """Causal EMA crossover events with a trend filter and diagnostic indicators."""

    def __init__(self, short_window: int = 9, long_window: int = 21, trend_window: int = 50):
        windows = (short_window, long_window, trend_window)
        if any(isinstance(window, bool) or not isinstance(window, Integral) or window <= 0
               for window in windows):
            raise ValueError("EMA windows must be positive integers.")
        if not short_window < long_window <= trend_window:
            raise ValueError("EMA windows must satisfy short_window < long_window <= trend_window.")
        self.short_window = short_window
        self.long_window = long_window
        self.trend_window = trend_window

    @property
    def warmup_bars(self) -> int:
        return self.trend_window + 1

    def generate_signals(self, market_data: pd.DataFrame) -> pd.DataFrame:
        if "close" not in market_data.columns:
            raise ValueError("Dataframe must include 'close' prices.")
        df = market_data.copy()
        for column in ("close", "volume"):
            if column not in df or df.empty:
                continue
            values = df[column]
            if (not pd.api.types.is_numeric_dtype(values)
                    or pd.api.types.is_bool_dtype(values)
                    or pd.api.types.is_complex_dtype(values)
                    or values.isna().any()
                    or not np.isfinite(values).all()
                    or (values <= 0 if column == "close" else values < 0).any()):
                raise ValueError(f"{column} must contain finite {'positive' if column == 'close' else 'nonnegative'} numbers.")

        for name, window in (("short_ma", self.short_window), ("long_ma", self.long_window),
                             ("ema50", self.trend_window)):
            df[name] = df["close"].ewm(span=window, adjust=False, min_periods=window).mean()

        changes = df["close"].diff()
        gains = changes.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        losses = (-changes.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        df["rsi14"] = (100 - 100 / (1 + gains / losses)).mask((gains == 0) & (losses == 0), 50)
        if "volume" in df:
            average_volume = df["volume"].rolling(20, min_periods=20).mean()
            df["relative_volume"] = df["volume"] / average_volume.where(average_volume > 0)

        ready = df["ema50"].shift(1).notna()
        previous_short = df["short_ma"].shift(1)
        previous_long = df["long_ma"].shift(1)
        cross_up = (df["short_ma"] > df["long_ma"]) & (previous_short <= previous_long)
        cross_down = (df["short_ma"] < df["long_ma"]) & (previous_short >= previous_long)
        buy = ready & cross_up & (df["close"] > df["ema50"])
        sell = ready & cross_down & (df["close"] < df["ema50"])
        df["signal"] = 0
        df["signal_reason"] = "hold"
        df.loc[~ready, "signal_reason"] = "insufficient data"
        df.loc[ready & (cross_up | cross_down), "signal_reason"] = "EMA crossover blocked by trend filter"
        df.loc[buy, "signal"] = 1
        df.loc[sell, "signal"] = -1
        df.loc[buy, "signal_reason"] = "short EMA crossed above long EMA; close above trend EMA"
        df.loc[sell, "signal_reason"] = "short EMA crossed below long EMA; close below trend EMA"
        return df
