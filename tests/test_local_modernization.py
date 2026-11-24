"""React/FastAPI parity for flows of the retired Streamlit dashboard. Offline, temporary data only."""
import os
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
