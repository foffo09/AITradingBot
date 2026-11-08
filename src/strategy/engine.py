"""Paper signal proposals. No broker, persistence, logger or order submission."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from numbers import Integral, Real

import pandas as pd

from config.settings import AppSettings
from src.data.bar_timing import BarTimingError, select_completed_bars, utc_timestamp
from src.data.instruments import INSTRUMENTS
from src.risk.trade_plan import RiskPolicy, RiskSnapshot, size_proposal
from src.risk.risk_manager import RiskViolationError
from src.strategy.levels import LevelConfig, plan_levels
from src.strategy.moving_average import MovingAverageStrategy
from src.strategy.trend import EMACrossoverStrategy


@dataclass(frozen=True)
class StrategyConfig:
    strategy: str = 'ema'
    short_window: int = 9
    long_window: int = 21
    trend_window: int = 50
    signal_ttl_seconds: int = 180
    levels: LevelConfig = field(default_factory=LevelConfig)
    risk: RiskPolicy = field(default_factory=RiskPolicy)

    def __post_init__(self):
        if self.strategy not in {'ema','sma'}:
            raise ValueError('Strategy must be ema or sma.')
        EMACrossoverStrategy(self.short_window, self.long_window, self.trend_window)
        if (isinstance(self.signal_ttl_seconds, bool) or not isinstance(self.signal_ttl_seconds, Integral)
                or self.signal_ttl_seconds <= 0):
            raise ValueError('Signal TTL must be a positive integer.')


@dataclass(frozen=True)
class SignalProposal:
    symbol: str
    direction: str = 'WAIT'
    validation_state: str = 'NO_TRADE'
    reason: str = ''
    signal_id: str | None = None
    timestamp: str | None = None
    expires_at: str | None = None
    reference_price: float | None = None
    entry: float | None = None
    entry_type: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    stop_distance: float | None = None
    target_distance: float | None = None
    reward_risk: float | None = None
    net_reward_risk: float | None = None
    quantity: float | None = None
    risk_amount: float | None = None
    quality: str = 'uncalibrated_rules'
    invalidation_conditions: tuple[str, ...] = ('expiry', 'gate_failure', 'quote_failure',
        'risk_failure', 'opposite_crossover', 'stop_breach', 'account_change')
    provenance: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)

    def to_dict(self):
        def json_safe(value):
            if isinstance(value, Real) and not math.isfinite(value):
                return None
            if isinstance(value, dict):
                return {key: json_safe(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [json_safe(item) for item in value]
            return value
        return json.loads(json.dumps(json_safe(asdict(self)), default=str, allow_nan=False))

    def is_expired(self, now):
        return self.expires_at is None or utc_timestamp(now, 'Decision time') >= utc_timestamp(self.expires_at, 'Expiry')


class StrategyEngine:
    def __init__(self, settings: AppSettings, config=StrategyConfig()):
        self.settings, self.config = settings, config
        self.strategy = (EMACrossoverStrategy(config.short_window, config.long_window, config.trend_window)
                         if config.strategy == 'ema' else MovingAverageStrategy(config.short_window, config.long_window))

    def evaluate(self, data, quote, *, symbol, interval, now, account: RiskSnapshot | None,
                 prior_signal_ids=()):
        """Pure evaluation: callers persist IDs and must revalidate before any Paper order."""
        symbol = str(symbol).strip().upper()
        origin = dict(bars=dict(data.attrs) if isinstance(data, pd.DataFrame) else {},
                      quote=dict(quote) if isinstance(quote, dict) else {})
        def wait(reason, **fields):
            return SignalProposal(symbol=symbol, reason=reason, provenance=origin, **fields)
        try:
            decision = utc_timestamp(now, 'Decision time')
            if self.settings.trading_mode != 'paper' or not self.settings.paper_trading_enabled:
                return wait('Only Alpaca Paper proposals are enabled.')
            if symbol not in INSTRUMENTS:
                return wait('Instrument is not in the verified catalog.')
            if not isinstance(data, pd.DataFrame) or data.attrs.get('interval') != interval:
                return wait('Missing data or interval mismatch.')
            completed = select_completed_bars(data, symbol, decision)
            if completed.empty:
                return wait('No completed operational bars.')
            source = ('Dati storici reali Alpaca Crypto' if '/' in symbol else
                      'Dati storici reali Alpaca IEX (copertura venue parziale)')
            if (data.attrs.get('source') != source
                    or ('data_quality' in data and not data['data_quality'].eq(source).all())):
                return wait('Missing or contradictory bar source metadata.')
            if not isinstance(quote, dict):
                return wait('Current bid/ask quote is required.')
            if (quote.get('is_synthetic', False) is not False
                    or quote.get('quality', 'real') != 'real'):
                return wait('Synthetic or unknown quote provenance is not operational.')
            bid, ask, midpoint = (quote.get(key) for key in ('bid','ask','price'))
            if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
                   for value in (bid, ask, midpoint)) or not 0 < bid <= ask:
                return wait('Invalid bid/ask quote.')
            if not math.isclose(midpoint, bid+(ask-bid)/2, rel_tol=1e-12):
                return wait('Quote midpoint contradicts bid/ask.')
            quote_time = utc_timestamp(quote.get('timestamp'), 'Quote timestamp')
            quote_source = 'Alpaca Crypto latest quote' if '/' in symbol else 'Alpaca IEX latest quote'
            if quote.get('source') != quote_source or not 0 <= (decision-quote_time).total_seconds() <= 120:
                return wait('Quote source or freshness is not verified.')
            if not isinstance(account, RiskSnapshot):
                return wait('Verified Paper risk snapshot is required.')
            if not 0 <= (decision-utc_timestamp(account.observed_at, 'Account timestamp')).total_seconds() <= 45:
                return wait('Account risk snapshot is stale or future.')
            signals = self.strategy.generate_signals(completed)
            if signals.empty or len(signals) < max(self.config.long_window+1, self.config.levels.atr_period+1):
                return wait('Insufficient indicator history.')
            latest = signals.iloc[-1]
            side = {1:'BUY', -1:'SELL'}.get(int(latest['signal']))
            if side is None:
                return wait('No new crossover; WAIT.')
            timestamp = utc_timestamp(completed.attrs['last_completed_at'], 'Signal close')
            expiry = min(timestamp+pd.Timedelta(seconds=self.config.signal_ttl_seconds),
                         quote_time+pd.Timedelta(seconds=120))
            if decision >= expiry:
                return wait('Signal expired.', timestamp=timestamp.isoformat(), expires_at=expiry.isoformat())
            identity = dict(account=account.account_id, symbol=symbol, interval=interval, side=side,
                            timestamp=timestamp.isoformat())
            signal_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            if signal_id in prior_signal_ids:
                return wait('Duplicate signal already consumed.', signal_id=signal_id)
            entry = float(ask if side == 'BUY' else bid)
            levels = plan_levels(completed, side, entry, ask-bid, self.config.levels)
            size = size_proposal(self.settings, account, side, levels, ask-bid, self.config.risk, symbol=symbol)
            if size['net_reward_risk'] < self.config.levels.min_reward_risk:
                return wait('Net reward/risk after costs is insufficient.')
            indicators = {key: float(latest[key]) if key in latest and pd.notna(latest[key]) else None
                          for key in ('short_ma','long_ma','ema50','rsi14','relative_volume')}
            indicators['atr'] = levels['atr']
            return SignalProposal(symbol=symbol, direction=side, validation_state='PAPER_PROPOSAL',
                reason=str(latest['signal_reason'])+('; reduce owned long only, no short entry' if side == 'SELL' else ''),
                signal_id=signal_id, timestamp=timestamp.isoformat(), expires_at=expiry.isoformat(),
                reference_price=float(latest['close']), entry_type='ask_reference' if side=='BUY' else 'bid_reference_exit_long',
                provenance=origin, indicators=indicators, **{key:value for key,value in levels.items() if key!='atr'},
                **size)
        except (BarTimingError, RiskViolationError, ValueError, TypeError, KeyError, OverflowError) as exc:
            return wait(str(exc))
