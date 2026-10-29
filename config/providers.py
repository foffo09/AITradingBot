from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, get_args
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ProviderSettings(BaseModel):
    model_config = ConfigDict(alias_generator=str.upper, populate_by_name=True, extra="ignore",
                              hide_input_in_errors=True, allow_inf_nan=False)

    omega_data_mode: Literal["live", "synthetic"] = "live"
    omega_enable_native_orders: bool = False
    omega_enable_live_orders: bool = False
    quote_max_age_seconds: float = Field(default=60, gt=0, le=300)
    request_timeout_seconds: float = Field(default=8, gt=0, le=60)
    crypto_provider: Literal["hyperliquid", "binance", "bybit"] = "hyperliquid"
    crypto_data_network: Literal["mainnet", "testnet"] = "mainnet"
    crypto_execution_network: Literal["mainnet", "testnet"] = "testnet"
    hyperliquid_coin: str = "BTC"
    hyperliquid_private_key: SecretStr | None = None
    hyperliquid_account_address: SecretStr | None = None
    ccxt_symbol: str = "BTC/USDT:USDT"
    binance_api_key: SecretStr | None = None
    binance_secret_key: SecretStr | None = None
    bybit_api_key: SecretStr | None = None
    bybit_secret_key: SecretStr | None = None
    solana_rpc_url: SecretStr | None = None
    solana_ws_url: SecretStr | None = None
    helius_api_key: SecretStr | None = None
    quicknode_rpc_url: SecretStr | None = None
    quicknode_ws_url: SecretStr | None = None
    solana_token_mint: str = "So11111111111111111111111111111111111111112"
    jupiter_api_key: SecretStr | None = None
    jupiter_base_url: str = "https://api.jup.ag/swap/v1"
    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_paper: bool = True
    options_symbol: str = ""
    options_underlying: str = "SPY"
    biotech_symbol: str = "MRNA"
    futures_yahoo_symbol: str = "CL=F"
    ib_enabled: bool = False
    ib_host: str = "127.0.0.1"
    ib_port: int = Field(default=7497, gt=0, le=65535)
    ib_client_id: int = Field(default=17, ge=0)
    ib_account: SecretStr | None = None
    ib_futures_symbol: str = "CL"
    ib_futures_expiry: str = ""
    ib_futures_exchange: str = "NYMEX"
    polygon_api_key: SecretStr | None = None
    polygon_base_url: str = "https://api.polygon.io"
    finnhub_api_key: SecretStr | None = None
    ai_provider: Literal["auto", "openai", "anthropic", "ollama", "none"] = "auto"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.5"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""

    @field_validator("solana_rpc_url", "solana_ws_url", "quicknode_rpc_url", "quicknode_ws_url", mode="before")
    @classmethod
    def validate_rpc_url(cls, value):
        if value is None or value == "":
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        parsed = urlparse(raw)
        allowed = parsed.scheme in {"https", "wss"} or (parsed.scheme in {"http", "ws"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        if not allowed or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Secure RPC URL required except for loopback")
        return raw

    @field_validator("jupiter_base_url", "polygon_base_url", "ollama_base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("HTTPS required except for loopback services")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid service base URL")
        return value.rstrip("/")

    @classmethod
    def from_env(cls, path: Path | None = None) -> ProviderSettings:
        path = path or Path(__file__).resolve().parent.parent / ".env"
        names = {name.upper() for name in cls.model_fields}
        secret_names = {name.upper() for name, field in cls.model_fields.items()
                        if field.annotation is SecretStr or SecretStr in get_args(field.annotation)}
        values = {key: value for key, value in dotenv_values(path, interpolate=False).items()
                  if key in names - secret_names and value not in {None, ""}}
        values.update({key: value for key, value in os.environ.items() if key in names and value != ""})
        return cls.model_validate(values)

    def secret(self, name: str) -> str | None:
        value = getattr(self, name)
        return value.get_secret_value() if value else None

    def rpc_endpoints(self) -> list[tuple[str, str, str]]:
        endpoints = []
        if self.solana_rpc_url:
            http = self.secret("solana_rpc_url")
            endpoints.append(("solana_custom", http, self.secret("solana_ws_url") or http.replace("https://", "wss://").replace("http://", "ws://")))
        if self.helius_api_key:
            key = self.secret("helius_api_key")
            endpoints.append(("helius", f"https://mainnet.helius-rpc.com/?api-key={key}", f"wss://mainnet.helius-rpc.com/?api-key={key}"))
        if self.quicknode_rpc_url:
            http = self.secret("quicknode_rpc_url")
            endpoints.append(("quicknode", http, self.secret("quicknode_ws_url") or http.replace("https://", "wss://")))
        endpoints.append(("solana_public", "https://api.mainnet.solana.com", "wss://api.mainnet.solana.com"))
        return endpoints

    def ai_backend(self) -> str:
        if self.ai_provider != "auto":
            return self.ai_provider
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "ollama" if self.ollama_model else "none"
