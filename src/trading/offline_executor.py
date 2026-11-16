"""Durable dry-run control journal. No broker adapter or financial ledger authority."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from functools import wraps
from uuid import UUID

import portalocker


class OfflineExecutionError(RuntimeError):
    pass


STATES = {'STOPPED', 'STARTING', 'RUNNING', 'PAUSING', 'PAUSED', 'STOPPING', 'ERROR', 'RECOVERY_REQUIRED'}
ORDER_STATES = {'pending', 'acknowledged', 'partial', 'filled', 'rejected', 'canceled', 'expired', 'unknown', 'reconciliation_required'}
TERMINAL = {'filled', 'rejected', 'canceled', 'expired'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp text required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def _number(value, positive=False):
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError('Invalid quantity or balance')
    return number


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._mutex:
            return method(self, *args, **kwargs)
    return call


class OfflineExecutor:
    """Single-host/process owner, one journal per explicit application context.

    Reconciliation accepts synthetic adapter snapshots only from Python callers;
    it never submits orders or books money. A matching snapshot only unlocks a
    stopped dry-run. The HTTP API deliberately exposes no snapshot import gate.
    """

    def __init__(self, directory: Path, context: str):
        if context not in {'demo', 'simulation', 'paper', 'mt5'}:
            raise ValueError('Unknown control context')
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ValueError('Absolute application directory required')
        self.context = context
        self.path = self.directory / f'local-v1-{context}-control.sqlite3'
        self.descriptor = None
        self.pid = os.getpid()
        self._mutex = threading.RLock()

    def _check_path(self):
        for path in (self.path, self.path.with_suffix('.lock')):
            if path.is_symlink() or (path.exists() and path.stat().st_nlink > 1):
                raise OfflineExecutionError('Control journal aliases are blocked.')

    def _db(self):
        self._check_path()
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _own(self):
        if self.pid != os.getpid():
            raise OfflineExecutionError('Inherited executor cannot own another process.')
        if self.descriptor is not None:
            owned, actual = os.fstat(self.descriptor.fileno()), self.path.with_suffix('.lock').stat()
            if (owned.st_dev, owned.st_ino) != (actual.st_dev, actual.st_ino):
                raise OfflineExecutionError('Control lock identity changed.')
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._check_path()
        descriptor = self.path.with_suffix('.lock').open('a+b')
        try:
            portalocker.lock(descriptor, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.LockException:
            descriptor.close()
            raise OfflineExecutionError('Dry-run context already owned; no cycle allowed.') from None
        self.descriptor = descriptor
        try:
            with closing(self._db()) as db, db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, command TEXT NOT NULL, result TEXT);
                    CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, proposal TEXT NOT NULL,
                        state TEXT NOT NULL, provider_status TEXT, broker_id TEXT, filled_quantity TEXT NOT NULL DEFAULT '0', updated_at TEXT);
                    CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, body TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
                ''')
                state = self._status(db)
                if state['state'] not in {'STOPPED', 'RECOVERY_REQUIRED'}:
                    state.update(state='RECOVERY_REQUIRED', reason='Previous owner stopped without verified recovery.', reconciliation='required')
                self._save(db, state, 'ownership')
        except BaseException:
            self.close(graceful=False)
            raise

    def _default(self):
        return dict(state='STOPPED', reason='Explicit dry-run start required. Broker execution is disabled.',
            last_start=None, last_stop=None, last_cycle=None, last_error=None, proposals=0, intents=0,
            reconciliation='not_required', mode='dry-run', execution_enabled=False, context=self.context)

    def _status(self, db):
        row = db.execute('SELECT body FROM control WHERE id=1').fetchone()
        state = json.loads(row[0]) if row else self._default()
        if state.get('state') not in STATES or state.get('context') != self.context:
            raise OfflineExecutionError('Control journal invalid; execution remains disabled.')
        state['execution_enabled'] = False
        state['intents'] = db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]
        return state

    def status(self):
        self._check_path()
        if not self.path.exists():
            return self._default()
        with closing(self._db()) as db:
            state = self._status(db)
        if self.descriptor is None and state['state'] not in {'STOPPED', 'RECOVERY_REQUIRED'}:
            state.update(state='RECOVERY_REQUIRED', reason='Active journal requires owner/restart verification.', reconciliation='required')
        return state

    def _save(self, db, state, event):
        state['execution_enabled'] = False
        db.execute('INSERT OR REPLACE INTO control VALUES(1,?)', (json.dumps(state),))
        db.execute('INSERT INTO events(timestamp,kind,detail) VALUES(?,?,?)', (_now(), event, state['state']))

    def _transition(self, state, target, reason):
        state.update(state=target, reason=reason)
        with closing(self._db()) as db, db:
            self._save(db, state, target)

    @_serialized
    def command(self, command: str, request_id: str, *, evaluate=None):
        if command not in {'start', 'pause', 'stop', 'cycle'}:
            raise OfflineExecutionError('Unknown dry-run command.')
        request_id = str(UUID(request_id))
        self._own()
        with closing(self._db()) as db, db:
            previous = db.execute('SELECT command,result FROM commands WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['command'] != command:
                    raise OfflineExecutionError('Request ID belongs to a different command.')
                # Return current state; never replay a previously active state to the UI.
                return self._status(db)
            state = self._status(db)
            if command == 'cycle' and (state['state'] != 'RUNNING' or not callable(evaluate)):
                raise OfflineExecutionError('An armed dry-run and explicit evaluator are required.')
            db.execute('INSERT INTO commands VALUES(?,?,NULL)', (request_id, command))
        if state['state'] == 'RECOVERY_REQUIRED':
            return state
        if command == 'start':
            if state['state'] not in {'STOPPED', 'PAUSED'}:
                raise OfflineExecutionError('Dry-run is already active.')
            self._transition(state, 'STARTING', 'Preparing offline analysis; broker writes disabled.')
            state['last_start'] = _now()
            self._transition(state, 'RUNNING', 'Dry-run armed. Run each analytical cycle explicitly; no scheduler or orders.')
        elif command == 'pause':
            if state['state'] != 'RUNNING':
                raise OfflineExecutionError('Only an armed dry-run can pause.')
            self._transition(state, 'PAUSING', 'Pausing offline cycles.')
            self._transition(state, 'PAUSED', 'Offline cycles paused; broker writes disabled.')
        elif command == 'stop':
            self._transition(state, 'STOPPING', 'Stopping offline cycles.')
            state['last_stop'] = _now()
            self._transition(state, 'STOPPED', 'Offline cycles stopped; broker writes disabled.')
        else:
            state['last_cycle'] = _now()
            self._transition(state, 'RUNNING', 'Analytical cycle in progress; no financial side effects.')
            try:
                proposal = evaluate()
                state['proposals'] += 1
                if not isinstance(proposal, dict):
                    raise ValueError('Invalid proposal')
                if proposal.get('validation_state') == 'PAPER_PROPOSAL':
                    if not proposal.get('signal_id') or _timestamp(proposal['expires_at']) <= datetime.now(timezone.utc):
                        raise ValueError('Invalid or expired intent')
                    identity = hashlib.sha256((self.context + ':' + proposal['signal_id']).encode()).hexdigest()
                    with closing(self._db()) as db, db:
                        db.execute('INSERT OR IGNORE INTO intents(id,proposal,state) VALUES(?,?,?)',
                            (identity, json.dumps(proposal, sort_keys=True, allow_nan=False), 'created'))
                    for target in ('validated', 'dry_run_completed'):
                        with closing(self._db()) as db, db:
                            db.execute("UPDATE intents SET state=? WHERE id=? AND state IN ('created','validated')", (target, identity))
                            db.execute('INSERT INTO events(timestamp,kind,detail) VALUES(?,?,?)', (_now(), target, identity))
                    state['reason'] = 'Intent recorded in dry-run only; no broker submission exists.'
                else:
                    state['reason'] = 'No executable proposal; analytical/risk gate did not authorize an intent.'
                self._transition(state, 'RUNNING', state['reason'])
            except Exception:
                state.update(last_error='Analytical cycle failed; diagnostics withheld.', reconciliation='required')
                self._transition(state, 'RECOVERY_REQUIRED', 'Cycle outcome requires explicit verified recovery; no retry.')
        with closing(self._db()) as db, db:
            state = self._status(db)
            db.execute('UPDATE commands SET result=? WHERE id=?', (json.dumps(state), request_id))
        return state

    def intents(self):
        if not self.path.exists():
            return []
        with closing(self._db()) as db:
            return [dict(row) for row in db.execute('SELECT * FROM intents ORDER BY rowid')]

    @_serialized
    def reconcile(self, snapshot: dict, *, expected_balance, expected_positions: dict) -> bool:
        """Validate a complete synthetic adapter view; never infer absence from silence."""
        self._own()
        state = self.status()
        try:
            if not isinstance(snapshot, dict) or not isinstance(expected_positions, dict):
                raise ValueError('Snapshot and expected positions required')
            if snapshot.get('scope') != self.context or snapshot.get('complete') is not True:
                raise ValueError('Incomplete scope')
            age = (datetime.now(timezone.utc) - _timestamp(snapshot['as_of'])).total_seconds()
            if not 0 <= age <= 30:
                raise ValueError('Stale snapshot')
            if _number(snapshot['balance']) != _number(expected_balance):
                raise ValueError('Balance divergence')
            actual = {key: _number(value) for key, value in snapshot['positions'].items() if _number(value) != 0}
            expected = {key: _number(value) for key, value in expected_positions.items() if _number(value) != 0}
            if actual != expected:
                raise ValueError('Position divergence')
            pages = {}
            for page in snapshot['pages']:
                cursor = page['cursor']
                if cursor in pages and pages[cursor] != page:
                    raise ValueError('Conflicting duplicate page')
                pages[cursor] = page
            cursor, visited, orders, fills = None, set(), {}, {}
            while True:
                if cursor not in pages or cursor in visited:
                    raise ValueError('Missing or cyclic pagination')
                visited.add(cursor)
                page = pages[cursor]
                for order in page['orders']:
                    identity = order['intent_id']
                    if identity in orders and orders[identity] != order:
                        raise ValueError('Conflicting orders')
                    orders[identity] = order
                for fill in page['fills']:
                    core = {key: fill[key] for key in ('intent_id', 'broker_id', 'quantity', 'price')}
                    if _timestamp(fill['timestamp']) > _timestamp(snapshot['as_of']):
                        raise ValueError('Execution newer than snapshot')
                    _number(fill['quantity'], positive=True)
                    _number(fill['price'], positive=True)
                    if fill['id'] in fills and fills[fill['id']] != core:
                        raise ValueError('Conflicting executions')
                    fills[fill['id']] = core
                cursor = page['next_cursor']
                if cursor is None:
                    break
            if len(visited) != len(pages):
                raise ValueError('Unreachable pagination')
            with closing(self._db()) as db, db:
                local = {row['id']: dict(row) for row in db.execute('SELECT * FROM intents')}
                if set(orders) - set(local) or any(identity not in orders for identity in local):
                    raise ValueError('Unknown or missing order; absence is not rejection')
                for identity, core in fills.items():
                    if core['intent_id'] not in local:
                        raise ValueError('Unknown execution')
                    old = db.execute('SELECT body FROM executions WHERE id=?', (identity,)).fetchone()
                    payload = json.dumps(core, sort_keys=True)
                    if old and old[0] != payload:
                        raise ValueError('Changed execution')
                    db.execute('INSERT OR IGNORE INTO executions VALUES(?,?,?)', (identity, core['intent_id'], payload))
                for identity, order in orders.items():
                    row = local[identity]
                    if order['status'] not in ORDER_STATES or order['status'] in {'unknown', 'reconciliation_required'}:
                        raise ValueError('Uncertain order')
                    updated = _timestamp(order['updated_at'])
                    if updated > _timestamp(snapshot['as_of']):
                        raise ValueError('Order newer than snapshot')
                    if row['broker_id'] not in {None, order['broker_id']} or not order['broker_id']:
                        raise ValueError('Order reference changed')
                    reported = _number(order['filled_quantity'])
                    executions = [json.loads(item[0]) for item in db.execute('SELECT body FROM executions WHERE intent_id=?', (identity,))]
                    if any(item['broker_id'] != order['broker_id'] for item in executions):
                        raise ValueError('Execution reference mismatch')
                    quantity = sum((_number(item['quantity'], positive=True) for item in executions), Decimal(0))
                    requested = _number(json.loads(row['proposal'])['quantity'], positive=True)
                    if quantity > requested:
                        raise ValueError('Overfill')
                    if row['updated_at'] and updated < _timestamp(row['updated_at']):
                        if quantity != _number(row['filled_quantity']):
                            raise ValueError('Late event with new execution requires current order view')
                        continue
                    if quantity != reported or (order['status'] == 'filled' and quantity != requested):
                        raise ValueError('Execution quantity mismatch')
                    if order['status'] in {'pending', 'acknowledged', 'rejected', 'expired'} and quantity != 0:
                        raise ValueError('Provider status contradicts fills')
                    if order['status'] == 'partial' and not 0 < quantity < requested:
                        raise ValueError('Invalid partial fill')
                    if row['state'] in TERMINAL and row['state'] != order['status']:
                        raise ValueError('Terminal state regression')
                    db.execute('UPDATE intents SET state=?,provider_status=?,broker_id=?,filled_quantity=?,updated_at=? WHERE id=?',
                        (order['status'], order['status'], order['broker_id'], str(quantity), order['updated_at'], identity))
                state.update(reconciliation='verified_offline', reason='Synthetic snapshot reconciled. Explicit start required; broker writes disabled.')
                if state['state'] == 'RECOVERY_REQUIRED':
                    state['state'] = 'STOPPED'
                self._save(db, state, 'reconciled')
            return True
        except (ValueError, KeyError, TypeError, InvalidOperation, sqlite3.Error):
            state.update(reconciliation='required', last_error='Snapshot incomplete, inconsistent or unavailable.')
            self._transition(state, 'RECOVERY_REQUIRED', 'Verified reconciliation required; no submission or retry is allowed.')
            return False

    @_serialized
    def close(self, *, graceful=True):
        if self.descriptor is None:
            return
        try:
            if graceful and self.pid == os.getpid():
                state = self.status()
                if state['state'] != 'RECOVERY_REQUIRED':
                    state['last_stop'] = _now()
                    self._transition(state, 'STOPPED', 'Service closed; explicit dry-run start required.')
        finally:
            self.descriptor.close()
            self.descriptor = None
