import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pytest

from src.simulation.ledger import SCHEMA_VERSION, SimulationLedger


def version(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('PRAGMA user_version').fetchone()[0]


def with_account(path):
    SimulationLedger(path).initialize_account(initial_eur=1000, eur_usd_rate=1, fx_source='test',
                                              fx_timestamp=datetime.now(timezone.utc).isoformat())


def test_new_ledger_is_stamped_without_backup(tmp_path):
    SimulationLedger(tmp_path / 'l.sqlite3')
    assert version(tmp_path / 'l.sqlite3') == SCHEMA_VERSION
    assert not list(tmp_path.glob('*.bak'))


def test_older_ledger_is_backed_up_before_migration_and_keeps_history(tmp_path):
    path = tmp_path / 'l.sqlite3'
    with_account(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA user_version = 0')
        db.commit()
    ledger = SimulationLedger(path)
    [backup] = tmp_path.glob('l.sqlite3.v0-*.bak')
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('SELECT COUNT(*) FROM account').fetchone()[0] == 1
    assert ledger.account() is not None and version(path) == SCHEMA_VERSION
    SimulationLedger(path)
    assert len(list(tmp_path.glob('*.bak'))) == 1, 'no backup once already current'


def test_ledger_from_a_newer_app_is_refused_untouched(tmp_path):
    path = tmp_path / 'l.sqlite3'
    with_account(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION + 1}')
        db.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='newer than this app'):
        SimulationLedger(path)
    assert path.read_bytes() == before
