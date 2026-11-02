"""Single-host Paper ownership and durable uncertainty; never a distributed lock."""
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import threading
import time

try:
    import fcntl
except ImportError:  # Unsupported platforms fail closed.
    fcntl = None


class PaperCoordinationError(RuntimeError):
    pass


def account_scope(account_id):
    if not isinstance(account_id, str) or not account_id.strip():
        raise PaperCoordinationError("Stable Paper account identity is required.")
    return hashlib.sha256(("alpaca-paper:" + account_id.strip()).encode()).hexdigest()


class PaperAccountCoordinator:
    """All cooperating processes must use the same local directory for an account."""

    def __init__(self, directory, account_id):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise PaperCoordinationError("Paper coordinator directory must be absolute.")
        self.scope = account_scope(account_id)

    @contextmanager
    def acquire(self):
        if fcntl is None:
            raise PaperCoordinationError("Exclusive Paper ownership is unavailable on this platform.")
        descriptor = None
        db = None
        lease = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.directory / (self.scope + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PaperCoordinationError("Paper account executor is already owned; no decision is allowed.") from None
            db = sqlite3.connect(self.directory / (self.scope + ".sqlite3"), timeout=1)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS intents (client_id TEXT PRIMARY KEY, resolved INTEGER NOT NULL)")
            lease = PaperExecutionLease(self.scope, self.directory.resolve(), descriptor, db)
            yield lease
        except (OSError, sqlite3.Error) as exc:
            raise PaperCoordinationError("Paper ownership/journal cannot be verified; execution is blocked.") from exc
        finally:
            if lease is not None:
                lease.active = False
            if db is not None:
                db.close()
            if descriptor is not None:
                os.close(descriptor)  # Never unlink: replacing the inode creates two owners.


class PaperExecutionLease:
    def __init__(self, scope, directory, descriptor, db):
        self.scope, self.descriptor, self.db = scope, descriptor, db
        self.directory = directory
        self.owner = (os.getpid(), threading.get_ident())
        self.started = time.monotonic()
        self.active = True
        self.reserved = None
        self.sent = False
        self.submission_check = None

    def assert_owner(self, account_id=None):
        if not self.active or self.owner != (os.getpid(), threading.get_ident()):
            raise PaperCoordinationError("Paper executor ownership is invalid or released.")
        if account_id is not None and account_scope(str(account_id)) != self.scope:
            raise PaperCoordinationError("Paper account changed during evaluation; execution is blocked.")
        if time.monotonic() - self.started > 30:
            raise PaperCoordinationError("Paper decision exceeded its 30-second validity; execution is blocked.")
        os.fstat(self.descriptor)
        current = os.stat(self.directory / (self.scope + ".lock"))
        owned = os.fstat(self.descriptor)
        if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
            raise PaperCoordinationError("Paper lock file was replaced; execution is blocked.")

    def assert_account(self, account_id):
        if account_scope(account_id) != self.scope:
            raise PaperCoordinationError("Paper account changed during evaluation; execution is blocked.")
        self.assert_owner()

    def reconcile_unfilled(self, orders):
        self.assert_owner()
        rows = self.db.execute("SELECT client_id FROM intents WHERE resolved=0").fetchall()
        for (client_id,) in rows:
            matches = [order for order in orders if _field(order, "client_order_id") == client_id]
            if len(matches) != 1:
                raise PaperCoordinationError("Uncertain Paper intent requires reconciliation; absence is not rejection.")
            order = matches[0]
            status = _field(order, "status")
            status = str(getattr(status, "value", status)).lower()
            try:
                quantity = float(_field(order, "filled_qty"))
            except (TypeError, ValueError, OverflowError):
                quantity = float("nan")
            if status not in {"rejected", "canceled", "cancelled", "expired"} or not math.isfinite(quantity) or quantity != 0:
                raise PaperCoordinationError("Pending or filled Paper intent needs verified account reconciliation; execution is blocked.")
            with self.db:
                self.db.execute("UPDATE intents SET resolved=1 WHERE client_id=?", (client_id,))

    def reserve(self, client_id):
        self.assert_owner()
        if self.db.execute("SELECT 1 FROM intents WHERE resolved=0 LIMIT 1").fetchone():
            raise PaperCoordinationError("Unresolved Paper intent blocks another submission.")
        try:
            with self.db:
                self.db.execute("INSERT INTO intents VALUES (?,0)", (client_id,))
        except sqlite3.IntegrityError:
            raise PaperCoordinationError("Paper decision was already reserved; no retry is allowed.") from None
        self.reserved = client_id

    def authorize_submission(self, client_id, account_id):
        self.assert_owner(account_id)
        if self.sent or self.reserved != client_id:
            raise PaperCoordinationError("Paper submission requires its own durable intent and active owner.")
        if not callable(self.submission_check):
            raise PaperCoordinationError("Paper submission requires final decision validation.")
        self.submission_check()
        self.assert_owner(account_id)
        self.sent = True


def _field(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
