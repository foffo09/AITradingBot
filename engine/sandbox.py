from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from agent.coder_brain import BaseStrategy
from config.settings import AppSettings
from core.ingestor import Ingestor
from core.state import Controls, LiveState, Market
from execution.vanguard import Vanguard
from src.backtesting.engine import BacktestEngine, BacktestResult


@dataclass(frozen=True)
class Evaluation:
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float
    profit_factor: float | None
    win_rate: float | None
    payoff: float | None
    trades: int
    net_return: float
    costs: float
    approved: bool
    synthetic: bool
    policy_verified: bool = False
    sizing_win_rate: float | None = None
    sizing_payoff: float | None = None


class Sandbox:
    def __init__(self) -> None:
        self.engine = BacktestEngine(AppSettings(trading_mode="demo"))

    def evaluate(self, data: pd.DataFrame, strategy: BaseStrategy, cap: float, periods_per_year: int = 365,
                 *, market: Market | None = None, sizing: tuple[float, float] | None = None,
                 kelly_multiplier: float = 0.5) -> Evaluation:
        if market is None:
            result = self.engine.run(
                data, short_window=strategy.short_window, long_window=strategy.long_window,
                initial_capital=10000, max_trade_fraction=cap, daily_loss_limit_fraction=0.05,
                commission_bps=5, spread_bps=10, slippage_bps=5, periods_per_year=periods_per_year,
            )
        else:
            if sizing is None:
                raise ValueError("Risk-policy validation requires sizing statistics from training")
            result = self._paper_replay(data, strategy, market, sizing, kelly_multiplier, periods_per_year)
        returns = pd.Series(result.equity_curve).pct_change().dropna().to_numpy()
        downside = float(np.sqrt(np.mean(np.minimum(returns, 0) ** 2)))
        sortino = float(returns.mean() / downside * np.sqrt(periods_per_year)) if downside > 0 else None
        years = len(returns) / periods_per_year
        annual = (result.final_capital / result.initial_capital) ** (1 / years) - 1
        equity = np.asarray(result.equity_curve, dtype=float)
        drawdown = float(np.max(1 - equity / np.maximum.accumulate(equity)))
        calmar = annual / drawdown if drawdown > 0 else None
        payoff = (result.average_profit_per_trade / abs(result.average_loss_per_trade)
                  if result.average_profit_per_trade is not None and result.average_loss_per_trade else None)
        trades = result.total_trades
        approved = (trades >= 10 and result.sharpe_ratio is not None and result.sharpe_ratio >= 2
                    and drawdown <= 0.08 and result.profit_factor is not None and result.profit_factor >= 1.6
                    and payoff is not None and payoff > 0)
        return Evaluation(
            result.sharpe_ratio, sortino, calmar, drawdown, result.profit_factor,
            result.win_rate / 100 if result.win_rate is not None else None, payoff,
            trades, result.return_pct / 100, result.total_transaction_costs, approved,
            bool(data.get("is_synthetic", pd.Series(False)).any()),
            market is not None,
            sizing[0] if sizing else None,
            sizing[1] if sizing else None,
        )

    def _paper_replay(self, data: pd.DataFrame, strategy: BaseStrategy, market: Market,
                      sizing: tuple[float, float], multiplier: float, periods_per_year: int) -> BacktestResult:
        frame = Ingestor.normalize(data).reset_index(drop=True)
        if len(frame) < strategy.long_window + 2:
            raise ValueError("Insufficient risk-policy validation history")
        state = LiveState(controls=Controls(market=market, kelly_multiplier=multiplier), running=True)
        risk = Vanguard(state)
        signals = strategy.generate_signals(frame).signal.to_numpy()
        previous = frame.close.shift()
        atr = pd.concat([frame.high - frame.low, (frame.high - previous).abs(),
                         (frame.low - previous).abs()], axis=1).max(axis=1).rolling(14, min_periods=1).mean()
        curve = [state.equity]
        # Replay has one simulated second per candle, matching the demo's playback rate.
        replay_start = 1577880000.0
        synthetic = bool(frame.get("is_synthetic", pd.Series(False)).any())
        for index in range(1, len(frame)):
            risk.apply_bar(
                active=[market], opening={market: float(frame.iloc[index].open)},
                closing={market: float(frame.iloc[index].close)}, signals={market: int(signals[index - 1])},
                atrs={market: float(atr.iloc[index - 1])}, statistics={market: sizing},
                now=replay_start + index if synthetic else frame.timestamp.iloc[index].timestamp(),
            )
            curve.append(state.equity)
        risk.flatten({market: float(frame.iloc[-1].close)}, reason="validation_end",
                     now=replay_start + len(frame) if synthetic else frame.timestamp.iloc[-1].timestamp())
        curve[-1] = state.equity
        pnls: dict[str, float] = {}
        for fill in state.fills:
            if fill.side == "sell":
                pnls[fill.position_id] = pnls.get(fill.position_id, 0) + fill.net_pnl
        wins = [pnl for pnl in pnls.values() if pnl > 0]
        losses = [pnl for pnl in pnls.values() if pnl < 0]
        _, sharpe = self.engine._risk_metrics(curve, periods_per_year=periods_per_year, risk_free_rate_annual=0)
        costs = sum(fill.commission + fill.quantity * abs(fill.price - fill.quote_price) for fill in state.fills)
        return BacktestResult(
            initial_capital=10000, final_capital=state.equity, return_pct=(state.equity / 10000 - 1) * 100,
            total_trades=len(pnls), winning_trades=len(wins), losing_trades=len(losses),
            win_rate=len(wins) / len(pnls) * 100 if pnls else None,
            max_drawdown_pct=self.engine.risk_manager.compute_drawdown(curve)["max_drawdown"],
            fees_paid=sum(fill.commission for fill in state.fills), equity_curve=curve,
            total_transaction_costs=costs, sharpe_ratio=sharpe,
            average_profit_per_trade=sum(wins) / len(wins) if wins else None,
            average_loss_per_trade=sum(losses) / len(losses) if losses else None,
            profit_factor=sum(wins) / abs(sum(losses)) if losses else None,
        )
