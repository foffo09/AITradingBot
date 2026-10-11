from __future__ import annotations

import pandas as pd


class MovingAverageStrategy:
    """Simple moving-average crossover strategy for educational use."""

    def __init__(self, short_window: int = 10, long_window: int = 30):
        if short_window <= 0 or long_window <= 0:
            raise ValueError("Moving average windows must be positive.")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window.")
        self.short_window = short_window
        self.long_window = long_window

    def calculate_moving_average(self, series: pd.Series) -> pd.Series:
        if series.empty:
            return pd.Series(dtype=float)
        return series.rolling(window=self.short_window, min_periods=self.short_window).mean()

    def generate_signals(self, market_data: pd.DataFrame) -> pd.DataFrame:
        df = market_data.copy()
        if "close" not in df.columns:
            raise ValueError("Dataframe must include 'close' prices.")

        if market_data.empty:
            df["short_ma"] = pd.Series(index=df.index, dtype=float)
            df["long_ma"] = pd.Series(index=df.index, dtype=float)
            df["signal"] = pd.Series(index=df.index, dtype=int)
            df["signal_reason"] = pd.Series(index=df.index, dtype=object)
            return df

        df["short_ma"] = df["close"].rolling(window=self.short_window, min_periods=self.short_window).mean()
        df["long_ma"] = df["close"].rolling(window=self.long_window, min_periods=self.long_window).mean()
        df["signal"] = 0

        previous_short = df["short_ma"].shift(1)
        previous_long = df["long_ma"].shift(1)

        buy_mask = (df["short_ma"] > df["long_ma"]) & (previous_short <= previous_long)
        sell_mask = (df["short_ma"] < df["long_ma"]) & (previous_short >= previous_long)
        df.loc[buy_mask, "signal"] = 1
        df.loc[sell_mask, "signal"] = -1

        df["signal_reason"] = "hold"
        df.loc[buy_mask, "signal_reason"] = "golden cross: short MA crossed above long MA"
        df.loc[sell_mask, "signal_reason"] = "death cross: short MA crossed below long MA"

        return df

    def current_signal(self, market_data: pd.DataFrame) -> dict[str, object]:
        signals = self.generate_signals(market_data)
        if signals.empty:
            return {
                "signal": 0,
                "short_ma": None,
                "long_ma": None,
                "reason": "insufficient data: no price bars available",
            }
        latest = signals.iloc[-1]
        short_ma = latest["short_ma"]
        long_ma = latest["long_ma"]
        if pd.isna(short_ma) or pd.isna(long_ma):
            return {
                "signal": 0,
                "short_ma": None,
                "long_ma": None,
                "reason": (
                    f"insufficient data: at least {self.long_window} valid price bars "
                    "are required"
                ),
            }
        return {
            "signal": int(latest.get("signal", 0)),
            "short_ma": float(short_ma),
            "long_ma": float(long_ma),
            "reason": str(latest.get("signal_reason", "hold")),
        }
