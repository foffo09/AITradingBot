from dataclasses import replace
import pytest

from config.settings import AppSettings
from src.risk.trade_plan import RiskPolicy, RiskSnapshot, size_proposal as _size_proposal
from src.risk.risk_manager import RiskViolationError


def size_proposal(*args, **kwargs):
    return _size_proposal(*args, **kwargs, symbol="SPY")


def settings():
    return AppSettings(trading_mode='paper', alpaca_api_key='fixture', alpaca_secret_key='fixture',
                       initial_capital_eur=10000, eur_usd_rate=1)


def snapshot():
    return RiskSnapshot('fixture-account', '2026-11-07T12:00:00Z', 10000, 9000, 1000, 0, 10000, 0, 1, 10, True, position_symbol="SPY")


LEVELS = dict(entry=100, stop_distance=5, target_distance=10)


def test_risk_sizing_respects_loss_budget_notional_and_global_exposure():
    result = size_proposal(settings(), snapshot(), 'BUY', LEVELS, .1)
    assert result['quantity']*5 <= 50
    assert result['risk_amount'] <= 50
    assert result['quantity']*100 <= 2000
    assert snapshot().exposure+result['quantity']*100 <= 5000


@pytest.mark.parametrize('changes', [dict(verified=False), dict(scope='demo'), dict(cash=None),
    dict(equity=float('nan')), dict(peak_equity=13000), dict(pnl_today=-500),
    dict(orders_today=5), dict(exposure=5000), dict(positions_count=3,position_quantity=0),
    dict(position_quantity=-1), dict(orders_today=True), dict(positions_count=0)])
def test_risk_failures_do_not_produce_a_size(changes):
    with pytest.raises(RiskViolationError):
        size_proposal(settings(), replace(snapshot(), **changes), 'BUY', LEVELS, .1)


def test_sell_is_limited_to_owned_long_and_never_short():
    assert size_proposal(settings(), snapshot(), 'SELL', LEVELS, .1)['quantity'] <= 10
    with pytest.raises(RiskViolationError):
        size_proposal(settings(), replace(snapshot(), position_quantity=0), 'SELL', LEVELS, .1)


@pytest.mark.parametrize('policy', [dict(risk_fraction=0), dict(risk_fraction=True),
                                   dict(max_drawdown_fraction=float('inf')), dict(max_trades=0)])
def test_invalid_risk_policy_is_rejected(policy):
    with pytest.raises(ValueError): RiskPolicy(**policy)


@pytest.mark.parametrize('key,value', [('entry',True),('entry',float('inf')),('stop_distance',0),
                                     ('target_distance',-1),('stop_distance',None)])
def test_invalid_trade_levels_never_size_a_proposal(key,value):
    levels=dict(LEVELS,**{key:value})
    with pytest.raises(RiskViolationError): size_proposal(settings(),snapshot(),'BUY',levels,.1)


def test_loss_never_increases_the_same_trade_risk_budget():
    original=size_proposal(settings(),snapshot(),'BUY',LEVELS,.1)
    after_loss=size_proposal(settings(),replace(snapshot(),equity=9990,pnl_today=-10),'BUY',LEVELS,.1)
    assert after_loss['risk_amount'] <= original['risk_amount']
    assert after_loss['quantity'] <= original['quantity']


def test_risk_api_rejects_a_position_for_another_symbol():
    with pytest.raises(RiskViolationError,match='symbol'):
        size_proposal(settings(),replace(snapshot(),position_symbol='AAPL'),'SELL',LEVELS,.1)
