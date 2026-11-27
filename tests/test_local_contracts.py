"""Public v1 output contracts; no broker, personal files or real credentials."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.local_app import create_local_app


@pytest.fixture
def service(tmp_path):
    app = create_local_app(data_dir=tmp_path / 'Dati di prova è', port=8123)
    with TestClient(app, base_url='http://127.0.0.1:8123', raise_server_exceptions=False) as client:
        headers = {'Origin': 'http://127.0.0.1:8123', 'X-Local-Request': '1'}
        assert client.get('/api/v1/session', headers=headers).status_code == 200
        yield app, client, headers
    app.state.close()


@pytest.mark.parametrize('method,path', [
    ('get', '/health'), ('get', '/session'), ('get', '/identity'),
    ('get', '/preferences'), ('post', '/preferences'),
    ('post', '/shutdown'), ('get', '/state'), ('get', '/instruments'),
    ('get', '/market'), ('post', '/local-account'), ('post', '/local-trades'),
    ('post', '/backtest'), ('get', '/proposal'), ('post', '/automation'),
    ('post', '/connections/paper'), ('post', '/connections/mt5'),
])
def test_openapi_defines_success_and_sanitized_error_contracts(service, method, path):
    app, _, _ = service
    operation = app.openapi()['paths']['/api/v1' + path][method]
    schema = operation['responses']['200']['content']['application/json']['schema']
    assert '$ref' in schema, f'Untyped success response: {method} {path}'
    error = operation['responses']['503']['content']['application/json']['schema']
    assert '$ref' in error


@pytest.mark.parametrize('snapshot', [
    {'connection': {'status': True, 'reason': 'fixture-private-sentinel'}, 'account': None, 'positions': [], 'orders': []},
    {'connection': {'status': 'connected'}, 'account': {'cash': float('nan')}, 'positions': [], 'orders': []},
    {'connection': {'status': 'connected'}, 'account': None, 'positions': None, 'orders': []},
    {'connection': {'status': 'connected'}, 'account': None, 'positions': [], 'orders': ['fixture-private-sentinel']},
])
def test_invalid_provider_snapshot_is_withheld_without_payload_or_traceback(service, monkeypatch, snapshot):
    from src.api import local_app
    _, client, _ = service
    monkeypatch.setattr(local_app.MT5Process, 'snapshot', lambda self: snapshot)
    response = client.get('/api/v1/state?context=mt5')
    assert response.status_code == 503
    assert set(response.json()) == {'detail'}
    assert 'fixture-private-sentinel' not in response.text
    assert 'Traceback' not in response.text


def test_bad_indicator_response_does_not_publish_usable_market(service, monkeypatch):
    from src.api import local_app
    _, client, _ = service
    monkeypatch.setattr(local_app, '_indicators', lambda *_: [{'id': 'broken', 'points': []}])
    response = client.get('/api/v1/market?context=demo&symbol=AAPL&interval=1Day')
    assert response.status_code == 503
    assert 'bars' not in response.json()


def test_response_failure_after_virtual_fill_preserves_retry_identity(service, monkeypatch):
    from src.api import local_app
    _, client, headers = service
    assert client.post('/api/v1/local-account', headers=headers,
                       json={'context': 'demo', 'initial_cash': 10000}).status_code == 200
    original = local_app.SimulationLedger.positions
    monkeypatch.setattr(local_app.SimulationLedger, 'positions', lambda self: None)
    body = {'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1,
            'idempotency_key': str(uuid4())}
    response = client.post('/api/v1/local-trades', headers=headers, json=body)
    assert response.status_code == 503
    assert response.headers.get('X-Request-Outcome') != 'rejected'
    monkeypatch.setattr(local_app.SimulationLedger, 'positions', original)
    retry = client.post('/api/v1/local-trades', headers=headers, json=body)
    assert retry.status_code == 200
    assert retry.json()['fill']['duplicate'] is True
    assert retry.json()['positions'][0]['quantity'] == 1
    assert len(retry.json()['trades']) == 1


def test_paper_sdk_records_keep_json_safe_fields_after_output_validation(service, monkeypatch):
    from datetime import datetime, timezone
    from decimal import Decimal
    from pydantic import BaseModel
    from uuid import UUID
    from src.api import local_app

    class SDKRow(BaseModel):
        id: UUID
        qty: Decimal
        updated_at: datetime

    row = SDKRow(id=UUID('00000000-0000-4000-8000-000000000001'), qty=Decimal('1.25'),
                 updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    class Broker:
        def __init__(self, settings):
            assert settings.trading_mode == 'paper' and not settings.paper_trading_enabled
        def verify_connection(self):
            return {'connected': True}
        def get_paper_snapshot(self):
            return {'account': {'cash': '100', 'equity': '100', 'currency': 'USD'},
                    'positions': [row], 'orders': [row], 'updated_at': '2026-01-01T00:00:00Z'}

    monkeypatch.setattr(local_app, 'AlpacaClient', Broker)
    monkeypatch.setenv('ALPACA_API_KEY', 'fixture-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY', 'fixture-secret')
    _, client, headers = service
    response = client.post('/api/v1/connections/paper', headers=headers)
    assert response.status_code == 200
    assert response.json()['positions'] == [{'id': '00000000-0000-4000-8000-000000000001',
                                            'qty': '1.25', 'updated_at': '2026-01-01T00:00:00Z'}]
    assert response.json()['orders'] == response.json()['positions']


@pytest.mark.parametrize('direction', ['BUY', 'SELL'])
def test_incomplete_operational_proposal_is_not_published_as_valid(service, monkeypatch, direction):
    from src.strategy import service as strategy_service
    monkeypatch.setattr(strategy_service, 'evaluate_proposal', lambda **kwargs: {
        'contract_version': '1', 'direction': direction, 'validation_state': 'PAPER_PROPOSAL',
        'expires_at': '2099-01-01T00:00:00Z', 'reason': 'fixture-private-sentinel',
    })
    _, client, _ = service
    # Use Demo data to reach the stub without connecting to any provider.
    response = client.get('/api/v1/proposal?context=demo')
    assert response.status_code == 503
    assert 'fixture-private-sentinel' not in response.text


def test_backtest_equity_cannot_use_nullable_indicator_warmup(service):
    from pydantic import ValidationError
    from src.api.schemas import BacktestResponse
    _, client, headers = service
    result = client.post('/api/v1/backtest', headers=headers,
                         json={'context': 'demo', 'symbol': 'AAPL'}).json()
    result['equity'][0]['value'] = None
    with pytest.raises(ValidationError):
        BacktestResponse.model_validate(result)


@pytest.mark.parametrize('direction', ['BUY', 'SELL'])
def test_paper_proposal_contract_requires_complete_levels_identity_and_times(service, direction):
    from pydantic import ValidationError
    from src.api.schemas import ProposalResponse
    _, client, _ = service
    result = client.get('/api/v1/proposal?context=demo').json()
    result.update(context='paper', direction=direction, validation_state='PAPER_PROPOSAL')
    with pytest.raises(ValidationError):
        ProposalResponse.model_validate(result)


@pytest.mark.parametrize('direction,entry_type,stop,target', [
    ('BUY', 'ask_reference', 99.0, 102.0),
    ('SELL', 'bid_reference_exit_long', 101.0, 98.0),
])
def test_complete_serialized_proposal_shape_remains_compatible(service, direction, entry_type, stop, target):
    from src.api.schemas import ProposalResponse
    _, client, _ = service
    result = client.get('/api/v1/proposal?context=demo').json()
    result.update(context='paper', direction=direction, validation_state='PAPER_PROPOSAL',
                  signal_id='fixture-signal', timestamp='2026-01-01T00:00:00Z',
                  expires_at='2026-01-01T00:05:00Z', reference_price=100.0,
                  entry=100.0, entry_type=entry_type, stop_loss=stop, take_profit=target,
                  stop_distance=1.0, target_distance=2.0, reward_risk=2.0,
                  net_reward_risk=1.9, quantity=1.0, risk_amount=1.0)
    # Schema validity is not operational freshness or authorization to execute.
    validated = ProposalResponse.model_validate(result).model_dump()
    assert validated['entry'] == 100.0 and validated['quantity'] == 1.0
    assert validated['direction'] == direction
