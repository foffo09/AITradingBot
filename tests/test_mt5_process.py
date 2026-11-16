import multiprocessing
import os
from pathlib import Path
import runpy
import sys
import time

import pandas as pd
import pytest


def synthetic_worker(connection):
    from conftest import guard
    from src.broker import mt5_process
    from src.broker.mt5_readonly import MT5ReadError

    class Reader:
        def connect(self):
            pass

        def snapshot(self):
            return {'connection': {'status': 'connected', 'reason': 'synthetic'},
                    'account': {'cash': 100}, 'positions': [], 'orders': []}

        def latest_quote(self, symbol):
            if symbol == 'hang':
                time.sleep(60)
            if symbol == 'crash':
                os._exit(7)
            if symbol == 'stale':
                raise MT5ReadError('Synthetic stale tick.', status='stale')
            assert not any(guard.attempts.values())
            return {'bid': 1, 'ask': 2, 'pid': os.getpid()}

        def market_data(self, symbol, interval):
            data = pd.DataFrame({'close': [1.]})
            data.attrs = {'source': 'synthetic', 'interval': interval}
            return data

        def close(self):
            if os.environ.get('MT5_TEST_HANG_CLOSE') == '1':
                time.sleep(60)

    mt5_process.MT5ReadOnly = Reader
    mt5_process._worker(connection)


@pytest.fixture
def module(monkeypatch):
    from src.broker import mt5_process
    monkeypatch.setattr(mt5_process, '_SUPPORTED', True)
    monkeypatch.setattr(mt5_process, '_worker', synthetic_worker)
    # Streamlit AppTest mutates __main__; spawned fixtures must not execute app.py.
    monkeypatch.setattr(sys.modules['__main__'], '__file__', None, raising=False)
    monkeypatch.setattr(sys.modules['__main__'], '__spec__', None, raising=False)
    return mt5_process


def test_native_reader_runs_in_owned_child_and_preserves_results(module):
    reader = module.MT5Process(timeout=5)
    try:
        assert reader.snapshot()['account'] is None
        reader.connect()
        assert reader.snapshot()['account']['cash'] == 100
        assert reader.latest_quote('ok')['pid'] != os.getpid()
        frame = reader.market_data('ok', '1Day')
        assert frame.iloc[0]['close'] == 1
        assert frame.attrs == {'source': 'synthetic', 'interval': '1Day'}
        with pytest.raises(module.MT5ReadError, match='Synthetic stale') as error:
            reader.latest_quote('stale')
        assert error.value.status == 'stale'
    finally:
        reader.close()
    assert reader.snapshot()['account'] is None


@pytest.mark.parametrize('symbol', ['hang', 'crash'])
def test_timeout_or_crash_invalidates_and_reaps_only_owned_worker(module, symbol):
    reader = module.MT5Process(timeout=5)
    reader.connect()
    child = reader._process
    pid = child.pid
    reader.timeout = .15
    started = time.monotonic()
    with pytest.raises(module.MT5ReadError):
        reader.latest_quote(symbol)
    assert time.monotonic() - started < 2
    assert reader.snapshot()['account'] is None
    assert pid not in {p.pid for p in multiprocessing.active_children()}
    with pytest.raises(module.MT5ReadError):
        reader.latest_quote('ok')
    reader.close()
    reader.close()


def test_hung_shutdown_is_bounded_and_idempotent(module, monkeypatch):
    monkeypatch.setenv('MT5_TEST_HANG_CLOSE', '1')
    reader = module.MT5Process(timeout=5)
    reader.connect()
    pid = reader._process.pid
    reader.timeout = .15
    started = time.monotonic()
    reader.close()
    reader.close()
    assert time.monotonic() - started < 2
    assert pid not in {p.pid for p in multiprocessing.active_children()}


def test_unsupported_does_not_spawn_or_import_sdk(module, monkeypatch):
    monkeypatch.setattr(module, '_SUPPORTED', False)
    monkeypatch.setattr(module.multiprocessing, 'get_context', lambda *a: pytest.fail('No process'))
    reader = module.MT5Process()
    reader.connect()
    assert reader.snapshot()['connection']['status'] == 'unsupported'
    assert reader._process is None
    reader.close()


def test_frozen_bootstrap_diverts_before_importing_runtime(monkeypatch):
    root = Path(__file__).parents[1]
    diverted = []
    def freeze():
        diverted.append(True)
        raise SystemExit(0)
    monkeypatch.setattr(multiprocessing, 'freeze_support', freeze)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(root / 'packaging/backend/entrypoint.py'), run_name='__main__')
    assert result.value.code == 0
    assert diverted == [True]


