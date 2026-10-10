from __future__ import annotations

from dataclasses import dataclass

from config.settings import AppSettings


class RiskViolationError(ValueError):
    """Raised when an order violates configured risk limits."""


@dataclass
class OrderValidationResult:
    ok: bool
    quantity: float
    notional: float
    reason: str = ""
    blocked_by: str = ""


class RiskManager:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    def _ensure_paper_mode(self) -> None:
        if not self.settings.paper_trading_enabled:
            raise RiskViolationError("Paper trading must be enabled before sending any simulated order.")

    def validate_order(
        self,
        *,
        side: str,
        quantity: float,
        price: float,
        available_cash: float,
        current_position: float = 0.0,
        symbol: str = "",
        max_trade_fraction: float | None = None,
    ) -> OrderValidationResult:
        self._ensure_paper_mode()

        normalized_side = str(side).lower()
        if normalized_side not in {"buy", "sell"}:
            raise RiskViolationError("Order side must be 'buy' or 'sell'.")

        if quantity <= 0:
            raise RiskViolationError("Order quantity must be positive.")
        if price <= 0:
            raise RiskViolationError("Order price must be positive.")

        max_trade_fraction = max_trade_fraction if max_trade_fraction is not None else self.settings.risk_max_trade_fraction
        if not 0 < max_trade_fraction <= 1:
            raise RiskViolationError("Risk trade fraction must be between 0 and 1.")

        order_value = quantity * price
        max_trade_value = self.settings.initial_capital_usd * max_trade_fraction
        if order_value > max_trade_value:
            return OrderValidationResult(
                ok=False,
                quantity=quantity,
                notional=order_value,
                reason=f"Order value {order_value:.2f} exceeds max trade cap {max_trade_value:.2f} USD.",
                blocked_by="max_trade_fraction",
            )

        if available_cash < order_value:
            return OrderValidationResult(
                ok=False,
                quantity=quantity,
                notional=order_value,
                reason=f"Available cash {available_cash:.2f} is lower than order value {order_value:.2f}.",
                blocked_by="cash",
            )

        exposure_value = (current_position + quantity) * price
        max_exposure = self.settings.initial_capital_usd * self.settings.risk_max_exposure_fraction
        if exposure_value > max_exposure:
            return OrderValidationResult(
                ok=False,
                quantity=quantity,
                notional=exposure_value,
                reason=f"Exposure {exposure_value:.2f} exceeds max exposure {max_exposure:.2f} USD.",
                blocked_by="max_exposure_fraction",
            )

        if not symbol:
            symbol = "UNKNOWN"

        return OrderValidationResult(ok=True, quantity=quantity, notional=order_value, reason=f"{side.upper()} {quantity} {symbol}", blocked_by="")

    def calculate_position_size(self, cash_available: float, price: float, max_fraction: float | None = None) -> float:
        if cash_available <= 0 or price <= 0:
            return 0.0
        trade_fraction = max_fraction if max_fraction is not None else self.settings.risk_max_trade_fraction
        max_trade_value = self.settings.initial_capital_usd * trade_fraction
        allowed_value = min(cash_available, max_trade_value)
        return max(0.0, allowed_value / price)

    def check_daily_loss_limit(self, pnl_today: float) -> bool:
        max_loss = self.settings.initial_capital_usd * self.settings.daily_loss_limit_pct
        return pnl_today > -max_loss

    def compute_drawdown(self, equity_curve: list[float]) -> dict[str, float]:
        if not equity_curve:
            return {"max_drawdown": 0.0, "peak": 0.0, "trough": 0.0}

        peak = equity_curve[0]
        max_drawdown = 0.0
        trough = equity_curve[0]

        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                trough = value

        return {"max_drawdown": round(max_drawdown * 100, 2), "peak": peak, "trough": trough}
