"""Small broker contract: positions and balances always come from the broker."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NativeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)


class Rules(NativeModel):
    size_decimals: int = Field(ge=0, le=6)
    min_notional: Decimal = Decimal("10")

    def quantity(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal(1).scaleb(-self.size_decimals), rounding=ROUND_DOWN)


class Book(NativeModel):
    symbol: str
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    timestamp: float


class NativePosition(NativeModel):
    symbol: str
    quantity: Decimal
    entry: Decimal = Field(gt=0)
    leverage: Decimal = Field(gt=0)


class NativeOrder(NativeModel):
    cloid: str | None = None
    broker_id: int | None = None
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(ge=0)
    remaining: Decimal = Field(ge=0)
    price: Decimal = Field(gt=0)
    reduce_only: bool
    trigger: Decimal | None = Field(default=None, gt=0)
    status: Literal["open", "filled", "canceled", "rejected", "triggered", "unknown"]

    @model_validator(mode="after")
    def valid_remaining(self):
        if self.remaining > self.quantity:
            raise ValueError("Remaining quantity exceeds original quantity")
        if self.quantity == 0 and not (self.reduce_only and self.trigger is not None):
            raise ValueError("Zero-size order is only valid for position-wide reduce-only triggers")
        return self


class NativeFill(NativeModel):
    id: str
    broker_id: int
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal
    realized_pnl: Decimal
    timestamp_ms: int


class AccountSnapshot(NativeModel):
    equity: Decimal
    cash: Decimal
    available: Decimal = Field(ge=0)
    timestamp: float
    positions: list[NativePosition]
    open_orders: list[NativeOrder]
    fills: list[NativeFill]


class NativeRequest(NativeModel):
    cloid: str = Field(pattern=r"^0x[0-9a-f]{32}$")
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    reduce_only: bool = False
    trigger: Decimal | None = Field(default=None, gt=0)


class BrokerUnavailable(RuntimeError):
    """No raw SDK exceptions, addresses or credentials cross this boundary."""


class BrokerRejected(BrokerUnavailable):
    """The venue explicitly rejected a write."""


class NativeBroker(Protocol):
    network: str
    scope: str

    async def snapshot(self, since_ms: int) -> AccountSnapshot: ...
    async def order(self, cloid: str) -> NativeOrder | None: ...
    async def submit(self, request: NativeRequest) -> None: ...
    async def cancel(self, order: NativeOrder) -> None: ...
    async def book(self, symbol: str) -> Book: ...
    async def rules(self, symbol: str) -> Rules: ...
    async def close(self) -> None: ...
