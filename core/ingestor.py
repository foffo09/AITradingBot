from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
import pandas as pd

from core.state import Market
from src.data.market_data import generate_demo_prices


class Ingestor:
    """Wrap the original generator; synthetic candles are never relabelled live."""

    def __init__(self, synthetic: bool = True) -> None:
        self.frames: dict[Market, pd.DataFrame] = {}
        if not synthetic:
            return
        for market, volatility in zip(Market, (0.08, 0.025, 0.06, 0.02, 0.045)):
            frame = generate_demo_prices(str(market), periods=2000, volatility=volatility)
            frame["timestamp"] = pd.date_range("2020-01-01", periods=len(frame), freq="D", tz="UTC")
            self.frames[market] = self.normalize(frame)

    @staticmethod
    def normalize(frame: pd.DataFrame) -> pd.DataFrame:
        required = ["open", "high", "low", "close", "volume"]
        if frame.empty or any(column not in frame for column in [*required, "timestamp"]):
            raise ValueError("Nonempty OHLCV with timestamp required")
        result = frame.copy()
        result[required] = result[required].apply(pd.to_numeric, errors="raise")
        values = result[required].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
            raise ValueError("Invalid OHLCV values")
        if (result.high < result[["open", "close", "low"]].max(axis=1)).any() or (
            result.low > result[["open", "close", "high"]].min(axis=1)
        ).any():
            raise ValueError("Inconsistent candle range")
        result["timestamp"] = pd.to_datetime(result.timestamp, utc=True, errors="raise")
        if result.timestamp.isna().any() or result.timestamp.duplicated().any() or not result.timestamp.is_monotonic_increasing:
            raise ValueError("Timestamps must be strictly increasing")
        return result

    async def clock(self, interval: float = 1.0) -> AsyncIterator[None]:
        while True:
            await asyncio.sleep(interval)
            yield None
