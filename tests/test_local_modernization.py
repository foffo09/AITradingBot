"""React/FastAPI parity for flows of the retired Streamlit dashboard. Offline, temporary data only."""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

ORIGIN = 'http://127.0.0.1:8123'
H = {'Origin': ORIGIN, 'X-Local-Request': '1'}


def client(tmp_path):
    from src.api.local_app import create_local_app
    c = TestClient(create_local_app(data_dir=tmp_path, port=8123), base_url=ORIGIN)
    assert c.get('/api/v1/session', headers={'Origin': ORIGIN}).status_code == 200
    return c


def test_walk_forward_runs_out_of_sample_on_synthetic_data_without_ledger_writes(tmp_path):
    c = client(tmp_path)
    r = c.post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'AAPL'}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body['source'] == 'synthetic-demo' and body['interval'] == '1Day'
    assert body['candidates'] == [{'short_window': 2, 'long_window': 4}, {'short_window': 3, 'long_window': 6}, {'short_window': 5, 'long_window': 10}]
    assert body['folds'], 'at least one out-of-sample fold'
    for fold in body['folds']:
        assert fold['parameters'] in body['candidates']
        assert fold['train_end'] < fold['test_start'], 'test slice strictly after training slice'
        assert 'trade_history' not in fold['out_of_sample'] and 'return_pct' in fold['out_of_sample']
    assert not any(p.suffix == '.sqlite3' and 'control' not in p.name for p in tmp_path.iterdir()), 'no ledger created'


def test_walk_forward_without_data_or_with_invalid_windows_fails_explicitly(tmp_path):
    c = client(tmp_path)
    paper = c.post('/api/v1/walk-forward', json={'context': 'paper', 'symbol': 'AAPL'}, headers=H)
    assert paper.status_code == 409 and 'no fallback' in paper.json()['detail']
    assert c.post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'AAPL', 'training_bars': 150, 'test_bars': 100}, headers=H).status_code == 422
    assert c.post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'AAPL', 'training_bars': 5}, headers=H).status_code == 422
    assert c.post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'NOPE'}, headers=H).status_code == 422


def test_walk_forward_reports_insufficient_history(tmp_path, monkeypatch):
    from src.api import local_app
    real = local_app.generate_demo_prices
    monkeypatch.setattr(local_app, 'generate_demo_prices', lambda symbol, periods: real(symbol, periods=20))
    r = client(tmp_path).post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'AAPL'}, headers=H)
    assert r.status_code == 409 and 'Insufficient history: 24' in r.json()['detail']


def test_system_status_is_read_only_secret_free_and_never_waits_for_paper(tmp_path, monkeypatch):
    from src.api import local_app

    class SlowPaper:
        def __init__(self, settings):
            pass
        def verify_connection(self):
            time.sleep(2)
            return {'connected': True}
        def get_paper_snapshot(self):
            return {'account': {'cash': '1'}, 'positions': [], 'orders': [], 'updated_at': 'now'}
    monkeypatch.setattr(local_app, 'AlpacaClient', SlowPaper)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key-value')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret-value')
    c = client(tmp_path)
    first = c.get('/api/v1/system')
    assert first.status_code == 200
    body = first.json()
    assert body['order_submission'] == 'disabled'
    assert body['contexts']['demo'] == {'connection': 'local', 'ledger': 'absent', 'automation': 'STOPPED'}
    assert body['contexts']['paper']['connection'] == 'disconnected'
    assert 'fake-key-value' not in first.text and 'fake-secret-value' not in first.text and str(tmp_path) not in first.text
    t = threading.Thread(target=lambda: c.post('/api/v1/connections/paper', headers=H))
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    busy = c.get('/api/v1/system').json()
    assert time.monotonic() - started < 1.0
    assert busy['contexts']['paper']['connection'] == 'busy'
    t.join()
    assert c.get('/api/v1/system').json()['contexts']['paper']['connection'] == 'connected'


