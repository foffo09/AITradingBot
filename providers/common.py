from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx
import pandas as pd
from pydantic import Field, model_validator

from core.state import ValidatedModel


class Quote(ValidatedModel):
    provider: str
    symbol: str
    price: float = Field(gt=0)
    bid: float | None = Field(default=None, gt=0)
    ask: float | None = Field(default=None, gt=0)
    source_time: float | None = None
    received_at: float = Field(default_factory=time.time)
    transport: Literal["websocket", "rest", "tws"]
    quality: Literal["realtime", "indicative", "unknown"] = "unknown"
    instrument: Literal["token", "perpetual", "equity", "option", "future", "proxy"]
    imbalance: float | None = Field(default=None, ge=-1, le=1)
    bids: list[tuple[float, float]] = Field(default_factory=list)
    asks: list[tuple[float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_book(self):
        import math
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("Crossed order book")
        if any(not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q < 0 for p, q in self.bids + self.asks):
            raise ValueError("Invalid book levels")
        return self

    @property
    def instrument_id(self) -> str:
        return f"{self.provider}:{self.symbol}"

    def fresh(self, max_age: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.source_time is not None and -5 <= now - self.source_time <= max_age and now - self.received_at <= max_age


QuoteSink = Callable[[Quote], Awaitable[None]]
HistorySink = Callable[[pd.DataFrame, str, str], Awaitable[None]]


class ProviderUnavailable(RuntimeError):
    """An optional provider cannot serve this request."""


def error_code(exc: Exception) -> str:
    # URLs may contain API keys: never put raw exception strings in logs or the UI.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retry = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {408, 429, 500, 502, 503, 504}
            if not retry or attempt == 2:
                raise ProviderUnavailable(error_code(exc)) from None
            await asyncio.sleep(0.5 * 2 ** attempt)
    raise ProviderUnavailable("HTTP retry budget exhausted")


def timestamp(value: Any) -> float:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, (int, float)):
        return float(value) / 1000 if value > 100_000_000_000 else float(value)
    return pd.Timestamp(value).timestamp()


def frame_from_rows(rows: list[list[Any]], symbol: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame.timestamp, unit="ms", utc=True)
    frame["symbol"] = symbol
    frame["is_synthetic"] = False
    return frame
