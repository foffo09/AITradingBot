"""Invoke the signal fragment repeatedly without a full application rerun."""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.data.bar_timing import BarTimingError, select_completed_bars
from src.data.market_data import generate_synthetic_market_data
from src.strategy.moving_average import MovingAverageStrategy
from src.ui.presentation import money, signal_view
from src.ui.dashboard_metrics import market_summary


class State(dict):
    __getattr__ = dict.__getitem__


class Display:
    def __init__(self, state):
        self.session_state = state
        self.views = []
        self.messages = []

    def columns(self, count):
        return [self] * count

    def json(self, view):
        self.views.append(view)

    def markdown(self, text):
        self.messages.append(text)

    info = warning = caption = write = markdown

    def metric(self, *args, **kwargs):
        pass

    def expander(self, *args):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_periodic_signal_rechecks_frame_and_calendar_without_full_rerun():
    # Only compile the real fragment body: AppTest does not drive wall-clock timers.
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    fragment = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == '_signal_monitor')
    assert any(keyword.arg == 'run_every' and keyword.value.value == '15s'
               for keyword in fragment.decorator_list[0].keywords)
    fragment.decorator_list = []
    frame = generate_synthetic_market_data('SPY', periods=40)
    state = State(market_frame=frame, market_request=('SPY',), market_symbol='SPY',
                  market_quality='real', market_interval='1Day')
    display = Display(state)
    blocked = False
    calls = []

    def completed(data, symbol, now):
        calls.append((float(data.iloc[-1]['close']), now))
        if blocked:
            raise BarTimingError('feed no longer current')
        return data

    namespace = dict(st=display, datetime=datetime, timezone=timezone,
                     MovingAverageStrategy=MovingAverageStrategy,
                     select_completed_bars=completed, BarTimingError=BarTimingError,
                     signal_view=signal_view, _money_or_unavailable=money, market_summary=market_summary)
    exec(compile(ast.Module(body=[fragment], type_ignores=[]), str(Path('app.py')), 'exec'), namespace)
    monitor = namespace['_signal_monitor']
    monitor(('SPY',), 5, 10)
    first_price = display.views[-1]['price']
    state.market_frame.loc[state.market_frame.index[-1], 'close'] += 10
    monitor(('SPY',), 5, 10)
    assert display.views[-1]['price'] == first_price + 10
    blocked = True
    monitor(('SPY',), 5, 10)
    assert display.views[-1]['state'] == 'ANALISI STORICA — NON OPERATIVA'
    assert display.views[-1]['reason'] == 'feed no longer current'
    assert len(calls) == 3
    view_count = len(display.views)
    state['market_request'] = ('MSFT',)
    monitor(('SPY',), 5, 10)
    assert len(display.views) == view_count
    assert 'Segnale non disponibile' in display.messages[-1]


@pytest.mark.parametrize('case', ['valid', 'stale_quote', 'missing_quote', 'future_quote',
                                   'unknown_source', 'synthetic_rows', 'missing_origin',
                                   'synthetic_origin', 'missing_contract', 'stale_bars',
                                   'missing_source', 'contradictory_source', 'contradictory_rows', 'refresh_error'])
def test_signal_uses_real_backend_gate_and_requires_current_quote(case):
    now = pd.Timestamp('2026-10-28T15:00:00Z')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.to_pydatetime()
    frame = generate_synthetic_market_data('BTC/USD', periods=40)
    frame['timestamp'] = pd.date_range(end=now-pd.Timedelta(minutes=1), periods=40, freq='min')
    frame['is_synthetic'] = False
    frame['data_quality'] = 'Dati storici reali Alpaca Crypto'
    frame.attrs = dict(quality='real', interval='1Min', source='Dati storici reali Alpaca Crypto',
                       bar_time_contract='alpaca-start-v1', bar_calendar='24/7',
                       session_scope='continuous', fetched_at=now.isoformat())
    quote = dict(bid=99, ask=101, price=100, timestamp=(now-pd.Timedelta(seconds=10)).isoformat(),
                 source='Alpaca Crypto latest quote', receipt_marker='preserve-me')
    if case == 'stale_quote': quote['timestamp'] = (now-pd.Timedelta(seconds=121)).isoformat()
    if case == 'future_quote': quote['timestamp'] = (now+pd.Timedelta(seconds=1)).isoformat()
    if case == 'missing_quote': quote = None
    if case == 'unknown_source': quote['source'] = 'unknown'
    if case == 'synthetic_rows': frame.loc[0, 'is_synthetic'] = True
    if case == 'missing_origin': frame.attrs.pop('quality')
    if case == 'synthetic_origin': frame.attrs['quality'] = 'synthetic'
    if case == 'missing_contract': frame.attrs.pop('bar_time_contract')
    if case == 'missing_source': frame.attrs.pop('source')
    if case == 'contradictory_source': frame.attrs['source'] = 'Serie sintetica locale'
    if case == 'contradictory_rows': frame.loc[0, 'data_quality'] = 'synthetic'
    if case == 'stale_bars': frame['timestamp'] -= pd.Timedelta(days=1)
    original_attrs = dict(frame.attrs)
    original_quote = dict(quote) if quote else None
    state = State(market_frame=frame, market_request=('BTC/USD',), market_symbol='BTC/USD',
                  market_quality='real', market_interval='1Min', market_quote=quote)
    if case == 'refresh_error': state['market_incremental_error'] = 'offline fixture'
    display = Display(state)
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    fragment = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == '_signal_monitor')
    fragment.decorator_list = []
    namespace = dict(st=display, datetime=Clock, timezone=timezone,
                     MovingAverageStrategy=MovingAverageStrategy,
                     select_completed_bars=select_completed_bars, BarTimingError=BarTimingError,
                     signal_view=signal_view, _money_or_unavailable=money, market_summary=market_summary)
    exec(compile(ast.Module(body=[fragment], type_ignores=[]), 'app.py', 'exec'), namespace)
    namespace['_signal_monitor'](('BTC/USD',), 5, 10)
    view = display.views[-1]
    if case != 'valid':
        assert view['state'] == 'ANALISI STORICA — NON OPERATIVA'
    assert view['operational_data'] is (case == 'valid')
    assert frame.attrs == original_attrs
    assert state['market_quote'] == original_quote
