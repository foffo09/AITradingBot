from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Market(StrEnum):
    MEME_SNIPER = "MEME_SNIPER"
    CRYPTO_PERPS = "CRYPTO_PERPS"
    OPTIONS_0DTE = "OPTIONS_0DTE"
    COMMODITIES_FUT = "COMMODITIES_FUT"
    BIOTECH_CATALYST = "BIOTECH_CATALYST"


class ValidatedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class Controls(ValidatedModel):
    market: Market = Market.CRYPTO_PERPS
    multi_split_kelly: bool = False
    switch_policy: Literal["flatten", "tight_trailing", "background"] = "flatten"
    bankroll: float = Field(default=10000, gt=0, le=1e9)
    kelly_multiplier: float = Field(default=0.5, ge=0.1, le=1.0)
    execution: Literal["PAPER_TRADING"] = "PAPER_TRADING"


class Position(ValidatedModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    market: Market
    quantity: float = Field(gt=0)
    entry: float = Field(gt=0)
    peak: float = Field(gt=0)
    stop: float = Field(gt=0)
    opened_at: float
    partial_taken: bool = False
    tight_trailing: bool = False
    instrument_id: str = ""


class Fill(ValidatedModel):
    position_id: str
    market: Market
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)
    quote_price: float = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = Field(ge=0)
    net_pnl: float | None = None
    timestamp: float
    reason: str
    instrument_id: str = ""


class LiveState(ValidatedModel):
    controls: Controls = Field(default_factory=Controls)
    source: Literal["SYNTHETIC_REPLAY", "LIVE_DATA_PAPER"] = "SYNTHETIC_REPLAY"
    running: bool = False
    cash: float = Field(default=10000, ge=0)
    equity: float = Field(default=10000, ge=0)
    daily_start_equity: float = Field(default=10000, gt=0)
    day: str = ""
    locked_until: float = Field(default=0, ge=0)
    positions: list[Position] = Field(default_factory=list)
    fills: list[Fill] = Field(default_factory=list)
    last_prices: dict[Market, float] = Field(default_factory=dict)
    decisions: dict[Market, str] = Field(default_factory=dict)
    pending_flatten: bool = False
    cursors: dict[Market, int] = Field(default_factory=lambda: {m: 1500 for m in Market})
    events: list[str] = Field(default_factory=list)
    updated_at: str = ""

    @model_validator(mode="after")
    def check_cursors(self) -> LiveState:
        import math
        if any(not math.isfinite(price) or price <= 0 for price in self.last_prices.values()):
            raise ValueError("Invalid persisted marks")
        if set(self.cursors) != set(Market) or any(not 1500 <= n <= 2000 for n in self.cursors.values()):
            raise ValueError("Invalid synthetic replay cursors")
        if len({p.market for p in self.positions}) != len(self.positions):
            raise ValueError("Only one demo position per market is supported")
        return self


def save_state(path: Path, state: LiveState) -> None:
    """Single runtime writer; atomic replacement prevents half-written snapshots."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(state.model_dump_json(indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
