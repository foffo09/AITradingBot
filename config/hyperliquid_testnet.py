"""Environment-only credentials for the native testnet runner."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TestnetRisk(BaseModel):
    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)
    network: Literal["testnet"] = "testnet"
    symbol: str = Field(default="BTC", pattern=r"^[A-Z0-9]{2,10}$")
    max_order_usd: Decimal = Field(default=Decimal("25"), ge=10, le=1000)
    max_equity_fraction: Decimal = Field(default=Decimal("0.04"), gt=0, le=Decimal("0.04"))
    stop_fraction: Decimal = Field(default=Decimal("0.015"), gt=0, le=Decimal("0.015"))
    quote_max_age: float = Field(default=5, gt=0, le=10)


class TestnetSettings(TestnetRisk):
    private_key: SecretStr = Field(repr=False)
    account_address: SecretStr = Field(repr=False)
    timeout: float = Field(default=8, gt=0, le=30)

    @classmethod
    def from_env(cls) -> TestnetSettings:
        # Deliberately no dotenv loading: secret-bearing files are not an input.
        if os.environ.get("CRYPTO_EXECUTION_NETWORK", "testnet") != "testnet":
            raise ValueError("Mainnet execution is prohibited")
        return cls(
            network=os.environ.get("HL_TESTNET_NETWORK", "testnet"),
            private_key=SecretStr(os.environ.get("HYPERLIQUID_PRIVATE_KEY", "")),
            account_address=SecretStr(os.environ.get("HYPERLIQUID_ACCOUNT_ADDRESS", "")),
            symbol=os.environ.get("HYPERLIQUID_COIN", "BTC"),
            max_order_usd=os.environ.get("HL_TESTNET_MAX_ORDER_USD", "25"),
        )
