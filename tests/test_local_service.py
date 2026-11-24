from uuid import uuid4

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
    r = c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1, 'idempotency_key': str(uuid4())}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['positions'][0]['quantity'] == 1
    c2 = client(tmp_path)
    authorize(c2)
    assert c2.get('/api/v1/state?context=demo').json()['positions'][0]['quantity'] == 1
    assert c2.get('/api/v1/state?context=paper').json()['account'] is None
    assert c.post('/api/v1/local-trades', json={'context': 'paper', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1, 'idempotency_key': str(uuid4())}, headers=headers).status_code == 422


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
    assert c.get('/api/v1/proposal?context=paper&symbol=AAPL').json()['validation_state'] == 'NO_TRADE'


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
        ACCOUNT_TRADE_MODE_DEMO = 0
        def initialize(self, **kwargs): return True
        def shutdown(self): pass
        def terminal_info(self): return SimpleNamespace(connected=True)
        def account_info(self): return SimpleNamespace(trade_mode=0, login=123, server='Offline broker', balance=100, equity=101, currency='USD')
        def positions_get(self): return ()
        def orders_get(self): return ()
        def order_send(self, *args): pytest.fail('No MT5 orders permitted')
    monkeypatch.setattr(mt5_readonly, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(mt5_readonly, 'importlib', SimpleNamespace(import_module=lambda name: Terminal()))
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
    c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1, 'idempotency_key': str(uuid4())}, headers=h)
    original = local_app.generate_demo_prices
    def higher(*args, **kwargs):
        data = original(*args, **kwargs)
        data['close'] *= 2
        return data
    monkeypatch.setattr(local_app, 'generate_demo_prices', higher)
    response = c.post('/api/v1/local-trades', json={'context': 'demo', 'symbol': 'AAPL', 'side': 'sell', 'quantity': 1, 'idempotency_key': str(uuid4())}, headers=h)
    assert response.status_code == 200
    assert response.json()['account']['profit_factor'] is None
    assert response.json()['account']['equity'] > 10000


def test_storage_failure_has_no_fallback_balance_or_internal_details(tmp_path):
    from src.api.local_app import create_local_app
    app = create_local_app(data_dir=tmp_path, port=8123)
    c = TestClient(app, base_url='http://127.0.0.1:8123', raise_server_exceptions=False)
    authorize(c)
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


def test_proposal_fallback_keeps_original_p3_dto_and_visible_reason(tmp_path, monkeypatch):
    import sys
    from src.strategy.engine import SignalProposal
    monkeypatch.setitem(sys.modules, 'src.strategy.service', None)
    c = client(tmp_path)
    authorize(c)
    result = c.get('/api/v1/proposal?context=demo&symbol=AAPL').json()
    assert set(SignalProposal(symbol='AAPL').to_dict()).issubset(result)
    assert result['direction'] == 'WAIT'
    assert result['validation_state'] == 'NO_TRADE'
    assert result['reason'] == 'Strategy service unavailable; no proposal can be verified.'
    assert result['entry'] is None and result['quantity'] is None
    assert result['contract_version'] == '1'


@pytest.mark.parametrize('failure', ['exception', 'verification'])
def test_failed_paper_connection_is_explicit_unavailable_without_old_values(tmp_path, monkeypatch, failure):
    from src.api import local_app
    class Broker:
        def __init__(self, settings):
            if failure == 'exception':
                raise RuntimeError('private broker diagnostic')
        def verify_connection(self): return {'connected': False}
    monkeypatch.setattr(local_app, 'AlpacaClient', Broker)
    monkeypatch.setenv('ALPACA_API_KEY', 'fake-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fake-secret')
    c = client(tmp_path)
    h = authorize(c)
    result = c.post('/api/v1/connections/paper', headers=h)
    assert result.json()['connection']['status'] == 'unavailable'
    assert 'private broker diagnostic' not in result.text
    assert result.json()['account'] is None
    assert result.json()['positions'] == []


def test_market_keeps_original_frame_metadata_and_clears_it_on_failure(tmp_path):
    c = client(tmp_path)
    authorize(c)
    market = c.get('/api/v1/market?context=demo&symbol=AAPL&interval=5Min').json()
    assert market['metadata']['source'] == market['source']
    assert market['metadata']['quality'] == 'synthetic'
    assert market['metadata']['interval'] == '5Min'
    unavailable = c.get('/api/v1/market?context=paper&symbol=AAPL').json()
    assert unavailable['metadata'] == {}


