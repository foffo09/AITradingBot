from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path

import portalocker

from src.broker.native import AccountSnapshot, NativeOrder, NativeRequest


TERMINAL = {"filled", "canceled", "rejected", "triggered"}


class NativeStore:
    """A single account/process owns this journal. No credentials are stored."""

    def __init__(self, path: Path, scope: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = path.with_suffix(path.suffix + ".lock").open("a+b")
        self.db = None
        self._locked = False
        try:
            try:
                portalocker.lock(self.lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
            except portalocker.AlreadyLocked:
                raise RuntimeError("Native account journal is already in use") from None
            self._locked = True
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    cloid TEXT PRIMARY KEY, purpose TEXT UNIQUE NOT NULL, role TEXT NOT NULL,
                    request TEXT NOT NULL, status TEXT NOT NULL, broker_id INTEGER, created_ms INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS fills (
                    id TEXT PRIMARY KEY, broker_id INTEGER NOT NULL, quantity TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS fills_order ON fills(broker_id);
                CREATE TABLE IF NOT EXISTS exits (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, target TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
            """)
            if self.get("scope") not in {None, scope}:
                raise RuntimeError("Journal belongs to a different account/network")
            self.set("scope", scope)
            if self.get("since_ms") is None:
                self.set("since_ms", int(time.time() * 1000) - 60000)
        except BaseException:
            self.close()
            raise

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def orders(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM orders ORDER BY created_ms, rowid")]

    def find(self, cloid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM orders WHERE cloid=?", (cloid,)).fetchone()
        return dict(row) if row else None

    def reserve(self, purpose: str, role: str, request: NativeRequest) -> bool:
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?,?)",
                (request.cloid, purpose, role, request.model_dump_json(), "submitting", None, int(time.time() * 1000)))
        return cursor.rowcount == 1

    def status(self, cloid: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET status=? WHERE cloid=?", (status, cloid))

    def latch_panic(self) -> None:
        self._latch_panic(self.db)

    @staticmethod
    def _latch_panic(db: sqlite3.Connection) -> None:
        def read(key, default=None):
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default
        with db:
            deadline = read("locked_until", 0)
            if not read("panic") or not deadline:
                deadline = max(deadline, time.time() + 86400)
            for key, value in (("panic", True), ("locked_until", deadline), ("panic_complete", False)):
                db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    @staticmethod
    def queue_panic(path: Path, scope: str) -> None:
        # A second CLI process can persist a kill request without owning the broker connection.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='scope'").fetchone()
            if not row or json.loads(row[0]) != scope:
                raise RuntimeError("Panic journal account/network mismatch")
            NativeStore._latch_panic(db)

    def record(self, snapshot: AccountSnapshot, reports: dict[str, NativeOrder | None]) -> None:
        with self.db:
            previous = self.get("snapshot")
            old_positions = {p["symbol"]: Decimal(p["quantity"]) for p in previous["positions"]} if previous else {}
            for position in snapshot.positions:
                key = "cycle:" + position.symbol
                if old_positions.get(position.symbol, Decimal(0)) == 0 or self.get(key) is None:
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(self.get(key, 0) + 1)))
            for fill in snapshot.fills:
                self.db.execute("INSERT OR IGNORE INTO fills VALUES (?,?,?,?)",
                                (fill.id, fill.broker_id, str(fill.quantity), fill.model_dump_json()))
            for cloid, order in reports.items():
                self.db.execute("UPDATE orders SET status=?,broker_id=COALESCE(?,broker_id) WHERE cloid=?",
                                (order.status if order else "unknown", order.broker_id if order else None, cloid))
                if order and order.broker_id is not None:
                    expected = order.quantity - order.remaining if order.status != "triggered" else Decimal(0)
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                                    (f"expected:{order.broker_id}", json.dumps(str(expected))))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('snapshot',?)", (snapshot.model_dump_json(),))
            if snapshot.fills:
                cursor = max(int(self.get("since_ms")), max(fill.timestamp_ms for fill in snapshot.fills) - 60000)
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('since_ms',?)", (json.dumps(cursor),))

    def filled(self, broker_id: int | None) -> Decimal:
        return sum((Decimal(row[0]) for row in self.db.execute("SELECT quantity FROM fills WHERE broker_id=?", (broker_id,))), Decimal(0))

    def exit_target(self, identity: str, symbol: str, target: Decimal, reopen: bool = False) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO exits(id,symbol,target) VALUES (?,?,?)", (identity, symbol, str(target)))
            if reopen:
                self.db.execute("UPDATE exits SET done=0 WHERE id=?", (identity,))

    def exits(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM exits WHERE done=0")]

    def finish_exit(self, identity: str) -> None:
        with self.db:
            self.db.execute("UPDATE exits SET done=1 WHERE id=?", (identity,))

    def close(self) -> None:
        try:
            if self.db is not None:
                self.db.close()
                self.db = None
        finally:
            if not self.lock_file.closed:
                try:
                    if self._locked:
                        portalocker.unlock(self.lock_file)
                finally:
                    self._locked = False
                    self.lock_file.close()  # Keep the stable sidecar; never unlink an owned lock.
