from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.broker import mt5_readonly


@pytest.fixture
def terminal(monkeypatch):
    now = pd.Timestamp.now(tz='UTC').floor('ms')
    rows = np.array([(int((now - pd.Timedelta(days=1)).timestamp()), 100., 102., 99., 101., 42)], dtype=[('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8')])
    state = SimpleNamespace(
        account=SimpleNamespace(trade_mode=0, login=123, server='Offline broker', balance=1000., equity=1001., currency='USD'),
        connected=True, positions=(), orders=(),
        tick=SimpleNamespace(bid=100., ask=101., time_msc=int(now.timestamp() * 1000)),
        rows=rows, initializations=[], shutdowns=[],
    )
    module = SimpleNamespace(
        initialize=lambda **kwargs: state.initializations.append(kwargs) or True,
        shutdown=lambda: state.shutdowns.append(True),
        terminal_info=lambda: SimpleNamespace(connected=state.connected),
        account_info=lambda: state.account,
        positions_get=lambda: state.positions,
        orders_get=lambda: state.orders,
        symbol_info_tick=lambda symbol: state.tick,
        copy_rates_from_pos=lambda *args: state.rows,
        TIMEFRAME_D1=1440, ACCOUNT_TRADE_MODE_DEMO=0,
    )
    monkeypatch.setattr(mt5_readonly.sys, 'platform', 'win32')
    monkeypatch.setattr(mt5_readonly.importlib, 'import_module', lambda name: module)
    reader = mt5_readonly.MT5ReadOnly()
    reader.connect()
    return reader, state


def test_snapshot_has_verified_connection_finite_units_and_utc_observation(terminal):
    reader, state = terminal
    assert state.initializations == [{'timeout': 5000}]
    snapshot = reader.snapshot()
    assert snapshot['connection']['status'] == 'connected'
    assert snapshot['account']['cash'] == 1000
    assert snapshot['account']['currency'] == 'USD'
    assert snapshot['account']['source'] == 'MetaTrader 5 terminal'
    assert datetime.fromisoformat(snapshot['account']['updated_at']).tzinfo == timezone.utc
    assert 'login' not in snapshot['account']


@pytest.mark.parametrize('field,value', [('balance', float('nan')), ('equity', float('inf')), ('balance', True), ('balance', '100'), ('login', None), ('login', True), ('server', ''), ('currency', '')])
def test_invalid_account_is_not_published_as_connected(terminal, field, value):
    reader, state = terminal
    setattr(state.account, field, value)
    result = reader.snapshot()
    assert result['connection']['status'] == 'unavailable'
    assert result['account'] is None
    assert result['positions'] == [] and result['orders'] == []


def test_disconnect_or_missing_collections_never_reuses_previous_balance(terminal):
    reader, state = terminal
    assert reader.snapshot()['account']['cash'] == 1000
    state.connected = False
    assert reader.snapshot()['account'] is None
    state.connected = True
    state.orders = None
    assert reader.snapshot()['account'] is None


def test_quote_is_real_bid_ask_with_utc_timestamp_and_midpoint(terminal):
    reader, state = terminal
    quote = reader.latest_quote('AAPL')
    assert quote['bid'] == 100 and quote['ask'] == 101 and quote['price'] == 100.5
    assert quote['source'] == 'MetaTrader 5 terminal tick'
    assert datetime.fromisoformat(quote['timestamp']).tzinfo == timezone.utc


@pytest.mark.parametrize('field,value', [('bid', float('nan')), ('ask', float('inf')), ('bid', True), ('bid', -1), ('ask', 99), ('time_msc', None), ('time_msc', True), ('time_msc', 0)])
def test_invalid_tick_never_falls_back_to_historical_close(terminal, field, value):
    reader, state = terminal
    setattr(state.tick, field, value)
    with pytest.raises(ValueError):
        reader.latest_quote('AAPL')


@pytest.mark.parametrize('age', [121, -10])
def test_stale_and_future_quote_are_rejected(terminal, age):
    reader, state = terminal
    state.tick.time_msc = int((pd.Timestamp.now(tz='UTC') - pd.Timedelta(seconds=age)).timestamp() * 1000)
    with pytest.raises(ValueError):
        reader.latest_quote('AAPL')


def test_missing_quote_is_not_synthetic(terminal):
    reader, state = terminal
    state.tick = None
    with pytest.raises(ValueError):
        reader.latest_quote('AAPL')


def test_history_preserves_real_source_and_tick_volume_units(terminal):
    reader, state = terminal
    data = reader.market_data('AAPL', '1Day')
    assert data.attrs['quality'] == 'real'
    assert data.attrs['volume_unit'] == 'ticks'
    assert data.attrs['fetched_at']
    assert data.iloc[0]['volume'] == 42


@pytest.mark.parametrize('field,value', [('open', float('nan')), ('high', 1), ('low', 1000), ('close', -1), ('time', 9999999999), ('tick_volume', -1)])
def test_invalid_bar_never_reaches_chart_or_strategy(terminal, field, value):
    reader, state = terminal
    state.rows[field][0] = value
    with pytest.raises(ValueError):
        reader.market_data('AAPL', '1Day')


def test_api_stale_tick_clears_values_and_does_not_reuse_earlier_quote(terminal, tmp_path):
    from src.api.local_app import create_local_app
    from fastapi.testclient import TestClient
    reader, state = terminal
    client = TestClient(create_local_app(data_dir=tmp_path, port=8123), base_url='http://127.0.0.1:8123')
    headers = {'Origin': 'http://127.0.0.1:8123', 'X-Local-Request': '1'}
    client.get('/api/v1/session', headers=headers)
    client.post('/api/v1/connections/mt5', headers=headers)
    first = client.get('/api/v1/market?context=mt5&symbol=AAPL').json()
    assert first['status'] == 'ready'
    assert first['quote']['bid'] == 100
    state.tick.time_msc = int((pd.Timestamp.now(tz='UTC') - pd.Timedelta(minutes=5)).timestamp() * 1000)
    stale = client.get('/api/v1/market?context=mt5&symbol=AAPL').json()
    assert stale['status'] == 'stale'
    assert stale['quote'] is None and stale['bars'] == []


def test_nonfinite_native_position_clears_entire_snapshot(terminal):
    reader, state = terminal
    from collections import namedtuple
    Position = namedtuple('Position', 'volume price_open price_current profit')
    state.positions = (Position(1, 100, 100, float('nan')),)
    assert reader.snapshot()['account'] is None


def test_boolean_bar_prices_are_not_money(terminal):
    reader, state = terminal
    state.rows = np.array([(int(pd.Timestamp.now(tz='UTC').timestamp()), True, True, True, True, 1)], dtype=[('time', 'i8'), ('open', '?'), ('high', '?'), ('low', '?'), ('close', '?'), ('tick_volume', 'i8')])
    with pytest.raises(ValueError):
        reader.market_data('AAPL', '1Day')


@pytest.mark.parametrize('mode', [None, True, 1, 2, '0'])
def test_non_demo_or_unknown_terminal_account_is_blocked_on_every_read(terminal, mode):
    reader, state = terminal
    state.account.trade_mode = mode
    assert reader.snapshot()['account'] is None
    with pytest.raises(mt5_readonly.MT5ReadError):
        reader.latest_quote('AAPL')
    with pytest.raises(mt5_readonly.MT5ReadError):
        reader.market_data('AAPL', '1Day')
    reader.connect()
    assert reader.snapshot()['connection']['status'] != 'connected'
    assert reader._module is None
