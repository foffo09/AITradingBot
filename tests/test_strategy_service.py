"""Offline application contract; quotes/bars are controlled test data, never a feed."""
from dataclasses import replace
import importlib
import json
import sys

import pandas as pd
import pytest

from config.settings import AppSettings
from src.risk.trade_plan import RiskSnapshot
from src.strategy.engine import StrategyConfig

NOW = pd.Timestamp('2026-11-07T15:00:00Z')
SOURCE = 'Dati storici reali Alpaca Crypto'


def inputs(side='BUY'):
    closes = [100.] * 40 + ([99., 98., 102.] if side == 'BUY' else [101., 102., 98.])
    bars = pd.DataFrame(dict(timestamp=pd.date_range(end=NOW-pd.Timedelta(minutes=2), periods=43, freq='min'),
        open=closes, close=closes, high=[x+1 for x in closes], low=[x-1 for x in closes],
        volume=1000., is_synthetic=False, data_quality=SOURCE))
    bars.attrs = dict(quality='real', source=SOURCE, interval='1Min', bar_calendar='24/7',
        session_scope='continuous', bar_time_contract='alpaca-start-v1', fetched_at=NOW.isoformat())
    bid, ask = (103.9, 104.) if side == 'BUY' else (96., 96.1)
    return dict(settings=AppSettings(trading_mode='paper', alpaca_api_key='fixture', alpaca_secret_key='fixture',
        initial_capital_eur=10000, eur_usd_rate=1), bars=bars,
        quote=dict(bid=bid, ask=ask, price=(bid+ask)/2, timestamp=(NOW-pd.Timedelta(seconds=10)).isoformat(),
            source='Alpaca Crypto latest quote'), source=SOURCE, as_of=NOW, symbol='BTC/USD', interval='1Min',
        risk_snapshot=RiskSnapshot('fixture', NOW.isoformat(), 10000, 9000, 1000, 0, 10000, 0, 1, 10,
            True, position_symbol='BTC/USD'), context='paper',
        config=StrategyConfig(short_window=2, long_window=3, trend_window=4))


def evaluate(args):
    from src.strategy.service import evaluate_proposal
    return evaluate_proposal(**args)


def assert_blocked(result):
    assert result['direction'] == 'WAIT'
    assert result['validation_state'] == 'NO_TRADE'
    assert result['reason']
    for field in ('entry', 'stop_loss', 'take_profit', 'quantity', 'risk_amount'):
        assert result[field] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_service_exposes_versioned_pure_proposal_without_changing_inputs(side):
    args = inputs(side)
    original_bars, original_quote = args['bars'].copy(deep=True), dict(args['quote'])
    result = evaluate(args)
    assert result['contract_version'] == '1'
    assert result['direction'] == side
    assert result['validation_state'] == 'PAPER_PROPOSAL'
    assert result['entry'] == args['quote']['ask' if side == 'BUY' else 'bid']
    assert result['quantity'] > 0
    if side == 'SELL':
        assert result['quantity'] <= 10
        assert 'reduce owned long' in result['reason']
    assert result['provenance']['bars'] == original_bars.attrs
    assert result['provenance']['quote'] == original_quote
    pd.testing.assert_frame_equal(args['bars'], original_bars)
    assert args['quote'] == original_quote
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('context', ['demo', 'sim', 'simulation', 'live', None])
def test_nonpaper_context_never_proposes_even_with_operational_looking_data(context):
    result = evaluate(dict(inputs(), context=context))
    assert_blocked(result)
    assert 'context' in result['reason'].lower()


@pytest.mark.parametrize('source', [None, '', 'synthetic fixture', 'Dati storici reali Alpaca IEX'])
def test_explicit_source_must_match_original_bar_metadata(source):
    result = evaluate(dict(inputs(), source=source))
    assert_blocked(result)
    assert 'source' in result['reason'].lower()


@pytest.mark.parametrize('change', ['missing_risk', 'incomplete_risk', 'unverified_risk', 'old_risk',
    'future_risk', 'stale_quote', 'future_quote', 'quote_source', 'synthetic', 'bar_source',
    'stale_bars', 'future_bars', 'duplicate_bars', 'nan_quote'])
def test_service_keeps_engine_provenance_freshness_and_risk_gates(change):
    args = inputs()
    if change == 'missing_risk': args['risk_snapshot'] = None
    if change == 'incomplete_risk': args['risk_snapshot'] = replace(args['risk_snapshot'], peak_equity=None)
    if change == 'unverified_risk': args['risk_snapshot'] = replace(args['risk_snapshot'], verified=False)
    if change in {'old_risk', 'future_risk'}:
        args['risk_snapshot'] = replace(args['risk_snapshot'], observed_at=(NOW+pd.Timedelta(seconds=-46 if change == 'old_risk' else 1)).isoformat())
    if change in {'stale_quote', 'future_quote'}:
        args['quote']['timestamp'] = (NOW+pd.Timedelta(seconds=-121 if change == 'stale_quote' else 1)).isoformat()
    if change == 'quote_source': args['quote']['source'] = 'other'
    if change == 'synthetic': args['bars']['is_synthetic'] = True
    if change == 'bar_source': args['bars'].attrs['source'] = 'synthetic fixture'
    if change in {'stale_bars', 'future_bars'}:
        args['bars']['timestamp'] += pd.Timedelta(days=-1 if change == 'stale_bars' else 1)
    if change == 'duplicate_bars': args['bars'].loc[1, 'timestamp'] = args['bars'].loc[0, 'timestamp']
    if change == 'nan_quote': args['quote']['bid'] = float('nan')
    result = evaluate(args)
    assert_blocked(result)
    if change == 'missing_risk': assert 'snapshot' in result['reason'].lower()
    if change == 'nan_quote': assert result['provenance']['quote']['bid'] is None


def test_flat_market_waits_without_operational_fields():
    args = inputs()
    args['bars'].loc[:, ['open', 'close']] = 100.
    args['bars']['high'], args['bars']['low'] = 101., 99.
    result = evaluate(args)
    assert_blocked(result)
    assert 'crossover' in result['reason'].lower()


def test_expiry_and_consumed_ids_cannot_be_renewed():
    args = inputs()
    first = evaluate(args)
    assert first['signal_id'] == evaluate(args)['signal_id']
    blocked = evaluate(dict(args, prior_signal_ids={first['signal_id']}))
    assert_blocked(blocked)
    assert 'duplicate' in blocked['reason'].lower()
    expired = evaluate(dict(args, config=replace(args['config'], signal_ttl_seconds=30)))
    assert_blocked(expired)
    assert 'expired' in expired['reason'].lower()


def test_import_and_evaluation_do_not_load_broker_storage_or_transport(monkeypatch):
    forbidden = ('src.broker', 'src.storage', 'src.api', 'streamlit', 'alpaca')
    original_import = __import__
    def guarded_import(name, *args, **kwargs):
        assert not any(name == prefix or name.startswith(prefix+'.') for prefix in forbidden), name
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr('builtins.__import__', guarded_import)
    monkeypatch.delitem(sys.modules, 'src.strategy.service', raising=False)
    importlib.import_module('src.strategy.service')
    args = inputs()
    monkeypatch.setattr(AppSettings, 'from_env', lambda: pytest.fail('service read environment'))
    assert evaluate(args)['direction'] == 'BUY'
