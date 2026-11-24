"""Run by tests/test_qa_macos_audit.py in a child process: the suite's network guard forbids sockets in-process.

Starts the real sidecar entry point (uvicorn + shared worker thread pool) with a fake Paper client whose reads
hang, queues many Paper polls like a UI left open on Paper, then times a Demo request. Prints JSON.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import httpx

ROOT, HANG, QUEUED = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])

if len(sys.argv) > 4 and sys.argv[4] == 'serve':
    sys.path.insert(0, ROOT)
    from src.api import local_app

    class HangingPaper:
        def __init__(self, settings):
            pass
        def verify_connection(self):
            return {'connected': True}
        def get_paper_snapshot(self):
            time.sleep(HANG)
            return {'account': {'cash': '1'}, 'positions': [], 'orders': [], 'updated_at': 'now'}
    local_app.AlpacaClient = HangingPaper
    from src.runtime import local_service
    local_service.main(['--port', '0', '--ui-dir', sys.argv[6], '--data-dir', sys.argv[5]])
    raise SystemExit

env = {'PYTHON_DOTENV_DISABLED': '1', 'ALPACA_API_KEY': 'fake-key', 'ALPACA_SECRET_KEY': 'fake-secret', 'PATH': '',
       'SYSTEMROOT': os.environ.get('SYSTEMROOT', '')}  # Windows sockets need SYSTEMROOT
ui = Path(tempfile.mkdtemp())
(ui / 'index.html').write_text('<!doctype html><title>probe</title>', encoding='utf-8')  # no React build needed
server = subprocess.Popen([sys.executable, __file__, ROOT, str(HANG), str(QUEUED), 'serve', tempfile.mkdtemp(), str(ui)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=ROOT)
try:
    base = f"http://127.0.0.1:{json.loads(server.stdout.readline())['port']}"
    headers = {'Origin': base, 'X-Local-Request': '1'}
    client = httpx.Client(base_url=base, headers=headers, timeout=60)
    client.get('/api/v1/session')
    client.post('/api/v1/local-account', json={'context': 'demo', 'initial_cash': 1000})
    threading.Thread(target=lambda: client.post('/api/v1/connections/paper'), daemon=True).start()
    time.sleep(0.5)
    codes = []
    def poll():
        try:
            codes.append(httpx.get(base + '/api/v1/state?context=paper', headers=headers, cookies=client.cookies, timeout=60).status_code)
        except httpx.HTTPError as error:
            codes.append(type(error).__name__)
    pollers = [threading.Thread(target=poll, daemon=True) for _ in range(QUEUED)]
    for thread in pollers:
        thread.start()
    time.sleep(1.0)
    started = time.monotonic()
    demo = client.get('/api/v1/state?context=demo', timeout=30)
    elapsed = time.monotonic() - started
    for thread in pollers:
        thread.join(15)
    print(json.dumps({'demo_status': demo.status_code, 'demo_seconds': round(elapsed, 2),
                      'demo_cash': demo.json().get('account', {}).get('cash'), 'paper_codes': sorted(set(map(str, codes)))}))
finally:
    server.stdin.write(b'shutdown\n')
    server.stdin.close()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()
