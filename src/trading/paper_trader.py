from __future__ import annotations

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager, RiskViolationError


class PaperTrader:
    """Protected simulated broker wrapper used for paper trading and demos."""

    def __init__(self, settings: AppSettings | None = None, risk_manager: RiskManager | None = None):
        self.settings = settings or AppSettings.from_env()
        self.risk_manager = risk_manager or RiskManager(self.settings)

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        available_cash: float,
        current_position: float = 0.0,
        pnl_today: float = 0.0,
    ) -> dict[str, object]:
        if self.settings.trading_mode not in {"paper", "demo"}:
            raise PermissionError("Only demo/paper mode is allowed in this bot.")
        if not self.settings.paper_trading_enabled and self.settings.trading_mode != "demo":
            raise PermissionError("Paper trading is disabled. Enable it from the dashboard or configuration.")

        result = self.risk_manager.validate_order(
            side=side,
            quantity=quantity,
            price=price,
            available_cash=available_cash,
            current_position=current_position,
            symbol=symbol,
            pnl_today=pnl_today,
        )
        if not result.ok:
            raise RiskViolationError(result.reason)

        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": "simulated",
            "mode": self.settings.trading_mode,
        }