def test_watchlist_is_validated_persistent_and_never_reset(tmp_path):
    c = client(tmp_path)
    assert c.get('/api/v1/watchlist').json() == {'api_version': '1', 'symbols': ['AAPL', 'MSFT', 'SPY'], 'stored': False}
    saved = c.post('/api/v1/watchlist', json={'symbols': ['BTC/USD', 'AAPL']}, headers=H)
    assert saved.json()['symbols'] == ['BTC/USD', 'AAPL']
    for bad in (['ZZZ'], ['AAPL', 'AAPL'], ['AAPL'] * 21):
        assert c.post('/api/v1/watchlist', json={'symbols': bad}, headers=H).status_code == 422
    assert c.post('/api/v1/watchlist', json={'symbols': ['AAPL']}, headers={'Origin': ORIGIN}).status_code == 403
    assert client(tmp_path).get('/api/v1/watchlist').json()['symbols'] == ['BTC/USD', 'AAPL'], 'survives a new service instance'
    path = tmp_path / 'local-v1-watchlist.json'
    path.write_text('{broken')
    assert c.get('/api/v1/watchlist').status_code == 503
    assert path.read_text() == '{broken', 'corrupt file is reported, not overwritten'


@pytest.mark.skipif(os.name == 'nt', reason='symlinks need privileges on Windows')
def test_watchlist_rejects_aliases(tmp_path):
    c = client(tmp_path)
    (tmp_path / 'elsewhere.json').write_text('{"symbols": []}')
    (tmp_path / 'local-v1-watchlist.json').symlink_to(tmp_path / 'elsewhere.json')
    assert c.get('/api/v1/watchlist').status_code == 409
    assert c.post('/api/v1/watchlist', json={'symbols': ['AAPL']}, headers=H).status_code == 409


def test_paper_refresh_failure_hides_previous_values(tmp_path, monkeypatch):
    """Port of the retired Streamlit AppTest: a failed Paper refresh must not keep showing stale broker values."""
    from src.api import local_app
    fetches = []

    class FlakyPaper:
        def __init__(self, settings):
            assert settings.paper_trading_enabled is False
        def verify_connection(self):
            return {'connected': True}
        def get_paper_snapshot(self):
            fetches.append(None)
            if len(fetches) > 1:
                raise RuntimeError('Unable to fetch orders: order endpoint unavailable fake-secret-value')
            return {'account': {'cash': '987654321', 'equity': '987654322'}, 'positions': [{'symbol': 'STALE_POSITION'}],
                    'orders': [{'id': 'STALE_ORDER', 'status': 'filled'}], 'updated_at': 'now'}
        def submit_order(self, *args, **kwargs):
            pytest.fail('No broker orders are permitted')
    monkeypatch.setattr(local_app, 'AlpacaClient', FlakyPaper)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key-value')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret-value')
    c = client(tmp_path)
    first = c.post('/api/v1/connections/paper', headers=H).json()
    assert first['account']['cash'] == '987654321' and first['orders'][0]['id'] == 'STALE_ORDER'
    failed = c.get('/api/v1/state?context=paper')
    body = failed.json()
    assert body['connection']['status'] == 'unavailable'
    assert body['account'] is None and body['positions'] == [] and body['orders'] == []
    for stale in ('987654321', '987654322', 'STALE_ORDER', 'STALE_POSITION', 'fake-secret-value'):
        assert stale not in failed.text
    assert body['automation']['state'] == 'STOPPED'
    assert len(fetches) == 2


@pytest.mark.parametrize('body', [{'training_bars': 190}, {'training_bars': 195}, {'training_bars': 200}])
def test_walk_forward_auto_test_window_below_minimum_is_a_clear_422(tmp_path, body):
    r = client(tmp_path).post('/api/v1/walk-forward', json={'context': 'demo', 'symbol': 'AAPL', **body}, headers=H)
    assert r.status_code == 422
    assert 'at least 12 bars each' in r.json()['detail']


