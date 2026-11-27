"""Non-financial preferences survive a port change; GET never creates storage."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from src.api.local_app import create_local_app

DEFAULTS = {'theme': 'light', 'density': 'comfortable', 'analysis_width': 68}
CHANGED = {'theme': 'light', 'density': 'compact', 'analysis_width': 72}


def open_client(root, port=8123):
    app = create_local_app(data_dir=root, port=port)
    client = TestClient(app, base_url=f'http://127.0.0.1:{port}')
    headers = {'Origin': f'http://127.0.0.1:{port}', 'X-Local-Request': '1'}
    assert client.get('/api/v1/session', headers=headers).status_code == 200
    return app, client, headers


def test_preferences_survive_restart_with_different_port_without_creating_accounts(tmp_path):
    root = tmp_path / 'Dati preferenze è'
    app, client, headers = open_client(root)
    try:
        response = client.get('/api/v1/preferences')
        assert response.status_code == 200
        assert response.json()['preferences'] == DEFAULTS
        assert response.json()['stored'] is False
        assert not root.exists()
        assert client.post('/api/v1/preferences', json=CHANGED, headers=headers).status_code == 200
        assert not list(root.glob('*.sqlite3'))
    finally:
        client.close()
        app.state.close()
    app, client, headers = open_client(root, port=9124)
    try:
        assert client.get('/api/v1/preferences').json() == {'api_version':'1', 'preferences':CHANGED, 'stored':True}
        assert client.get('/api/v1/state?context=demo').json()['account'] is None
        assert client.get('/api/v1/state?context=simulation').json()['account'] is None
    finally:
        client.close()
        app.state.close()


@pytest.mark.parametrize('change', [
    {'theme': 'evil'}, {'density': 'evil'}, {'analysis_width': True},
    {'analysis_width': '72'}, {'analysis_width': 49}, {'analysis_width': 76},
    {'analysis_width': 60.5}, {'ALPACA_API_KEY': 'fixture-secret'},
    {'risk_max_trade_fraction': .9}, {'initial_cash': 1000000},
])
def test_invalid_or_financial_preferences_are_rejected_without_writes(tmp_path, change):
    app, client, headers = open_client(tmp_path)
    try:
        response = client.post('/api/v1/preferences', json={**CHANGED, **change}, headers=headers)
        assert response.status_code == 422
        assert 'fixture-secret' not in response.text
        assert not (tmp_path / 'local-v1-ui-preferences.json').exists()
    finally:
        client.close()
        app.state.close()


def test_preferences_require_session_and_same_origin(tmp_path):
    app, client, headers = open_client(tmp_path)
    try:
        client.cookies.clear()
        assert client.get('/api/v1/preferences').status_code == 401
        assert client.post('/api/v1/preferences', json=CHANGED, headers=headers).status_code == 401
        client.get('/api/v1/session', headers=headers)
        assert client.post('/api/v1/preferences', json=CHANGED, headers={**headers, 'Origin': 'http://evil.test'}).status_code == 403
        assert not (tmp_path / 'local-v1-ui-preferences.json').exists()
    finally:
        client.close()
        app.state.close()


@pytest.mark.parametrize('payload', [b'not JSON fixture-secret', b'{}', b'X'*4097, b'\xff'], ids=['invalid-json', 'missing-fields', 'oversized', 'bad-utf8'])
def test_corrupt_preferences_are_reported_without_reset_or_contents(tmp_path, payload):
    path = tmp_path / 'local-v1-ui-preferences.json'
    path.write_bytes(payload)
    app, client, _ = open_client(tmp_path)
    try:
        response = client.get('/api/v1/preferences')
        assert response.status_code == 503
        assert 'fixture-secret' not in response.text
        assert path.read_bytes() == payload
    finally:
        client.close()
        app.state.close()


def test_preference_hardlink_is_neither_read_nor_replaced(tmp_path):
    original = tmp_path / 'original.json'
    original.write_text(json.dumps(DEFAULTS), encoding='utf-8')
    os.link(original, tmp_path / 'local-v1-ui-preferences.json')
    app, client, headers = open_client(tmp_path)
    try:
        assert client.get('/api/v1/preferences').status_code == 409
        assert client.post('/api/v1/preferences', json=CHANGED, headers=headers).status_code == 409
        assert json.loads(original.read_text()) == DEFAULTS
    finally:
        client.close()
        app.state.close()


def test_failed_atomic_save_preserves_previous_preferences(tmp_path, monkeypatch):
    app, client, headers = open_client(tmp_path)
    try:
        assert client.post('/api/v1/preferences', json=DEFAULTS, headers=headers).status_code == 200
        def fail(*args):
            raise PermissionError('fixture-secret')
        monkeypatch.setattr('src.api.local_app.os.replace', fail)
        response = client.post('/api/v1/preferences', json=CHANGED, headers=headers)
        assert response.status_code == 503 and 'fixture-secret' not in response.text
        assert client.get('/api/v1/preferences').json()['preferences'] == DEFAULTS
        assert sorted(p.name for p in tmp_path.iterdir()) == ['local-v1-ui-preferences.json']
    finally:
        client.close()
        app.state.close()
