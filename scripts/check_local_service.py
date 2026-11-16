"""Real HTTP smoke with disposable synthetic data; never connects to a broker."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from scripts.start_local import wait_ready, shutdown_child, _NoRedirect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    ui = root / 'frontend' / 'dist'
    assert (ui / 'index.html').is_file(), 'Build the React frontend first.'
    env = {key: value for key, value in os.environ.items()
           if not any(word in key.upper() for word in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'ALPACA', 'MT5'))}
    env.update(PYTHON_DOTENV_DISABLED='1', AUTO_TRADE='false', PAPER_EXECUTION_SCOPE='disabled')
    with tempfile.TemporaryDirectory(prefix='aitrading-smoke-') as folder:
        command = [str(args.binary.resolve())] if args.binary else [sys.executable, '-m', 'src.runtime.local_service']
        child = subprocess.Popen(command + ['--port', '0', '--ui-dir', str(ui), '--data-dir', folder],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        try:
            # The frozen onefile bootloader owns a Python subprocess; the pipe
            # remains the only control channel, never a PID supplied by HTTP.
            info = wait_ready(child.stdout, expected_pid=None)
            assert info['pid'] == child.pid or args.binary, 'Unexpected source runtime PID.'
            origin = f"http://127.0.0.1:{info['port']}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())
            def request(path, body=None, *, foreign=False):
                headers = {'Origin': 'http://untrusted.invalid' if foreign else origin,
                           'X-Local-Request': '1', 'Content-Type': 'application/json'}
                data = None if body is None else json.dumps(body).encode()
                with opener.open(urllib.request.Request(origin + '/api/v1/' + path,
                                  data=data, headers=headers), timeout=10) as response:
                    return json.load(response)
            def denied(path, body=None, *, foreign=False, status=403):
                try:
                    request(path, body, foreign=foreign)
                except urllib.error.HTTPError as error:
                    assert error.code == status, error.code
                else:
                    raise AssertionError('Untrusted request unexpectedly accepted.')
            assert request('health')['status'] == 'ready'
            denied('state?context=demo', status=401)
            request('session')
            denied('local-account', {'context': 'demo', 'initial_cash': 10000.0}, foreign=True)
            assert request('state?context=demo')['account'] is None
            demo = request('local-account', {'context': 'demo', 'initial_cash': 10000.0})
            assert demo['account']['cash'] == 10000
            traded = request('local-trades', {'context': 'demo', 'symbol': 'AAPL', 'side': 'buy', 'quantity': 1.0})
            assert len(traded['positions']) == 1
            assert request('state?context=simulation')['account'] is None
            assert request('state?context=paper')['account'] is None
            assert request('state?context=paper')['automation']['state'] == 'stopped'
            market = request('market?context=demo&symbol=AAPL&interval=1Day')
            assert len(market['bars']) == 200 and market['source'] == 'synthetic-demo'
            assert request('proposal?context=demo')['validation_state'] == 'NO_TRADE'
            result = request('backtest', {'context': 'demo', 'symbol': 'AAPL'})
            assert result['source'] == 'synthetic-demo' and len(result['equity']) == 200
            assert result['metrics']['total_transaction_costs'] >= 0
            request('shutdown', {})
            child.wait(timeout=15)
            assert child.returncode == 0, child.returncode
            print('HTTP SMOKE PASS: session, origin rejection, Demo fill, isolated accounts, synthetic market, NO_TRADE, backtest, shutdown.')
            print('No broker connection, credentials or authenticated order; disposable databases only.')
        finally:
            shutdown_child(child)


if __name__ == '__main__':
    main()