def test_system_reports_mt5_state_without_talking_to_the_terminal(tmp_path, monkeypatch):
    from src.broker import mt5_process
    c = client(tmp_path)
    expected = 'unsupported' if not mt5_process._SUPPORTED else 'disconnected'
    assert c.get('/api/v1/system').json()['contexts']['mt5']['connection'] == expected
    monkeypatch.setattr(mt5_process, '_SUPPORTED', True)
    process = mt5_process.MT5Process()
    assert process.state == 'disconnected'
    process._process = object()  # a live worker after connect()
    assert process.state == 'connected'
    process._status = 'unavailable'
    assert process.state == 'unavailable'


def _trade_body(context='demo', quantity=1, key=None, side='buy'):
    from uuid import uuid4
    return {'context': context, 'symbol': 'AAPL', 'side': side, 'quantity': quantity, 'idempotency_key': key or str(uuid4())}


def test_uncertain_trade_survives_restart_and_blocks_duplicates(tmp_path):
    """Finding 6: response lost after commit, app restarted on a new port (fresh browser storage)."""
    c = client(tmp_path)
    assert c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=H).status_code == 200
    body = _trade_body()
    assert c.put('/api/v1/pending-trade', json=body, headers=H).json()['pending'] == body
    # The trade is booked, but imagine the response never reached the UI; restart = new service, new origin storage.
    from src.api import local_app
    original = local_app.SimulationLedger.buy
    def booked_then_lost(self, **kwargs):
        original(self, **kwargs)
        raise OSError('response lost')
    local_app.SimulationLedger.buy = booked_then_lost
    try:
        assert c.post('/api/v1/local-trades', json=body, headers=H).status_code == 503
    finally:
        local_app.SimulationLedger.buy = original
    restarted = client(tmp_path)
    assert restarted.get('/api/v1/pending-trade?context=demo').json()['pending'] == body, 'service remembers it'
    fresh = _trade_body()
    blocked = restarted.post('/api/v1/local-trades', json=fresh, headers=H)
    assert blocked.status_code == 409 and blocked.headers['X-Request-Outcome'] == 'rejected'
    retried = restarted.post('/api/v1/local-trades', json=body, headers=H)
    assert retried.status_code == 200 and retried.json()['fill']['duplicate'] is True
    assert len(retried.json()['positions']) == 1, 'exactly one virtual fill'
    assert restarted.get('/api/v1/pending-trade?context=demo').json()['pending'] is None
    assert restarted.post('/api/v1/local-trades', json=fresh, headers=H).status_code == 200


def test_pending_trade_is_cleared_on_definitive_rejection_and_scoped_per_context(tmp_path):
    c = client(tmp_path)
    for context in ('demo', 'simulation'):
        c.post('/api/v1/local-account', json={'context': context, 'initial_cash': 10000}, headers=H)
    huge = _trade_body(quantity=10000)
    c.put('/api/v1/pending-trade', json=huge, headers=H)
    assert c.post('/api/v1/local-trades', json=_trade_body('simulation'), headers=H).status_code == 200, 'other context unaffected'
    rejected = c.post('/api/v1/local-trades', json=huge, headers=H)
    assert rejected.status_code == 409 and rejected.headers['X-Request-Outcome'] == 'rejected'
    assert c.get('/api/v1/pending-trade?context=demo').json()['pending'] is None
    other = _trade_body()
    c.put('/api/v1/pending-trade', json=other, headers=H)
    assert c.put('/api/v1/pending-trade', json=_trade_body(), headers=H).status_code == 409, 'one pending per context'
    assert c.put('/api/v1/pending-trade', json=other, headers=H).status_code == 200, 'same record is idempotent'
    changed = {**other, 'quantity': 2}
    assert c.post('/api/v1/local-trades', json=changed, headers=H).headers.get('X-Request-Outcome') != 'rejected'
    assert c.put('/api/v1/pending-trade', json={**other, 'symbol': 'NOPE'}, headers=H).status_code == 422
    assert c.put('/api/v1/pending-trade', json=other, headers={'Origin': ORIGIN}).status_code == 403
    (tmp_path / 'local-v1-demo-pending-trade.json').write_text('{bad')
    assert c.get('/api/v1/pending-trade?context=demo').status_code == 503
    assert c.post('/api/v1/local-trades', json=other, headers=H).status_code == 503, 'unreadable record blocks, never guesses'
