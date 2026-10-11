from __future__ import annotations

import math
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

    @staticmethod
    def _finite_number(value: float, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RiskViolationError(f"{label} must be a finite number.") from exc
        if not math.isfinite(number):
            raise RiskViolationError(f"{label} must be a finite number.")
        return number

    def _initial_capital(self) -> float:
        capital = self._finite_number(self.settings.initial_capital_usd, "Initial capital")
        if capital <= 0:
            raise RiskViolationError("Initial capital must be positive.")
        return capital

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
        pnl_today: float = 0.0,
    ) -> OrderValidationResult:
        self._ensure_paper_mode()

        normalized_side = str(side).lower()
        if normalized_side not in {"buy", "sell"}:
            raise RiskViolationError("Order side must be 'buy' or 'sell'.")

        quantity = self._finite_number(quantity, "Order quantity")
        price = self._finite_number(price, "Order price")
        available_cash = self._finite_number(available_cash, "Available cash")
        current_position = self._finite_number(current_position, "Current position")
        pnl_today = self._finite_number(pnl_today, "Today's P/L")
        if quantity <= 0:
            raise RiskViolationError("Order quantity must be positive.")
        if price <= 0:
            raise RiskViolationError("Order price must be positive.")
        if available_cash < 0:
            raise RiskViolationError("Available cash cannot be negative.")
        if current_position < 0:
            raise RiskViolationError("Current position cannot be negative; short positions are not supported.")

        capital = self._initial_capital()
        configured_trade_fraction = self.settings.risk_max_trade_fraction
        max_trade_fraction = (
            configured_trade_fraction if max_trade_fraction is None else max_trade_fraction
        )
        max_trade_fraction = self._finite_number(max_trade_fraction, "Risk trade fraction")
        if not 0 < max_trade_fraction <= 1:
            raise RiskViolationError("Risk trade fraction must be between 0 and 1.")

        order_value = quantity * price
        if not math.isfinite(order_value) or order_value <= 0:
            raise RiskViolationError("Order notional must be finite and positive.")

        if normalized_side == "buy":
            max_trade_value = capital * max_trade_fraction
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
            if not math.isfinite(exposure_value):
                raise RiskViolationError("Projected exposure must be finite.")
            max_exposure_fraction = self._finite_number(
                self.settings.risk_max_exposure_fraction, "Maximum exposure fraction"
            )
            if not 0 < max_exposure_fraction <= 1:
                raise RiskViolationError("Risk exposure fraction must be between 0 and 1.")
            max_exposure = capital * max_exposure_fraction
            if exposure_value > max_exposure:
                return OrderValidationResult(
                    ok=False,
                    quantity=quantity,
                    notional=order_value,
                    reason=f"Exposure {exposure_value:.2f} exceeds max exposure {max_exposure:.2f} USD.",
                    blocked_by="max_exposure_fraction",
                )

            if not self.check_daily_loss_limit(pnl_today):
                return OrderValidationResult(
                    ok=False,
                    quantity=quantity,
                    notional=order_value,
                    reason="Daily loss limit reached; new buy orders are blocked.",
                    blocked_by="daily_loss_limit",
                )
        elif quantity > current_position:
            return OrderValidationResult(
                ok=False,
                quantity=quantity,
                notional=order_value,
                reason="Sell quantity exceeds the open long position; short selling is disabled.",
                blocked_by="position",
            )
        else:
            remaining_exposure = (current_position - quantity) * price
            if not math.isfinite(remaining_exposure) or remaining_exposure < 0:
                raise RiskViolationError("Projected exposure after sale must be finite and non-negative.")

        symbol = symbol or "UNKNOWN"
        return OrderValidationResult(
            ok=True,
            quantity=quantity,
            notional=order_value,
            reason=f"{normalized_side.upper()} {quantity} {symbol}",
        )

    def calculate_position_size(self, cash_available: float, price: float, max_fraction: float | None = None) -> float:
        cash_available = self._finite_number(cash_available, "Available cash")
        price = self._finite_number(price, "Order price")
        if cash_available < 0:
            raise RiskViolationError("Available cash cannot be negative.")
        if price <= 0:
            raise RiskViolationError("Order price must be positive.")
        trade_fraction = self._finite_number(
            self.settings.risk_max_trade_fraction if max_fraction is None else max_fraction,
            "Risk trade fraction",
        )
        if not 0 < trade_fraction <= 1:
            raise RiskViolationError("Risk trade fraction must be between 0 and 1.")
        max_trade_value = self._initial_capital() * trade_fraction
        allowed_value = min(cash_available, max_trade_value)
        return allowed_value / price

    def check_daily_loss_limit(self, pnl_today: float) -> bool:
        pnl_today = self._finite_number(pnl_today, "Today's P/L")
        capital = self._initial_capital()
        loss_fraction = self._finite_number(
            self.settings.daily_loss_limit_pct, "Daily loss limit fraction"
        )
        if not 0 <= loss_fraction <= 1:
            raise RiskViolationError("Daily loss limit fraction must be between 0 and 1.")
        if loss_fraction == 0:
            return pnl_today >= 0
        max_loss = capital * loss_fraction
        return pnl_today > -max_loss

    def compute_drawdown(self, equity_curve: list[float]) -> dict[str, float]:
        if not equity_curve:
            return {"max_drawdown": 0.0, "peak": 0.0, "trough": 0.0}

        values = [self._finite_number(value, "Equity value") for value in equity_curve]
        if any(value < 0 for value in values):
            raise RiskViolationError("Equity values cannot be negative.")

        peak = values[0]
        max_drawdown = 0.0
        trough = values[0]

        for value in values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                trough = value

        return {"max_drawdown": round(max_drawdown * 100, 2), "peak": peak, "trough": trough}
