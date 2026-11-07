import pandas as pd
import pytest

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.strategy.levels import LevelConfig
from src.strategy.moving_average import MovingAverageStrategy


class FixtureStrategy:
    """Signals depend only on the row's explicit fixture input."""
    warmup_bars = 3

    def generate_signals(self, data):
        return data.assign(signal=data['fixture_signal'], signal_reason='fixture')


def market():
    return pd.DataFrame({
        'open': [99.] * 3 + [100.] * 4, 'close': [99.] * 3 + [100.] * 4,
        'high': [100.] * 3 + [101.] * 4, 'low': [98.] * 3 + [99.] * 4,
        'fixture_signal': [0, 0, 1, 0, 0, -1, 0],
    })


def run(data, **kwargs):
    settings = AppSettings(trading_mode='paper', alpaca_api_key='fake',
                           alpaca_secret_key='fake', paper_trading_enabled=True)
    return BacktestEngine(settings).run(
        data, strategy=kwargs.pop('strategy', FixtureStrategy()), initial_capital=1000,
        max_trade_fraction=.2, daily_loss_limit_fraction=1,
        commission_bps=kwargs.pop('commission_bps', 0),
        spread_bps=kwargs.pop('spread_bps', 0),
        slippage_bps=kwargs.pop('slippage_bps', 0), **kwargs,
    )


def protection():
    return LevelConfig(atr_period=2, atr_multiple=1.5, structure_window=2)


def test_explicit_sma_preserves_default_result():
    data = market().assign(close=[100, 100, 100, 102, 103, 99, 98])
    engine = BacktestEngine(AppSettings(trading_mode='paper'))
    default = engine.run(data, short_window=2, long_window=3)
    explicit = engine.run(data, strategy=MovingAverageStrategy(2, 3),
                          short_window=2, long_window=3)
    assert explicit.to_dict() == default.to_dict()


def test_custom_strategy_next_open_and_prefix_causality():
    data = market()
    data.loc[3, 'open'] = 105
    result = run(data)
    assert result.trade_history[0]['entry_market_price'] == 105
    assert result.trade_history[0]['opened_at'] == '3'
    full = FixtureStrategy().generate_signals(data)
    for length in range(3, len(data) + 1):
        pd.testing.assert_series_equal(
            FixtureStrategy().generate_signals(data.iloc[:length]).signal,
            full.signal.iloc[:length],
        )
    assert result.expectancy == pytest.approx(result.net_pnl)
    assert result.average_realized_r is None


@pytest.mark.parametrize(('low', 'high', 'expected', 'reason'), [
    (96, 107, 97, 'stop_loss'), (99, 107, 106, 'take_profit'),
])
def test_protection_includes_entry_bar_and_stop_wins_ambiguous_bar(low, high, expected, reason):
    data = market()
    data.loc[3, ['low', 'high']] = [low, high]
    result = run(data, protection=protection())
    trade = result.trade_history[0]
    assert trade['closed_at'] == '3'
    assert trade['exit_market_price'] == expected
    assert trade['exit_reason'] == reason
    assert trade['stop_loss'] == 97
    assert trade['take_profit'] == 106
    assert trade['realized_r'] == pytest.approx((expected - 100) / 3)
    assert result.average_realized_r == pytest.approx(trade['realized_r'])


@pytest.mark.parametrize(('opening', 'expected', 'reason'), [
    (90, 90, 'stop_loss'), (110, 106, 'take_profit'),
])
def test_protection_gap_fills_are_conservative(opening, expected, reason):
    data = market()
    data.loc[4, ['open', 'low', 'high', 'close']] = [opening, opening - 1, opening + 1, opening]
    result = run(data, protection=protection())
    trade = result.trade_history[0]
    assert trade['exit_market_price'] == expected
    assert trade['exit_reason'] == reason


