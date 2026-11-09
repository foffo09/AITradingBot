"""Invoke the signal fragment repeatedly without a full application rerun."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.data.bar_timing import BarTimingError, select_completed_bars
from src.data.market_data import generate_synthetic_market_data
from src.strategy.moving_average import MovingAverageStrategy
from src.ui.presentation import money, signal_view
from src.ui.dashboard_metrics import market_summary
from src.broker.alpaca_client import BrokerConnectionError


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Display:
    def __init__(self, state):
        self.session_state = state
        self.views = []
        self.messages = []
        self.reruns = []

    def columns(self, count):
        return [self] * count

    def json(self, view):
        self.views.append(view)

    def markdown(self, text):
        self.messages.append(text)

    info = warning = caption = write = markdown
    error = subheader = markdown

    def button(self, *args, **kwargs):
        return False

    def metric(self, *args, **kwargs):
        pass

    def rerun(self, scope=None):
        self.reruns.append(scope)
        raise AppRerun(scope)

    def expander(self, *args):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AppRerun(Exception):
    pass


def _compile_app_functions(display, names, namespace):
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    functions = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == set(names)
    for function in functions:
        function.decorator_list = []
    namespace['st'] = display
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), 'app.py', 'exec'),
        namespace,
    )
    return namespace


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


def _real_market_frame(now):
    frame = pd.DataFrame({
        'timestamp': pd.date_range(end=now-pd.Timedelta(minutes=1), periods=20, freq='min'),
        'open': range(100, 120),
        'high': range(101, 121),
        'low': range(99, 119),
        'close': range(100, 120),
        'volume': range(1000, 1020),
        'is_synthetic': [False] * 20,
    })
    frame.attrs.update(
        quality='real', interval='1Min', source='Dati storici reali Alpaca IEX',
        bar_time_contract='alpaca-start-v1', bar_calendar='NYSE',
        session_scope='regular', fetched_at=(now-pd.Timedelta(seconds=10)).isoformat(),
    )
    return frame


def _quote_fragment_namespace(display, frame, quote, incremental_error=None):
    now = pd.Timestamp.now(tz='UTC').floor('s')
    frame.attrs['fetched_at'] = (now-pd.Timedelta(seconds=10)).isoformat()
    state = display.session_state
    state.update(
        market_frame=frame,
        market_request=('SPY', '1Min', '3M', False),
        market_quality='real',
        market_symbol='SPY',
        market_interval='1Min',
        market_source=frame.attrs['source'],
        market_quote=quote,
        market_quote_refreshed_at=now.to_pydatetime() if quote else None,
        market_quote_error=None,
        market_incremental_error=incremental_error,
    )

    class Broker:
        paper_client_configured = True

        def __init__(self):
            self.bar_calls = 0
            self.quote_calls = 0

        def get_market_data(self, symbol, **kwargs):
            self.bar_calls += 1
            update = frame.tail(1).copy()
            update['timestamp'] = [pd.Timestamp.now(tz='UTC').floor('s')]
            update['open'] = [120]
            update['high'] = [121]
            update['low'] = [119]
            update['close'] = [120]
            update['volume'] = [1020]
            update.attrs.update(frame.attrs)
            update.attrs['fetched_at'] = pd.Timestamp.now(tz='UTC').isoformat()
            return update

        def get_latest_quote(self, symbol):
            self.quote_calls += 1
            observed = pd.Timestamp.now(tz='UTC').floor('s')
            return {
                'bid': 119.9, 'ask': 120.1, 'price': 120,
                'timestamp': observed.isoformat(),
                'source': 'Alpaca IEX latest quote',
            }

    class Ledger:
        @staticmethod
        def account():
            return None

        @staticmethod
        def history():
            return []

    broker = Broker()
    namespace = {
        'pd': pd,
        'datetime': datetime,
        'timezone': timezone,
        'timedelta': timedelta,
        'MovingAverageStrategy': MovingAverageStrategy,
        'BrokerConnectionError': BrokerConnectionError,
        'market_summary': market_summary,
        'broker': broker,
        'ledger': Ledger(),
        '_latest_timestamp': lambda data: pd.Timestamp(data['timestamp'].iloc[-1]),
        '_plot_market_chart': lambda *args, **kwargs: None,
        '_model_dict': lambda item: dict(item),
        'market_cards': lambda *args, **kwargs: None,
    }
    return _compile_app_functions(
        display,
        {'_market_view_revision', '_sync_dashboard_views', '_live_quote_monitor'},
        namespace,
    ), broker


def test_quote_refresh_syncs_external_summaries_and_skips_duplicate_requests():
    now = pd.Timestamp.now(tz='UTC').floor('s')
    display = Display(State())
    namespace, broker = _quote_fragment_namespace(display, _real_market_frame(now), None)
    monitor = namespace['_live_quote_monitor']

    with pytest.raises(AppRerun, match='app'):
        monitor('SPY', 'real', display.session_state.market_frame, 5, 10, False)

    assert display.session_state['_market_status_sync_rerun'] is True
    assert display.session_state['_paper_status_sync_rerun'] is True
    assert broker.bar_calls == broker.quote_calls == 1

    monitor('SPY', 'real', display.session_state.market_frame, 5, 10, False)

    assert display.reruns == ['app']
    assert broker.bar_calls == broker.quote_calls == 1
    assert display.session_state.get('_market_status_sync_rerun') is None


@pytest.mark.parametrize(
    ('age', 'expected_message'),
    [
        (pd.Timedelta(seconds=121), 'più vecchia di due minuti'),
        (pd.Timedelta(seconds=-1), 'timestamp futuro'),
    ],
)
def test_quote_refresh_syncs_and_invalidates_stale_or_future_quote(age, expected_message):
    now = pd.Timestamp.now(tz='UTC').floor('s')
    quote = {
        'bid': 99.9, 'ask': 100.1, 'price': 100,
        'timestamp': (now-age).isoformat(),
        'source': 'Alpaca IEX latest quote',
    }
    display = Display(State())
    namespace, broker = _quote_fragment_namespace(display, _real_market_frame(now), quote)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.to_pydatetime()

    namespace["datetime"] = Clock
    monitor = namespace['_live_quote_monitor']

    with pytest.raises(AppRerun, match='app'):
        monitor('SPY', 'real', display.session_state.market_frame, 5, 10, False)

    assert display.session_state['market_quote'] is None
    assert expected_message in display.session_state['market_quote_error']
    assert broker.quote_calls == 0
    assert display.session_state['_market_status_sync_rerun'] is True


@pytest.mark.parametrize('refresh_fails', [False, True])
def test_paper_snapshot_fragment_syncs_changed_state_and_does_not_repeat_request(refresh_fails):
    class Broker:
        paper_client_configured = True

        def __init__(self):
            self.calls = 0

        def get_paper_snapshot(self):
            self.calls += 1
            if refresh_fails:
                raise BrokerConnectionError('offline fixture')
            return {
                'account': {'equity': '101', 'cash': '101'},
                'positions': [],
                'orders': [],
                'updated_at': pd.Timestamp.now(tz='UTC').isoformat(),
            }

    broker = Broker()
    initial_snapshot = {
        'account': {'equity': '100', 'cash': '100'},
        'positions': [],
        'orders': [],
        'updated_at': (pd.Timestamp.now(tz='UTC')-pd.Timedelta(seconds=1)).isoformat(),
    }
    display = Display(State(
        paper_verified=True,
        paper_automation_active=True,
        paper_snapshot=initial_snapshot,
        paper_snapshot_error=None,
        market_quality='real',
    ))
    shown = []
    namespace = _compile_app_functions(
        display,
        {'_paper_snapshot_revision', '_sync_dashboard_views', '_paper_account_monitor'},
        {
            'broker': broker,
            'settings': type('Settings', (), {'trading_mode': 'paper'})(),
            'BrokerConnectionError': BrokerConnectionError,
            '_show_paper_snapshot': lambda snapshot: shown.append(snapshot),
        },
    )
    monitor = namespace['_paper_account_monitor']

    with pytest.raises(AppRerun, match='app'):
        monitor()

    assert broker.calls == 1
    assert display.session_state['_paper_status_sync_rerun'] is True
    assert display.session_state['_market_status_sync_rerun'] is True
    if refresh_fails:
        assert display.session_state['paper_verified'] is False
        assert display.session_state['paper_automation_active'] is False
        assert 'paper_snapshot' not in display.session_state
        assert display.session_state['paper_snapshot_error'] == 'offline fixture'
    else:
        assert display.session_state['paper_snapshot']['account']['equity'] == '101'

    monitor()

    assert broker.calls == 1
    assert display.reruns == ['app']
    if not refresh_fails:
        assert shown[-1]['account']['equity'] == '101'


def test_paper_timestamp_only_refresh_does_not_rerun_dashboard():
    class Broker:
        paper_client_configured = True

        def get_paper_snapshot(self):
            return {
                'account': {'equity': '100', 'cash': '100'},
                'positions': [],
                'orders': [],
                'updated_at': pd.Timestamp.now(tz='UTC').isoformat(),
            }

    snapshot = {
        'account': {'equity': '100', 'cash': '100'},
        'positions': [],
        'orders': [],
        'updated_at': (pd.Timestamp.now(tz='UTC')-pd.Timedelta(seconds=1)).isoformat(),
    }
    display = Display(State(
        paper_verified=True,
        paper_automation_active=False,
        paper_snapshot=snapshot,
        paper_snapshot_error=None,
        market_quality='real',
    ))
    namespace = _compile_app_functions(
        display,
        {'_paper_snapshot_revision', '_sync_dashboard_views', '_paper_account_monitor'},
        {
            'broker': Broker(),
            'settings': type('Settings', (), {'trading_mode': 'paper'})(),
            'BrokerConnectionError': BrokerConnectionError,
            '_show_paper_snapshot': lambda snapshot: None,
        },
    )

    namespace['_paper_account_monitor']()

    assert display.reruns == []
    assert display.session_state['paper_snapshot']['updated_at'] != snapshot['updated_at']


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
