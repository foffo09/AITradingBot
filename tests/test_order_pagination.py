"""Order history uses only offline SDK-shaped responses and temporary state."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def orders(count):
    return [{'id': f'order-{index}', 'submitted_at': NOW - timedelta(seconds=index), 'status': 'filled'} for index in range(count)]


def reader(respond):
    broker = AlpacaClient(AppSettings(trading_mode='demo'))
    broker.client = SimpleNamespace(get_orders=respond)
    broker._paper_connection_verified = True
    broker._verified_account = {'id': 'offline-account'}
    return broker


def test_paginated_orders_overlap_boundary_and_deduplicate_without_omissions():
    history = orders(1200)
    calls = []
    def respond(filter):
        calls.append(filter)
        assert filter.limit == 500
        assert filter.status.value == 'all'
        assert filter.direction.value == 'desc'
        available = [item for item in history if filter.until is None or item['submitted_at'] < filter.until]
        return available[:filter.limit]
    broker = reader(respond)
    assert broker.get_orders() == history
    assert len(calls) == 3
    assert calls[1].until == history[498]['submitted_at']
    assert calls[2].until == history[997]['submitted_at']
    assert broker.is_connected()


def test_equal_timestamps_at_boundary_are_recovered_with_overlap():
    history = orders(700)
    history[499]['submitted_at'] = history[498]['submitted_at']
    history[500]['submitted_at'] = history[498]['submitted_at']
    def respond(filter):
        return [item for item in history if filter.until is None or item['submitted_at'] < filter.until][:500]
    assert reader(respond).get_orders() == history


@pytest.mark.parametrize('failure', ['missing-time', 'naive-time', 'missing-id', 'duplicate-id', 'unsorted', 'same-time', 'repeated-page', 'missing-overlap', 'changed-time', 'intermediate-error', 'oversized'])
def test_ambiguous_or_failed_pagination_never_returns_partial_history(failure):
    history = orders(700)
    first = history[:500]
    if failure == 'missing-time': first[499] = {'id': 'missing-time'}
    if failure == 'naive-time': first[499] = {**first[499], 'submitted_at': NOW.replace(tzinfo=None)}
    if failure == 'missing-id': first[499] = {'submitted_at': history[499]['submitted_at']}
    if failure == 'duplicate-id': first[499] = {**first[499], 'id': first[498]['id']}
    if failure == 'unsorted': first[1], first[2] = first[2], first[1]
    if failure == 'same-time': first = [{**item, 'submitted_at': NOW} for item in first]
    if failure == 'oversized': first = history[:501]
    calls = []
    def respond(filter):
        calls.append(filter)
        if len(calls) == 1: return first
        if failure == 'intermediate-error': raise TimeoutError('offline timeout')
        if failure == 'repeated-page': return first
        if failure == 'missing-overlap': return history[500:]
        if failure == 'changed-time': return [{**history[499], 'submitted_at': history[500]['submitted_at']}, *history[500:]]
        return history[499:]
    broker = reader(respond)
    with pytest.raises(BrokerConnectionError):
        broker.get_orders()
    assert not broker.is_connected()
    assert broker._verified_account is None


def test_more_than_page_of_orders_at_same_timestamp_is_ambiguous():
    history = orders(1100)
    for item in history[499:]:
        item['submitted_at'] = history[499]['submitted_at']
    def respond(filter):
        return [item for item in history if filter.until is None or item['submitted_at'] < filter.until][:500]
    with pytest.raises(BrokerConnectionError):
        reader(respond).get_orders()


def test_pagination_is_bounded_even_with_valid_infinite_history():
    calls = []
    def respond(filter):
        calls.append(filter)
        offset = 499 * (len(calls) - 1)
        return [{'id': f'order-{index}', 'submitted_at': NOW - timedelta(seconds=index)} for index in range(offset, offset + 500)]
    with pytest.raises(BrokerConnectionError):
        reader(respond).get_orders()
    assert len(calls) == 100
