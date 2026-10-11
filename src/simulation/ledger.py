from __future__ import annotations

import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_simulation_database_path(
    project_root: str | Path,
    demo_database_path: str | Path | None = None,
) -> Path:
    """Resolve an optional demo database path without allowing the personal ledger."""
    root = Path(project_root).resolve()
    personal_path = (root / "data" / "simulation.sqlite3").resolve()
    if demo_database_path is None:
        return personal_path
    if not str(demo_database_path).strip():
        raise ValueError("Demo database path is required when demo isolation is configured.")

    configured_path = Path(demo_database_path).expanduser()
    if not configured_path.is_absolute():
        raise ValueError("Demo database path must be an absolute path.")
    try:
        resolved_path = configured_path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Demo database path could not be safely resolved.") from exc

    if resolved_path == personal_path:
        raise ValueError("Demo database path must not point to the personal simulation ledger.")
    if resolved_path.exists() and not resolved_path.is_file():
        raise ValueError("Demo database path must be a file path, not a directory.")
    if resolved_path.exists() and personal_path.exists():
        try:
            if resolved_path.samefile(personal_path):
                raise ValueError(
                    "Demo database path must not alias the personal simulation ledger."
                )
        except OSError as exc:
            raise ValueError("Demo database path could not be safely verified.") from exc
    return resolved_path


