from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass
class AppSettings:
    """Centralized runtime configuration for the trading app."""

    trading_mode: str = "paper"
    auto_trade_enabled: bool = False
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    base_currency: str = "USD"
    initial_capital_eur: float = 100.0
    eur_usd_rate: float = 1.09
    initial_capital_usd: float = field(init=False)
    short_window: int = 10
    long_window: int = 30
    risk_max_trade_fraction: float = 0.20
    risk_max_exposure_fraction: float = 0.50
    daily_loss_limit_pct: float = 0.05
    max_positions: int = 3
    log_level: str = "INFO"
    allowed_market_hours_only: bool = True
    slippage_bps: float = 5.0
    spread_bps: float = 0.0
    commission_bps: float = 5.0
    paper_trading_enabled: bool = True

    def __post_init__(self) -> None:
        if (not self.alpaca_api_key or not self.alpaca_secret_key) and self.trading_mode == "paper":
            self.trading_mode = "demo"
            self.paper_trading_enabled = True
            self.auto_trade_enabled = False

        self.initial_capital_usd = self.initial_capital_eur * self.eur_usd_rate
        self.validate()

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "AppSettings":
        path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
        load_dotenv(path, override=False)

        mode = (os.getenv("TRADING_MODE") or "paper").strip().lower()
        if mode not in {"demo", "paper", "live"}:
            mode = "paper"

        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")

        if mode == "live":
            mode = "demo"

        settings = cls(
            trading_mode=mode,
            auto_trade_enabled=False,
            alpaca_api_key=api_key,
            alpaca_secret_key=secret_key,
            base_currency=os.getenv("BASE_CURRENCY", "USD").upper(),
            initial_capital_eur=float(os.getenv("INITIAL_CAPITAL_EUR", "100.0")),
            eur_usd_rate=float(os.getenv("EUR_USD_RATE", "1.09")),
            short_window=int(os.getenv("SHORT_WINDOW", "10")),
            long_window=int(os.getenv("LONG_WINDOW", "30")),
            risk_max_trade_fraction=float(os.getenv("RISK_MAX_TRADE_FRACTION", "0.20")),
            risk_max_exposure_fraction=float(os.getenv("RISK_MAX_EXPOSURE_FRACTION", "0.50")),
            daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.05")),
            max_positions=int(os.getenv("MAX_POSITIONS", "3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            allowed_market_hours_only=os.getenv("ALLOWED_MARKET_HOURS_ONLY", "true").strip().lower() != "false",
            slippage_bps=float(os.getenv("SLIPPAGE_BPS", "5.0")),
            spread_bps=float(os.getenv("SPREAD_BPS", "0.0")),
            commission_bps=float(os.getenv("COMMISSION_BPS", "5.0")),
            paper_trading_enabled=mode in {"paper", "demo"},
        )

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            settings.trading_mode = "demo"
            settings.paper_trading_enabled = True
            settings.auto_trade_enabled = False

        return settings

    def validate(self) -> None:
        if self.trading_mode not in {"demo", "paper", "live"}:
            raise ValueError("trading_mode must be one of: demo, paper, live")

        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("Moving average windows must be positive integers.")
        if self.short_window >= self.long_window:
            raise ValueError("Short window must be smaller than long window.")

        if not math.isfinite(self.initial_capital_eur) or self.initial_capital_eur <= 0:
            raise ValueError("Initial capital must be positive.")
        if not math.isfinite(self.eur_usd_rate) or self.eur_usd_rate <= 0:
            raise ValueError("EUR/USD rate must be positive.")
        if not 0 < self.risk_max_trade_fraction <= 1:
            raise ValueError("Max trade fraction must be between 0 and 1.")
        if not 0 < self.risk_max_exposure_fraction <= 1:
            raise ValueError("Max exposure fraction must be between 0 and 1.")
        if not 0 <= self.daily_loss_limit_pct <= 1:
            raise ValueError("Daily loss limit must be within 0 and 1.")
        for label, bps in (
            ("commission", self.commission_bps),
            ("spread", self.spread_bps),
            ("slippage", self.slippage_bps),
        ):
            if not math.isfinite(bps) or not 0 <= bps <= 1000:
                raise ValueError(f"{label.title()} must be between 0 and 1000 bps.")
        if self.max_positions <= 0:
            raise ValueError("Max positions must be positive.")

        if self.trading_mode == "live":
            raise ValueError("Live trading is not supported in this application. Use paper or demo mode only.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_mode": self.trading_mode,
            "auto_trade_enabled": self.auto_trade_enabled,
            "alpaca_api_key_configured": bool(self.alpaca_api_key and self.alpaca_secret_key),
            "base_currency": self.base_currency,
            "initial_capital_eur": self.initial_capital_eur,
            "initial_capital_usd": self.initial_capital_usd,
            "short_window": self.short_window,
            "long_window": self.long_window,
            "risk_max_trade_fraction": self.risk_max_trade_fraction,
            "risk_max_exposure_fraction": self.risk_max_exposure_fraction,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_positions": self.max_positions,
            "paper_trading_enabled": self.paper_trading_enabled,
        }
