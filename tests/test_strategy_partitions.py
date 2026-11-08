import pandas as pd
import pytest

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.backtesting.walk_forward import evaluate_strategy_partitions
from src.strategy.levels import LevelConfig


class FixedStrategy:
    warmup_bars = 3

    def generate_signals(self, data):
        assert data.attrs['source'] == 'Synthetic fixture'
        return data.assign(signal=data['fixture_signal'], signal_reason='fixed fixture')


def market():
    starts = pd.date_range('2024-01-01', periods=15, freq='h', tz='UTC')
    data = pd.DataFrame({
        'timestamp': starts, 'closed_at': starts + pd.Timedelta(hours=1),
        'open': [99, 99, 99, 100, 100] * 3,
        'close': [99, 99, 99, 100, 100] * 3,
        'high': [100, 100, 100, 101, 101] * 3,
        'low': [98, 98, 98, 99, 99] * 3,
        'fixture_signal': [0, 0, 1, -1, 0] * 3,
    })
    data.attrs['source'] = 'Synthetic fixture'
    return data


def evaluate(data=None, **overrides):
    options = dict(
        engine=BacktestEngine(AppSettings(trading_mode='paper')),
        strategy=FixedStrategy(), training_bars=5, validation_bars=5,
        as_of='2024-01-01T15:00:00Z', data_source='Synthetic fixture',
        backtest_options={'initial_capital': 1000, 'commission_bps': 10,
                          'spread_bps': 20, 'slippage_bps': 30},
    )
    options.update(overrides)
    return evaluate_strategy_partitions(market() if data is None else data, **options)


def test_partitions_are_disjoint_and_reuse_same_costed_engine():
    result = evaluate()
    assert result['data_source'] == 'Synthetic fixture'
    assert result['excluded_incomplete_bars'] == 0
    for name, start, end in [('training', 0, 5), ('validation', 5, 10), ('out_of_sample', 10, 15)]:
        partition = result[name]
        assert (partition['start'], partition['end'], partition['bars']) == (start, end, 5)
        assert partition['metrics']['initial_capital'] == 1000
        assert partition['metrics']['total_trades'] == 1
        assert partition['metrics']['total_transaction_costs'] > 0
        assert partition['metrics']['final_capital'] == pytest.approx(
            1000 + partition['metrics']['net_pnl'])
    assert result['training']['end_timestamp'] < result['validation']['start_timestamp']
    assert result['validation']['end_timestamp'] < result['out_of_sample']['start_timestamp']


def test_future_edits_cannot_change_training_or_validation():
    baseline = evaluate()
    data = market()
    data.loc[10:, ['open', 'close', 'high', 'low']] *= 2
    changed = evaluate(data)
    assert baseline['training'] == changed['training']
    assert baseline['validation'] == changed['validation']
    assert baseline['out_of_sample']['metrics'] != changed['out_of_sample']['metrics']


def test_incomplete_tail_is_excluded_before_splitting():
    result = evaluate(as_of='2024-01-01T14:30:00Z')
    assert result['excluded_incomplete_bars'] == 1
    assert result['out_of_sample']['bars'] == 4
    assert result['out_of_sample']['last_closed_at'] == '2024-01-01T14:00:00+00:00'


def test_protection_is_forwarded_to_existing_simulator():
    result = evaluate(protection=LevelConfig(atr_period=2, structure_window=2))
    for name in ('training', 'validation', 'out_of_sample'):
        trade = result[name]['metrics']['trade_history'][0]
        assert trade['stop_loss'] == 97
        assert trade['take_profit'] == 106
        assert trade['realized_r'] < 0


@pytest.mark.parametrize('field', ['timestamp', 'closed_at'])
def test_naive_missing_duplicate_or_unordered_timestamps_are_rejected(field):
    for value in [None, '2024-01-01T02:00:00', '2024-01-01T00:00:00Z']:
        data = market()
        data[field] = data[field].astype(object)
        data.loc[2, field] = value
        with pytest.raises(ValueError):
            evaluate(data)
    with pytest.raises(ValueError):
        evaluate(market().drop(columns=field))


@pytest.mark.parametrize('as_of', [None, 'invalid', '2024-01-02'])
def test_reference_time_requires_timezone(as_of):
    with pytest.raises(ValueError):
        evaluate(as_of=as_of)


def test_closed_at_must_be_after_start():
    data = market()
    data['closed_at'] = data['timestamp']
    with pytest.raises(ValueError, match='after its bar timestamp'):
        evaluate(data)


@pytest.mark.parametrize('overrides', [
    {'training_bars': 0}, {'validation_bars': True}, {'training_bars': 2.5},
    {'training_bars': 3}, {'validation_bars': 3}, {'training_bars': 10},
    {'as_of': '2024-01-01T10:00:00Z'}, {'data_source': '  '},
])
def test_invalid_partition_lengths_or_missing_oos_rejected(overrides):
    with pytest.raises(ValueError):
        evaluate(**overrides)



def test_overlapping_intervals_are_rejected():
    data = market()
    data['closed_at'] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='must not overlap'):
        evaluate(data)


def test_optional_default_window_override_is_accepted():
    result = evaluate(backtest_options={'long_window': None})
    assert result['training']['bars'] == 5