def test_demo_proposal_reaches_pure_service_and_keeps_its_rejection_provenance(tmp_path):
    c = client(tmp_path)
    authorize(c)
    proposal = c.get('/api/v1/proposal?context=demo&symbol=AAPL&interval=5Min').json()
    assert proposal['reason'] == 'Only the Paper context can produce an analytical proposal.'
    assert proposal['provenance']['bars']['source'] == 'synthetic-demo'
    assert proposal['provenance']['bars']['interval'] == '5Min'
    assert proposal['validation_state'] == 'NO_TRADE'


def test_api_trade_replay_is_idempotent_across_restart_and_payload_is_bound(tmp_path):
    from uuid import uuid4
    c = client(tmp_path)
    h = authorize(c)
    c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=h)
    body = dict(context='demo', symbol='AAPL', side='buy', quantity=1, idempotency_key=str(uuid4()))
    first = c.post('/api/v1/local-trades', json=body, headers=h)
    assert first.status_code == 200, first.text
    again = c.post('/api/v1/local-trades', json=body, headers=h)
    assert again.json()['positions'][0]['quantity'] == 1
    assert again.json()['fill']['duplicate'] is True
    restarted = client(tmp_path)
    h2 = authorize(restarted)
    replay = restarted.post('/api/v1/local-trades', json=body, headers=h2)
    assert replay.json()['fill']['duplicate'] is True
    assert restarted.post('/api/v1/local-trades', json={**body, 'quantity': 2}, headers=h2).status_code == 409


def test_market_indicators_and_backtest_sample_are_explicit(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    market = c.get('/api/v1/market?context=demo&symbol=AAPL').json()
    indicators = {item['id']: item for item in market['indicators']}
    assert set(indicators) == {'sma10', 'sma30', 'ema9', 'ema21', 'ema50', 'rsi14'}
    assert indicators['sma10']['points'][0]['value'] is None
    assert indicators['rsi14']['method'] == 'Wilder EWM'
    result = c.post('/api/v1/backtest', json={'context': 'demo', 'symbol': 'AAPL'}, headers=h).json()
    assert result['validation'] == {'kind': 'single_sample', 'out_of_sample': None}
    assert result['sample']['bars'] == 200
    assert c.get('/api/v1/proposal?interval=5Min').json()['interval'] == '5Min'


def test_automation_is_explicit_offline_idempotent_and_context_isolated(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    assert c.get('/api/v1/state').json()['automation']['state'] == 'STOPPED'
    assert not list(tmp_path.glob('*control.sqlite3'))
    body = dict(context='demo', command='start', request_id=str(uuid4()))
    started = c.post('/api/v1/automation', json=body, headers=h)
    assert started.status_code == 200, started.text
    assert started.json()['automation']['execution_enabled'] is False
    assert started.json()['automation']['state'] == 'RUNNING'
    cycle = dict(context='demo', command='cycle', request_id=str(uuid4()))
    first = c.post('/api/v1/automation', json=cycle, headers=h).json()['automation']
    again = c.post('/api/v1/automation', json=cycle, headers=h).json()['automation']
    assert first['proposals'] == again['proposals'] == 1
    assert first['intents'] == 0  # Pure strategy rejects synthetic operational data.
    assert c.get('/api/v1/state?context=simulation').json()['automation']['state'] == 'STOPPED'
    assert c.post('/api/v1/automation', json={**body, 'context': 'paper'}, headers=h).status_code == 422
    c.app.state.close()


def test_definitive_risk_rejection_is_distinct_from_idempotency_conflict(tmp_path):
    c = client(tmp_path)
    h = authorize(c)
    c.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 10000}, headers=h)
    body = dict(context='demo', symbol='AAPL', side='buy', quantity=10000, idempotency_key=str(uuid4()))
    rejected = c.post('/api/v1/local-trades', json=body, headers=h)
    assert rejected.status_code == 409
    assert rejected.headers['X-Request-Outcome'] == 'rejected'
    body.update(quantity=1, idempotency_key=str(uuid4()))
    assert c.post('/api/v1/local-trades', json=body, headers=h).status_code == 200
    conflict = c.post('/api/v1/local-trades', json={**body, 'quantity': 2}, headers=h)
    assert conflict.status_code == 409
    assert conflict.headers.get('X-Request-Outcome') != 'rejected'
