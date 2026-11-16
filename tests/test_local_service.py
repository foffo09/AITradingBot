from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def client(tmp_path):
    from src.api.local_app import create_local_app
    return TestClient(create_local_app(data_dir=tmp_path, port=8123), base_url='http://127.0.0.1:8123')


def authorize(c):
    response = c.get('/api/v1/session', headers={'Origin': 'http://127.0.0.1:8123'})
    assert response.status_code == 200
    assert response.json() == {'api_version': '1', 'status': 'ready'}
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'samesite=strict' in response.headers['set-cookie'].lower()
    return {'Origin': 'http://127.0.0.1:8123', 'X-Local-Request': '1'}


def test_local_accounts_are_explicit_separate_and_persistent(tmp_path):
    c = client(tmp_path)
    assert c.get('/api/v1/health').json() == {'api_version': '1', 'status': 'ready'}
    assert c.get('/api/v1/state').status_code == 401
    headers = authorize(c)
    assert c.get('/api/v1/state?context=demo').json()['account'] is None
    assert not list(tmp_path.glob('*.sqlite3'))
    r = c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=headers)
    assert r.status_code == 200
    assert r.json()['account']['cash'] == 10000
    assert c.get('/api/v1/state?context=simulation').json()['account'] is None
    assert c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 99}, headers=headers).status_code == 409
    r = c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['positions'][0]['quantity'] == 1
    c2 = client(tmp_path)
    authorize(c2)
    assert c2.get('/api/v1/state?context=demo').json()['positions'][0]['quantity'] == 1
    assert c2.get('/api/v1/state?context=paper').json()['account'] is None
    assert c.post('/api/v1/local-trades', json={'context': 'paper', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1}, headers=headers).status_code == 422


def test_security_rejects_rebinding_csrf_and_untrusted_bootstrap(tmp_path):
    c = client(tmp_path)
    assert c.get('/api/v1/health', headers={'Host': 'evil.test'}).status_code == 403
    assert c.get('/api/v1/session').status_code == 403
    assert c.get('/api/v1/session', headers={'Origin': 'http://localhost:8123.evil.test'}).status_code == 403
    h = authorize(c)
    payload = {'context': 'demo', 'initial_cash': 1000}
    assert c.post('/api/v1/local-account', json=payload).status_code == 403
    assert c.post('/api/v1/local-account', json=payload, headers={'Origin': h['Origin']}).status_code == 403
    assert c.post('/api/v1/local-account', json=payload, headers={**h, 'Origin': 'http://evil.test'}).status_code == 403
    assert c.get('/api/v1/state', headers={'Origin': 'http://evil.test'}).status_code == 403


@pytest.mark.parametrize('value', [True, 0, -1, 'bad', 'NaN', 1e309])
def test_account_validation(tmp_path, value):
    c = client(tmp_path)
    h = authorize(c)
    # String infinity also checks JSON numbers that cannot be represented safely.
    value = 'Infinity' if value == float('inf') else value
    assert c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': value}, headers=h).status_code == 422