def test_protection_costs_and_capital_accounting():
    data = market()
    data.loc[3, 'low'] = 90
    result = run(data, protection=protection(), commission_bps=10, spread_bps=20, slippage_bps=30)
    trade = result.trade_history[0]
    costs = sum(trade[key] for key in ('entry_fee', 'exit_fee', 'entry_spread', 'exit_spread',
                                      'entry_slippage', 'exit_slippage'))
    assert trade['net_pnl'] == pytest.approx(trade['gross_pnl'] - costs)
    assert result.final_capital == pytest.approx(1000 + result.net_pnl)
    assert result.total_transaction_costs == pytest.approx(costs)
    assert trade['realized_r'] == pytest.approx(trade['net_pnl'] / (trade['quantity'] * trade['stop_distance']))


def test_levels_use_prior_bars_only_and_future_edits_preserve_closed_trade():
    data = market()
    data.loc[3, 'low'] = 90
    first = run(data, protection=protection())
    data.loc[4:, ['high', 'low', 'close', 'open']] = [200, 150, 175, 175]
    second = run(data, protection=protection())
    assert first.trade_history == second.trade_history
    assert first.trade_history[0]['stop_distance'] == 3


@pytest.mark.parametrize('column', ['high', 'low'])
def test_protection_requires_valid_ohlc(column):
    with pytest.raises(ValueError, match='OHLC'):
        run(market().drop(columns=column), protection=protection())
    data = market()
    data.loc[4, column] = float('nan')
    with pytest.raises(ValueError, match='OHLC'):
        run(data, protection=protection())


def test_invalid_levels_do_not_silently_remove_protection():
    data = market()
    with pytest.raises(ValueError):
        run(data, protection=LevelConfig(atr_period=14))


def test_custom_strategy_rejects_invalid_signal_contract():
    class Invalid(FixtureStrategy):
        def generate_signals(self, data):
            return super().generate_signals(data).assign(signal=.5)
    with pytest.raises(ValueError, match='signals'):
        run(market(), strategy=Invalid())


@pytest.mark.parametrize('warmup', [True, 0, 1.5])
def test_custom_strategy_requires_valid_warmup(warmup):
    strategy = FixtureStrategy()
    strategy.warmup_bars = warmup
    with pytest.raises(ValueError, match='warmup_bars'):
        run(market(), strategy=strategy)


def test_custom_strategy_requires_history_for_next_open():
    with pytest.raises(ValueError, match='at least 4 bars'):
        run(market().iloc[:3])


def test_no_closed_trades_have_unavailable_expectancy_and_r():
    result = run(market().assign(fixture_signal=0), protection=protection())
    assert result.expectancy is None
    assert result.average_realized_r is None
    assert result.final_capital == 1000


def test_discretionary_exit_at_open_precedes_intrabar_stop():
    data = market()
    data.loc[3, 'fixture_signal'] = -1
    data.loc[4, 'low'] = 90
    result = run(data, protection=protection())
    assert result.trade_history[0]['exit_reason'] == 'fixture'
    assert result.trade_history[0]['exit_market_price'] == 100


def test_gap_stop_precedes_discretionary_exit():
    data = market()
    data.loc[3, 'fixture_signal'] = -1
    data.loc[4, ['open', 'low', 'close']] = [90, 89, 90]
    result = run(data, protection=protection())
    assert result.trade_history[0]['exit_reason'] == 'stop_loss'
    assert result.trade_history[0]['exit_market_price'] == 90


def test_strategy_cannot_replace_market_execution_prices():
    class Repricing(FixtureStrategy):
        def generate_signals(self, data):
            return super().generate_signals(data).assign(open=1)
    result = run(market(), strategy=Repricing())
    assert result.trade_history[0]['entry_market_price'] == 100


def test_real_ema_strategy_reuses_backtest_and_requires_its_own_warmup():
    from src.strategy.trend import EMACrossoverStrategy

    data = pd.DataFrame({'open': [100.] * 52, 'close': [100.] * 52})
    result = run(data, strategy=EMACrossoverStrategy())
    assert result.total_trades == 0
    with pytest.raises(ValueError, match='at least 52 bars'):
        run(data.iloc[:-1], strategy=EMACrossoverStrategy())
