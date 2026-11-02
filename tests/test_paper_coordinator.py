import multiprocessing
import os
import sys
import threading

import pytest

from config.settings import AppSettings
from src.trading.paper_coordinator import PaperAccountCoordinator, PaperCoordinationError


@pytest.fixture(autouse=True)
def spawn_without_reexecuting_streamlit(monkeypatch):
    # AppTest leaves __main__.__file__ pointing at app.py; spawn must not execute it.
    monkeypatch.setattr(sys.modules["__main__"], "__file__", None, raising=False)
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", None, raising=False)


def worker(directory, barrier, pipe, crash=False):
    from conftest import guard
    coordinator = PaperAccountCoordinator(directory, "fixture-account")
    if barrier is not None:
        barrier.wait(timeout=10)
    try:
        with coordinator.acquire() as lease:
            lease.reconcile_unfilled([])
            lease.reserve("ma-process-intent")
            assert not any(guard.attempts.values())
            pipe.send("reserved")
            if crash:
                os._exit(0)
    except PaperCoordinationError:
        pipe.send("blocked")
    finally:
        pipe.close()


def test_three_simultaneous_processes_cannot_reserve_using_the_same_empty_snapshot(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(3)
    processes, pipes = [], []
    for _ in range(3):
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=worker, args=(str(tmp_path), barrier, child))
        process.start()
        child.close()
        processes.append(process)
        pipes.append(parent)
    outcomes = []
    for pipe, process in zip(pipes, processes):
        assert pipe.poll(15), "Worker did not complete its local coordination check"
        outcomes.append(pipe.recv())
        pipe.close()
        process.join(10)
        assert process.exitcode == 0
    assert outcomes.count("reserved") == 1
    assert outcomes.count("blocked") == 2


def test_owner_is_exclusive_nonexpiring_and_released_after_error(tmp_path, monkeypatch):
    coordinator = PaperAccountCoordinator(tmp_path, "fixture-account")
    with pytest.raises(ValueError, match="fixture failure"):
        with coordinator.acquire() as lease:
            with pytest.raises(PaperCoordinationError, match="already owned"):
                with coordinator.acquire():
                    pytest.fail("Second owner must not enter")
            monkeypatch.setattr("src.trading.paper_coordinator.time.monotonic", lambda: lease.started + 31)
            with pytest.raises(PaperCoordinationError, match="30-second"):
                lease.reserve("expired-decision")
            # An expired decision does not permit stealing the live OS lock.
            with pytest.raises(PaperCoordinationError, match="already owned"):
                with coordinator.acquire():
                    pytest.fail("Expired decision must not release ownership")
            raise ValueError("fixture failure")
    with pytest.raises(PaperCoordinationError, match="released"):
        lease.assert_owner()
    with coordinator.acquire() as new_lease:
        new_lease.assert_owner()


def test_process_crash_releases_os_lock_but_preserves_uncertainty(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=worker, args=(str(tmp_path), None, child, True))
    process.start()
    child.close()
    assert parent.poll(15)
    assert parent.recv() == "reserved"
    parent.close()
    process.join(10)
    assert process.exitcode == 0
    with PaperAccountCoordinator(tmp_path, "fixture-account").acquire() as lease:
        with pytest.raises(PaperCoordinationError, match="absence is not rejection"):
            lease.reconcile_unfilled([])
        with pytest.raises(PaperCoordinationError, match="Unresolved"):
            lease.reserve("different-signal")


@pytest.mark.parametrize("status,quantity", [("accepted", "0"), ("partially_filled", "0.2"),
    ("filled", "1"), ("canceled", "0.2"), ("rejected", None), ("rejected", "NaN")])
def test_unverified_or_filled_intent_never_clears_on_restart(tmp_path, status, quantity):
    coordinator = PaperAccountCoordinator(tmp_path, "fixture-account")
    with coordinator.acquire() as lease:
        lease.reserve("ma-uncertain")
    with coordinator.acquire() as lease:
        with pytest.raises(PaperCoordinationError, match="execution is blocked"):
            lease.reconcile_unfilled([{"client_order_id": "ma-uncertain", "status": status, "filled_qty": quantity}])


def test_recovery_only_after_terminal_zero_fill_and_duplicate_stays_reserved(tmp_path):
    coordinator = PaperAccountCoordinator(tmp_path, "fixture-account")
    with coordinator.acquire() as lease:
        lease.reserve("ma-rejected")
    with coordinator.acquire() as lease:
        lease.reconcile_unfilled([{"client_order_id": "ma-rejected", "status": "rejected", "filled_qty": "0"}])
        with pytest.raises(PaperCoordinationError, match="already reserved"):
            lease.reserve("ma-rejected")
        lease.reserve("ma-new-signal")
        with pytest.raises(PaperCoordinationError, match="final decision validation"):
            lease.authorize_submission("ma-new-signal", "fixture-account")
        lease.submission_check = lambda: None
        lease.authorize_submission("ma-new-signal", "fixture-account")
        with pytest.raises(PaperCoordinationError):
            lease.authorize_submission("ma-new-signal", "fixture-account")


def test_different_account_thread_and_released_lease_cannot_authorize(tmp_path):
    with PaperAccountCoordinator(tmp_path, "fixture-account").acquire() as lease:
        lease.reserve("ma-owned")
        with pytest.raises(PaperCoordinationError, match="account changed"):
            lease.authorize_submission("ma-owned", "other-account")
        errors = []
        def try_other_thread():
            try:
                lease.assert_owner()
            except PaperCoordinationError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=try_other_thread)
        thread.start()
        thread.join(5)
        assert errors and not thread.is_alive()
    with pytest.raises(PaperCoordinationError, match="released"):
        lease.authorize_submission("ma-owned", "fixture-account")


def test_final_validation_cannot_extend_the_decision_deadline(tmp_path, monkeypatch):
    with PaperAccountCoordinator(tmp_path, "fixture-account").acquire() as lease:
        lease.reserve("ma-deadline")
        def slow_validation():
            monkeypatch.setattr("src.trading.paper_coordinator.time.monotonic", lambda: lease.started + 31)
        lease.submission_check = slow_validation
        with pytest.raises(PaperCoordinationError, match="30-second"):
            lease.authorize_submission("ma-deadline", "fixture-account")
        assert lease.sent is False


def test_invalid_scope_identity_platform_and_journal_fail_closed(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="distributed execution is unsupported"):
        AppSettings(paper_execution_scope="distributed")
    with pytest.raises(ValueError, match="absolute shared"):
        AppSettings(paper_execution_scope="single_host")
    with pytest.raises(PaperCoordinationError, match="Stable"):
        PaperAccountCoordinator(tmp_path, "")
    coordinator = PaperAccountCoordinator(tmp_path, "fixture-account")
    tmp_path.joinpath(coordinator.scope + ".sqlite3").write_bytes(b"not a sqlite file")
    with pytest.raises(PaperCoordinationError, match="cannot be verified"):
        with coordinator.acquire():
            pytest.fail("Corrupt journal must block evaluation")
    monkeypatch.setattr("src.trading.paper_coordinator.fcntl", None)
    with pytest.raises(PaperCoordinationError, match="unavailable on this platform"):
        with coordinator.acquire():
            pytest.fail("Unsupported locking must block evaluation")
