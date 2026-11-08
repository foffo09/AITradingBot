import numpy as np
import pandas as pd
import pytest

from src.strategy.levels import LevelConfig, plan_levels


def bars():
    close = np.linspace(95, 100, 40)
    return pd.DataFrame(dict(close=close, high=close+1, low=close-1))


@pytest.mark.parametrize('side,entry', [('BUY', 102), ('SELL', 93)])
def test_levels_use_atr_and_structure_with_correct_order(side, entry):
    data = bars()
    result = plan_levels(data, side, entry, spread=.1)
    assert result['atr'] == pytest.approx(2)
    assert result['reward_risk'] >= 1.5
    assert result['stop_distance'] >= max(3*.1, 1.5*result['atr'])
    if side == 'BUY': assert result['stop_loss'] < entry < result['take_profit']
    else: assert result['take_profit'] < entry < result['stop_loss']
    assert list(data.columns) == ['close', 'high', 'low']


@pytest.mark.parametrize('change', ['short', 'nan', 'flat', 'crossed', 'negative', 'boolean'])
def test_levels_reject_missing_or_invalid_volatility(change):
    data = bars()
    if change == 'short': data = data.head(5)
    if change == 'nan': data.loc[39, 'high'] = np.nan
    if change == 'flat': data.loc[:, ['close','high','low']] = 100
    if change == 'crossed': data.loc[39, 'low'] = 200
    if change == 'boolean': data['close'] = True
    if change == 'negative': data.loc[39, 'close'] = -1
    with pytest.raises(ValueError): plan_levels(data, 'BUY', 102)


def test_structure_rejects_target_with_insufficient_reward():
    data = bars()
    with pytest.raises(ValueError, match='reward'):
        plan_levels(data, 'BUY', 100)


@pytest.mark.parametrize('values', [dict(atr_period=True), dict(atr_multiple=0),
    dict(reward_risk=1), dict(min_spread_multiple=-1), dict(structure_window=0), dict(atr_multiple="invalid")])
def test_level_configuration_is_validated(values):
    with pytest.raises(ValueError): LevelConfig(**values)
