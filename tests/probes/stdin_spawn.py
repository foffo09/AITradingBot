"""Diagnostic (not a pytest test): does a thread blocked on the stdin pipe stop the MT5 worker from starting?

Each mode runs in a child process whose stdin is an open pipe, like the service under Tauri or the launcher:
  none   - nobody reads stdin (a standalone script);
  reader - a thread waits on sys.stdin, as watch_stdin did;
  fixed  - a thread waits on local_service.shutdown_stream(), the fix.
Without the MetaTrader5 package a started worker stops at phase 'import'; 'startup' means it never answered.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def child(mode):
    from src.broker import mt5_process
    from src.runtime.local_service import shutdown_stream
    if mode != 'none':
        stream = shutdown_stream() if mode == 'fixed' else sys.stdin
        threading.Thread(target=stream.readline, daemon=True).start()
        time.sleep(.5)
    mt5_process._STARTUP_SECONDS = 10.0
    process = mt5_process.MT5Process()
    started = time.monotonic()
    process.connect()
    diagnostics = process.diagnostics
    print(json.dumps({'mode': mode, 'phase': diagnostics['phase'], 'error_type': diagnostics['error_type'],
                      'startup_ms': (diagnostics['worker'] or {}).get('startup_ms'),
                      'seconds': round(time.monotonic() - started, 2)}), flush=True)
    process.close()


def run(mode):
    proc = subprocess.Popen([sys.executable, __file__, mode], cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline()  # stdin stays open until the child has answered
    proc.stdin.close()
    proc.wait(30)
    return json.loads(line)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(sys.argv[1])
    else:
        results = [run(mode) for mode in ('none', 'reader', 'fixed')]
        for result in results:
            print(json.dumps(result))
        sys.exit(0 if results[2]['phase'] != 'startup' else 1)