def test_market_provenance_backtest_and_proposal(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    market = c.get('/api/v1/market?context=demo&symbol=AAPL&interval=1Day').json()
    assert market['source'] == 'synthetic-demo'
    assert len(market['bars']) == 200
    assert isinstance(market['bars'][0]['time'], int)
    assert market['quote'] is None
    paper = c.get('/api/v1/market?context=paper&symbol=AAPL').json()
    assert paper['bars'] == [] and paper['status'] == 'unavailable'
    assert c.get('/api/v1/market?context=demo&symbol=UNKNOWN').status_code == 422
    assert c.get('/api/v1/market?context=demo&symbol=AAPL&interval=wrong').status_code == 422
    result = c.post('/api/v1/backtest', json={'context': 'demo', 'symbol': 'AAPL', 'short_window': 5, 'long_window': 20}, headers=h)
    assert result.status_code == 200, result.text
    assert len(result.json()['equity']) == 200
    assert result.json()['source'] == 'synthetic-demo'
    assert c.get('/api/v1/proposal?context=paper&symbol=AAPL').json()['action'] == 'NO_TRADE'


def test_paper_is_opt_in_read_only_and_errors_do_not_leak(tmp_path, monkeypatch):
    from src.api import local_app
    created = []
    class Broker:
        def __init__(self, settings):
            assert settings.trading_mode == 'paper'
            assert not settings.paper_trading_enabled
            created.append(self)
        def verify_connection(self):
            return {'connected': True}
        def get_paper_snapshot(self):
            return {'account': {'cash': '123', 'equity': '124', 'account_number': 'private'}, 'positions': [], 'orders': [], 'updated_at': 'now'}
        def get_market_data(self, *args, **kwargs):
            raise RuntimeError('secret fake-key')
        def submit_order(self, *args, **kwargs):
            pytest.fail('No broker orders are permitted')
    monkeypatch.setattr(local_app, 'AlpacaClient', Broker)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret')
    c = client(tmp_path)
    h = authorize(c)
    assert not created
    assert c.get('/api/v1/state?context=paper').json()['account'] is None
    assert not created
    result = c.post('/api/v1/connections/paper', headers=h)
    assert result.status_code == 200
    assert result.json()['account']['cash'] == '123'
    assert 'private' not in result.text
    result = c.get('/api/v1/market?context=paper&symbol=AAPL')
    assert result.json()['bars'] == []
    assert 'fake-key' not in result.text


def test_mt5_platform_gate_has_no_import_on_mac(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    import sys
    if sys.platform != 'win32':
        result = c.post('/api/v1/connections/mt5', headers=h).json()
        assert result['connection']['status'] == 'unsupported'
        assert result['account'] is None


def test_browser_bootstrap_and_shutdown_are_explicit(tmp_path):
    from src.api.local_app import create_local_app
    app = create_local_app(data_dir=tmp_path, port=8123)
    stopped = []
    app.state.request_shutdown = lambda: stopped.append(True)
    c = TestClient(app, base_url='http://127.0.0.1:8123')
    assert c.get('/api/v1/session', headers={'Sec-Fetch-Site': 'cross-site', 'X-Local-Request': '1'}).status_code == 403
    assert c.get('/api/v1/session', headers={'Sec-Fetch-Site': 'same-origin', 'X-Local-Request': '1'}).status_code == 200
    assert c.post('/api/v1/shutdown').status_code == 403
    assert not stopped
    assert c.post('/api/v1/shutdown', headers={'Origin': 'http://127.0.0.1:8123', 'X-Local-Request': '1'}).status_code == 200
    assert stopped == [True]


def test_static_ui_served_same_origin_and_missing_api_not_html(tmp_path):
    from src.api.local_app import create_local_app
    ui = tmp_path / 'ui'
    ui.mkdir()
    (ui / 'index.html').write_text('<html>local ui</html>')
    c = TestClient(create_local_app(data_dir=tmp_path / 'data', port=8123, ui_dir=ui), base_url='http://127.0.0.1:8123')
    assert 'local ui' in c.get('/').text
    authorize(c)
    assert c.get('/api/v1/missing').status_code == 404


def test_mt5_reads_whitelisted_methods_only(monkeypatch):
    from src.broker import mt5_readonly
    from types import SimpleNamespace
    class Terminal:
        def initialize(self, **kwargs): return True
        def shutdown(self): pass
        def terminal_info(self): return SimpleNamespace(connected=True)
        def account_info(self): return SimpleNamespace(login=123, server='Offline broker', balance=100, equity=101, currency='USD')
        def positions_get(self): return ()
        def orders_get(self): return ()
        def order_send(self, *args): pytest.fail('No MT5 orders permitted')
    monkeypatch.setattr(mt5_readonly.sys, 'platform', 'win32')
    monkeypatch.setattr(mt5_readonly.importlib, 'import_module', lambda name: Terminal())
    reader = mt5_readonly.MT5ReadOnly()
    reader.connect()
    assert reader.snapshot()['account']['cash'] == 100
    reader.close()
    assert reader.snapshot()['account'] is None


def test_proposal_delegates_without_inventing_risk_snapshot(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    def evaluate(**kwargs):
        assert kwargs['risk_snapshot'] is None
        assert kwargs['source'] == 'synthetic-demo'
        assert kwargs['bars'].attrs['source'] == 'synthetic-demo'
        return {'contract_version': '1', 'action': 'NO_TRADE', 'reason': 'Verified risk required.'}
    monkeypatch.setitem(sys.modules, 'src.strategy.service', SimpleNamespace(evaluate_proposal=evaluate))
    c = client(tmp_path)
    authorize(c)
    result = c.get('/api/v1/proposal?context=demo&symbol=AAPL').json()
    assert result['reason'] == 'Verified risk required.'


def test_ledger_alias_created_after_startup_is_rejected(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    other = tmp_path / 'other.sqlite3'
    other.write_text('do not touch')
    (tmp_path / 'local-v1-demo.sqlite3').symlink_to(other)
    assert c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 100}, headers=h).status_code == 409
    assert other.read_text() == 'do not touch'


def test_local_equity_and_profitable_sell_have_json_safe_metrics(tmp_path, monkeypatch):
    from src.api import local_app
    c = client(tmp_path)
    h = authorize(c)
    state = c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=h).json()
    assert state['account']['equity'] == 10000
    c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1}, headers=h)
    original = local_app.generate_demo_prices
    def higher(*args, **kwargs):
        data = original(*args, **kwargs)
        data['close'] *= 2
        return data
    monkeypatch.setattr(local_app, 'generate_demo_prices', higher)
    response = c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'sell', 'quantity': 1}, headers=h)
    assert response.status_code == 200
    assert response.json()['account']['profit_factor'] is None
    assert response.json()['account']['equity'] > 10000


def test_storage_failure_has_no_fallback_balance_or_internal_details(tmp_path):
    from src.api.local_app import create_local_app
    app = create_local_app(data_dir=tmp_path, port=8123)
    c = TestClient(app, base_url='http://127.0.0.1:8123', raise_server_exceptions=False)
    h = authorize(c)
    (tmp_path / 'local-v1-demo.sqlite3').write_text('invalid database')
    result = c.get('/api/v1/state?context=demo')
    assert result.status_code == 503
    assert result.json() == {'detail': 'Local storage unavailable; no account state was inferred.'}


def test_missing_trade_statistics_are_null_not_fabricated_zero(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    response = c.post('/api/v1/local-account', json={'context': 'simulation', 'initial_cash': 1000}, headers=h)
    account = response.json()['account']
    for metric in ('win_rate', 'average_win', 'average_loss', 'profit_factor'):
        assert account[metric] is None


def test_usd_account_does_not_expose_legacy_eur_identity_fields(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    account = c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 1000}, headers=h).json()['account']
    assert account['currency'] == 'USD'
    assert 'initial_eur' not in account
    assert 'eur_usd_rate' not in account
