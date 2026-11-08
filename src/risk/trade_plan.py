"""Risk sizing for proposals only; all execution-time checks remain mandatory."""
from dataclasses import dataclass
import math
from numbers import Integral, Real

from config.settings import AppSettings
from src.risk.risk_manager import RiskManager, RiskViolationError


@dataclass(frozen=True)
class RiskSnapshot:
    account_id: str
    observed_at: str
    equity: float
    cash: float
    exposure: float
    pnl_today: float
    peak_equity: float
    orders_today: int
    positions_count: int
    position_quantity: float
    verified: bool = False
    scope: str = 'paper'
    position_symbol: str = ''


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: float = .005
    max_drawdown_fraction: float = .10
    max_trades: int = 5

    def __post_init__(self):
        for value in (self.risk_fraction, self.max_drawdown_fraction):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError('Risk fractions must be finite and in (0,1].')
        if isinstance(self.max_trades, bool) or not isinstance(self.max_trades, Integral) or self.max_trades <= 0:
            raise ValueError('Trade limit must be a positive integer.')


def size_proposal(settings: AppSettings, snapshot: RiskSnapshot, side, levels, spread, policy=RiskPolicy(), *, symbol):
    if not symbol or snapshot.position_symbol != symbol:
        raise RiskViolationError('Position snapshot symbol does not match requested symbol.')
    manager = RiskManager(settings)
    if (settings.trading_mode != 'paper' or not settings.paper_trading_enabled
            or snapshot.verified is not True or snapshot.scope != 'paper' or not snapshot.account_id):
        raise RiskViolationError('A verified Paper account snapshot is required.')
    values = (snapshot.equity, snapshot.cash, snapshot.exposure, snapshot.pnl_today,
              snapshot.peak_equity, snapshot.position_quantity)
    if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) for value in values):
        raise RiskViolationError('Incomplete or invalid account risk values.')
    if (snapshot.equity <= 0 or snapshot.peak_equity < snapshot.equity
            or min(snapshot.cash, snapshot.exposure, snapshot.position_quantity) < 0):
        raise RiskViolationError('Account risk values are inconsistent.')
    for value in (snapshot.orders_today, snapshot.positions_count):
        if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
            raise RiskViolationError('Account counters must be nonnegative integers.')
    if snapshot.position_quantity > 0 and snapshot.positions_count == 0:
        raise RiskViolationError('Held quantity contradicts position count.')
    if (snapshot.peak_equity-snapshot.equity)/snapshot.peak_equity >= policy.max_drawdown_fraction:
        raise RiskViolationError('Maximum drawdown reached.')
    if snapshot.orders_today >= min(policy.max_trades, settings.paper_max_daily_orders):
        raise RiskViolationError('Daily trade limit reached.')
    if not manager.check_daily_loss_limit(snapshot.pnl_today):
        raise RiskViolationError('Daily loss limit reached.')
    if side == 'BUY' and snapshot.position_quantity == 0 and snapshot.positions_count >= settings.max_positions:
        raise RiskViolationError('Maximum position count reached.')
    for value in (levels['entry'], levels['stop_distance'], levels['target_distance'], spread):
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value < 0:
            raise RiskViolationError('Invalid numeric trade levels or spread.')
    if min(levels['entry'], levels['stop_distance'], levels['target_distance']) <= 0:
        raise RiskViolationError('Trade distances and entry must be positive.')
    entry = levels['entry']
    cost = entry*2*(settings.commission_bps+settings.slippage_bps)/10000 + max(spread, entry*settings.spread_bps/10000)
    unit_risk = levels['stop_distance']+cost
    net_reward_risk = (levels['target_distance']-cost)/unit_risk
    budget = min(snapshot.equity, settings.initial_capital_usd)*policy.risk_fraction
    quantity = budget/unit_risk
    exposure_cap = min(snapshot.equity, settings.initial_capital_usd)*settings.risk_max_exposure_fraction
    if side == 'BUY':
        quantity = min(quantity, manager.calculate_position_size(snapshot.cash, entry),
                       (exposure_cap-snapshot.exposure)/entry,
                       snapshot.cash/(entry+cost))
    else:
        quantity = min(quantity, snapshot.position_quantity)
    if not all(math.isfinite(value) for value in (quantity, quantity*1e8, unit_risk, cost, net_reward_risk)):
        raise RiskViolationError('Trade sizing exceeds finite numeric bounds.')
    quantity = math.floor(quantity*1e8)/1e8
    if not math.isfinite(quantity) or quantity <= 0:
        raise RiskViolationError('No quantity allowed by cash, exposure or held long position.')
    result = manager.validate_order(side=side.lower(), quantity=quantity, price=entry,
                                    available_cash=snapshot.cash, current_position=snapshot.position_quantity,
                                    pnl_today=snapshot.pnl_today)
    if not result.ok:
        raise RiskViolationError(result.reason)
    return dict(quantity=quantity, risk_amount=quantity*unit_risk,
                net_reward_risk=net_reward_risk)
