"""Backend regressions use synthetic responses, never authenticated operations."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from requests import Response, Session

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError

NOW = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_backend_clock(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr("src.broker.alpaca_client.datetime", FrozenDatetime)


def paper_client():
    return AlpacaClient(AppSettings(trading_mode='paper', alpaca_api_key='synthetic-key',
                                   alpaca_secret_key='synthetic-secret'))


def install_http(monkeypatch, statuses):
    calls = []
    def send(self, request, **kwargs):
        calls.append((request, kwargs))
        response = Response()
        response.status_code = statuses[min(len(calls) - 1, len(statuses) - 1)]
        response._content_consumed = True
        response._content = b'{"code":429,"message":"synthetic response"}'
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(Session, 'send', send)
    monkeypatch.setattr('alpaca.common.rest.time.sleep', lambda _: None)
    return calls


@pytest.mark.parametrize('attribute', ['client', 'market_data_client', 'crypto_data_client'])
def test_sdk_requests_have_bounded_timeout(monkeypatch, attribute):
    calls = install_http(monkeypatch, [200])
    client = getattr(paper_client(), attribute)
    client._request('GET', '/synthetic-test')
    assert calls[0][1]['timeout'] == (3.05, 10.0)
    assert calls[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('method', ['POST', 'DELETE', 'PATCH'])
def test_paper_writes_are_never_retried_on_429(monkeypatch, method):
    calls = install_http(monkeypatch, [429, 200])
    from alpaca.common.exceptions import APIError
    with pytest.raises(APIError):
        paper_client().client._request(method, '/synthetic-test')
    assert len(calls) == 1


def test_only_market_data_gets_receive_bounded_429_retries(monkeypatch):
    calls = install_http(monkeypatch, [429, 429, 200])
    paper_client().market_data_client._request('GET', '/synthetic-test')
    assert len(calls) == 3
    calls.clear()
    from alpaca.common.exceptions import APIError
    with pytest.raises(APIError):
        paper_client().client._request('GET', '/synthetic-test')
    assert len(calls) == 1


@pytest.mark.parametrize('url', ['https://api.alpaca.markets', 'http://paper-api.alpaca.markets',
                                  'https://paper-api.alpaca.markets.evil.invalid'])
def test_wrong_trading_destination_is_blocked_before_http(monkeypatch, url):
    calls = install_http(monkeypatch, [200])
    client = paper_client()
    client.client._base_url = url
    assert client.verify_connection()['connected'] is False
    assert calls == []


def test_data_transport_rejects_writes_and_redirects(monkeypatch):
    calls = install_http(monkeypatch, [302])
    client = paper_client().market_data_client
    with pytest.raises(ValueError, match='read-only'):
        client._request('POST', '/synthetic-test')
    assert calls == []
    with pytest.raises(ValueError, match='redirect'):
        client._request('GET', '/synthetic-test')
    assert len(calls) == 1


def quote_client(quote):
    client = AlpacaClient(AppSettings(trading_mode='demo'))
    client.market_data_client = SimpleNamespace(get_stock_latest_quote=lambda request: {'AAPL': quote})
    return client


@pytest.mark.parametrize('timestamp', [datetime(2026, 1, 1), pd.NaT,
    NOW - timedelta(minutes=5), NOW + timedelta(days=1)])
def test_quotes_reject_naive_missing_stale_and_future_times(timestamp):
    client = quote_client(SimpleNamespace(bid_price=99, ask_price=101, timestamp=timestamp))
    with pytest.raises(BrokerConnectionError):
        client.get_latest_quote('AAPL')


@pytest.mark.parametrize('price', [1e308, 5e-324])
def test_quote_timestamp_is_utc_and_midpoint_cannot_overflow(price):
    quote = SimpleNamespace(bid_price=price, ask_price=price,
                            timestamp=pd.Timestamp(NOW).tz_convert('America/New_York'))
    result = quote_client(quote).get_latest_quote('AAPL')
    assert result['price'] == price
    assert pd.Timestamp(result['timestamp']).utcoffset() == timedelta(0)


@pytest.mark.parametrize('method,attribute', [('get_positions', 'get_all_positions'), ('get_orders', 'get_orders'),
                                            ('get_account', 'get_account')])
@pytest.mark.parametrize('payload', [None, 'invalid'])
def test_missing_or_malformed_broker_response_invalidates_connection(method, attribute, payload):
    client = AlpacaClient(AppSettings(trading_mode='demo'))
    client.client = SimpleNamespace(**{attribute: lambda **kwargs: payload})
    client._paper_connection_verified = True
    client._verified_account = {'id': 'synthetic-account'}
    with pytest.raises(BrokerConnectionError):
        getattr(client, method)()
    assert not client.is_connected()
    assert client._verified_account is None


def test_stale_account_is_cleared_after_timeout_without_leaking_secrets():
    client = paper_client()
    def timeout():
        raise TimeoutError('synthetic-key synthetic-secret')
    client.client = SimpleNamespace(get_account=timeout)
    client._paper_connection_verified = True
    client._verified_account = {'id': 'synthetic-account'}
    with pytest.raises(BrokerConnectionError) as caught:
        client.get_account()
    assert not client.is_connected() and client._verified_account is None
    assert 'synthetic-key' not in str(caught.value)
    assert 'synthetic-secret' not in str(caught.value)


@pytest.mark.parametrize('timestamp', [NOW + timedelta(days=1), datetime(2026, 1, 1)])
def test_bars_reject_future_or_timezone_free_timestamps(timestamp):
    frame = pd.DataFrame([dict(timestamp=timestamp, open=10, high=11, low=9, close=10, volume=1)])
    client = AlpacaClient(AppSettings(trading_mode='demo'))
    client.market_data_client = SimpleNamespace(get_stock_bars=lambda request: SimpleNamespace(df=frame))
    with pytest.raises(BrokerConnectionError):
        client.get_market_data('AAPL', timeframe='1Min')


def test_transport_does_not_read_personal_netrc(monkeypatch):
    calls = install_http(monkeypatch, [200])
    def forbidden(*args, **kwargs):
        pytest.fail('Explicit SDK credentials must not trigger personal netrc lookup')
    monkeypatch.setattr('requests.sessions.get_netrc_auth', forbidden)
    paper_client().client._request('GET', '/synthetic-test')
    assert len(calls) == 1


@pytest.mark.parametrize('method', ['get_account', 'get_positions', 'get_orders'])
def test_failed_paper_initialization_is_not_a_demo_or_empty_account(monkeypatch, method):
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic unavailable SDK')
    monkeypatch.setattr('src.broker.alpaca_client.TradingClient', fail)
    client = paper_client()
    verification = client.verify_connection()
    assert verification['mode'] == 'paper'
    assert verification['status'] == 'error'
    with pytest.raises(BrokerConnectionError):
        getattr(client, method)()


@pytest.mark.parametrize('value', ['NaN', 'Infinity', True, 'unavailable'])
def test_invalid_account_amounts_block_snapshot_instead_of_becoming_zero(value):
    client = AlpacaClient(AppSettings(trading_mode='demo'))
    client.client = SimpleNamespace(get_account=lambda: {'status': 'ACTIVE', 'cash': value})
    with pytest.raises(BrokerConnectionError):
        client.get_account()


def test_unknown_account_amounts_remain_missing():
    account = {'status': 'ACTIVE', 'cash': None, 'equity': None, 'buying_power': None}
    client = AlpacaClient(AppSettings(trading_mode='demo'))
    client.client = SimpleNamespace(get_account=lambda: account)
    assert client.get_account() == account


@pytest.mark.parametrize('bid,ask', [(True, 2), (1, True), (0, 1), (2, 1), (float('nan'), 2), (1, float('inf'))])
def test_invalid_bid_ask_are_rejected(bid, ask):
    quote = SimpleNamespace(bid_price=bid, ask_price=ask, timestamp=NOW)
    with pytest.raises(BrokerConnectionError):
        quote_client(quote).get_latest_quote('AAPL')


def test_shared_coordinator_path_accepts_spaces_and_unicode(tmp_path):
    from src.trading.paper_coordinator import PaperAccountCoordinator
    directory = tmp_path / 'dati Paper è' / 'account'
    settings = AppSettings(paper_execution_scope='single_host', paper_coordinator_directory=str(directory))
    with PaperAccountCoordinator(settings.paper_coordinator_directory, 'synthetic-account').acquire() as lease:
        lease.assert_owner('synthetic-account')
    assert directory.exists()
    with pytest.raises(ValueError, match='absolute'):
        AppSettings(paper_execution_scope='single_host', paper_coordinator_directory='relative/paper')


@pytest.mark.parametrize('status,expected_attempts', [(429, 3), (504, 3), (401, 1), (403, 1), (503, 1)])
def test_market_data_retries_are_exhausted_and_other_errors_are_immediate(monkeypatch, status, expected_attempts):
    from alpaca.common.exceptions import APIError
    calls = install_http(monkeypatch, [status])
    with pytest.raises(APIError):
        paper_client().market_data_client._request('GET', '/synthetic-test')
    assert len(calls) == expected_attempts


def test_market_data_transport_timeout_is_not_silently_retried(monkeypatch):
    from requests import Timeout
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        raise Timeout('synthetic HTTP timeout')
    monkeypatch.setattr(Session, 'send', timeout)
    with pytest.raises(Timeout):
        paper_client().market_data_client._request('GET', '/synthetic-test')
    assert calls == [(3.05, 10.0)]


def test_reenabled_sdk_retries_block_public_submission_before_http(monkeypatch):
    calls = install_http(monkeypatch, [200])
    client = paper_client()
    client._paper_connection_verified = True
    client._verified_account = {'id': 'synthetic-account'}
    client.client._retry = 1
    with pytest.raises(PermissionError, match='retries must remain disabled'):
        client.submit_order(symbol='AAPL', side='buy', quantity=1, client_order_id='synthetic-intent')
    assert calls == []
    assert not client.is_connected() and client._verified_account is None


@pytest.mark.parametrize('age', [0, 120])
def test_quote_freshness_boundary_is_inclusive(age):
    quote = SimpleNamespace(bid_price=99, ask_price=101, timestamp=NOW - timedelta(seconds=age))
    result = quote_client(quote).get_latest_quote('AAPL')
    assert result['bid'] == 99 and result['ask'] == 101 and result['price'] == 100


@pytest.mark.parametrize('timestamp', [NOW - timedelta(seconds=120, microseconds=1), NOW + timedelta(microseconds=1)])
def test_quote_just_outside_freshness_boundary_is_rejected(timestamp):
    quote = SimpleNamespace(bid_price=99, ask_price=101, timestamp=timestamp)
    with pytest.raises(BrokerConnectionError):
        quote_client(quote).get_latest_quote('AAPL')


def coordinated_fake_client(monkeypatch, tmp_path, response=None):
    account = dict(id='synthetic-account', status='ACTIVE', trading_blocked=False, account_blocked=False)
    sent = []
    def submit(request):
        sent.append(request)
        return response
    fake = SimpleNamespace(get_account=lambda: account, submit_order=submit)
    monkeypatch.setattr('src.broker.alpaca_client.TradingClient', lambda *args, **kwargs: fake)
    settings = AppSettings(trading_mode='paper', alpaca_api_key='synthetic-key',
                           alpaca_secret_key='synthetic-secret', paper_execution_scope='single_host',
                           paper_coordinator_directory=str(tmp_path / 'Paper è'))
    client = AlpacaClient(settings)
    assert client.verify_connection()['connected'] is True
    return client, account, sent


@pytest.mark.parametrize('field', ['trading_blocked', 'account_blocked'])
@pytest.mark.parametrize('value', [None, 0, 'false', True])
def test_unknown_final_account_flags_never_authorize_orders(monkeypatch, tmp_path, field, value):
    client, account, sent = coordinated_fake_client(monkeypatch, tmp_path)
    account[field] = value
    with client.paper_coordinator.acquire() as lease:
        lease.reserve('synthetic-intent')
        lease.submission_check = lambda: None
        with pytest.raises(PermissionError, match='unblocked'):
            client.submit_order(symbol='AAPL', side='buy', quantity=1,
                                client_order_id='synthetic-intent', _execution_lease=lease)
    assert sent == []
    assert not client.is_connected()


def broken_ack_serialization(**kwargs):
    raise ValueError('synthetic serialization error')


@pytest.mark.parametrize('response', [None, {}, 'invalid',
    SimpleNamespace(model_dump=broken_ack_serialization), {'id': 'synthetic-ack', 'status': 'accepted',
                                                         'client_order_id': 'different-intent'}])
def test_ambiguous_or_mismatched_ack_blocks_connection_and_retry(monkeypatch, tmp_path, response):
    client, account, sent = coordinated_fake_client(monkeypatch, tmp_path, response)
    with client.paper_coordinator.acquire() as lease:
        lease.reserve('synthetic-intent')
        lease.submission_check = lambda: None
        with pytest.raises(BrokerConnectionError, match='order response'):
            client.submit_order(symbol='AAPL', side='buy', quantity=1,
                                client_order_id='synthetic-intent', _execution_lease=lease)
        assert not client.is_connected()
        with pytest.raises(PermissionError):
            client.submit_order(symbol='AAPL', side='buy', quantity=1,
                                client_order_id='synthetic-intent', _execution_lease=lease)
    assert len(sent) == 1
    assert client._verified_account is None


def test_wrapped_sdk_traceback_does_not_leak_credentials():
    import traceback
    client = paper_client()
    def failure():
        raise RuntimeError('synthetic-key synthetic-secret')
    client.client = SimpleNamespace(get_account=failure)
    with pytest.raises(BrokerConnectionError) as caught:
        client.get_account()
    rendered = ''.join(traceback.format_exception(caught.value))
    assert 'synthetic-key' not in rendered
    assert 'synthetic-secret' not in rendered
    assert '<redacted>' in rendered
