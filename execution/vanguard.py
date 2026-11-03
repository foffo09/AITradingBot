from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from core.state import Fill, LiveState, Market, Position


LIMITS = {
    Market.MEME_SNIPER: (0.015, 0.25),
    Market.CRYPTO_PERPS: (0.04, 0.015),
    Market.OPTIONS_0DTE: (0.025, 0.30),
    Market.COMMODITIES_FUT: (0.05, None),
    Market.BIOTECH_CATALYST: (0.03, 0.10),
}
# Each side: 5 bps commission, 5 bps half spread, 5 bps slippage (estimates).
COMMISSION = 0.0005
IMPACT = 0.001


class Vanguard:
    def __init__(self, state: LiveState) -> None:
        self.state = state

    @staticmethod
    def kelly(p: float, b: float, multiplier: float = 0.5) -> float:
        if not all(math.isfinite(x) for x in (p, b, multiplier)) or not 0 <= p <= 1 or b <= 0 or not 0.1 <= multiplier <= 1:
            raise ValueError("Invalid Kelly inputs")
        return max(0.0, multiplier * (b * p - (1 - p)) / b)

    def mark(self, prices: dict[Market, float]) -> float:
        if any(not math.isfinite(p) or p <= 0 for p in prices.values()):
            raise ValueError("Invalid mark")
        # Net estimated liquidation value, including the cost of exiting positions.
        self.state.equity = self.state.cash + sum(
            position.quantity * prices[position.market] * (1 - IMPACT) * (1 - COMMISSION)
            for position in self.state.positions
        )
        return self.state.equity

    def close(self, position: Position, price: float, fraction: float = 1,
              reason: str = "manual", now: float | None = None) -> None:
        if position not in self.state.positions or not math.isfinite(price) or price <= 0 or not 0 < fraction <= 1:
            raise ValueError("Invalid simulated close")
        quantity = position.quantity * fraction
        fill_price = price * (1 - IMPACT)
        commission = quantity * fill_price * COMMISSION
        proceeds = quantity * fill_price - commission
        self.state.fills.append(Fill(
            position_id=position.id, market=position.market, side="sell", quantity=quantity,
            quote_price=price, price=fill_price, commission=commission,
            net_pnl=proceeds - quantity * position.entry * (1 + COMMISSION),
            timestamp=time.time() if now is None else now, reason=reason,
            instrument_id=position.instrument_id,
        ))
        self.state.cash += proceeds
        if fraction == 1:
            self.state.positions.remove(position)
        else:
            position.quantity -= quantity
            position.partial_taken = True

    def flatten(self, prices: dict[Market, float], reason: str = "flatten", now: float | None = None) -> None:
        for position in list(self.state.positions):
            self.close(position, prices[position.market], reason=reason, now=now)
        self.mark(prices)

    def guard(self, prices: dict[Market, float], now: float | None = None) -> bool:
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        equity = self.mark(prices)
        if not self.state.day:
            self.state.day = today
        # Test the existing baseline before a UTC rollover so overnight losses cannot bypass it.
        if equity <= self.state.daily_start_equity * 0.95:
            self.flatten(prices, reason="daily_loss", now=now)
            if self.state.locked_until <= now:
                self.state.locked_until = now + 86400
            self.state.running = False
            self.state.daily_start_equity = self.state.equity or self.state.daily_start_equity
        if self.state.day != today:
            self.state.day = today
            if equity > 0:
                self.state.daily_start_equity = self.state.equity
        return now >= self.state.locked_until

    def open(self, market: Market, price: float, p: float, b: float, atr: float, splits: int,
             now: float | None = None, instrument_id: str = "") -> bool:
        now = time.time() if now is None else now
        if (not self.state.running or now < self.state.locked_until
                or any(position.market == market for position in self.state.positions)):
            return False
        if not math.isfinite(price) or price <= 0 or not math.isfinite(atr) or atr <= 0 or splits < 1:
            raise ValueError("Invalid simulated entry")
        cap, stop_fraction = LIMITS[market]
        fraction = min(cap, self.kelly(p, b, self.state.controls.kelly_multiplier)) / splits
        budget = min(self.state.cash, self.state.equity * fraction)
        if budget < 0.01:
            return False
        entry = price * (1 + IMPACT)
        stop = entry * (1 - stop_fraction) if stop_fraction is not None else entry - 1.5 * atr
        if stop <= 0:
            return False
        quantity = budget / (entry * (1 + COMMISSION))
        position = Position(
            market=market, quantity=quantity, entry=entry, peak=price, stop=stop, opened_at=now,
            instrument_id=instrument_id,
        )
        self.state.positions.append(position)
        self.state.fills.append(Fill(
            position_id=position.id, market=market, side="buy", quantity=quantity, quote_price=price,
            price=entry, commission=quantity * entry * COMMISSION, timestamp=now, reason="signal",
            instrument_id=instrument_id,
        ))
        self.state.cash = max(0.0, self.state.cash - budget)
        return True

    def monitor(self, prices: dict[Market, float], now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        if any(not math.isfinite(price) or price <= 0 for price in prices.values()):
            raise ValueError("Invalid monitoring prices")
        events: list[str] = []
        for position in list(self.state.positions):
            if position.market not in prices:
                continue
            price = prices[position.market]
            position.peak = max(position.peak, price)
            if position.tight_trailing:
                position.stop = max(position.stop, position.peak * 0.99)
            timed_out = position.market == Market.OPTIONS_0DTE and now - position.opened_at >= 900
            if price <= position.stop or timed_out:
                self.close(position, price, reason="time_stop" if timed_out else "stop", now=now)
                events.append(f"{position.market}: simulated stop/time exit")
            elif position.market == Market.MEME_SNIPER and not position.partial_taken and price >= position.entry * 2:
                self.close(position, price, 0.5, reason="partial_take_profit", now=now)
                events.append(f"{position.market}: simulated 50% take profit")
        return events

    def apply_bar(
        self, *, active: list[Market], opening: dict[Market, float], closing: dict[Market, float],
        signals: dict[Market, int], atrs: dict[Market, float], statistics: dict[Market, tuple[float, float]],
        now: float | None = None,
        instruments: dict[Market, str] | None = None,
    ) -> list[str]:
        """One execution policy shared by runtime and out-of-sample validation."""
        now = time.time() if now is None else now
        previous_lock = self.state.locked_until
        events = []
        unlocked = self.guard(opening, now)
        events.extend(self.monitor(opening, now))
        if self.state.running and unlocked:
            for market in active:
                signal = signals.get(market, 0)
                if signal == 1 and market in statistics:
                    p, b = statistics[market]
                    if self.open(market, opening[market], p, b, atrs[market], len(active), now,
                                 instrument_id=(instruments or {}).get(market, "")):
                        events.append(f"{market}: simulated entry")
                elif signal == -1:
                    for position in list(self.state.positions):
                        if position.market == market:
                            self.close(position, opening[market], reason="signal", now=now)
                            events.append(f"{market}: simulated signal exit")
        events.extend(self.monitor(closing, now))
        self.guard(closing, now)
        if self.state.locked_until > previous_lock:
            events.append("Daily loss kill switch: simulated positions flattened, entries locked for 24 hours")
        return events
