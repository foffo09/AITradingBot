"""Owned MT5 worker: native calls never execute in the API process.

State machine (one worker at most, every transition under ``_lock``):

    disconnected --connect--> starting --ready--> connecting --outcome--> connected | unavailable
    any --close / failure--> disconnected | unavailable (worker always reaped)

Phases have separate bounds: worker start-up (a new interpreter re-imports the service's __main__)
is not charged to the MT5 deadline, and ``connect`` gets more than the 5 s initialize() timeout it wraps.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import multiprocessing
import os
import platform
import queue
import sys
import threading
import time
import uuid

from src.broker.mt5_readonly import INITIALIZE_TIMEOUT_MS, MT5ReadError, MT5ReadOnly

_SUPPORTED = sys.platform == 'win32'
_OPERATIONS = {'connect', 'snapshot', 'latest_quote', 'market_data', 'close'}
_CLEANUP_SECONDS = .25
# Cold interpreter + __mp_main__ re-import + package import, measured separately from MT5 itself.
_STARTUP_SECONDS = 30.0
# initialize() may legitimately use its whole timeout, then terminal_info() and account_info() follow.
_CONNECT_SECONDS = INITIALIZE_TIMEOUT_MS / 1000 + 5.0
_LOG = logging.getLogger('aitradingbot.mt5')


def _worker(connection):
    try:
        # First message: proves the worker started and says which interpreter it runs on.
        connection.send(('ready', {'pid': os.getpid(), 'executable': sys.executable,
                                   'python': platform.python_version()}))
    except (EOFError, OSError):
        connection.close()
        return
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
        self._worker_info = None
        self._diagnostics = {'state': 'disconnected', 'phase': None, 'error_type': None, 'mt5_error': None,
                             'elapsed_ms': None, 'request_id': None, 'worker': None, 'at': None}

    @property
    def state(self):
        """Last verified terminal state, for status pages: never talks to the worker.

        'connected' only after the worker verified initialize, terminal and Demo account (connect outcome
        or a later snapshot); a live worker alone proves nothing.
        """
        if not _SUPPORTED:
            return 'unsupported'
        return self._status if self._status in {'connected', 'unavailable'} else 'disconnected'

    @property
    def diagnostics(self):
        """Safe troubleshooting data: no credentials, balances or account identifiers."""
        return {**self._diagnostics, 'state': self.state, 'reason': self._reason}

    def _record(self, status, reason, *, phase=None, error_type=None, mt5_error=None, elapsed_ms=None):
        self._status, self._reason = status, reason
        self._diagnostics.update(state=status, phase=phase, error_type=error_type, mt5_error=mt5_error,
                                 elapsed_ms=elapsed_ms, worker=self._worker_info,
                                 at=datetime.now(timezone.utc).isoformat())
        if status == 'unavailable':
            _LOG.warning('MT5 %s failed: %s (type=%s, mt5=%s, worker=%s, elapsed_ms=%s, request=%s)', phase, reason,
                         error_type, mt5_error, self._worker_info, elapsed_ms, self._diagnostics['request_id'])

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

    def _exchange(self, message, seconds):
        """Send (unless None) and receive one frame within ``seconds``; None on timeout or broken pipe."""
        result = queue.Queue(maxsize=1)
        connection = self._connection

        def exchange():
            try:
                if message is not None:
                    connection.send(message)
                result.put(connection.recv())
            except Exception:
                result.put(None)

        # Waiting covers complete send/receive, including a partial response frame.
        self._thread = threading.Thread(target=exchange, daemon=True)
        self._thread.start()
        try:
            return result.get(timeout=max(0, seconds))
        except queue.Empty:
            return None

    def _fail(self, phase, started):
        """The worker is gone, hung or spoke garbage: say which, reap it, and raise."""
        process = self._process
        if process is not None:
            process.join(_CLEANUP_SECONDS)  # a broken pipe arrives before Windows reports the exit code
        exitcode = None if process is None else process.exitcode
        error_type = 'worker_exited' if exitcode is not None else 'timeout'
        detail = f'exited with code {exitcode}' if exitcode is not None else 'did not answer in time'
        self._dispose()
        self._record('unavailable', f'Terminal worker {detail} during {phase}; reconnect explicitly.', phase=phase,
                     error_type=error_type, elapsed_ms=round((time.monotonic() - started) * 1000))
        raise MT5ReadError(self._reason)

    def _request(self, operation, *args, seconds=None):
        started = time.monotonic()
        deadline = started + (self.timeout if seconds is None else seconds)
        if not self._lock.acquire(timeout=self.timeout):
            raise MT5ReadError('Terminal request deadline exceeded.')
        try:
            if self._process is None or self._connection is None:
                raise MT5ReadError(self._reason)
            response = self._exchange((operation, args), deadline - time.monotonic())
            if (not isinstance(response, tuple) or not response
                    or not isinstance(response[0], str)
                    or response[0] not in {'ok', 'error'}
                    or len(response) != (2 if response[0] == 'ok' else 3)):
                if response is not None:
                    self._dispose()
                    self._record('unavailable', 'Terminal worker returned an invalid response; reconnect explicitly.',
                                 phase=operation, error_type='invalid_response',
                                 elapsed_ms=round((time.monotonic() - started) * 1000))
                    raise MT5ReadError(self._reason)
                self._fail(operation, started)
            self._thread.join(_CLEANUP_SECONDS)
            self._thread = None
            if response[0] == 'error':
                raise MT5ReadError(response[1], status=response[2])
            return response[1]
        finally:
            self._lock.release()

    def connect(self):
        self.close()
        self._diagnostics['request_id'] = uuid.uuid4().hex[:12]
        if not _SUPPORTED:
            self._record('unsupported', 'MetaTrader 5 is unsupported on this platform; Windows terminal required.',
                         phase='platform')
            return
        with self._lock:
            if self._process is not None:
                self._record('unavailable', 'Previous terminal worker cleanup was not confirmed.', phase='cleanup',
                             error_type='worker_alive')
                return
            started = time.monotonic()
            self._status = 'starting'
            self._worker_info = None
            context = multiprocessing.get_context('spawn')
            parent, child = context.Pipe()
            process = context.Process(target=_worker, args=(child,), daemon=True)
            try:
                process.start()
            except Exception as error:
                parent.close()
                process.close()
                self._record('unavailable', 'Terminal worker could not start.', phase='startup',
                             error_type=type(error).__name__)
                return
            finally:
                child.close()
            self._process, self._connection = process, parent
            ready = self._exchange(None, _STARTUP_SECONDS)
            if not (isinstance(ready, tuple) and len(ready) == 2 and ready[0] == 'ready' and isinstance(ready[1], dict)):
                try:
                    self._fail('startup', started)
                except MT5ReadError:
                    return
            self._thread.join(_CLEANUP_SECONDS)
            self._thread = None
            info = ready[1]
            self._worker_info = {key: info.get(key) for key in ('pid', 'executable', 'python')}
            self._worker_info['startup_ms'] = round((time.monotonic() - started) * 1000)
            self._status = 'connecting'
            try:
                outcome = self._request('connect', seconds=_CONNECT_SECONDS)
            except MT5ReadError:
                return
            if isinstance(outcome, dict) and outcome.get('status') in {'connected', 'unavailable', 'unsupported'}:
                if outcome['status'] != 'connected':
                    self._shutdown_worker()  # nothing to read from: keep the precise reason, not a stale worker
                self._record(outcome['status'], str(outcome.get('reason') or 'Terminal connection outcome unavailable.'),
                             phase=outcome.get('phase'), mt5_error=outcome.get('mt5_error'),
                             elapsed_ms=outcome.get('elapsed_ms'),
                             error_type=None if outcome['status'] == 'connected' else 'mt5')
            else:
                # Older readers answered None: the outcome is only known after a snapshot.
                self._status = 'connecting'

    def snapshot(self):
        if self._process is not None:
            try:
                result = self._request('snapshot')
            except MT5ReadError:
                if self._status != 'unavailable':
                    self._record('unavailable', self._reason, phase='snapshot', error_type='mt5')
            else:
                connection = result.get('connection', {}) if isinstance(result, dict) else {}
                status = connection.get('status')
                if isinstance(result, dict) and status in {'connected', 'disconnected', 'unavailable'}:
                    if status != self._status or status != 'connected':
                        self._record(status, str(connection.get('reason') or self._reason), phase='snapshot',
                                     error_type=None if status == 'connected' else 'mt5')
                    return result
                self._shutdown_worker()
                self._record('unavailable', 'Terminal snapshot was not verifiable; reconnect explicitly.',
                             phase='snapshot', error_type='invalid_response')
        return {'connection': {'status': self._status if self._status in {'connected', 'disconnected', 'unavailable', 'unsupported'}
                               else 'disconnected', 'reason': self._reason},
                'account': None, 'positions': [], 'orders': []}

    def latest_quote(self, symbol):
        return self._request('latest_quote', symbol)

    def market_data(self, symbol, interval):
        return self._request('market_data', symbol, interval)

    def _shutdown_worker(self):
        """Best-effort 'close' to a live worker (MT5 shutdown), then reap it; never records a failure."""
        with self._lock:
            if self._connection is not None and self._process is not None and self._process.is_alive():
                self._exchange(('close', ()), self.timeout)
            self._dispose()

    def close(self):
        with self._lock:
            self._shutdown_worker()
            self._worker_info = None
            self._status = 'disconnected'
            self._reason = 'Explicit terminal connection required.'
            self._diagnostics.update(state='disconnected', worker=None)
