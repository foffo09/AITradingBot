"""Pure, versioned application boundary for analytical Paper proposals."""
import pandas as pd

from config.settings import AppSettings
from src.risk.trade_plan import RiskSnapshot
from src.strategy.engine import SignalProposal, StrategyConfig, StrategyEngine


def evaluate_proposal(*, settings: AppSettings, bars, quote, source: str, as_of,
                      symbol: str, interval: str, risk_snapshot: RiskSnapshot | None,
                      context: str, config: StrategyConfig = StrategyConfig(),
                      prior_signal_ids=()) -> dict:
    """Evaluate explicit inputs without I/O, environment settings or order authority.

    ``source`` must attest the untouched frame metadata; it never replaces it.
    Callers own verified snapshots, consumed-ID persistence and revalidation.
    """
    reason = None
    if context != 'paper':
        reason = 'Only the Paper context can produce an analytical proposal.'
    elif not isinstance(source, str) or not source.strip():
        reason = 'Explicit bar source is required.'
    elif not isinstance(bars, pd.DataFrame) or source != bars.attrs.get('source'):
        reason = 'Explicit bar source does not match original data metadata.'
    if reason:
        proposal = SignalProposal(symbol=str(symbol).strip().upper(), reason=reason,
            provenance=dict(bars=dict(bars.attrs) if isinstance(bars, pd.DataFrame) else {},
                            quote=dict(quote) if isinstance(quote, dict) else {}))
    else:
        proposal = StrategyEngine(settings, config).evaluate(
            bars, quote, symbol=symbol, interval=interval, now=as_of,
            account=risk_snapshot, prior_signal_ids=prior_signal_ids)
    return dict(contract_version='1', **proposal.to_dict())
