from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from config.providers import ProviderSettings
from core.ingestor import Ingestor
from core.runtime import Runtime
from core.state import Controls, Market, save_state
from execution.providers import ExecutionProviders
from providers.ai import AIProvider
from providers.common import Quote, error_code
from providers.hub import ProviderHub


class LiveRuntime(Runtime):
    """Live market data feeding an isolated local paper account; never synthetic fallback."""

    def __init__(self, state_path: Path, settings: ProviderSettings) -> None:
        super().__init__(state_path, ingestor=Ingestor(synthetic=False))
        self.state.source = "LIVE_DATA_PAPER"
        self.settings = settings
        self.quotes: dict[Market, Quote] = {}
        self.history_sources: dict[Market, str] = {}
        self.blocked: dict[Market, str] = {market: "Waiting for public data" for market in Market}
        self.ai = AIProvider(settings)
        import yfinance as yf
        cache = state_path.parent / "feed_cache"
        cache.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache))
        self.hub = ProviderHub(settings, self.on_quote, self.on_history)
        self.execution = ExecutionProviders(settings, state_path.parent / "native_orders.sqlite3")
        self.analysis_periods = {market: 365 * 1440 if market in {Market.CRYPTO_PERPS, Market.MEME_SNIPER}
                                 else 252 * 390 for market in Market}

    def prices(self) -> dict[Market, float]:
        result = dict(self.state.last_prices)
        for position in self.state.positions:
            result.setdefault(position.market, position.entry)
        return result

    def fresh_position(self, position) -> bool:
        quote = self.quotes.get(position.market)
        return bool(quote and quote.instrument_id == position.instrument_id and quote.instrument != "proxy"
                    and quote.fresh(self.settings.quote_max_age_seconds))

    async def initialize(self) -> None:
        save_state(self.path, self.state)
        await self.hub.start()

    async def close(self) -> None:
        await self.hub.close()

    async def on_quote(self, market: Market, quote: Quote) -> None:
        async with self.lock:
            previous = self.quotes.get(market)
            if (previous and previous.instrument_id == quote.instrument_id and previous.source_time is not None
                    and quote.source_time is not None and quote.source_time < previous.source_time):
                return
            self.quotes[market] = quote
            position = next((p for p in self.state.positions if p.market == market), None)
            if position and position.instrument_id != quote.instrument_id:
                self.blocked[market] = "Provider/instrument changed: existing position requires its original feed"
                return
            self.state.last_prices[market] = quote.price
            if quote.instrument == "proxy":
                self.blocked[market] = "Underlying/continuous-series proxy: monitoring only, no contract execution"
            elif not quote.fresh(self.settings.quote_max_age_seconds):
                self.blocked[market] = "Stale quote or missing exchange timestamp: entries blocked"
            elif market not in self.reports:
                self.blocked[market] = "Waiting for enough matching historical bars for sandbox"
            elif not self.reports[market].approved:
                self.blocked[market] = "Sandbox rejected strategy: monitoring only"
            else:
                self.blocked[market] = ""

    def prepare(self, market: Market) -> None:
        frame = self.ingestor.frames.get(market)
        if frame is None or len(frame) < 250:
            self.strategies.pop(market, None)
            self.reports.pop(market, None)
            return
        super().prepare(market)

    async def on_history(self, market: Market, frame: pd.DataFrame, provider: str, symbol: str) -> None:
        normalized = Ingestor.normalize(frame)
        normalized = normalized[normalized.timestamp + pd.Timedelta(minutes=1) <= pd.Timestamp.now(tz="UTC")].tail(1500).reset_index(drop=True)
        instrument_id = f"{provider}:{symbol}"
        async with self.lock:
            position = next((p for p in self.state.positions if p.market == market), None)
            if position and position.instrument_id != instrument_id:
                return
            changed = self.history_sources.get(market) != instrument_id
            self.ingestor.frames[market] = normalized
            self.history_sources[market] = instrument_id
            if changed:
                self.strategies.pop(market, None)
                self.reports.pop(market, None)
        if len(normalized) < 250 or (market in self.reports and not changed):
            return
        if self.ai.backend != "none":
            try:
                self.ai_candidates[market] = await self.ai.propose(market, float(normalized.close.pct_change().std()))
            except Exception as exc:
                self.ai.status = f"{error_code(exc)}; deterministic fallback"
        async with self.lock:
            try:
                await asyncio.to_thread(self.prepare, market)
            except Exception as exc:
                self.strategies.pop(market, None)
                self.reports.pop(market, None)
                self.blocked[market] = f"Sandbox unavailable: {error_code(exc)}"

    async def configure(self, controls: Controls) -> None:
        async with self.lock:
            old = self.state.controls
            switching = (controls.market, controls.multi_split_kelly) != (old.market, old.multi_split_kelly)
            if switching and controls.switch_policy == "flatten" and any(not self.fresh_position(p) for p in self.state.positions):
                raise ValueError("Fresh original quotes required for flatten; Panic queues exits until data returns")
        await super().configure(controls)

    async def command(self, action: str) -> None:
        async with self.lock:
            if action == "start":
                if self.state.pending_flatten or any(not self.fresh_position(p) for p in self.state.positions):
                    raise ValueError("Waiting for original position quotes or pending flatten")
                if not self.risk.guard(self.prices()):
                    save_state(self.path, self.state)
                    raise ValueError("24-hour lock active")
                self.state.running = True
            elif action == "pause":
                self.state.running = False
            elif action == "panic":
                self.state.running = False
                self.state.locked_until = max(self.state.locked_until, time.time() + 86400)
                self.state.pending_flatten = bool(self.state.positions)
                self.flatten_fresh()
            else:
                raise ValueError("Unknown action")
            self.event(f"Live-data paper command: {action}")
            save_state(self.path, self.state)

    def flatten_fresh(self) -> None:
        for position in list(self.state.positions):
            if self.fresh_position(position):
                self.risk.close(position, self.quotes[position.market].price, reason="panic")
        self.state.pending_flatten = bool(self.state.positions)
        self.risk.mark(self.prices())

    async def tick(self) -> None:
        async with self.lock:
            if self.state.pending_flatten:
                self.flatten_fresh()
                save_state(self.path, self.state)
                return
            if any(not self.fresh_position(p) for p in self.state.positions):
                fresh = {p.market: self.quotes[p.market].price for p in self.state.positions if self.fresh_position(p)}
                for message in self.risk.monitor(fresh):
                    self.event(message)
                self.risk.mark(self.prices())
                save_state(self.path, self.state)
                return
            active = self.router.active(self.state.controls)
            signals, atrs, statistics, instruments = {}, {}, {}, {}
            for market in active:
                quote, report = self.quotes.get(market), self.reports.get(market)
                if (not quote or quote.instrument == "proxy" or not quote.fresh(self.settings.quote_max_age_seconds)
                        or not report or not report.approved or not report.policy_verified
                        or market not in self.strategies or self.history_sources.get(market) != quote.instrument_id):
                    continue
                history = self.ingestor.frames[market]
                decision_id = f"{quote.instrument_id}:{history.timestamp.iloc[-1].isoformat()}"
                if self.state.decisions.get(market) == decision_id:
                    continue
                try:
                    signal = self.strategies[market].current_signal(history)["signal"]
                    if isinstance(signal, bool) or signal not in {-1, 0, 1}:
                        raise ValueError("Invalid strategy signal")
                    signals[market] = int(signal)
                    atrs[market] = self.router.adapters[market].atr(history)
                    statistics[market] = (report.sizing_win_rate, report.sizing_payoff)
                    instruments[market] = quote.instrument_id
                    self.state.decisions[market] = decision_id
                except Exception as exc:
                    self.strategies.pop(market, None)
                    self.event(f"{market}: strategy disabled ({error_code(exc)})")
            prices = self.prices()
            for message in self.risk.apply_bar(active=active, opening=prices, closing=prices, signals=signals,
                                                atrs=atrs, statistics=statistics, instruments=instruments):
                self.event(message)
            save_state(self.path, self.state)

    async def snapshot(self):
        async with self.lock:
            return {**self.state.model_dump(mode="json"), "prices": self.prices(),
                    "reports": {market: asdict(report) for market, report in self.reports.items()},
                    "sources": self.sources, "unavailable": {market: self.blocked[market] for market in Market},
                    "quotes": {market: {**quote.model_dump(mode="json"), "fresh": quote.fresh(self.settings.quote_max_age_seconds)}
                               for market, quote in self.quotes.items()},
                    "providers": self.hub.status, "solana_rpc": self.hub.solana.rpc_status,
                    "news": self.hub.news, "ai": {"provider": self.ai.backend, "status": self.ai.status},
                    "execution_providers": self.execution.capabilities()}
