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


def test_system_reports_only_a_verified_mt5_state_without_talking_to_the_terminal(tmp_path, monkeypatch):
    """Codex review #3: a live worker is not a connection; only a verified snapshot is."""
    from src.broker import mt5_process
    c = client(tmp_path)
    expected = 'unsupported' if not mt5_process._SUPPORTED else 'disconnected'
    assert c.get('/api/v1/system').json()['contexts']['mt5']['connection'] == expected
    monkeypatch.setattr(mt5_process, '_SUPPORTED', True)
    process = mt5_process.MT5Process()
    replies = []
    def fake_request(operation, *args):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(process, '_request', fake_request)
    process._process = object()  # worker alive
    snapshot = lambda status: {'connection': {'status': status, 'reason': 'x'}, 'account': None, 'positions': [], 'orders': []}
    assert process.state == 'disconnected', 'alive worker without a verified snapshot'
    replies.append(snapshot('unavailable'))  # initialisation failed / Demo account rejected
    process.snapshot()
    assert process.state == 'unavailable'
    replies.append(snapshot('connected'))
    process.snapshot()
    assert process.state == 'connected'
    replies.append(snapshot('disconnected'))  # terminal dropped later
    process.snapshot()
    assert process.state == 'disconnected'
    replies.append(mt5_process.MT5ReadError('worker failed'))
    process.snapshot()
    assert process.state == 'unavailable'
    calls = []
    monkeypatch.setattr(process, '_request', lambda operation, *args: calls.append(operation))
    assert process.state == 'unavailable' and calls == [], 'reading state performs no IPC'


def test_mt5_connect_endpoint_reports_the_verified_snapshot_state(tmp_path, monkeypatch):
    """/connections/mt5 answers with state('mt5'), whose snapshot records the verified outcome."""
    from src.broker import mt5_process
    monkeypatch.setattr(mt5_process, '_SUPPORTED', True)
    monkeypatch.setattr(mt5_process.MT5Process, 'connect', lambda self: setattr(self, '_process', object()))
    monkeypatch.setattr(mt5_process.MT5Process, '_request', lambda self, operation, *args: {
        'connection': {'status': 'unavailable', 'reason': 'Demo account not verified.'}, 'account': None, 'positions': [], 'orders': []})
    c = client(tmp_path)
    assert c.post('/api/v1/connections/mt5', headers=H).json()['connection']['status'] == 'unavailable'
    assert c.get('/api/v1/system').json()['contexts']['mt5']['connection'] == 'unavailable'



def _trade_body(context='demo', quantity=1, key=None, side='buy'):
    from uuid import uuid4
    return {'context': context, 'symbol': 'AAPL', 'side': side, 'quantity': quantity, 'idempotency_key': key or str(uuid4())}


def test_uncertain_trade_survives_restart_and_blocks_duplicates(tmp_path):
    """Codex review #1: the trade completes, its response never reaches the UI, the app restarts on a new port."""
    c = client(tmp_path)
    assert c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=H).status_code == 200
    body = _trade_body()
    assert c.put('/api/v1/pending-trade', json=body, headers=H).json()['pending'] == body
    booked = c.post('/api/v1/local-trades', json=body, headers=H)
    assert booked.status_code == 200  # ...but this response is lost; the browser storage is gone after restart
    restarted = client(tmp_path)
    assert restarted.get('/api/v1/pending-trade?context=demo').json()['pending'] == body, 'still known after commit'
    fresh = _trade_body()
    blocked = restarted.post('/api/v1/local-trades', json=fresh, headers=H)
    assert blocked.status_code == 409 and blocked.headers['X-Request-Outcome'] == 'rejected'
    assert restarted.put('/api/v1/pending-trade', json=fresh, headers=H).status_code == 409
    retried = restarted.post('/api/v1/local-trades', json=body, headers=H)
    assert retried.status_code == 200 and retried.json()['fill']['duplicate'] is True
    assert len(retried.json()['positions']) == 1, 'exactly one virtual fill'
    assert restarted.get('/api/v1/pending-trade?context=demo').json()['pending'] == body, 'kept until confirmed'
    confirm = restarted.delete(f"/api/v1/pending-trade?context=demo&idempotency_key={body['idempotency_key']}", headers=H)
    assert confirm.status_code == 200 and confirm.json()['pending'] is None
    assert restarted.post('/api/v1/local-trades', json=fresh, headers=H).status_code == 200


