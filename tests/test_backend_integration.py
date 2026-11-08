"""Phase 2 regressions at the real SDK/mock HTTP and consumer boundaries."""
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from requests import Response, Session

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError
from src.data import fx_rates
from src.data.bar_timing import BarTimingError, select_completed_bars


@pytest.fixture
def client():
    return AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key='synthetic-key',
                                   alpaca_secret_key='synthetic-secret'))


def http_body(monkeypatch, body, status=200):
    calls = []
    def send(self, request, **kwargs):
        calls.append(request)
        response = Response()
        response.status_code = status
        response.request = request
        response.url = request.url
        response._content = body
        response._content_consumed = True
        return response
    monkeypatch.setattr(Session, 'send', send)
    return calls


@pytest.mark.parametrize('method', ['get_orders', 'get_positions'])
@pytest.mark.parametrize('body,status', [(b'{}', 200), (b'""', 200), (b'null', 200), (b'', 204)])
def test_incomplete_http_collection_is_not_a_verified_empty_account(monkeypatch, client, method, body, status):
    calls = http_body(monkeypatch, body, status)
    client._paper_connection_verified = True
    client._verified_account = {'id': 'synthetic-account'}
    with pytest.raises(BrokerConnectionError):
        getattr(client, method)()
    assert len(calls) == 1
    assert not client.is_connected() and client._verified_account is None


@pytest.mark.parametrize('method', ['get_orders', 'get_positions'])
def test_explicit_http_empty_array_remains_a_valid_empty_collection(monkeypatch, client, method):
    calls = http_body(monkeypatch, b'[]')
    assert getattr(client, method)() == []
    assert len(calls) == 1


def test_incomplete_http_asset_list_is_unknown_not_verified_untradable(monkeypatch, client):
    http_body(monkeypatch, b'{}')
    assert client.get_instrument_availability('AAPL')['paper_tradable'] == 'unknown'


@pytest.mark.parametrize('payload', [
    b'{"rates":{"USD":true},"date":"2026-01-01"}',
    b'{"rates":{"USD":1.1},"date":"2999-01-01"}',
])
def test_unusable_fx_response_is_not_a_valid_conversion(monkeypatch, payload):
    monkeypatch.setattr(fx_rates, 'urlopen', lambda *args, **kwargs: io.BytesIO(payload))
    with pytest.raises(RuntimeError):
        fx_rates.fetch_eur_usd_rate()


def operational_bars():
    now = pd.Timestamp('2026-10-28T15:00:30Z')
    frame = pd.DataFrame({'timestamp': pd.to_datetime(['2026-10-28T14:58:00Z', '2026-10-28T14:59:00Z']),
                          'close': [100.0, 101.0]})
    frame.attrs.update(quality='real', interval='1Min', bar_time_contract='alpaca-start-v1',
                       fetched_at=now, bar_calendar='NYSE', session_scope='all_sessions')
    return frame, now


@pytest.mark.parametrize('quality', ['synthetic', None, 'unavailable'])
def test_operational_gate_rejects_non_real_or_missing_provenance(quality):
    frame, now = operational_bars()
    frame.attrs['quality'] = quality
    with pytest.raises(BarTimingError):
        select_completed_bars(frame, 'AAPL', now)


@pytest.mark.parametrize('flag', [True, None, 'false'])
def test_synthetic_or_unknown_row_markers_cannot_be_overridden_by_real_attrs(flag):
    frame, now = operational_bars()
    frame['is_synthetic'] = [False, flag]
    with pytest.raises(BarTimingError):
        select_completed_bars(frame, 'AAPL', now)


def test_closed_real_rows_and_false_synthetic_markers_remain_usable():
    frame, now = operational_bars()
    frame['is_synthetic'] = False
    assert len(select_completed_bars(frame, 'AAPL', now)) == 2


def test_old_bars_do_not_pass_the_operational_gate_even_with_fresh_quote():
    frame, now = operational_bars()
    with pytest.raises(BarTimingError, match='stale'):
        select_completed_bars(frame, 'AAPL', now + pd.Timedelta(minutes=20))


