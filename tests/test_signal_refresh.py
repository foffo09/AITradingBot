"""Invoke the signal fragment repeatedly without a full application rerun."""
import ast
from datetime import datetime, timezone
from pathlib import Path

from src.data.bar_timing import BarTimingError
from src.data.market_data import generate_synthetic_market_data
from src.strategy.moving_average import MovingAverageStrategy
from src.ui.presentation import money, signal_view


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
                     signal_view=signal_view, _money_or_unavailable=money)
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