def test_pending_trade_confirmation_rules_and_context_scope(tmp_path):
    c = client(tmp_path)
    for context in ('demo', 'simulation'):
        c.post('/api/v1/local-account', json={'context': context, 'initial_cash': 10000}, headers=H)
    huge = _trade_body(quantity=10000)
    c.put('/api/v1/pending-trade', json=huge, headers=H)
    assert c.post('/api/v1/local-trades', json=_trade_body('simulation'), headers=H).status_code == 200, 'other context unaffected'
    rejected = c.post('/api/v1/local-trades', json=huge, headers=H)
    assert rejected.status_code == 409 and rejected.headers['X-Request-Outcome'] == 'rejected'
    assert c.get('/api/v1/pending-trade?context=demo').json()['pending'] == huge, 'rejection response could be lost too'
    from uuid import uuid4
    wrong = c.delete(f'/api/v1/pending-trade?context=demo&idempotency_key={uuid4()}', headers=H)
    assert wrong.status_code == 200 and wrong.json()['pending'] == huge, 'another key never removes it'
    assert c.delete(f"/api/v1/pending-trade?context=demo&idempotency_key={huge['idempotency_key']}", headers={'Origin': ORIGIN}).status_code == 403
    assert c.delete(f"/api/v1/pending-trade?context=demo&idempotency_key={huge['idempotency_key']}", headers=H).json()['pending'] is None
    assert c.delete(f"/api/v1/pending-trade?context=demo&idempotency_key={huge['idempotency_key']}", headers=H).status_code == 200, 'idempotent'
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


def test_demo_series_differ_per_symbol_and_stay_deterministic():
    from src.data.market_data import generate_demo_prices
    aapl, msft = generate_demo_prices('AAPL'), generate_demo_prices('MSFT')
    assert not aapl['close'].equals(msft['close'])
    assert aapl['close'].equals(generate_demo_prices('AAPL')['close'])


def test_paper_monitor_verifies_and_reads_with_the_real_client_logic_but_cannot_submit(tmp_path, monkeypatch):
    """Codex review #4: API + real AlpacaClient verification; only the SDK transport is faked."""
    from src.broker import alpaca_client
    calls = []

    sessions = []

    class FakeTradingClient:
        def __init__(self, key, secret, paper):
            assert paper is True
            from types import SimpleNamespace
            self._session = SimpleNamespace(read_only=False)  # the SDK's HTTP session
            sessions.append(self._session)
        def get_account(self):
            calls.append('account')
            return {'id': 'acct', 'status': 'ACTIVE', 'trading_blocked': False, 'account_blocked': False,
                    'cash': '1000', 'equity': '1010', 'buying_power': '2000', 'last_equity': '1005', 'currency': 'USD'}
        def get_all_positions(self):
            calls.append('positions')
            return []
        def get_orders(self, *args, **kwargs):
            calls.append('orders')
            return []
        def submit_order(self, *args, **kwargs):
            pytest.fail('The desktop monitor must never submit')
    monkeypatch.setattr(alpaca_client, 'TradingClient', FakeTradingClient)
    monkeypatch.setattr(alpaca_client, 'StockHistoricalDataClient', None)
    monkeypatch.setattr(alpaca_client, 'CryptoHistoricalDataClient', None)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key-value')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret-value')
    c = client(tmp_path)
    result = c.post('/api/v1/connections/paper', headers=H)
    body = result.json()
    assert body['connection']['status'] == 'connected', body
    assert body['account']['cash'] == '1000' and body['account']['source'] == 'Alpaca Paper'
    assert 'account' in calls and 'fake-secret-value' not in result.text
    assert sessions[0].read_only is True, 'desktop service forces the transport read-only'
    assert c.get('/api/v1/state?context=paper').json()['account']['equity'] == '1010', 'later reads work too'
    from config.settings import AppSettings
    broker = alpaca_client.AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key='k', alpaca_secret_key='s', paper_trading_enabled=False))
    assert broker.verify_connection()['connected'] is True
    # Every other precondition of the first submit guard holds, so only paper_trading_enabled can stop it.
    assert broker.client is not None and broker.paper_client_is_paper and broker.is_connected()
    with pytest.raises(PermissionError, match='Only the dedicated Alpaca Paper client may submit orders'):
        broker.submit_order(symbol='AAPL', side='buy', quantity=1, client_order_id='never-sent')
    # Control: with the flag on, the same broker passes that guard and is stopped later (no coordinator).
    enabled = alpaca_client.AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key='k', alpaca_secret_key='s', paper_trading_enabled=True))
    assert enabled.verify_connection()['connected'] is True
    with pytest.raises(PermissionError) as later:
        enabled.submit_order(symbol='AAPL', side='buy', quantity=1, client_order_id='never-sent')
    assert 'Only the dedicated Alpaca Paper client' not in str(later.value)
