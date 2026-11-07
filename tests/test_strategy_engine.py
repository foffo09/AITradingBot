from dataclasses import replace
import json

import pandas as pd
import pytest

from config.settings import AppSettings
from src.strategy.engine import StrategyConfig, StrategyEngine
from src.risk.trade_plan import RiskSnapshot

NOW = pd.Timestamp('2026-11-07T15:00:00Z')


def fixture(side='BUY'):
    closes = [100.]*40+([99.,98.,102.] if side=='BUY' else [101.,102.,98.])
    data = pd.DataFrame(dict(timestamp=pd.date_range(end=NOW-pd.Timedelta(minutes=2), periods=len(closes),freq='min'),
        close=closes, open=closes, high=[x+1 for x in closes], low=[x-1 for x in closes], volume=1000.,
        is_synthetic=False, data_quality='Dati storici reali Alpaca Crypto'))
    data.attrs=dict(quality='real', source='Dati storici reali Alpaca Crypto', interval='1Min',
        bar_calendar='24/7', session_scope='continuous', bar_time_contract='alpaca-start-v1', fetched_at=NOW.isoformat())
    bid,ask=(103.9,104.) if side=='BUY' else (96.,96.1)
    quote=dict(bid=bid,ask=ask,price=bid+(ask-bid)/2, timestamp=(NOW-pd.Timedelta(seconds=10)).isoformat(),
               source='Alpaca Crypto latest quote', receipt_marker='unchanged')
    settings=AppSettings(trading_mode='paper',alpaca_api_key='fixture',alpaca_secret_key='fixture',
                         initial_capital_eur=10000,eur_usd_rate=1)
    account=RiskSnapshot('fixture', NOW.isoformat(),10000,9000,1000,0,10000,0,1,10,True,position_symbol="BTC/USD")
    return data,quote,settings,account


def evaluate(data=None,quote=None,settings=None,account=None,side='BUY',config=None,**kwargs):
    default_data,default_quote,default_settings,default_account=fixture(side)
    return StrategyEngine(settings or default_settings, config or StrategyConfig(short_window=2,long_window=3,trend_window=4)).evaluate(
        default_data if data is None else data, default_quote if quote is None else quote,
        symbol=kwargs.pop('symbol','BTC/USD'), interval=kwargs.pop('interval','1Min'),
        now=kwargs.pop('now',NOW), account=account or default_account, **kwargs)


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_valid_proposal_includes_entry_levels_risk_expiry_and_metadata(side):
    data,quote,settings,account=fixture(side)
    original=data.copy(deep=True)
    result=evaluate(data,quote,settings,account,side=side)
    assert result.direction==side, result.reason
    assert result.validation_state=='PAPER_PROPOSAL'
    assert result.entry==quote['ask' if side=='BUY' else 'bid']
    assert result.reward_risk>=1.5 and result.net_reward_risk>=1.5
    assert result.stop_loss<result.entry<result.take_profit if side=='BUY' else result.take_profit<result.entry<result.stop_loss
    assert result.risk_amount<=50
    assert result.quantity>0
    if side=='SELL': assert result.quantity<=account.position_quantity
    assert not result.is_expired(NOW)
    assert result.is_expired(pd.Timestamp(result.expires_at))
    assert result.reference_price==data.iloc[-1]['close']
    assert result.provenance['quote']==quote
    pd.testing.assert_frame_equal(data,original)
    assert json.loads(json.dumps(result.to_dict()))['direction']==side
    assert 'probability' not in result.to_dict()


@pytest.mark.parametrize('change', ['synthetic','missing_origin','source_conflict','row_conflict', 'future_bars',
    'stale_bars','missing_contract','interval','quote_old','quote_future','quote_naive','quote_source',
    'quote_crossed','quote_bool','quote_midpoint','quote_synthetic','quote_quality_conflict','quote_missing','snapshot_old','account_unverified','daily_loss',
    'max_drawdown','max_trades','cash_missing','unknown_symbol','demo'])
