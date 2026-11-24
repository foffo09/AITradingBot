"""Owned MT5 worker: native calls never execute in the API process."""
from __future__ import annotations

import multiprocessing
import queue
import sys
import threading
import time

from src.broker.mt5_readonly import MT5ReadError, MT5ReadOnly

_SUPPORTED = sys.platform == 'win32'
_OPERATIONS = {'connect', 'snapshot', 'latest_quote', 'market_data', 'close'}
_CLEANUP_SECONDS = .25


def _worker(connection):
    reader = MT5ReadOnly()
    try:
        while True:
            operation, args = connection.recv()
            if operation not in _OPERATIONS:
                connection.send(('error', 'Unsupported terminal operation.', 'unavailable'))
                continue
            try:
                value = getattr(reader, operation)(*args)
                connection.send(('ok', value))
            except MT5ReadError as error:
                connection.send(('error', str(error), error.status))
            except Exception:
                connection.send(('error', 'Terminal operation unavailable.', 'unavailable'))
            if operation == 'close':
                return
    except (EOFError, OSError):
        pass
    finally:
        try:
            reader.close()
        finally:
            connection.close()


class MT5Process:
    def __init__(self, timeout=5.0):
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 60:
            raise ValueError('A finite terminal deadline between 0 and 60 seconds is required.')
        self.timeout = timeout
        self._process = None
        self._connection = None
        self._thread = None
        self._lock = threading.RLock()
        self._status = 'disconnected'
        self._reason = 'Explicit terminal connection required.'

    @property
    def state(self):
        """Cheap local view for status pages: never talks to the terminal worker."""
        if not _SUPPORTED:
            return 'unsupported'
        if self._process is not None and self._status != 'unavailable':
            return 'connected'
        return 'unavailable' if self._status == 'unavailable' else 'disconnected'

    def _dispose(self):
        process, connection = self._process, self._connection
        self._connection = None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(_CLEANUP_SECONDS)
            if process.is_alive():
                process.kill()
                process.join(_CLEANUP_SECONDS)
            if not process.is_alive():
                process.close()
                self._process = None
        if connection is not None:
            connection.close()
        if self._thread is not None:
            self._thread.join(_CLEANUP_SECONDS)
            self._thread = None

    def _request(self, operation, *args):
        deadline = time.monotonic() + self.timeout
        if not self._lock.acquire(timeout=self.timeout):
            raise MT5ReadError('Terminal request deadline exceeded.')
        try:
            if self._process is None or self._connection is None:
                raise MT5ReadError(self._reason)
            result = queue.Queue(maxsize=1)
            connection = self._connection

            def exchange():
                try:
                    connection.send((operation, args))
                    result.put(connection.recv())
                except Exception:
                    result.put(None)

            # Waiting covers complete send/receive, including a partial response frame.
            self._thread = threading.Thread(target=exchange, daemon=True)
            self._thread.start()
            try:
                response = result.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                response = None
            if (not isinstance(response, tuple) or not response
                    or not isinstance(response[0], str)
                    or response[0] not in {'ok', 'error'}
                    or len(response) != (2 if response[0] == 'ok' else 3)):
                self._status = 'unavailable'
                self._reason = 'Terminal worker failed or exceeded its deadline; reconnect explicitly.'
                self._dispose()
                raise MT5ReadError(self._reason)
            self._thread.join(_CLEANUP_SECONDS)
            self._thread = None
            if response[0] == 'error':
                raise MT5ReadError(response[1], status=response[2])
            return response[1]
        finally:
            self._lock.release()

    def connect(self):
        self.close()
        if not _SUPPORTED:
            self._status = 'unsupported'
            self._reason = 'MetaTrader 5 is unsupported on this platform; Windows terminal required.'
            return
        with self._lock:
            if self._process is not None:
                self._status = 'unavailable'
                self._reason = 'Previous terminal worker cleanup was not confirmed.'
                return
            parent, child = multiprocessing.get_context('spawn').Pipe()
            process = multiprocessing.get_context('spawn').Process(target=_worker, args=(child,), daemon=True)
            try:
                process.start()
            except Exception:
                parent.close()
                process.close()
                self._status = 'unavailable'
                self._reason = 'Terminal worker could not start.'
                return
            finally:
                child.close()
            self._process, self._connection = process, parent
            try:
                self._request('connect')
            except MT5ReadError:
                return

    def snapshot(self):
        if self._process is not None:
            try:
                return self._request('snapshot')
            except MT5ReadError:
                pass
        return {'connection': {'status': self._status, 'reason': self._reason},
                'account': None, 'positions': [], 'orders': []}

    def latest_quote(self, symbol):
        return self._request('latest_quote', symbol)

    def market_data(self, symbol, interval):
        return self._request('market_data', symbol, interval)

    def close(self):
        with self._lock:
            if self._connection is not None:
                try:
                    self._request('close')
                except MT5ReadError:
                    pass
            self._dispose()
            self._status = 'disconnected'
            self._reason = 'Explicit terminal connection required.'
