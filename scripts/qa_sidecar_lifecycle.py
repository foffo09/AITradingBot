"""Independent QA: lifecycle of the frozen sidecar, spawned exactly like src-tauri/src/service.rs.

Loopback only, temporary data dir, no credentials. Prints one PASS/FAIL line per scenario.
Usage: python scripts/qa_sidecar_lifecycle.py dist/backend/aitradingbot-service-<target>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); ask ps for the real state.
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def wait_gone(pids, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(alive(p) for p in pids) and not listening(port):
            return round(timeout - (deadline - time.monotonic()), 2)
        time.sleep(0.1)
    return None


def spawn(binary: str, data: Path):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('ALPACA', 'APCA', 'MT5', 'HYPERLIQUID'))}
    env.update(TRADING_MODE='demo', AUTO_TRADE='false', PAPER_EXECUTION_SCOPE='disabled', PYTHON_DOTENV_DISABLED='1')
    child = subprocess.Popen([binary, '--port', '0', '--ui-dir', str(ROOT / 'frontend/dist'), '--data-dir', str(data)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    ready = json.loads(child.stdout.readline())
    assert ready['supervisor_pid'] == child.pid, ready
    return child, ready['pid'], ready['port']


def scenario(name, binary, action, timeout=25):
    with tempfile.TemporaryDirectory(prefix='aitb-qa-') as tmp:
        child, worker, port = spawn(binary, Path(tmp))
        assert alive(worker) and listening(port)
        action(child, worker)
        took = wait_gone([child.pid, worker], port, timeout)
        child.poll()
        for pid in (worker, child.pid):  # never leave QA processes behind
            if alive(pid):
                os.kill(pid, signal.SIGCONT)
                os.kill(pid, signal.SIGKILL)
        print(f"{'PASS' if took is not None else 'FAIL'} {name}: bootloader={child.pid} worker={worker} port={port} "
              f"{'gone in %ss' % took if took is not None else 'STILL ALIVE/LISTENING after %ss' % timeout}")
        return took is not None


def shutdown_line(child, worker):
    child.stdin.write(b'shutdown\n'); child.stdin.flush()


def close_stdin(child, worker):
    child.stdin.close()


def kill_bootloader_like_tauri_deadline(child, worker):
    # service.rs shutdown(): stdin already dropped, then child.kill() == SIGKILL to the bootloader only.
    child.stdin.close(); os.kill(child.pid, signal.SIGKILL)


def hung_worker_then_tauri_kill(child, worker):
    # Worker blocked (e.g. native read): Tauri gives up after 20s and SIGKILLs the bootloader only.
    os.kill(worker, signal.SIGSTOP)
    child.stdin.write(b'shutdown\n'); child.stdin.flush(); child.stdin.close()
    os.kill(child.pid, signal.SIGKILL)
    time.sleep(3)
    # Known limit (AUDIT-L3): the worker is orphaned (ppid 1) and keeps the port while it is blocked.
    print(f'  LIMIT hung worker orphaned while blocked: alive={alive(worker)}; resuming it to check bounded exit')
    os.kill(worker, signal.SIGCONT)


def sigterm_bootloader(child, worker):
    os.kill(child.pid, signal.SIGTERM)


def main():
    binary = sys.argv[1]
    results = [
        scenario('stdin shutdown (window close / Cmd+Q path)', binary, shutdown_line),
        scenario('stdin EOF (shell crash / pipe closed)', binary, close_stdin),
        scenario('SIGTERM to bootloader', binary, sigterm_bootloader),
        scenario('SIGKILL bootloader after EOF (Tauri 20s deadline)', binary, kill_bootloader_like_tauri_deadline),
        scenario('hung worker + SIGKILL bootloader', binary, hung_worker_then_tauri_kill, timeout=8),
    ]
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
