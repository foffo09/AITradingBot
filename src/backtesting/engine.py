from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field

import pandas as pd

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager
from src.strategy.moving_average import MovingAverageStrategy


@dataclass
class BacktestResult:
    initial_capital: float
    final_capital: float
    return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown_pct: float
    fees_paid: float
    equity_curve: list[float]
    slippage_paid: float = 0.0
    open_position_quantity: float = 0.0
    trade_history: list[dict[str, object]] = field(default_factory=list)
    spread_paid: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BacktestEngine:
    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings.from_env()
        self.risk_manager = RiskManager(self.settings)

    def run(
        self,
        data: pd.DataFrame,
        *,
        short_window: int | None = None,
        long_window: int | None = None,
        initial_capital: float | None = None,
        max_trade_fraction: float | None = None,
        daily_loss_limit_fraction: float | None = None,
        commission_bps: float | None = None,
        spread_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> BacktestResult:
        if data.empty:
            raise ValueError("Backtest data is empty.")
        if "open" not in data.columns or "close" not in data.columns:
            raise ValueError("Backtest data must contain open and close prices.")

        strategy = MovingAverageStrategy(
            short_window=short_window or self.settings.short_window,
            long_window=long_window or self.settings.long_window,
        )
        signals = strategy.generate_signals(data.copy()).reset_index(drop=True)

        starting_cash = float(initial_capital if initial_capital is not None else self.settings.initial_capital_usd)
        if not math.isfinite(starting_cash) or starting_cash <= 0:
            raise ValueError("Initial backtest capital must be positive.")
        prices = data[["open", "close"]].apply(pd.to_numeric, errors="coerce")
        if prices.isna().any().any() or (prices <= 0).any().any():
            raise ValueError("Backtest open and close prices must be present and positive.")
        trade_fraction = max_trade_fraction if max_trade_fraction is not None else self.settings.risk_max_trade_fraction
        loss_fraction = daily_loss_limit_fraction if daily_loss_limit_fraction is not None else self.settings.daily_loss_limit_pct
        commission_rate = (commission_bps if commission_bps is not None else self.settings.commission_bps) / 10_000
        spread_rate_bps = spread_bps if spread_bps is not None else self.settings.spread_bps
        slippage_rate_bps = slippage_bps if slippage_bps is not None else self.settings.slippage_bps
        if not 0 < trade_fraction <= 1 or not 0 <= loss_fraction <= 1:
            raise ValueError("Backtest risk fractions are outside their valid range.")
        if any(not math.isfinite(value) or not 0 <= value <= 1000 for value in (
            commission_rate * 10_000, spread_rate_bps, slippage_rate_bps
        )):
            raise ValueError("Backtest costs must be between 0 and 1000 bps.")
        cash = starting_cash
        position_qty = 0.0
        entry_fill = 0.0
        entry_fee = 0.0
        fees_paid = 0.0
        slippage_paid = 0.0
        spread_paid = 0.0
        equity_curve = [cash]
        winning_trades = 0
        losing_trades = 0
        total_trades = 0
        trade_history: list[dict[str, object]] = []
        open_trade: dict[str, object] | None = None
        slippage_rate = slippage_rate_bps / 10_000
        half_spread_rate = spread_rate_bps / 20_000
        daily_start_equity = starting_cash
        previous_day = None

        # Signal on bar i-1 is only actionable at the next available bar's open.
        for index in range(1, len(signals)):
            signal = int(signals.iloc[index - 1]["signal"])
            execution_price = float(signals.iloc[index]["open"])
            if not pd.notna(execution_price) or execution_price <= 0:
                equity_curve.append(cash + position_qty * float(signals.iloc[index - 1]["close"]))
                continue

            timestamp = signals.iloc[index].get("timestamp", index)
            current_day = pd.Timestamp(timestamp).date() if not isinstance(timestamp, int) else index
            if previous_day is not None and current_day != previous_day:
                daily_start_equity = cash + position_qty * float(signals.iloc[index - 1]["close"])
            previous_day = current_day
            equity_at_open = cash + position_qty * execution_price
            daily_pnl = equity_at_open - daily_start_equity
            daily_loss_reached = (
                daily_pnl < 0 if loss_fraction == 0
                else daily_pnl <= -daily_start_equity * loss_fraction
            )

            if signal == 1 and position_qty == 0:
                buy_fill = execution_price * (1 + half_spread_rate + slippage_rate)
                max_notional = starting_cash * trade_fraction
                quantity = min(cash, max_notional) / (buy_fill * (1 + commission_rate))
                if quantity <= 0:
                    equity_curve.append(cash + position_qty * float(signals.iloc[index]["close"]))
                    continue
                notional = quantity * buy_fill
                entry_fee = notional * commission_rate
                entry_spread = quantity * execution_price * half_spread_rate
                entry_slippage = quantity * execution_price * slippage_rate
                if daily_loss_reached or notional + entry_fee > cash:
                    equity_curve.append(cash + position_qty * float(signals.iloc[index]["close"]))
                    continue
                cash -= notional + entry_fee
                position_qty = quantity
                entry_fill = buy_fill
                fees_paid += entry_fee
                slippage_paid += entry_slippage
                spread_paid += entry_spread
                entry_timestamp = signals.iloc[index].get("timestamp", index)
                open_trade = {
                    "id": f"backtest-{len(trade_history) + 1}",
                    "symbol": str(signals.iloc[index].get("symbol", "")),
                    "opened_at": str(entry_timestamp),
                    "direction": "long",
                    "quantity": quantity,
                    "entry_price": buy_fill,
                    "entry_fee": entry_fee,
                    "entry_spread": entry_spread,
                    "entry_slippage": entry_slippage,
                    "entry_reason": str(signals.iloc[index - 1]["signal_reason"]),
                    "status": "open",
                }
            elif signal == -1 and position_qty > 0:
                sell_fill = execution_price * (1 - half_spread_rate - slippage_rate)
                exit_value = position_qty * sell_fill
                sell_fee = exit_value * commission_rate
                sell_spread = position_qty * execution_price * half_spread_rate
                sell_slippage = position_qty * execution_price * slippage_rate
                pnl = position_qty * (sell_fill - entry_fill) - entry_fee - sell_fee
                fees_paid += sell_fee
                slippage_paid += sell_slippage
                spread_paid += sell_spread
                if open_trade is not None:
                    trade_history.append({
                        **open_trade,
                        "closed_at": str(signals.iloc[index].get("timestamp", index)),
                        "exit_price": sell_fill,
                        "exit_fee": sell_fee,
                        "exit_spread": sell_spread,
                        "exit_slippage": sell_slippage,
                        "gross_pnl": position_qty * (sell_fill - entry_fill),
                        "net_pnl": pnl,
                        "exit_reason": str(signals.iloc[index - 1]["signal_reason"]),
                        "status": "closed",
                    })
                if pnl > 0:
                    winning_trades += 1
                elif pnl < 0:
                    losing_trades += 1
                cash += exit_value - sell_fee
                position_qty = 0.0
                entry_fee = 0.0
                open_trade = None
                total_trades += 1

            current_equity = cash + (position_qty * float(signals.iloc[index]["close"]))
            equity_curve.append(current_equity)

        if position_qty > 0 and open_trade is not None:
            trade_history.append({
                **open_trade,
                "exit_price": None,
                "gross_pnl": None,
                "net_pnl": None,
                "exit_reason": None,
                "status": "open",
            })

        final_capital = equity_curve[-1]
        return_pct = ((final_capital - starting_cash) / starting_cash) * 100
        drawdown = self.risk_manager.compute_drawdown(equity_curve)
        win_rate = (winning_trades / (winning_trades + losing_trades)) * 100 if (winning_trades + losing_trades) else 0.0

        return BacktestResult(
            initial_capital=starting_cash,
            final_capital=final_capital,
            return_pct=return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            max_drawdown_pct=drawdown["max_drawdown"],
            fees_paid=fees_paid,
            equity_curve=equity_curve,
            slippage_paid=slippage_paid,
            open_position_quantity=position_qty,
            trade_history=trade_history,
            spread_paid=spread_paid,
        )
