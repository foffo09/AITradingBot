"""Causal analytical levels; these functions never place protective orders."""
from dataclasses import dataclass
import math
from numbers import Integral, Real

import pandas as pd


@dataclass(frozen=True)
class LevelConfig:
    atr_period: int = 14
    atr_multiple: float = 1.5
    reward_risk: float = 2.0
    min_reward_risk: float = 1.5
    structure_window: int = 10
    min_spread_multiple: float = 3.0

    def __post_init__(self):
        for value in (self.atr_period, self.structure_window):
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 2:
                raise ValueError('Indicator windows must be integers of at least two.')
        for value in (self.atr_multiple, self.reward_risk, self.min_reward_risk, self.min_spread_multiple):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
                raise ValueError('Level parameters must be finite and positive.')
        if self.reward_risk < self.min_reward_risk:
            raise ValueError('Target reward must meet minimum reward/risk.')


def plan_levels(data, side, entry, spread=0, config=LevelConfig()):
    """ATR simple mean and trailing structure, using only the supplied prefix."""
    if side not in {'BUY', 'SELL'}:
        raise ValueError('Levels require BUY or SELL.')
    if (isinstance(entry, bool) or isinstance(spread, bool) or not isinstance(entry, Real)
            or not isinstance(spread, Real) or not math.isfinite(entry)
            or not math.isfinite(spread) or entry <= 0 or spread < 0):
        raise ValueError('Entry and spread must be finite and valid.')
    required = max(config.atr_period+1, config.structure_window)
    if len(data) < required or not {'high','low','close'}.issubset(data.columns):
        raise ValueError('Insufficient OHLC history for ATR and structure.')
    if data[['high','low','close']].map(lambda value: isinstance(value, bool)).any().any():
        raise ValueError('Boolean OHLC values are invalid.')
    prices = data[['high','low','close']].apply(pd.to_numeric, errors='coerce')
    if (prices.isna().any().any() or not prices.map(lambda x: math.isfinite(x) and x > 0).all().all()
            or (prices['high'] < prices['close']).any() or (prices['low'] > prices['close']).any()):
        raise ValueError('Invalid OHLC prices for levels.')
    previous = prices['close'].shift(1)
    true_range = pd.concat([prices['high']-prices['low'],
                           (prices['high']-previous).abs(), (prices['low']-previous).abs()], axis=1).max(axis=1)
    atr = float(true_range.iloc[-config.atr_period:].mean())
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError('ATR must be finite and positive.')
    support = float(prices['low'].tail(config.structure_window).min())
    resistance = float(prices['high'].tail(config.structure_window).max())
    minimum_stop = max(config.atr_multiple*atr, config.min_spread_multiple*spread)
    if side == 'BUY':
        stop = min(entry-minimum_stop, support-.1*atr)
        target = entry+(entry-stop)*config.reward_risk
        if resistance > entry:
            target = min(target, resistance-.1*atr)
        stop_distance, target_distance = entry-stop, target-entry
    else:
        stop = max(entry+minimum_stop, resistance+.1*atr)
        target = entry-(stop-entry)*config.reward_risk
        if support < entry:
            target = max(target, support+.1*atr)
        stop_distance, target_distance = stop-entry, entry-target
    values = (stop, target, stop_distance, target_distance)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError('Nonpositive or nonfinite levels.')
    ratio = target_distance/stop_distance
    if not math.isfinite(ratio) or ratio+1e-12 < config.min_reward_risk:
        raise ValueError('Insufficient reward/risk before market structure.')
    return dict(entry=float(entry), stop_loss=stop, take_profit=target,
                stop_distance=stop_distance, target_distance=target_distance,
                reward_risk=ratio, atr=atr)