def test_invalid_data_or_risk_returns_no_trade(change):
    data,quote,settings,account=fixture()
    kwargs={}
    if change=='synthetic': data['is_synthetic']=True
    if change=='missing_origin': data.attrs.pop('quality')
    if change=='source_conflict': data.attrs['source']='synthetic fixture'
    if change=='row_conflict': data.loc[0,'data_quality']='synthetic fixture'
    if change=='future_bars': data['timestamp']+=pd.Timedelta(days=1)
    if change=='stale_bars': data['timestamp']-=pd.Timedelta(days=1)
    if change=='missing_contract': data.attrs.pop('bar_time_contract')
    if change=='interval': kwargs['interval']='5Min'
    if change=='quote_old': quote['timestamp']=(NOW-pd.Timedelta(seconds=121)).isoformat()
    if change=='quote_future': quote['timestamp']=(NOW+pd.Timedelta(seconds=1)).isoformat()
    if change=='quote_naive': quote['timestamp']='2026-11-07T15:00:00'
    if change=='quote_source': quote['source']='Alpaca IEX latest quote'
    if change=='quote_crossed': quote['bid']=200
    if change=='quote_bool': quote['bid']=True
    if change=='quote_midpoint': quote['price']=50
    if change=='quote_synthetic': quote['is_synthetic']=True
    if change=='quote_quality_conflict': quote['quality']='synthetic'
    if change=='quote_missing': quote={}
    if change=='snapshot_old': account=replace(account,observed_at=(NOW-pd.Timedelta(seconds=46)).isoformat())
    if change=='account_unverified': account=replace(account,verified=False)
    if change=='daily_loss': account=replace(account,pnl_today=-500)
    if change=='max_drawdown': account=replace(account,peak_equity=13000)
    if change=='max_trades': account=replace(account,orders_today=5)
    if change=='cash_missing': account=replace(account,cash=None)
    if change=='unknown_symbol': kwargs['symbol']='XAU/USD'
    if change=='demo': settings=AppSettings(trading_mode='demo')
    result=evaluate(data,quote,settings,account,**kwargs)
    assert result.direction=='WAIT'
    assert result.validation_state=='NO_TRADE'
    assert result.entry is None and result.quantity is None
    assert result.reason


def test_duplicate_ids_are_stable_and_caller_can_block_replay_after_restart():
    first=evaluate()
    assert first.signal_id==evaluate().signal_id
    again=evaluate(prior_signal_ids={first.signal_id})
    assert again.direction=='WAIT' and 'Duplicate' in again.reason
    assert first.signal_id!=evaluate(account=replace(fixture()[3],account_id='other-account')).signal_id


def test_expired_bar_event_cannot_be_renewed_by_a_new_quote():
    result=evaluate(config=StrategyConfig(short_window=2,long_window=3,trend_window=4,signal_ttl_seconds=30))
    assert result.direction=='WAIT' and 'expired' in result.reason


def test_flat_market_waits_and_unowned_sell_never_opens_a_short():
    data,quote,settings,account=fixture()
    data.loc[:,['open','close']]=100
    data['high'],data['low']=101,99
    assert evaluate(data,quote,settings,account).direction=='WAIT'
    result=evaluate(side='SELL',account=replace(account,position_quantity=0))
    assert result.direction=='WAIT'


def test_engine_calls_existing_gate_and_cannot_send_orders(monkeypatch):
    import src.strategy.engine as module
    from src.broker.alpaca_client import AlpacaClient
    actual=module.select_completed_bars
    calls=[]
    def gate(*args,**kwargs):
        calls.append(args[1]); return actual(*args,**kwargs)
    monkeypatch.setattr(module,'select_completed_bars',gate)
    monkeypatch.setattr(AlpacaClient,'submit_order',lambda *args,**kwargs: pytest.fail('strategy sent an order'))
    assert evaluate().direction=='BUY'
    assert calls==['BTC/USD']


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_position_snapshot_for_another_instrument_cannot_be_reused(side):
    account=replace(fixture(side)[3], position_symbol='AAPL')
    result=evaluate(side=side,account=account)
    assert result.direction=='WAIT'
    assert 'symbol' in result.reason.lower()


def test_rejected_nonfinite_quote_still_has_a_json_safe_dashboard_contract():
    quote=dict(fixture()[1],bid=float('nan'))
    result=evaluate(quote=quote)
    assert result.direction=='WAIT'
    payload=result.to_dict()
    json.dumps(payload,allow_nan=False)
    assert payload['provenance']['quote']['bid'] is None


def test_risk_configuration_change_cannot_renew_a_consumed_bar_event():
    from src.risk.trade_plan import RiskPolicy
    first=evaluate()
    config=StrategyConfig(short_window=2,long_window=3,trend_window=4,risk=RiskPolicy(risk_fraction=.004))
    second=evaluate(config=config)
    assert first.signal_id==second.signal_id
    assert evaluate(config=config,prior_signal_ids={first.signal_id}).direction=='WAIT'
