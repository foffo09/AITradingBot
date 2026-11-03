"""Real local locks and temporary journals; no broker or credentials."""
import multiprocessing
import os
import sqlite3
import sys

import portalocker
import pytest

from src.trading.native_store import NativeStore


@pytest.fixture(autouse=True)
def safe_spawn(monkeypatch):
    # Streamlit AppTest can leave app.py as the multiprocessing entry point.
    monkeypatch.setattr(sys.modules['__main__'], '__file__', None, raising=False)
    monkeypatch.setattr(sys.modules['__main__'], '__spec__', None, raising=False)


def hold_journal(path, ready, release, crash):
    from conftest import guard
    store = NativeStore(path, 'synthetic-testnet-account')
    store.set('intent', 'synthetic-intent')
    assert not any(guard.attempts.values())
    ready.set()
    if crash:
        os._exit(0)
    try:
        assert release.wait(15)
    finally:
        store.close()


@pytest.mark.parametrize('crash', [False, True])
def test_process_ownership_and_release_preserve_journal(tmp_path, crash):
    path = tmp_path / 'journal.sqlite3'
    ctx = multiprocessing.get_context('spawn')
    ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=hold_journal, args=(path, ready, release, crash))
    process.start()
    try:
        assert ready.wait(15)
        if not crash:
            with pytest.raises(RuntimeError, match='already in use'):
                NativeStore(path, 'synthetic-testnet-account')
        release.set()
        process.join(15)
        assert process.exitcode == 0
        store = NativeStore(path, 'synthetic-testnet-account')
        try:
            assert store.get('intent') == 'synthetic-intent'
            assert path.with_suffix('.sqlite3.lock').exists()
        finally:
            store.close()
    finally:
        release.set()
        if process.is_alive():
            process.terminate()
        process.join(10)


def test_second_handle_is_excluded_and_close_is_idempotent(tmp_path):
    path = tmp_path / 'journal.sqlite3'
    first = NativeStore(path, 'fixture')
    try:
        with pytest.raises(RuntimeError, match='already in use'):
            NativeStore(path, 'fixture')
    finally:
        first.close()
    first.close()
    second = NativeStore(path, 'fixture')
    second.close()


@pytest.mark.parametrize('failure', ['connect', 'schema', 'scope'])
def test_initialization_failure_releases_lock_and_connection(tmp_path, monkeypatch, failure):
    path = tmp_path / 'journal.sqlite3'
    if failure == 'schema':
        path.write_bytes(b'not sqlite')
    if failure == 'scope':
        first = NativeStore(path, 'fixture')
        first.close()
    with monkeypatch.context() as patch:
        if failure == 'connect':
            def fail(*args, **kwargs):
                raise sqlite3.OperationalError('synthetic initialization failure')
            patch.setattr('src.trading.native_store.sqlite3.connect', fail)
        with pytest.raises((sqlite3.Error, RuntimeError)) as caught:
            NativeStore(path, 'different' if failure == 'scope' else 'fixture')
    assert caught.value is not None
    # Keep the failing traceback alive: cleanup must not depend on GC.
    with path.with_suffix('.sqlite3.lock').open('a+b') as handle:
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        portalocker.unlock(handle)
    if failure != 'schema':
        recovered = NativeStore(path, 'fixture')
        recovered.close()


def test_lock_backend_failure_never_opens_database(tmp_path, monkeypatch):
    def fail(*args):
        raise portalocker.LockException('synthetic lock failure')
    monkeypatch.setattr('src.trading.native_store.portalocker.lock', fail)
    path = tmp_path / 'journal.sqlite3'
    with pytest.raises((RuntimeError, portalocker.LockException)):
        NativeStore(path, 'fixture')
    assert not path.exists()
    # The failed open handle must be closed even though no lock was acquired.
    path.with_suffix('.sqlite3.lock').unlink()


def test_unlock_error_still_closes_handle(tmp_path, monkeypatch):
    path = tmp_path / 'journal.sqlite3'
    store = NativeStore(path, 'fixture')
    with monkeypatch.context() as patch:
        def fail(*args):
            raise portalocker.LockException('synthetic unlock failure')
        patch.setattr('src.trading.native_store.portalocker.unlock', fail)
        with pytest.raises(portalocker.LockException):
            store.close()
    assert store.lock_file.closed
    recovered = NativeStore(path, 'fixture')
    recovered.close()


def test_panic_uri_preserves_windows_style_path_characters(tmp_path):
    path = tmp_path / 'synthetic journal #1.sqlite3'
    store = NativeStore(path, 'fixture')
    try:
        NativeStore.queue_panic(path, 'fixture')
        assert store.get('panic') is True
    finally:
        store.close()