def test_overlapping_credentials_are_completely_redacted():
    client = AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key='synthetic',
                                     alpaca_secret_key='synthetic-secret-long'))
    assert client.describe_error(RuntimeError('synthetic-secret-long synthetic')) == '<redacted> <redacted>'


@pytest.mark.parametrize('method,args', [
    ('get_orders', ()), ('get_positions', ()), ('get_market_data', ('AAPL',)), ('get_latest_quote', ('AAPL',)),
])
def test_truncated_http_body_is_an_error_not_partial_data_or_fallback(monkeypatch, client, method, args):
    from requests.exceptions import ChunkedEncodingError
    calls = []
    def truncated(*args, **kwargs):
        calls.append(1)
        raise ChunkedEncodingError('synthetic incomplete response body')
    monkeypatch.setattr(Session, 'send', truncated)
    client._paper_connection_verified = True
    client._verified_account = {'id': 'synthetic-account'}
    with pytest.raises(BrokerConnectionError):
        getattr(client, method)(*args)
    assert len(calls) == 1
    if method in {'get_orders', 'get_positions'}:
        assert not client.is_connected() and client._verified_account is None


def test_account_read_error_requires_reverification_and_never_reuses_old_balance(client):
    old_account = dict(id='synthetic-account', status='ACTIVE', cash='1000',
                       trading_blocked=False, account_blocked=False)
    new_account = dict(old_account, cash='2000')
    def timeout():
        raise TimeoutError('synthetic connection loss')
    client._paper_connection_verified = True
    client._verified_account = old_account
    fake = SimpleNamespace(get_account=timeout, get_all_positions=lambda: [], get_orders=lambda **kwargs: [])
    client.client = fake
    with pytest.raises(BrokerConnectionError):
        client.get_paper_snapshot()
    assert not client.is_connected() and client._verified_account is None
    fake.get_account = lambda: new_account
    snapshot = client.get_paper_snapshot()
    assert client.is_connected() and snapshot['account']['cash'] == '2000'
    assert old_account['cash'] == '1000'


@pytest.mark.parametrize('symbol', ['AAPL', 'BTC/USD'])
@pytest.mark.parametrize('limit,incremental,expected_sort', [(1000, False, 'desc'),
    (None, False, 'asc'), (100, True, 'asc')])
def test_limited_history_fetches_recent_window_without_changing_full_history_or_backfill(
    monkeypatch, client, symbol, limit, incremental, expected_sort
):
    import json
    from urllib.parse import parse_qs, urlsplit
    now = datetime(2026, 10, 28, 15, 0, 30, tzinfo=timezone.utc)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr('src.broker.alpaca_client.datetime', FrozenDatetime)
    queries = []
    def send(self, request, **kwargs):
        query = parse_qs(urlsplit(request.url).query)
        queries.append(query)
        # Emulate the SDK/API default ASC contract for a capped historical window.
        recent = query.get('sort') == ['desc']
        times = ['2026-10-28T14:59:00Z', '2026-10-28T14:58:00Z'] if recent else [
                 '2026-08-01T14:58:00Z', '2026-08-01T14:59:00Z']
        rows = [dict(t=t, o=100, h=101, l=99, c=100, v=10, n=1, vw=100) for t in times]
        response = Response()
        response.status_code = 200
        response.request = request
        response.url = request.url
        response._content = json.dumps({'bars': {symbol: rows}, 'next_page_token': None}).encode('utf-8')
        response._content_consumed = True
        return response
    monkeypatch.setattr(Session, 'send', send)
    start = now - timedelta(minutes=3) if incremental else None
    data = client.get_market_data(symbol, timeframe='1Min', period='3M', limit=limit, start_time=start)
    assert queries[0].get('sort', ['asc']) == [expected_sort]
    assert data['timestamp'].is_monotonic_increasing
    if expected_sort == 'desc':
        assert len(select_completed_bars(data, symbol, now)) == 2