def stalled_worker(connection):
    operation, args = connection.recv()
    assert operation == 'connect'
    connection.send(('ok', None))
    time.sleep(60)


def test_deadline_also_bounds_blocked_parent_send(module, monkeypatch):
    monkeypatch.setattr(module, '_worker', stalled_worker)
    reader = module.MT5Process(timeout=5)
    reader.connect()
    pid = reader._process.pid
    reader.timeout = .15
    started = time.monotonic()
    with pytest.raises(module.MT5ReadError):
        reader.latest_quote('x' * 5_000_000)
    assert time.monotonic() - started < 2
    assert pid not in {p.pid for p in multiprocessing.active_children()}
    reader.close()


def test_worker_blocks_operations_outside_read_allowlist(module):
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe()
    process = context.Process(target=synthetic_worker, args=(child,))
    process.start()
    child.close()
    try:
        parent.send(('order_send', ()))
        assert parent.poll(5)
        assert parent.recv() == ('error', 'Unsupported terminal operation.', 'unavailable')
        parent.send(('close', ()))
        assert parent.poll(5)
        assert parent.recv() == ('ok', None)
        process.join(5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(2)
        parent.close()
        process.close()


def native_worker(connection):
    from conftest import guard
    from types import SimpleNamespace
    from src.broker import mt5_readonly, mt5_process

    account = SimpleNamespace(trade_mode=0, login=123, server='Fixture', currency='USD', balance=100., equity=100.)
    def tick(symbol):
        return SimpleNamespace(bid=1., ask=2., time_msc=int(time.time() * 1000))
    def account_info():
        return account
    def forbidden(*args):
        raise AssertionError('SDK writes are forbidden')
    sdk = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0,
        initialize=lambda **kwargs: True, shutdown=lambda: None,
        terminal_info=lambda: SimpleNamespace(connected=True), account_info=account_info,
        positions_get=lambda: (), orders_get=lambda: (), symbol_info_tick=tick,
        order_send=forbidden, order_check=forbidden)
    mt5_readonly.sys = SimpleNamespace(platform='win32')
    mt5_readonly.importlib = SimpleNamespace(import_module=lambda name: sdk)
    class Reader(mt5_readonly.MT5ReadOnly):
        def latest_quote(self, symbol):
            if symbol == 'real':
                account.trade_mode = 2
            assert not any(guard.attempts.values())
            return super().latest_quote(symbol)
    mt5_process.MT5ReadOnly = Reader
    mt5_process._worker(connection)


def test_real_native_validation_survives_process_boundary(module, monkeypatch):
    monkeypatch.setattr(module, '_worker', native_worker)
    reader = module.MT5Process(timeout=5)
    try:
        reader.connect()
        assert reader.snapshot()['account']['cash'] == 100
        assert reader.latest_quote('ok')['bid'] == 1
        with pytest.raises(module.MT5ReadError, match='Demo'):
            reader.latest_quote('real')
        snapshot = reader.snapshot()
        assert snapshot['account'] is None
        assert snapshot['positions'] == [] and snapshot['orders'] == []
    finally:
        reader.close()


def malformed_worker(connection):
    connection.recv()
    connection.send(('ok', None))
    connection.recv()
    connection.send(([], None))
    time.sleep(60)


def test_malformed_reply_invalidates_worker_without_exposing_values(module, monkeypatch):
    monkeypatch.setattr(module, '_worker', malformed_worker)
    reader = module.MT5Process(timeout=5)
    try:
        reader.connect()
        pid = reader._process.pid
        result = reader.snapshot()
        assert result['connection']['status'] == 'unavailable'
        assert result['account'] is None
        assert pid not in {p.pid for p in multiprocessing.active_children()}
    finally:
        reader.close()


def silent_worker(connection):
    time.sleep(60)


def test_connect_timeout_reaps_worker_and_allows_explicit_reconnect(module, monkeypatch):
    monkeypatch.setattr(module, '_worker', silent_worker)
    before = {p.pid for p in multiprocessing.active_children()}
    reader = module.MT5Process(timeout=.15)
    started = time.monotonic()
    reader.connect()
    assert time.monotonic() - started < 2
    assert reader.snapshot()['account'] is None
    assert {p.pid for p in multiprocessing.active_children()} == before
    monkeypatch.setattr(module, '_worker', synthetic_worker)
    reader.timeout = 5
    try:
        reader.connect()
        assert reader.snapshot()['account']['cash'] == 100
    finally:
        reader.close()
