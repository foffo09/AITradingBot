from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
    paper_max_daily_orders: int = 5
    log_level: str = "INFO"
    allowed_market_hours_only: bool = True
    slippage_bps: float = 5.0
    spread_bps: float = 0.0
    commission_bps: float = 5.0
    paper_trading_enabled: bool = True
    paper_execution_scope: str = "disabled"
    paper_coordinator_directory: str | None = None

    def __post_init__(self) -> None:
        self.trading_mode = (self.trading_mode or "paper").strip().lower()
        self.alpaca_api_key = _normalize_optional_string(self.alpaca_api_key)
        self.alpaca_secret_key = _normalize_optional_string(self.alpaca_secret_key)
        self.base_currency = (self.base_currency or "USD").strip().upper()
        self.log_level = (self.log_level or "INFO").strip().upper()

        if (not self.alpaca_api_key or not self.alpaca_secret_key) and self.trading_mode == "paper":
            self.trading_mode = "demo"
            self.paper_trading_enabled = True
            self.auto_trade_enabled = False

        if not self._is_finite(self.initial_capital_eur) or self.initial_capital_eur <= 0:
            raise ValueError("Initial capital must be a finite positive number.")
        if not self._is_finite(self.eur_usd_rate) or self.eur_usd_rate <= 0:
            raise ValueError("EUR/USD rate must be a finite positive number.")
        self.initial_capital_usd = self.initial_capital_eur * self.eur_usd_rate
        self.validate()

    def __repr__(self) -> str:
        return (
            "AppSettings("
            f"trading_mode={self.trading_mode!r}, "
            f"auto_trade_enabled={self.auto_trade_enabled!r}, "
            "alpaca_api_key=<redacted>, "
            "alpaca_secret_key=<redacted>, "
            f"base_currency={self.base_currency!r}, "
            f"initial_capital_eur={self.initial_capital_eur!r}, "
            f"eur_usd_rate={self.eur_usd_rate!r}, "
            f"initial_capital_usd={self.initial_capital_usd!r}, "
            f"short_window={self.short_window!r}, "
            f"long_window={self.long_window!r}, "
            f"risk_max_trade_fraction={self.risk_max_trade_fraction!r}, "
            f"risk_max_exposure_fraction={self.risk_max_exposure_fraction!r}, "
            f"daily_loss_limit_pct={self.daily_loss_limit_pct!r}, "
            f"max_positions={self.max_positions!r}, "
            f"paper_max_daily_orders={self.paper_max_daily_orders!r}, "
            f"log_level={self.log_level!r}, "
            f"allowed_market_hours_only={self.allowed_market_hours_only!r}, "
            f"slippage_bps={self.slippage_bps!r}, "
            f"spread_bps={self.spread_bps!r}, "
            f"commission_bps={self.commission_bps!r}, "
            f"paper_trading_enabled={self.paper_trading_enabled!r})"
        )

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "AppSettings":
        path = Path(env_path) if env_path is not None else DEFAULT_ENV_PATH
        explicit_demo_mode = (os.getenv("TRADING_MODE") or "").strip().lower() == "demo"
        if not explicit_demo_mode:
            load_dotenv(path, override=False)

        mode = (os.getenv("TRADING_MODE") or "paper").strip().lower()
        if mode not in {"demo", "paper", "live"}:
            mode = "paper"

        api_key = _normalize_optional_string(os.getenv("ALPACA_API_KEY"))
        secret_key = _normalize_optional_string(os.getenv("ALPACA_SECRET_KEY"))

        if mode == "live":
            mode = "demo"

        settings = cls(
            trading_mode=mode,
            auto_trade_enabled=False,
            alpaca_api_key=api_key,
            alpaca_secret_key=secret_key,
            base_currency=_normalize_optional_string(os.getenv("BASE_CURRENCY")) or "USD",
            initial_capital_eur=float(os.getenv("INITIAL_CAPITAL_EUR", "100.0")),
            eur_usd_rate=float(os.getenv("EUR_USD_RATE", "1.09")),
            short_window=int(os.getenv("SHORT_WINDOW", "10")),
            long_window=int(os.getenv("LONG_WINDOW", "30")),
            risk_max_trade_fraction=float(os.getenv("RISK_MAX_TRADE_FRACTION", "0.20")),
            risk_max_exposure_fraction=float(os.getenv("RISK_MAX_EXPOSURE_FRACTION", "0.50")),
            daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.05")),
            max_positions=int(os.getenv("MAX_POSITIONS", "3")),
            paper_max_daily_orders=int(os.getenv("PAPER_MAX_DAILY_ORDERS", "5")),
            log_level=(_normalize_optional_string(os.getenv("LOG_LEVEL")) or "INFO").upper(),
            allowed_market_hours_only=os.getenv("ALLOWED_MARKET_HOURS_ONLY", "true").strip().lower() != "false",
            slippage_bps=float(os.getenv("SLIPPAGE_BPS", "5.0")),
            spread_bps=float(os.getenv("SPREAD_BPS", "0.0")),
            commission_bps=float(os.getenv("COMMISSION_BPS", "5.0")),
            paper_trading_enabled=mode in {"paper", "demo"},
            paper_execution_scope=os.getenv("PAPER_EXECUTION_SCOPE", "disabled"),
            paper_coordinator_directory=_normalize_optional_string(os.getenv("PAPER_COORDINATOR_DIRECTORY")),
        )

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            settings.trading_mode = "demo"
            settings.paper_trading_enabled = True
            settings.auto_trade_enabled = False

        return settings

    def validate(self) -> None:
        if self.paper_execution_scope not in {"disabled", "single_host"}:
            raise ValueError("Paper execution scope must be disabled or single_host; distributed execution is unsupported.")
        if self.paper_execution_scope == "single_host" and (
            not self.paper_coordinator_directory or not Path(self.paper_coordinator_directory).is_absolute()
        ):
            raise ValueError("Single-host Paper execution requires an absolute shared coordinator directory.")
        if self.trading_mode not in {"demo", "paper", "live"}:
            raise ValueError("trading_mode must be one of: demo, paper, live")

        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("Moving average windows must be positive integers.")
        if self.short_window >= self.long_window:
            raise ValueError("Short window must be smaller than long window.")

        if not self._is_finite(self.initial_capital_eur) or self.initial_capital_eur <= 0:
            raise ValueError("Initial capital must be positive.")
        if not self._is_finite(self.eur_usd_rate) or self.eur_usd_rate <= 0:
            raise ValueError("EUR/USD rate must be positive.")
        if not self._is_finite(self.initial_capital_usd) or self.initial_capital_usd <= 0:
            raise ValueError("Initial USD capital must be finite and positive.")
        if not self._is_finite(self.risk_max_trade_fraction) or not 0 < self.risk_max_trade_fraction <= 1:
            raise ValueError("Max trade fraction must be between 0 and 1.")
        if not self._is_finite(self.risk_max_exposure_fraction) or not 0 < self.risk_max_exposure_fraction <= 1:
            raise ValueError("Max exposure fraction must be between 0 and 1.")
        if not self._is_finite(self.daily_loss_limit_pct) or not 0 <= self.daily_loss_limit_pct <= 1:
            raise ValueError("Daily loss limit must be within 0 and 1.")
        for label, bps in (
            ("commission", self.commission_bps),
            ("spread", self.spread_bps),
            ("slippage", self.slippage_bps),
        ):
            if not self._is_finite(bps) or not 0 <= bps <= 1000:
                raise ValueError(f"{label.title()} must be between 0 and 1000 bps.")
        if self.max_positions <= 0:
            raise ValueError("Max positions must be positive.")
        if not 1 <= self.paper_max_daily_orders <= 100:
            raise ValueError("Paper maximum daily orders must be between 1 and 100.")

        if self.trading_mode == "live":
            raise ValueError("Live trading is not supported in this application. Use paper or demo mode only.")

    @staticmethod
    def _is_finite(value: float) -> bool:
        try:
            return math.isfinite(value)
        except (TypeError, ValueError, OverflowError):
            return False

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
            "paper_max_daily_orders": self.paper_max_daily_orders,
            "paper_trading_enabled": self.paper_trading_enabled,
        }
