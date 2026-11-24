"""Diagnostic (not a pytest test): time from MT5Process.connect() to the worker's first answer.

PROBE_HEAVY=1 gives the spawn child the same heavy __main__ imports as the real API process
(src.runtime.local_service); PROBE_HEAVY=0 uses a light __main__, like a standalone script.
Without the MetaTrader5 package the reader fails fast, so the time measures worker bootstrap only.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if os.environ.get('PROBE_HEAVY') == '1':
    import src.runtime.local_service  # noqa: F401  re-imported by every spawn child as __mp_main__

if __name__ == '__main__':
    from src.broker import mt5_process
    mt5_process._SUPPORTED = True  # the probe only needs a worker; non-Windows readers answer at once
    timings = []
    for _ in range(3):
        process = mt5_process.MT5Process(timeout=60)
        started = time.monotonic()
        process.connect()
        timings.append(round(time.monotonic() - started, 2))
        process.close()
    print(json.dumps({'heavy_main': os.environ.get('PROBE_HEAVY') == '1', 'platform': sys.platform,
                      'executable': sys.executable, 'seconds': timings}))
