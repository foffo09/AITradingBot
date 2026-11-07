"""Dashboard numbers must preserve missing values and provenance."""
import pandas as pd
import pytest

from src.ui.dashboard_metrics import dashboard_summary, market_summary

NOW = pd.Timestamp('2026-11-07T12:00:00Z')


def test_local_summary_uses_ledger_values_and_utc_closed_pnl():
    result = dashboard_summary('simulation', account={'initial_eur': 100, 'eur_usd_rate': 1.1},
        overview={'current_capital': 120, 'cash': 70, 'total_pnl': 10, 'market_value': 50,
                  'fees': 2, 'max_drawdown_pct': 7, 'equity_curve': [{'equity': 130}, {'equity': 120}]},
        history=[{'closed_at': '2026-11-07T01:00:00+02:00', 'net_pnl': 99},
                 {'closed_at': '2026-11-07T10:00:00Z', 'net_pnl': 3},
                 {'closed_at': None, 'net_pnl': None}], now=NOW)
    assert result == {'capital': pytest.approx(110), 'equity': 120, 'cash': 70, 'daily_pnl': 3,
                      'cumulative_pnl': 10, 'drawdown': 7, 'exposure_value': 50,
                      'exposure_pct': pytest.approx(41.6666667), 'fees': 2, 'source': 'simulation'}


def test_missing_local_values_are_unknown_and_explicit_empty_history_is_zero():
    result = dashboard_summary('demo', overview={'max_drawdown_pct': 0})
    assert all(value is None for key, value in result.items() if key != 'source')
    assert dashboard_summary('demo', history=[], now=NOW)['daily_pnl'] == 0


def test_paper_never_borrows_ledger_capital_pnl_or_fees():
    result = dashboard_summary('paper', account={'equity': '120', 'last_equity': '100', 'cash': '30',
        'initial_eur': 900, 'fees': 10}, positions=[{'market_value': '-90'}],
        overview={'current_capital': 999, 'fees': 22}, history=[], now=NOW)
    assert result['daily_pnl'] == 20
    assert result['exposure_pct'] == 75
    assert result['source'] == 'paper'
    assert all(result[key] is None for key in ('capital', 'cumulative_pnl', 'drawdown', 'fees'))


@pytest.mark.parametrize('positions,expected', [(None, None), ([{'market_value': 5}, {}], None), ([], 0)])
def test_paper_exposure_requires_complete_positions(positions, expected):
    assert dashboard_summary('paper', positions=positions)['exposure_value'] == expected


def test_invalid_daily_history_is_not_silently_dropped():
    assert dashboard_summary('demo', history=[{'closed_at': 'bad', 'net_pnl': 5}], now=NOW)['daily_pnl'] is None
    assert dashboard_summary('demo', history=[{'closed_at': NOW, 'net_pnl': float('nan')}], now=NOW)['daily_pnl'] is None


def quote(**changes):
    return dict({'bid': 99, 'ask': 101, 'price': 999, 'timestamp': NOW.isoformat(),
                 'source': 'Alpaca IEX latest quote'}, **changes)


def test_real_quote_computes_midpoint_and_spread_without_trusting_price():
    result = market_summary(quote=quote(), quality='real', now=NOW)
    assert (result['bid'], result['ask'], result['price'], result['spread'], result['spread_bps']) == (99, 101, 100, 2, 200)
    assert result['state'] == 'fresh'
    assert result['age_seconds'] == 0


@pytest.mark.parametrize('changes', [{'bid': True}, {'ask': float('inf')}, {'bid': 102},
    {'timestamp': '2026-11-07T12:00:00'}, {'timestamp': NOW + pd.Timedelta(seconds=1)},
    {'timestamp': NOW - pd.Timedelta(seconds=121)}, {'source': 'synthetic demo'}, {'source': ''}])
def test_invalid_quote_never_displays_live_prices(changes):
    result = market_summary(quote=quote(**changes), quality='real', now=NOW)
    assert all(result[key] is None for key in ('bid', 'ask', 'price', 'spread', 'spread_bps'))
    assert result['state'] != 'fresh'


def test_demo_quote_never_becomes_live_and_history_is_explicit():
    data = pd.DataFrame({'timestamp': [NOW - pd.Timedelta(days=1), NOW], 'close': [80, 100]})
    data.attrs.update(source='Serie sintetica locale', quality='synthetic')
    result = market_summary(quote=quote(), data=data, quality='synthetic', now=NOW)
    assert result['bid'] is None and result['ask'] is None
    assert result['price'] == 100 and result['change_pct'] == 25
    assert result['state'] == 'synthetic'
    assert result['source'] == 'Serie sintetica locale'


def test_real_label_cannot_override_synthetic_frame_metadata():
    data = pd.DataFrame({'timestamp': [NOW], 'close': [100], 'is_synthetic': [True]})
    data.attrs.update(source='Alpaca', quality='real')
    assert market_summary(data=data, quality='real', now=NOW)['state'] == 'synthetic'


def test_historical_close_does_not_claim_to_be_live_quote():
    data = pd.DataFrame({'timestamp': [NOW - pd.Timedelta(days=1), NOW], 'close': [50, 55]})
    data.attrs.update(source='Alpaca IEX', quality='real')
    result = market_summary(data=data, now=NOW)
    assert result['state'] == 'historical'
    assert result['price'] == 55
    assert result['change_pct'] == pytest.approx(10)
    assert result['spread'] is None


def test_local_exposure_can_use_complete_positions_when_overview_is_missing():
    result = dashboard_summary('simulation', positions=[{'market_value': 20}, {'market_value': -5}])
    assert result['exposure_value'] == 25
    assert dashboard_summary('simulation', positions=[{}])['exposure_value'] is None


def test_drawdown_requires_valid_portfolio_curve():
    assert dashboard_summary('demo', overview={'max_drawdown_pct': 3,
        'equity_curve': [{'equity': float('nan')}]})['drawdown'] is None


def test_local_positions_use_ledger_quantity_and_market_price():
    result = dashboard_summary('simulation', positions=[{'quantity': 2, 'market_price': 15}])
    assert result['exposure_value'] == 30
    assert dashboard_summary('simulation', positions=[{'quantity': 2}])['exposure_value'] is None