def _positive(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number.")
    return number


def _validate_fresh_data(timestamp: str, max_age_seconds: float) -> None:
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("Maximum market-data age must be positive.")
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Market-data timestamp is invalid.") from exc
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    if age < -120 or age > max_age_seconds:
        raise ValueError("Market data is stale or has a future timestamp; simulated order blocked.")


class SimulationLedger:
    """SQLite ledger for local simulated trades; it never calls a broker."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_cash REAL NOT NULL,
                    cash REAL NOT NULL,
                    initial_eur REAL NOT NULL,
                    eur_usd_rate REAL NOT NULL,
                    fx_source TEXT NOT NULL,
                    fx_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS marks (
                    symbol TEXT PRIMARY KEY,
                    price REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction = 'long'),
                    quantity REAL NOT NULL,
                    remaining_qty REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_fee REAL NOT NULL,
                    entry_spread REAL NOT NULL,
                    entry_slippage REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    entry_reason TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open', 'closed', 'cancelled')),
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS closes (
                    id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL REFERENCES trades(id),
                    quantity REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    exit_fee REAL NOT NULL,
                    exit_spread REAL NOT NULL,
                    exit_slippage REAL NOT NULL,
                    gross_pnl REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    closed_at TEXT NOT NULL,
                    exit_reason TEXT NOT NULL,
                    data_source TEXT NOT NULL DEFAULT '',
                    source_timestamp TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    equity REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS trades_symbol_status ON trades(symbol, status);
                CREATE INDEX IF NOT EXISTS closes_closed_at ON closes(closed_at);
                """
            )
            trade_columns = {row["name"] for row in db.execute("PRAGMA table_info(trades)")}
            if "entry_spread" not in trade_columns:
                db.execute("ALTER TABLE trades ADD COLUMN entry_spread REAL NOT NULL DEFAULT 0")
            close_columns = {row["name"] for row in db.execute("PRAGMA table_info(closes)")}
            if "exit_spread" not in close_columns:
                db.execute("ALTER TABLE closes ADD COLUMN exit_spread REAL NOT NULL DEFAULT 0")
            if "data_source" not in close_columns:
                db.execute("ALTER TABLE closes ADD COLUMN data_source TEXT NOT NULL DEFAULT ''")
            if "source_timestamp" not in close_columns:
                db.execute("ALTER TABLE closes ADD COLUMN source_timestamp TEXT NOT NULL DEFAULT ''")

    def account(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM account WHERE id = 1").fetchone()
            return dict(row) if row else None

    def initialize_account(
        self,
        *,
        initial_eur: float,
        eur_usd_rate: float,
        fx_source: str,
        fx_timestamp: str,
    ) -> dict[str, Any]:
        initial_eur = _positive(initial_eur, "Initial EUR capital")
        eur_usd_rate = _positive(eur_usd_rate, "EUR/USD rate")
        if not fx_source.strip() or not fx_timestamp.strip():
            raise ValueError("FX source and timestamp are required.")
        with self._connect() as db:
            db.execute(
                """INSERT INTO account
                   (id, initial_cash, cash, initial_eur, eur_usd_rate, fx_source, fx_timestamp, created_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                (initial_eur * eur_usd_rate, initial_eur * eur_usd_rate, initial_eur,
                 eur_usd_rate, fx_source, fx_timestamp, _utc_now()),
            )
            db.execute(
                "INSERT INTO snapshots(timestamp, equity) VALUES (?, ?)",
                (_utc_now(), initial_eur * eur_usd_rate),
            )
        return self.account()  # type: ignore[return-value]

    def reset(self, *, initial_eur: float, eur_usd_rate: float, fx_source: str, fx_timestamp: str) -> None:
        initial_eur = _positive(initial_eur, "Initial EUR capital")
        eur_usd_rate = _positive(eur_usd_rate, "EUR/USD rate")
        if not fx_source.strip() or not fx_timestamp.strip():
            raise ValueError("FX source and timestamp are required.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM closes")
            db.execute("DELETE FROM trades")
            db.execute("DELETE FROM marks")
            db.execute("DELETE FROM snapshots")
            db.execute("DELETE FROM account")
            now = _utc_now()
            initial_usd = initial_eur * eur_usd_rate
            db.execute(
                """INSERT INTO account
                   (id, initial_cash, cash, initial_eur, eur_usd_rate, fx_source, fx_timestamp, created_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                (initial_usd, initial_usd, initial_eur, eur_usd_rate, fx_source, fx_timestamp, now),
            )
            db.execute("INSERT INTO snapshots(timestamp, equity) VALUES (?, ?)", (now, initial_usd))

    def update_mark(self, symbol: str, price: float, timestamp: str, source: str) -> None:
        price = _positive(price, "Mark price")
        if not symbol.strip() or not timestamp.strip() or not source.strip():
            raise ValueError("Symbol, timestamp and data source are required.")
        with self._connect() as db:
            db.execute(
                """INSERT INTO marks(symbol, price, timestamp, source) VALUES (?, ?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,
                   timestamp=excluded.timestamp, source=excluded.source""",
                (symbol.upper(), price, timestamp, source),
            )
            account = db.execute("SELECT initial_cash, cash FROM account WHERE id=1").fetchone()
            if account:
                positions = db.execute(
                    "SELECT symbol, remaining_qty, entry_price FROM trades WHERE status='open'"
                ).fetchall()
                market_value = 0.0
                for position in positions:
                    mark = db.execute("SELECT price FROM marks WHERE symbol=?", (position["symbol"],)).fetchone()
                    market_value += position["remaining_qty"] * (mark["price"] if mark else position["entry_price"])
                db.execute(
                    "INSERT INTO snapshots(timestamp, equity) VALUES (?, ?)",
                    (_utc_now(), account["cash"] + market_value),
                )

    def _find_duplicate(self, db: sqlite3.Connection, key: str) -> dict[str, Any] | None:
        row = db.execute("SELECT id FROM trades WHERE idempotency_key=?", (key,)).fetchone()
        if row:
            return {"id": row["id"], "duplicate": True, "kind": "buy"}
        row = db.execute(
            "SELECT id FROM closes WHERE idempotency_key=? OR idempotency_key LIKE ? LIMIT 1",
            (key, f"{key}:%"),
        ).fetchone()
        if row:
            return {"id": row["id"], "duplicate": True, "kind": "sell"}
        return None

    def buy(
        self,
        *,
        symbol: str,
        quantity: float,
        market_price: float,
        commission_bps: float,
        spread_bps: float = 0.0,
        slippage_bps: float,
        max_trade_fraction: float,
        max_exposure_fraction: float,
        daily_loss_limit_fraction: float,
        data_timestamp: str,
        data_source: str,
        reason: str,
        max_data_age_seconds: float = 86_400,
        max_positions: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        quantity = _positive(quantity, "Quantity")
        market_price = _positive(market_price, "Market price")
        if not symbol or not data_timestamp.strip() or not data_source.strip():
            raise ValueError("Symbol, data timestamp and source are required.")
        _validate_fresh_data(data_timestamp, max_data_age_seconds)
        if not 0 <= commission_bps <= 1000 or not 0 <= spread_bps <= 1000 or not 0 <= slippage_bps <= 1000:
            raise ValueError("Commission, spread and slippage must be between 0 and 1000 bps.")
        if not 0 < max_trade_fraction <= 1 or not 0 < max_exposure_fraction <= 1:
            raise ValueError("Risk fractions must be greater than 0 and at most 1.")
        if not 0 <= daily_loss_limit_fraction <= 1:
            raise ValueError("Daily loss limit fraction must be between 0 and 1.")
        key = idempotency_key or str(uuid.uuid4())
        now = _utc_now()
        spread = quantity * market_price * (spread_bps / 2) / 10_000
        slippage = quantity * market_price * slippage_bps / 10_000
        fill = market_price + (spread + slippage) / quantity
        notional = quantity * fill
        fee = notional * commission_bps / 10_000

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = self._find_duplicate(db, key)
            if duplicate:
                return duplicate
            account = db.execute("SELECT * FROM account WHERE id=1").fetchone()
            if not account:
                raise RuntimeError("Initialize the local simulation account before trading.")
            if not math.isfinite(quantity * fill + fee):
                raise ValueError("Order total is not finite.")
            if notional > account["initial_cash"] * max_trade_fraction:
                raise ValueError("Order exceeds the configured maximum per-trade amount.")
            if account["cash"] + 1e-9 < notional + fee:
                raise ValueError("Insufficient simulation cash, including estimated commission.")
            positions = db.execute(
                "SELECT symbol, remaining_qty, entry_price FROM trades WHERE status='open'"
            ).fetchall()
            for position in positions:
                if position["symbol"] == symbol:
                    continue
                mark = db.execute(
                    "SELECT timestamp FROM marks WHERE symbol=?", (position["symbol"],)
                ).fetchone()
                if not mark:
                    raise ValueError("New entries blocked: refresh prices for all existing positions first.")
                _validate_fresh_data(mark["timestamp"], max_data_age_seconds)
            if max_positions is not None:
                if max_positions <= 0:
                    raise ValueError("Maximum open positions must be positive.")
                open_symbols = {position["symbol"] for position in positions}
                if symbol not in open_symbols and len(open_symbols) >= max_positions:
                    raise ValueError("Maximum number of open simulated positions reached.")
            exposure = 0.0
            for position in positions:
                mark = db.execute("SELECT price FROM marks WHERE symbol=?", (position["symbol"],)).fetchone()
                exposure += position["remaining_qty"] * (mark["price"] if mark else position["entry_price"])
            current_mark = db.execute("SELECT price FROM marks WHERE symbol=?", (symbol,)).fetchone()
            exposure += quantity * (current_mark["price"] if current_mark else market_price)
            if exposure > account["initial_cash"] * max_exposure_fraction:
                raise ValueError("Order exceeds the configured maximum total exposure.")
            day_start = datetime.now(timezone.utc).date().isoformat()
            opening_snapshot = db.execute(
                "SELECT equity FROM snapshots WHERE timestamp < ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                (day_start,),
            ).fetchone()
            day_start_equity = opening_snapshot["equity"] if opening_snapshot else account["initial_cash"]
            open_market_value = 0.0
            for position in positions:
                mark = db.execute("SELECT price FROM marks WHERE symbol=?", (position["symbol"],)).fetchone()
                open_market_value += position["remaining_qty"] * (mark["price"] if mark else position["entry_price"])
            current_equity = account["cash"] + open_market_value
            daily_pnl = current_equity - day_start_equity
            loss_limit = day_start_equity * daily_loss_limit_fraction
            if daily_pnl < 0 and (daily_loss_limit_fraction == 0 or daily_pnl <= -loss_limit):
                raise ValueError("Daily loss limit reached; new entries are blocked.")
            trade_id = str(uuid.uuid4())
            db.execute("UPDATE account SET cash=cash-? WHERE id=1", (notional + fee,))
            db.execute(
                """INSERT INTO trades
                   (id,symbol,direction,quantity,remaining_qty,entry_price,entry_fee,entry_spread,entry_slippage,
                    opened_at,entry_reason,data_source,source_timestamp,status,idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trade_id, symbol, "long", quantity, quantity, fill, fee, spread, slippage, now,
                 reason, data_source, data_timestamp, "open", key),
            )
            db.execute(
                """INSERT INTO marks(symbol,price,timestamp,source) VALUES (?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,
                   timestamp=excluded.timestamp, source=excluded.source""",
                (symbol, market_price, data_timestamp, data_source),
            )
            db.execute(
                """INSERT INTO snapshots(timestamp, equity)
                   SELECT ?, account.cash + COALESCE(
                   (SELECT SUM(t.remaining_qty * COALESCE(m.price, t.entry_price))
                    FROM trades t LEFT JOIN marks m ON m.symbol=t.symbol WHERE t.status='open'), 0
               ) FROM account WHERE id=1""",
                (now,),
            )
            return {"id": trade_id, "duplicate": False, "kind": "buy", "fill_price": fill, "fee": fee}

    def sell(
        self,
        *,
        symbol: str,
        quantity: float,
        market_price: float,
        commission_bps: float,
        spread_bps: float = 0.0,
        slippage_bps: float,
        reason: str,
        data_timestamp: str,
        data_source: str,
        max_data_age_seconds: float = 86_400,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        quantity = _positive(quantity, "Quantity")
        market_price = _positive(market_price, "Market price")
        if not symbol:
            raise ValueError("Symbol is required.")
        if not data_timestamp.strip() or not data_source.strip():
            raise ValueError("Market-data timestamp and source are required.")
        _validate_fresh_data(data_timestamp, max_data_age_seconds)
        if not 0 <= commission_bps <= 1000 or not 0 <= spread_bps <= 1000 or not 0 <= slippage_bps <= 1000:
            raise ValueError("Commission, spread and slippage must be between 0 and 1000 bps.")
        key = idempotency_key or str(uuid.uuid4())
        now = _utc_now()
        fill = market_price * (1 - (spread_bps / 2 + slippage_bps) / 10_000)
        remaining_to_sell = quantity
        total_net = 0.0
        close_ids: list[str] = []

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = self._find_duplicate(db, key)
            if duplicate:
                return duplicate
            account = db.execute("SELECT * FROM account WHERE id=1").fetchone()
            if not account:
                raise RuntimeError("Initialize the local simulation account before trading.")
            db.execute(
                """INSERT INTO marks(symbol,price,timestamp,source) VALUES (?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,
                   timestamp=excluded.timestamp, source=excluded.source""",
                (symbol, market_price, data_timestamp, data_source),
            )
            lots = db.execute(
                "SELECT * FROM trades WHERE symbol=? AND status='open' ORDER BY opened_at, id",
                (symbol,),
            ).fetchall()
            available = sum(lot["remaining_qty"] for lot in lots)
            if quantity > available + 1e-9:
                raise ValueError("Sell quantity exceeds the open long position; short selling is disabled.")
            for lot in lots:
                if remaining_to_sell <= 1e-9:
                    break
                sold = min(remaining_to_sell, lot["remaining_qty"])
                exit_notional = sold * fill
                exit_fee = exit_notional * commission_bps / 10_000
                exit_spread = sold * market_price * (spread_bps / 2) / 10_000
                exit_slippage = sold * market_price * slippage_bps / 10_000
                entry_fee_alloc = lot["entry_fee"] * sold / lot["quantity"]
                gross = sold * (fill - lot["entry_price"])
                net = gross - entry_fee_alloc - exit_fee
                close_id = str(uuid.uuid4())
                db.execute(
                    """INSERT INTO closes
                       (id,trade_id,quantity,exit_price,exit_fee,exit_spread,exit_slippage,gross_pnl,net_pnl,
                        closed_at,exit_reason,data_source,source_timestamp,idempotency_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (close_id, lot["id"], sold, fill, exit_fee, exit_spread, exit_slippage, gross, net,
                     now, reason, data_source, data_timestamp, f"{key}:{close_id}"),
                )
                new_remaining = max(0.0, lot["remaining_qty"] - sold)
                db.execute(
                    "UPDATE trades SET remaining_qty=?, status=? WHERE id=?",
                    (new_remaining, "closed" if new_remaining <= 1e-9 else "open", lot["id"]),
                )
                db.execute("UPDATE account SET cash=cash+? WHERE id=1", (exit_notional - exit_fee,))
                total_net += net
                remaining_to_sell -= sold
                close_ids.append(close_id)
            db.execute(
                """INSERT INTO snapshots(timestamp, equity)
                   SELECT ?, account.cash + COALESCE(
                       (SELECT SUM(t.remaining_qty * COALESCE(m.price, t.entry_price))
                        FROM trades t LEFT JOIN marks m ON m.symbol=t.symbol WHERE t.status='open'), 0
                   ) FROM account WHERE id=1""",
                (now,),
            )
        return {"id": close_ids[0], "close_ids": close_ids, "duplicate": False, "kind": "sell", "net_pnl": total_net}

    def positions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT t.symbol, SUM(t.remaining_qty) AS quantity,
                          SUM(t.remaining_qty*t.entry_price) / SUM(t.remaining_qty) AS average_entry,
                          COALESCE(m.price, SUM(t.remaining_qty*t.entry_price)/SUM(t.remaining_qty)) AS market_price,
                          m.timestamp AS mark_timestamp, m.source AS mark_source
                   FROM trades t LEFT JOIN marks m ON m.symbol=t.symbol
                   WHERE t.status='open' GROUP BY t.symbol"""
            ).fetchall()
            return [dict(row) for row in rows]

    def history(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            closed = db.execute(
                """SELECT t.id, c.id AS close_id, t.symbol, t.opened_at, c.closed_at, t.direction, c.quantity,
                          t.entry_price, c.exit_price, t.entry_reason, c.exit_reason,
                          c.gross_pnl + c.exit_spread + c.exit_slippage
                              + t.entry_spread*c.quantity/t.quantity
                              + t.entry_slippage*c.quantity/t.quantity AS gross_pnl,
                          c.net_pnl, c.exit_fee, c.exit_spread, c.exit_slippage,
                          t.entry_fee*c.quantity/t.quantity AS entry_fee_alloc,
                          t.entry_spread*c.quantity/t.quantity AS entry_spread_alloc,
                          t.entry_slippage*c.quantity/t.quantity AS entry_slippage_alloc,
                          c.quantity*t.entry_price AS entry_notional,
                          c.quantity*t.entry_price + t.entry_fee*c.quantity/t.quantity AS entry_invested,
                          c.quantity*c.exit_price AS exit_notional,
                          t.data_source AS entry_data_source, c.data_source AS exit_data_source,
                          c.source_timestamp AS exit_data_timestamp, 'closed' AS status
                   FROM closes c JOIN trades t ON t.id=c.trade_id"""
            ).fetchall()
            open_rows = db.execute(
                """SELECT t.id, NULL AS close_id, t.symbol, t.opened_at, NULL AS closed_at, t.direction,
                          t.remaining_qty AS quantity, t.entry_price, NULL AS exit_price,
                          t.entry_reason, NULL AS exit_reason, NULL AS gross_pnl, NULL AS net_pnl,
                          0 AS exit_fee, 0 AS exit_spread, 0 AS exit_slippage,
                          t.entry_fee*t.remaining_qty/t.quantity AS entry_fee_alloc,
                          t.entry_spread*t.remaining_qty/t.quantity AS entry_spread_alloc,
                          t.entry_slippage*t.remaining_qty/t.quantity AS entry_slippage_alloc,
                          t.remaining_qty*t.entry_price AS entry_notional,
                          t.remaining_qty*t.entry_price + t.entry_fee*t.remaining_qty/t.quantity AS entry_invested,
                          NULL AS exit_notional,
                          t.data_source AS entry_data_source, NULL AS exit_data_source,
                          NULL AS exit_data_timestamp, t.status
                   FROM trades t WHERE t.status='open'"""
            ).fetchall()
            rows = [dict(row) for row in closed] + [dict(row) for row in open_rows]
            return sorted(rows, key=lambda row: row["opened_at"], reverse=True)

    def summary(self, commission_bps: float, slippage_bps: float, spread_bps: float = 0.0) -> dict[str, Any]:
        with self._connect() as db:
            account = db.execute("SELECT * FROM account WHERE id=1").fetchone()
            if not account:
                return {"initialized": False}
            positions = db.execute(
                """SELECT t.symbol, t.remaining_qty, t.entry_price,
                          t.entry_fee*t.remaining_qty/t.quantity AS remaining_entry_fee,
                          m.price AS mark_price
                   FROM trades t LEFT JOIN marks m ON m.symbol=t.symbol
                   WHERE t.status='open'"""
            ).fetchall()
            market_value = 0.0
            unrealized = 0.0
            open_exit_costs = 0.0
            for position in positions:
                mark = position["mark_price"] or position["entry_price"]
                qty = position["remaining_qty"]
                market_value += qty * mark
                exit_fill = mark * (1 - (spread_bps / 2 + slippage_bps) / 10_000)
                fee = qty * exit_fill * commission_bps / 10_000
                spread = qty * mark * (spread_bps / 2) / 10_000
                slippage = qty * mark * slippage_bps / 10_000
                open_exit_costs += fee + spread + slippage
                unrealized += qty * (mark - position["entry_price"]) - position["remaining_entry_fee"] - fee - spread - slippage
            closes = db.execute("SELECT net_pnl, gross_pnl FROM closes").fetchall()
            realized = sum(row["net_pnl"] for row in closes)
            closed_wins = sum(1 for row in closes if row["net_pnl"] > 0)
            closed_losses = sum(1 for row in closes if row["net_pnl"] < 0)
            positive_total = sum(row["net_pnl"] for row in closes if row["net_pnl"] > 0)
            negative_total = sum(row["net_pnl"] for row in closes if row["net_pnl"] < 0)
            costs = db.execute(
                """SELECT COALESCE((SELECT SUM(entry_fee) FROM trades),0)
                          + COALESCE((SELECT SUM(exit_fee) FROM closes),0) AS fees,
                          COALESCE((SELECT SUM(entry_slippage) FROM trades),0)
                          + COALESCE((SELECT SUM(exit_slippage) FROM closes),0) AS slippage,
                          COALESCE((SELECT SUM(entry_spread) FROM trades),0)
                          + COALESCE((SELECT SUM(exit_spread) FROM closes),0) AS spread"""
            ).fetchone()
            equity = account["cash"] + market_value - open_exit_costs
            pnl = realized + unrealized
            snapshots = [row["equity"] for row in db.execute(
                "SELECT equity FROM snapshots ORDER BY timestamp, id"
            ).fetchall()]
            if not snapshots:
                snapshots = [account["initial_cash"]]
            snapshots.append(equity)
            snapshot_rows = db.execute(
                "SELECT timestamp, equity FROM snapshots ORDER BY timestamp, id"
            ).fetchall()
            curve = [{"timestamp": row["timestamp"], "equity": row["equity"]} for row in snapshot_rows]
            curve.append({"timestamp": _utc_now(), "equity": equity})
            peak = snapshots[0]
            max_drawdown = 0.0
            for value in snapshots:
                peak = max(peak, value)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - value) / peak)
            return {
                "initialized": True,
                "initial_capital": account["initial_cash"],
                "initial_eur": account["initial_eur"],
                "eur_usd_rate": account["eur_usd_rate"],
                "fx_source": account["fx_source"],
                "fx_timestamp": account["fx_timestamp"],
                "cash": account["cash"],
                "market_value": market_value,
                "current_capital": equity,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_pnl": pnl,
                "return_pct": pnl / account["initial_cash"] * 100 if account["initial_cash"] else 0.0,
                "closed_trades": len(closes),
                "winning_trades": closed_wins,
                "losing_trades": closed_losses,
                "win_rate": closed_wins / len(closes) * 100 if closes else 0.0,
                "average_win": positive_total / closed_wins if closed_wins else 0.0,
                "average_loss": negative_total / closed_losses if closed_losses else 0.0,
                "profit_factor": positive_total / abs(negative_total) if negative_total else (math.inf if positive_total else 0.0),
                "max_drawdown_pct": max_drawdown * 100,
                "fees": costs["fees"],
                "slippage": costs["slippage"],
                "spread": costs["spread"],
                "open_positions": len(positions),
                "equity_curve": curve,
            }
