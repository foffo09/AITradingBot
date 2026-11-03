from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def generate_demo_prices(
    symbol: str = "AAPL",
    periods: int = 200,
    start_price: float = 100.0,
    drift: float = 0.0005,
    volatility: float = 0.012,
) -> pd.DataFrame:
    """Generate synthetic market data clearly marked as demo-only."""
    if periods <= 0:
        raise ValueError("periods must be positive")

    rng = np.arange(periods)
    noise = np.random.default_rng(42).normal(0.0, volatility, periods)
    trend = rng * drift
    prices = start_price * (1.0 + (trend / 100.0) + noise)

    dates = pd.date_range(end=datetime.now(timezone.utc) - timedelta(days=1), periods=periods, freq="D")
    df = pd.DataFrame({
        "symbol": symbol,
        "timestamp": dates,
        "close": prices,
        "open": prices * (1 - 0.003),
        "high": prices * (1 + 0.008),
        "low": prices * (1 - 0.008),
        "volume": 1000 + (rng * 12).astype(int),
    })
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["is_synthetic"] = True
    df["data_quality"] = "synthetic-demo"
    return df


def generate_synthetic_market_data(symbol: str = "AAPL", periods: int = 200) -> pd.DataFrame:
    return generate_demo_prices(symbol=symbol, periods=periods)
