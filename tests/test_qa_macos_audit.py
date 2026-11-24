"""Independent QA regressions (Claude macOS audit 2026-11-24). Offline, temporary data only."""
import os
import sqlite3
import stat
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ORIGIN = 'http://127.0.0.1:8123'
H = {'Origin': ORIGIN, 'X-Local-Request': '1'}


def client(tmp_path):
    from src.api.local_app import create_local_app
    c = TestClient(create_local_app(data_dir=tmp_path, port=8123), base_url=ORIGIN)
    assert c.get('/api/v1/session', headers={'Origin': ORIGIN}).status_code == 200
    return c


def trade(c, key=None, context='demo', side='buy', quantity=1):
    body = {'context': context, 'symbol': 'AAPL', 'side': side, 'quantity': quantity, 'idempotency_key': key or str(uuid4())}
    return c.post('/api/v1/local-trades', json=body, headers=H)


def account(c, context='demo', cash=10000):
    assert c.post('/api/v1/local-account', json={'context': context, 'initial_cash': cash}, headers=H).status_code == 200


def test_modes_keep_separate_capital_ledger_and_automation(tmp_path):
    c = client(tmp_path)
    account(c, 'demo', 10000)
    account(c, 'simulation', 5000)
    assert trade(c).status_code == 200
    demo = c.get('/api/v1/state?context=demo').json()
    sim = c.get('/api/v1/state?context=simulation').json()
    paper = c.get('/api/v1/state?context=paper').json()
    assert len(demo['positions']) == 1 and sim['positions'] == [] and sim['account']['cash'] == 5000
    assert demo['account']['cash'] < 10000
    assert paper['account'] is None and paper['positions'] == [] and paper['connection']['status'] == 'disconnected'
    assert c.post('/api/v1/automation', json={'context': 'demo', 'command': 'start', 'request_id': str(uuid4())}, headers=H).status_code == 200
    assert c.get('/api/v1/state?context=simulation').json()['automation']['state'].upper() == 'STOPPED'
    assert c.post('/api/v1/automation', json={'context': 'paper', 'command': 'start', 'request_id': str(uuid4())}, headers=H).status_code == 422


def test_lost_response_retry_never_duplicates_and_conflict_stays_uncertain(tmp_path):
    c = client(tmp_path)
    account(c)
    key = str(uuid4())
    first = trade(c, key)
    assert first.status_code == 200
    # Response "lost": the UI retries with the same key and payload.
    assert trade(c, key).status_code == 200
    assert len(c.get('/api/v1/state?context=demo').json()['trades'] or c.get('/api/v1/state?context=demo').json()['positions']) == 1
    conflict = trade(c, key, quantity=2)
    assert conflict.status_code == 409
    assert conflict.headers.get('X-Request-Outcome') != 'rejected'  # must not be read as a clean rejection


def test_failed_transaction_rolls_back_and_is_not_a_rejection(tmp_path):
    c = client(tmp_path)
    account(c)
    db = tmp_path / 'local-v1-demo.sqlite3'
    with sqlite3.connect(db) as con:
        con.execute("CREATE TRIGGER qa_fail AFTER INSERT ON trades BEGIN SELECT RAISE(ABORT, 'qa interrupted'); END")
    key = str(uuid4())
    failed = trade(c, key)
    assert failed.status_code == 503 and failed.headers.get('X-Request-Outcome') != 'rejected'
    assert 'qa interrupted' not in failed.text
    state = c.get('/api/v1/state?context=demo').json()
    assert state['account']['cash'] == 10000 and state['positions'] == []
    with sqlite3.connect(db) as con:
        con.execute('DROP TRIGGER qa_fail')
    assert trade(c, key).status_code == 200  # same key recovers exactly once
    assert len(c.get('/api/v1/state?context=demo').json()['positions']) == 1


def test_corrupt_database_reports_unavailable_and_recovers_without_restart(tmp_path):
    c = client(tmp_path)
    account(c)
    db = tmp_path / 'local-v1-demo.sqlite3'
    good = db.read_bytes()
    db.write_bytes(b'not a sqlite database' * 100)
    broken = c.get('/api/v1/state?context=demo')
    assert broken.status_code == 503 and 'account' not in broken.json()
    assert c.get('/api/v1/state?context=simulation').status_code == 200  # other modes unaffected
    db.write_bytes(good)
    assert c.get('/api/v1/state?context=demo').json()['account']['cash'] == 10000


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores directory permissions')
def test_read_only_data_directory_fails_closed(tmp_path):
    data = tmp_path / 'ro'
    data.mkdir()
    c = client(data)
    data.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        r = c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 100}, headers=H)
        assert r.status_code == 503
        assert c.get('/api/v1/state?context=demo').json()['account'] is None
    finally:
        data.chmod(stat.S_IRWXU)


@pytest.mark.xfail(strict=True, reason='AUDIT-M1: one global RLock serialises every context; a slow Paper read blocks Demo')
def test_slow_paper_read_does_not_block_demo(tmp_path, monkeypatch):
    from src.api import local_app

    class SlowPaper:
        def __init__(self, settings):
            pass
        def verify_connection(self):
            return {'connected': True}
        def get_paper_snapshot(self):
            time.sleep(3)  # Alpaca transport allows (3.05, 10.0)s per request
            return {'account': {'cash': '1', 'equity': '1'}, 'positions': [], 'orders': [], 'updated_at': 'now'}
    monkeypatch.setattr(local_app, 'AlpacaClient', SlowPaper)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret')
    c = client(tmp_path)
    paper_thread = threading.Thread(target=lambda: c.post('/api/v1/connections/paper', headers=H))
    paper_thread.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert c.get('/api/v1/state?context=demo').status_code == 200
    elapsed = time.monotonic() - started
    paper_thread.join()
    assert elapsed < 1.0, f'Demo state waited {elapsed:.2f}s behind a Paper network read'
