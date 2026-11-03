from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from agent.coder_brain import BaseStrategy, CoderBrain
from core.ingestor import Ingestor
from core.market_router import MarketRouter
from core.state import Controls, LiveState, Market, save_state
from engine.sandbox import Evaluation, Sandbox
from execution.vanguard import LIMITS, Vanguard


class Runtime:
    def __init__(self, state_path: Path, ingestor: Ingestor | None = None) -> None:
        self.path = state_path
        self.state = LiveState.model_validate_json(state_path.read_text()) if state_path.exists() else LiveState()
        self.state.running = False
        self.ingestor = ingestor if ingestor is not None else Ingestor()
        self.analysis_periods: dict[Market, int] = {}
        self.ai_candidates: dict[Market, tuple[tuple[int, int], ...]] = {}
        self.router = MarketRouter()
        self.brain = CoderBrain(state_path.parent / "generated")
        self.sandbox = Sandbox()
        self.risk = Vanguard(self.state)
        self.strategies: dict[Market, BaseStrategy] = {}
        self.reports: dict[Market, Evaluation] = {}
        self.sources: dict[Market, str] = {}
        self.repair_attempted: set[Market] = set()
        self.lock = asyncio.Lock()
        self.logger = logging.getLogger("omega")

    def event(self, message: str) -> None:
        self.logger.info(message)
        self.state.events = [*self.state.events[-99:], f"{time.strftime('%H:%M:%S')} {message}"]

    def prices(self) -> dict[Market, float]:
        return {market: float(frame.iloc[self.state.cursors[market] - 1].close)
                for market, frame in self.ingestor.frames.items()}

    def prepare(self, market: Market) -> None:
        history = self.ingestor.frames[market].iloc[:self.state.cursors[market]]
        split = int(len(history) * 0.6)
        training, holdout = history.iloc[:split], history.iloc[split:]
        candidates = []
        periods = self.analysis_periods.get(market, 365)
        for short, long in self.ai_candidates.get(market, self.brain.candidates(float(training.close.pct_change().std()))):
            source, strategy = self.brain.generate(market, short, long)
            report = self.sandbox.evaluate(training, strategy, LIMITS[market][0], periods)
            candidates.append((report.net_return, source, strategy, report))
        _, source, strategy, training_report = max(candidates, key=lambda candidate: candidate[0])
        self.brain.generate(market, strategy.short_window, strategy.long_window)
        if training_report.win_rate is not None and training_report.payoff is not None:
            report = self.sandbox.evaluate(
                holdout, strategy, LIMITS[market][0], periods, market=market,
                sizing=(training_report.win_rate, training_report.payoff),
                kelly_multiplier=self.state.controls.kelly_multiplier,
            )
        else:
            report = replace(self.sandbox.evaluate(holdout, strategy, LIMITS[market][0], periods), approved=False)
        self.sources[market], self.reports[market] = source, report
        if report.approved:
            self.strategies[market] = strategy
        else:
            self.strategies.pop(market, None)
        self.event(f"{market}: holdout {'APPROVED FOR DEMO' if report.approved else 'REJECTED'}; trades={report.trades}")

    async def initialize(self) -> None:
        async with self.lock:
            for market in Market:
                await asyncio.to_thread(self.prepare, market)
            self.risk.guard(self.prices())
            save_state(self.path, self.state)

    async def configure(self, controls: Controls) -> None:
        async with self.lock:
            old = self.state.controls
            if controls.bankroll != old.bankroll:
                if self.state.positions or self.state.running or time.time() < self.state.locked_until:
                    raise ValueError("Bankroll changes require stopped, flat and unlocked demo")
                if self.state.cash != old.bankroll:
                    raise ValueError("Existing simulation PnL cannot be reset by editing bankroll")
                self.state.cash = self.state.equity = self.state.daily_start_equity = controls.bankroll
            if (controls.market, controls.multi_split_kelly) != (old.market, old.multi_split_kelly):
                if controls.switch_policy == "flatten":
                    self.risk.flatten(self.prices())
                elif controls.switch_policy == "tight_trailing":
                    for position in self.state.positions:
                        position.tight_trailing = True
                self.event(f"Hot swap: {controls.market}; policy={controls.switch_policy}; split={controls.multi_split_kelly}")
            self.state.controls = controls
            if controls.kelly_multiplier != old.kelly_multiplier:
                self.state.running = False
                for market in Market:
                    await asyncio.to_thread(self.prepare, market)
                self.event("Kelly changed: entries paused; holdout risk policy revalidated")
            save_state(self.path, self.state)

    async def command(self, action: str) -> None:
        async with self.lock:
            if action == "start":
                if not self.risk.guard(self.prices()):
                    save_state(self.path, self.state)
                    raise ValueError("24-hour lock active")
                if any(self.state.cursors[m] >= 2000 for m in self.router.active(self.state.controls)):
                    raise ValueError("Replay exhausted; cannot restart on the same data")
                self.state.running = True
            elif action == "pause":
                self.state.running = False
            elif action == "panic":
                self.risk.flatten(self.prices())
                self.state.running = False
                self.state.locked_until = max(self.state.locked_until, time.time() + 86400)
            else:
                raise ValueError("Unknown action")
            self.event(f"Command: {action}")
            save_state(self.path, self.state)

    async def tick(self) -> None:
        async with self.lock:
            active = self.router.active(self.state.controls)
            monitored = set(active if self.state.running else []) | {p.market for p in self.state.positions}
            opening_prices = self.prices()
            for market in monitored:
                if self.state.cursors[market] >= 2000:
                    self.risk.flatten(self.prices())
                    self.state.running = False
                    self.event("Replay exhausted; flattened demo and stopped")
                    break
                self.state.cursors[market] += 1
                opening_prices[market] = float(self.ingestor.frames[market].iloc[self.state.cursors[market] - 1].open)
            prices = self.prices()
            signals: dict[Market, int] = {}
            statistics: dict[Market, tuple[float, float]] = {}
            atrs: dict[Market, float] = {}
            if self.state.running:
                for market in active:
                    strategy = self.strategies.get(market)
                    if strategy is None:
                        continue
                    history = self.ingestor.frames[market].iloc[:self.state.cursors[market]]
                    try:
                        # The previous close's signal fills at the current open, as in the repo backtester.
                        signal = strategy.current_signal(history.iloc[:-1])["signal"]
                        if isinstance(signal, bool) or signal not in {-1, 0, 1}:
                            raise ValueError("Strategy signals must be -1, 0 or 1")
                    except Exception:
                        self.strategies.pop(market, None)
                        self.state.running = False
                        self.event(f"{market}: strategy disabled; {traceback.format_exc()}")
                        if market not in self.repair_attempted:
                            self.repair_attempted.add(market)
                            await asyncio.to_thread(self.prepare, market)
                        continue
                    report = self.reports[market]
                    if report.approved and report.policy_verified:
                        signals[market] = int(signal)
                        statistics[market] = (report.sizing_win_rate, report.sizing_payoff)
                        atrs[market] = self.router.adapters[market].atr(history.iloc[:-1])
            for message in self.risk.apply_bar(
                active=active, opening=opening_prices, closing=prices, signals=signals,
                atrs=atrs, statistics=statistics,
            ):
                self.event(message)
            save_state(self.path, self.state)

    async def run(self) -> None:
        async for _ in self.ingestor.clock():
            try:
                await self.tick()
            except Exception:
                self.state.running = False
                self.event(f"Runtime stopped: {traceback.format_exc()}")
                save_state(self.path, self.state)

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            return {
                **self.state.model_dump(mode="json"),
                "prices": self.prices(),
                "reports": {market: asdict(report) for market, report in self.reports.items()},
                "sources": self.sources,
                "unavailable": {market: adapter.unavailable for market, adapter in self.router.adapters.items()},
            }
