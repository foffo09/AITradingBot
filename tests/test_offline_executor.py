"""Synthetic journal tests: no broker object or credentials are constructed."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.trading.offline_executor import OfflineExecutor, OfflineExecutionError


def now():
    return datetime.now(timezone.utc).isoformat()


def proposal(identity='signal-1'):
    return dict(signal_id=identity, symbol='AAPL', direction='BUY', validation_state='PAPER_PROPOSAL',
        timestamp=now(), expires_at='2099-01-01T00:00:00+00:00', quantity=2, entry=100,
        stop_loss=95, take_profit=110, provenance={'bars': {'source': 'synthetic-test'}})


def command(executor, name, evaluate=None, identity=None):
    return executor.command(name, identity or str(uuid4()), evaluate=evaluate)


def snapshot(orders=(), fills=(), complete=True, pages=None):
    return dict(scope='demo', as_of=now(), complete=complete, balance='1000', positions={},
        pages=pages if pages is not None else [dict(cursor=None, next_cursor=None, orders=list(orders), fills=list(fills))])


def order(intent, state='filled', filled='2', timestamp=None):
    return dict(intent_id=intent, broker_id='synthetic-order', status=state,
        filled_quantity=filled, updated_at=timestamp or now())


def fill(intent, identity='fill-1', qty='2'):
    return dict(id=identity, intent_id=intent, broker_id='synthetic-order', quantity=qty, price='100', timestamp=now())


def test_dry_run_idempotent_separate_and_restart_requires_recovery(tmp_path):
    executor = OfflineExecutor(tmp_path, 'demo')
    assert executor.status()['state'] == 'STOPPED'
    assert not list(tmp_path.glob('*.sqlite3'))
    command(executor, 'start')
    key = str(uuid4())
    first = command(executor, 'cycle', lambda: proposal(), key)
    assert first['state'] == 'RUNNING'
    assert first['intents'] == 1 and first['proposals'] == 1
    command(executor, 'cycle', lambda: pytest.fail('Replay must not evaluate'), key)
    assert executor.intents()[0]['state'] == 'dry_run_completed'
    assert executor.status()['execution_enabled'] is False
    assert OfflineExecutor(tmp_path, 'simulation').status()['intents'] == 0
    # Simulate crash: ownership released without graceful stop.
    executor.close(graceful=False)
    restarted = OfflineExecutor(tmp_path, 'demo')
    assert command(restarted, 'start')['state'] == 'RECOVERY_REQUIRED'
    assert restarted.status()['intents'] == 1
    restarted.close()


def test_no_trade_duplicate_signal_and_pause_stop(tmp_path):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: {'validation_state': 'NO_TRADE', 'reason': 'gate blocked'})
    assert executor.status()['intents'] == 0
    command(executor, 'cycle', lambda: proposal())
    command(executor, 'cycle', lambda: proposal())
    assert executor.status()['intents'] == 1
    assert command(executor, 'pause')['state'] == 'PAUSED'
    with pytest.raises(OfflineExecutionError):
        command(executor, 'cycle', lambda: proposal())
    assert command(executor, 'stop')['state'] == 'STOPPED'
    executor.close()


def test_two_owners_and_command_payload_collision(tmp_path):
    one, two = OfflineExecutor(tmp_path, 'demo'), OfflineExecutor(tmp_path, 'demo')
    identity = str(uuid4())
    command(one, 'start', identity=identity)
    with pytest.raises(OfflineExecutionError):
        command(two, 'start')
    with pytest.raises(OfflineExecutionError):
        command(one, 'pause', identity=identity)
    one.close()
    two.close()


def test_partial_fills_duplicates_late_events_and_verified_recovery(tmp_path):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: proposal())
    intent = executor.intents()[0]['id']
    partial = fill(intent, qty='1')
    assert executor.reconcile(snapshot([order(intent, 'partial', '1')], [partial]),
        expected_balance='1000', expected_positions={}) is True
    assert executor.intents()[0]['filled_quantity'] == '1'
    assert executor.reconcile(snapshot([order(intent)], [partial, fill(intent, 'fill-2', '1')]),
        expected_balance='1000', expected_positions={}) is True
    assert executor.intents()[0]['filled_quantity'] == '2'
    # Old order notification cannot undo a terminal fill; duplicate fill is unchanged.
    assert executor.reconcile(snapshot([order(intent, 'partial', '1', '2000-01-01T00:00:00+00:00')], [partial]),
        expected_balance='1000', expected_positions={}) is True
    assert executor.intents()[0]['state'] == 'filled'
    assert executor.reconcile(snapshot(complete=False), expected_balance='1000', expected_positions={}) is False
    assert executor.status()['state'] == 'RECOVERY_REQUIRED'
    assert command(executor, 'stop')['state'] == 'RECOVERY_REQUIRED'
    assert executor.reconcile(snapshot([order(intent)], [partial, fill(intent, 'fill-2', '1')]),
        expected_balance='1000', expected_positions={}) is True
    assert executor.status()['state'] == 'STOPPED'
    executor.close()


@pytest.mark.parametrize('bad', ['empty', 'missing_page', 'balance', 'positions', 'stale', 'missing_order', 'unknown_order', 'duplicate_fill_changed'])
def test_unverifiable_snapshot_blocks_without_replaying(tmp_path, bad):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: proposal())
    identity = executor.intents()[0]['id']
    current = snapshot([order(identity, 'pending', '0')])
    if bad == 'empty': current = {}
    if bad == 'missing_page': current['pages'][0]['next_cursor'] = 'not-returned'
    if bad == 'balance': current['balance'] = '999'
    if bad == 'positions': current['positions'] = {'AAPL': '1'}
    if bad == 'stale': current['as_of'] = '2000-01-01T00:00:00+00:00'
    if bad == 'missing_order': current['pages'][0]['orders'] = []
    if bad == 'unknown_order': current['pages'][0]['orders'] = [order('other')]
    if bad == 'duplicate_fill_changed':
        current['pages'][0]['orders'] = [order(identity)]
        current['pages'][0]['fills'] = [fill(identity), fill(identity, qty='1')]
    assert executor.reconcile(current, expected_balance='1000', expected_positions={}) is False
    assert executor.status()['state'] == 'RECOVERY_REQUIRED'
    assert command(executor, 'start')['state'] == 'RECOVERY_REQUIRED'
    assert executor.status()['intents'] == 1
    executor.close()


def test_callback_failure_is_sanitized_and_requires_recovery(tmp_path):
    executor = OfflineExecutor(tmp_path, 'paper')
    command(executor, 'start')
    def broken(): raise TimeoutError('sensitive provider diagnostic')
    state = command(executor, 'cycle', broken)
    assert state['state'] == 'RECOVERY_REQUIRED'
    assert 'sensitive' not in str(state)
    executor.close()


def test_restart_read_is_fail_closed_without_creating_or_altering_state(tmp_path):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    executor.close(graceful=False)
    restarted = OfflineExecutor(tmp_path, 'demo')
    assert restarted.status()['state'] == 'RECOVERY_REQUIRED'
    assert restarted.status()['execution_enabled'] is False


def test_complete_pagination_overlap_and_cancel_after_partial(tmp_path):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: proposal())
    identity = executor.intents()[0]['id']
    execution = fill(identity, qty='1')
    last = order(identity, 'canceled', '1')
    a = dict(cursor=None, next_cursor='page2', orders=[last], fills=[execution])
    b = dict(cursor='page2', next_cursor=None, orders=[last], fills=[execution])
    assert executor.reconcile(snapshot(pages=[a, a, b]), expected_balance='1000', expected_positions={})
    assert executor.intents()[0]['filled_quantity'] == '1'
    assert executor.intents()[0]['state'] == 'canceled'
    executor.close()


@pytest.mark.parametrize('status', ['pending', 'acknowledged', 'rejected', 'canceled', 'expired', 'unknown'])
def test_provider_outcomes_are_not_inferred_from_empty_response(tmp_path, status):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: proposal())
    identity = executor.intents()[0]['id']
    valid = executor.reconcile(snapshot([order(identity, status, '0')]), expected_balance='1000', expected_positions={})
    assert valid is (status != 'unknown')
    if valid:
        assert executor.intents()[0]['state'] == status
    else:
        assert executor.status()['state'] == 'RECOVERY_REQUIRED'
    executor.close()


def test_concurrent_command_replay_waits_for_original_cycle(tmp_path):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    import threading
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    entered, release = threading.Event(), threading.Event()
    key = str(uuid4())
    def evaluate():
        entered.set()
        assert release.wait(3)
        return proposal()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(command, executor, 'cycle', evaluate, key)
        assert entered.wait(3)
        second = pool.submit(command, executor, 'cycle', lambda: pytest.fail('Duplicate evaluation'), key)
        try:
            with pytest.raises(FutureTimeout):
                second.result(timeout=.05)
        finally:
            release.set()
        assert first.result()['intents'] == second.result()['intents'] == 1
    executor.close()


@pytest.mark.parametrize('bad', ['missing_time', 'future_fill', 'not_a_snapshot'])
def test_malformed_or_future_execution_blocks_verified_recovery(tmp_path, bad):
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    command(executor, 'cycle', lambda: proposal())
    identity = executor.intents()[0]['id']
    execution = fill(identity)
    current = snapshot([order(identity)], [execution])
    if bad == 'missing_time': current['as_of'] = None
    elif bad == 'future_fill': execution['timestamp'] = '2099-01-01T00:00:00+00:00'
    else: current = None
    assert executor.reconcile(current, expected_balance='1000', expected_positions={}) is False
    assert executor.status()['state'] == 'RECOVERY_REQUIRED'
    executor.close()


def test_owned_context_rejects_an_independent_process(tmp_path):
    import subprocess
    import sys
    executor = OfflineExecutor(tmp_path, 'demo')
    command(executor, 'start')
    script = '''
from pathlib import Path
import sys
from uuid import uuid4
from src.trading.offline_executor import OfflineExecutor, OfflineExecutionError
try:
    OfflineExecutor(Path(sys.argv[1]), 'demo').command('start', str(uuid4()))
except OfflineExecutionError:
    print('OWNERSHIP BLOCKED')
else:
    raise SystemExit('Second process acquired the same context')
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'OWNERSHIP BLOCKED'
    executor.close()
