from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict, field
from numbers import Integral

import numpy as np
import pandas as pd

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager
from src.strategy.moving_average import MovingAverageStrategy


def backtest_input_key(
    data: pd.DataFrame,
    *,
    source: str,
    parameters: dict[str, object],
) -> str:
    metadata = json.dumps(
        {"source": source, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    frame_hash = pd.util.hash_pandas_object(data, index=True).values.tobytes()
    columns = json.dumps(
        [(str(column), str(dtype)) for column, dtype in zip(data.columns, data.dtypes)],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(metadata + columns + frame_hash).hexdigest()


@dataclass
class BacktestResult:
    initial_capital: float
    final_capital: float
    return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    max_drawdown_pct: float
    fees_paid: float
    equity_curve: list[float]
    slippage_paid: float = 0.0
    open_position_quantity: float = 0.0
    trade_history: list[dict[str, object]] = field(default_factory=list)
    spread_paid: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    unrealized_gross_pnl: float = 0.0
    unrealized_net_pnl: float = 0.0
    estimated_liquidation_costs: float = 0.0
    total_transaction_costs: float = 0.0
    annualized_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    periods_per_year: int | None = None
    risk_free_rate_annual: float = 0.0
    benchmark_final_capital: float = 0.0
    benchmark_return_pct: float = 0.0
    benchmark_max_drawdown_pct: float = 0.0
    benchmark_fees_paid: float = 0.0
    benchmark_spread_paid: float = 0.0
    benchmark_slippage_paid: float = 0.0
    benchmark_estimated_liquidation_costs: float = 0.0
    benchmark_total_transaction_costs: float = 0.0
    benchmark_annualized_volatility_pct: float | None = None
    benchmark_sharpe_ratio: float | None = None
    average_profit_per_trade: float | None = None
    average_loss_per_trade: float | None = None
    profit_factor: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BacktestEngine:
    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings or AppSettings.from_env()
        self.risk_manager = RiskManager(self.settings)

    @staticmethod
    def periods_per_year_for_interval(interval: str, *, crypto: bool = False) -> int:
        """Annualization assumes regular exchange sessions (equities) or 365-day markets."""
        bars_per_year = {
            "1Min": 252 * 390,
            "5Min": 252 * 78,
            "15Min": 252 * 26,
            "1Hour": 252 * 6,
            "1Day": 252,
            "1Week": 52,
        }
        if crypto:
            bars_per_year = {
                "1Min": 365 * 24 * 60,
                "5Min": 365 * 24 * 12,
                "15Min": 365 * 24 * 4,
                "1Hour": 365 * 24,
                "1Day": 365,
                "1Week": 52,
            }
        try:
            return bars_per_year[interval]
        except KeyError as exc:
            raise ValueError(f"Unsupported backtest interval for annualization: {interval}") from exc

    @staticmethod
    def _risk_metrics(
        equity_curve: list[float],
        *,
        periods_per_year: int | None,
        risk_free_rate_annual: float,
    ) -> tuple[float | None, float | None]:
        if periods_per_year is None or len(equity_curve) < 3:
            return None, None
        returns = pd.Series(equity_curve, dtype=float).pct_change().dropna()
        if len(returns) < 2 or not np.isfinite(returns.to_numpy()).all():
            return None, None
        volatility = float(returns.std(ddof=1))
        if volatility == 0:
            return None, None
        annualized_volatility = volatility * math.sqrt(periods_per_year) * 100
        excess_return = float(returns.mean()) - risk_free_rate_annual / periods_per_year
        sharpe = excess_return / volatility * math.sqrt(periods_per_year)
        if not math.isfinite(sharpe) or not math.isfinite(annualized_volatility):
            return None, None
        return annualized_volatility, sharpe

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
        periods_per_year: int | None = None,
        risk_free_rate_annual: float = 0.0,
    ) -> BacktestResult:
        if data.empty:
            raise ValueError("Backtest data is empty.")
        if "open" not in data.columns or "close" not in data.columns:
            raise ValueError("Backtest data must contain open and close prices.")

        starting_cash = float(initial_capital if initial_capital is not None else self.settings.initial_capital_usd)
        if not math.isfinite(starting_cash) or starting_cash <= 0:
            raise ValueError("Initial backtest capital must be positive.")
        prices = data[["open", "close"]].apply(pd.to_numeric, errors="coerce")
        if (
            prices.isna().any().any()
            or not np.isfinite(prices.to_numpy(dtype=float)).all()
            or (prices <= 0).any().any()
        ):
            raise ValueError("Backtest open and close prices must be present and positive.")
        short_period = self.settings.short_window if short_window is None else short_window
        long_period = self.settings.long_window if long_window is None else long_window
        if any(
            isinstance(window, bool) or not isinstance(window, Integral)
            for window in (short_period, long_period)
        ):
            raise ValueError("Moving average windows must be integers.")
        short_period = int(short_period)
        long_period = int(long_period)
        if short_period <= 0 or long_period <= 0:
            raise ValueError("Moving average windows must be positive.")
        if short_period >= long_period:
            raise ValueError("short_window must be smaller than long_window.")
        if len(data) < long_period + 2:
            raise ValueError(
                f"Backtest needs at least {long_period + 2} bars for a complete "
                "moving-average signal and next-bar execution."
            )
        if "timestamp" in data.columns:
            timestamps = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
            if timestamps.isna().any() or not timestamps.is_monotonic_increasing or timestamps.duplicated().any():
                raise ValueError("Backtest timestamps must be valid, strictly increasing, and unique.")
        normalized_data = data.copy()
        normalized_data[["open", "close"]] = prices
        strategy = MovingAverageStrategy(
            short_window=short_period,
            long_window=long_period,
        )
        signals = strategy.generate_signals(normalized_data).reset_index(drop=True)
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
        if periods_per_year is not None and (
            isinstance(periods_per_year, bool)
            or not isinstance(periods_per_year, Integral)
            or periods_per_year <= 0
        ):
            raise ValueError("Periods per year must be a positive integer when specified.")
        if periods_per_year is not None:
            periods_per_year = int(periods_per_year)
        if not math.isfinite(risk_free_rate_annual) or not 0 <= risk_free_rate_annual <= 1:
            raise ValueError("Annual risk-free rate must be between 0 and 1.")
        cash = starting_cash
        position_qty = 0.0
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
        entry_spread = 0.0
        entry_slippage = 0.0

        def net_liquidation_equity(available_cash: float, quantity: float, price: float) -> float:
            liquidation_price = price * (1 - half_spread_rate - slippage_rate)
            liquidation_value = quantity * liquidation_price
            liquidation_fee = liquidation_value * commission_rate
            return available_cash + liquidation_value - liquidation_fee

        benchmark_entry_market_price = float(signals.iloc[1]["open"])
        benchmark_entry_price = benchmark_entry_market_price * (
            1 + half_spread_rate + slippage_rate
        )
        benchmark_quantity = starting_cash / (
            benchmark_entry_price * (1 + commission_rate)
        )
        benchmark_entry_notional = benchmark_quantity * benchmark_entry_price
        benchmark_entry_fee = benchmark_entry_notional * commission_rate
        benchmark_entry_spread = (
            benchmark_quantity * benchmark_entry_market_price * half_spread_rate
        )
        benchmark_entry_slippage = (
            benchmark_quantity * benchmark_entry_market_price * slippage_rate
        )
        benchmark_cash = starting_cash - benchmark_entry_notional - benchmark_entry_fee

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
                daily_start_equity = net_liquidation_equity(
                    cash, position_qty, float(signals.iloc[index - 1]["close"])
                )
            previous_day = current_day
            equity_at_open = net_liquidation_equity(cash, position_qty, execution_price)
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
                    equity_curve.append(net_liquidation_equity(
                        cash, position_qty, float(signals.iloc[index]["close"])
                    ))
                    continue
                notional = quantity * buy_fill
                entry_fee = notional * commission_rate
                entry_spread = quantity * execution_price * half_spread_rate
                entry_slippage = quantity * execution_price * slippage_rate
                if daily_loss_reached or notional + entry_fee > cash:
                    equity_curve.append(net_liquidation_equity(
                        cash, position_qty, float(signals.iloc[index]["close"])
                    ))
                    continue
                cash -= notional + entry_fee
                position_qty = quantity
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
                    "entry_market_price": execution_price,
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
                gross_pnl = position_qty * (
                    execution_price - float(open_trade["entry_market_price"])
                )
                pnl = (
                    gross_pnl - entry_fee - sell_fee - entry_spread - sell_spread
                    - entry_slippage - sell_slippage
                )
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
                        "gross_pnl": gross_pnl,
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

            close_price = float(signals.iloc[index]["close"])
            current_equity = net_liquidation_equity(cash, position_qty, close_price)
            equity_curve.append(current_equity)
        # The benchmark enters at the same first executable open (bar 1).
        benchmark_equity_curve = [starting_cash] + [
            net_liquidation_equity(
                benchmark_cash, benchmark_quantity, float(signals.iloc[index]["close"])
            )
            for index in range(1, len(signals))
        ]
        if position_qty > 0 and open_trade is not None:
            final_mark = float(signals.iloc[-1]["close"])
            unrealized_gross = position_qty * (
                final_mark - float(open_trade["entry_market_price"])
            )
            final_liquidation_price = final_mark * (
                1 - half_spread_rate - slippage_rate
            )
            estimated_exit_notional = position_qty * final_liquidation_price
            estimated_exit_fee = estimated_exit_notional * commission_rate
            estimated_exit_spread = position_qty * final_mark * half_spread_rate
            estimated_exit_slippage = position_qty * final_mark * slippage_rate
            estimated_liquidation_costs = (
                estimated_exit_fee + estimated_exit_spread + estimated_exit_slippage
            )
            unrealized_net = (
                unrealized_gross - entry_fee - entry_spread - entry_slippage
                - estimated_liquidation_costs
            )
            trade_history.append({
                **open_trade,
                "exit_price": None,
                "gross_pnl": None,
                "net_pnl": None,
                "unrealized_gross_pnl": unrealized_gross,
                "unrealized_net_pnl": unrealized_net,
                "exit_reason": None,
                "status": "open",
            })
        else:
            unrealized_gross = 0.0
            unrealized_net = 0.0
            estimated_liquidation_costs = 0.0

        benchmark_final_mark = float(signals.iloc[-1]["close"])
        benchmark_exit_price = benchmark_final_mark * (
            1 - half_spread_rate - slippage_rate
        )
        benchmark_exit_notional = benchmark_quantity * benchmark_exit_price
        benchmark_exit_fee = benchmark_exit_notional * commission_rate
        benchmark_exit_spread = (
            benchmark_quantity * benchmark_final_mark * half_spread_rate
        )
        benchmark_exit_slippage = (
            benchmark_quantity * benchmark_final_mark * slippage_rate
        )
        benchmark_estimated_liquidation_costs = (
            benchmark_exit_fee + benchmark_exit_spread + benchmark_exit_slippage
        )
        benchmark_final_capital = benchmark_equity_curve[-1]

        final_capital = equity_curve[-1]
        return_pct = ((final_capital - starting_cash) / starting_cash) * 100
        drawdown = self.risk_manager.compute_drawdown(equity_curve)
        closed_trades = [trade for trade in trade_history if trade["status"] == "closed"]
        closed_net_pnls = [float(trade["net_pnl"]) for trade in closed_trades]
        winning_net_pnls = [pnl for pnl in closed_net_pnls if pnl > 0]
        losing_net_pnls = [pnl for pnl in closed_net_pnls if pnl < 0]
        closed_trade_count = len(closed_net_pnls)
        win_rate = (
            winning_trades / closed_trade_count * 100
            if closed_trade_count
            else None
        )
        average_profit_per_trade = (
            sum(winning_net_pnls) / len(winning_net_pnls)
            if winning_net_pnls
            else None
        )
        average_loss_per_trade = (
            sum(losing_net_pnls) / len(losing_net_pnls)
            if losing_net_pnls
            else None
        )
        profit_factor = (
            sum(winning_net_pnls) / abs(sum(losing_net_pnls))
            if losing_net_pnls
            else None
        )
        annualized_volatility_pct, sharpe_ratio = self._risk_metrics(
            equity_curve,
            periods_per_year=periods_per_year,
            risk_free_rate_annual=risk_free_rate_annual,
        )
        benchmark_drawdown = self.risk_manager.compute_drawdown(benchmark_equity_curve)
        benchmark_annualized_volatility_pct, benchmark_sharpe_ratio = self._risk_metrics(
            benchmark_equity_curve,
            periods_per_year=periods_per_year,
            risk_free_rate_annual=risk_free_rate_annual,
        )
        paid_transaction_costs = fees_paid + slippage_paid + spread_paid
        benchmark_fees_paid = benchmark_entry_fee
        benchmark_spread_paid = benchmark_entry_spread
        benchmark_slippage_paid = benchmark_entry_slippage

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
            gross_pnl=sum(float(trade["gross_pnl"]) for trade in closed_trades),
            net_pnl=sum(float(trade["net_pnl"]) for trade in closed_trades),
            unrealized_gross_pnl=unrealized_gross,
            unrealized_net_pnl=unrealized_net,
            estimated_liquidation_costs=estimated_liquidation_costs,
            total_transaction_costs=paid_transaction_costs + estimated_liquidation_costs,
            annualized_volatility_pct=annualized_volatility_pct,
            sharpe_ratio=sharpe_ratio,
            periods_per_year=periods_per_year,
            risk_free_rate_annual=risk_free_rate_annual,
            benchmark_final_capital=benchmark_final_capital,
            benchmark_return_pct=(benchmark_final_capital / starting_cash - 1) * 100,
            benchmark_max_drawdown_pct=benchmark_drawdown["max_drawdown"],
            benchmark_fees_paid=benchmark_fees_paid,
            benchmark_spread_paid=benchmark_spread_paid,
            benchmark_slippage_paid=benchmark_slippage_paid,
            benchmark_estimated_liquidation_costs=benchmark_estimated_liquidation_costs,
            benchmark_total_transaction_costs=(
                benchmark_fees_paid + benchmark_spread_paid + benchmark_slippage_paid
                + benchmark_estimated_liquidation_costs
            ),
            benchmark_annualized_volatility_pct=benchmark_annualized_volatility_pct,
            benchmark_sharpe_ratio=benchmark_sharpe_ratio,
            average_profit_per_trade=average_profit_per_trade,
            average_loss_per_trade=average_loss_per_trade,
            profit_factor=profit_factor,
        )
