"""Windows check of MT5 through the real application service (not a standalone script).

Starts the FastAPI service exactly as the launcher does (``python -m src.runtime.local_service``, or the
frozen sidecar with --binary) on a temporary data directory, opens a local session, asks it to connect
to the running MetaTrader 5 terminal and prints a report without credentials, account numbers or
balances. Read-only: no order, position or terminal setting is touched.

    .\\.venv\\Scripts\\python.exe -m scripts.check_mt5_api
    .\\.venv\\Scripts\\python.exe -m scripts.check_mt5_api --binary dist\\backend\\aitradingbot-service-x86_64-pc-windows-msvc.exe

It prints one PASS/FAIL line per step: SDK, terminal, worker, connection, account, quote, bars,
timestamps (measured gap vs UTC, never corrected), orderly shutdown. Exit code 0 only if the service
reports a verified connection.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import http.cookiejar
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.broker.mt5_process import _private_path  # noqa: E402
SAFE_ACCOUNT_FIELDS = ('currency', 'server', 'source', 'updated_at')


_PHASES = ('platform', 'import', 'terminal_not_running', 'initialize', 'terminal_info', 'account', 'connected')


def steps(report):
    """(step, ok, detail) for each read-only check, derived only from the service's own answers."""
    diagnostics = report.get('diagnostics') or {}
    phase = diagnostics.get('phase')
    reached = _PHASES.index(phase) if phase in _PHASES else -1
    connected = (report.get('connection') or {}).get('status') == 'connected'
    market = report.get('market') or {}
    age, bar_age = market.get('quote_age_s'), market.get('last_bar_age_s')
    reason = (report.get('connection') or {}).get('reason') or diagnostics.get('reason')
    skipped = None if market else 'not read: no verified connection'
    return [
        ('1 SDK MetaTrader5', connected or reached > 1, f'phase {phase}' if not connected else 'imported'),
        ('2 terminal MT5', connected or reached > 2, 'running' if connected or reached > 2 else 'not running or not found'),
        ('3 worker', bool((diagnostics.get('worker') or {}).get('pid')), 'started' if (diagnostics.get('worker') or {}).get('pid') else 'not started'),
        ('4 connection', connected, 'read-only, verified' if connected else reason),
        ('5 account', connected and {'currency', 'server'} <= set(report.get('account_fields_present') or ()), 'currency/server present (values not printed beyond server name)'),
        ('6 quote', market.get('quote_timestamp') is not None, skipped or (market.get('reason') if market.get('quote_timestamp') is None else f"digits {market.get('price_digits')}")),
        ('7 bars', bool(market.get('bars')), skipped or f"{market.get('bars', 0)} bars"),
        ('8 timestamps', age is not None and 0 <= age <= 120 and bar_age is not None and bar_age >= 0,
         skipped or f"quote age {age} s, last bar age {bar_age} s vs UTC (no offset applied); {market.get('reason') or ''}".strip('; ')),
        ('9 shutdown', report.get('service_exit_code') == 0, f"service exit {report.get('service_exit_code')}"),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--binary', type=Path, help='frozen sidecar instead of the source service')
    parser.add_argument('--symbol', default='EURUSD', help='symbol in Market Watch for the quote/bars read (default EURUSD)')
    parser.add_argument('--expect-phase', help='CI without a terminal: succeed if the worker started and stopped at this phase')
    args = parser.parse_args(argv)
    data = Path(tempfile.mkdtemp(prefix='aitb-mt5-check-'))
    ui = data / 'ui'
    ui.mkdir()
    (ui / 'index.html').write_text('<!doctype html><title>mt5 check</title>', encoding='utf-8')
    command = ([str(args.binary)] if args.binary else [sys.executable, '-m', 'src.runtime.local_service'])
    command += ['--port', '0', '--ui-dir', str(ui), '--data-dir', str(data / 'service')]
    env = {**__import__('os').environ, 'PYTHON_DOTENV_DISABLED': '1', 'AUTO_TRADE': 'false', 'PAPER_EXECUTION_SCOPE': 'disabled'}
    started = time.monotonic()
    service = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    report = {'service': 'frozen sidecar' if args.binary else 'source (python -m src.runtime.local_service)',
              'service_python': None if args.binary else _private_path(sys.executable)}
    try:
        ready = json.loads(service.stdout.readline())
        report['service_ready_s'] = round(time.monotonic() - started, 2)
        base = f"http://127.0.0.1:{ready['port']}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        headers = {'Origin': base, 'X-Local-Request': '1', 'Content-Type': 'application/json'}

        def call(path, method='GET'):
            request = urllib.request.Request(base + path, data=b'{}' if method == 'POST' else None, method=method, headers=headers)
            with opener.open(request, timeout=60) as response:
                return json.loads(response.read())

        call('/api/v1/session')
        connect_started = time.monotonic()
        state = call('/api/v1/connections/mt5', 'POST')
        report['connect_request_s'] = round(time.monotonic() - connect_started, 2)
        state = call('/api/v1/state?context=mt5')
        account = state.get('account') or {}
        report['connection'] = state['connection']
        report['account_fields_present'] = sorted(k for k, v in account.items() if v is not None)
        report['account'] = {k: account.get(k) for k in SAFE_ACCOUNT_FIELDS if k in account}
        report['positions_count'] = len(state.get('positions') or [])
        report['orders_count'] = len(state.get('orders') or [])
        report['automation'] = state['automation']['state']
        report['diagnostics'] = call('/api/v1/diagnostics/mt5')
        report['order_submission'] = call('/api/v1/system')['order_submission']
        if report['connection'].get('status') == 'connected':
            from urllib.parse import quote as escape
            market = call(f'/api/v1/market?context=mt5&interval=1Hour&symbol={escape(args.symbol)}')
            bars = market.get('bars') or []
            quote_time = (market.get('quote') or {}).get('timestamp')
            report['market'] = {'symbol': args.symbol, 'status': market.get('status'), 'reason': market.get('reason'),
                                'price_digits': (market.get('metadata') or {}).get('price_digits'),
                                'quote_timestamp': quote_time,
                                'quote_age_s': round(time.time() - datetime.fromisoformat(quote_time).timestamp(), 1) if quote_time else None,
                                'bars': len(bars),
                                'last_bar_age_s': round(time.time() - bars[-1]['time']) if bars else None}
    finally:
        try:
            service.stdin.write('shutdown\n')
            service.stdin.close()
            report['service_exit_code'] = service.wait(30)
        except Exception:
            service.kill()
            report['service_exit_code'] = 'killed after 30 s'
    report['local_utc_offset'] = time.strftime('%z')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    for name, ok, detail in steps(report):
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if args.expect_phase:
        diagnostics = report.get('diagnostics') or {}
        ok = diagnostics.get('phase') == args.expect_phase and (diagnostics.get('worker') or {}).get('pid')
        print('MT5 API CHECK:', f'PASS (worker started through the service, stopped at phase {args.expect_phase})' if ok
              else f'FAIL (expected phase {args.expect_phase} with a started worker)')
        return 0 if ok else 1
    connected = report.get('connection', {}).get('status') == 'connected'
    market = report.get('market') or {}
    if connected:
        print('MT5 MARKET READ:', 'OK' if market.get('status') == 'ready' else f"NOT READY ({market.get('reason')})")
    print('MT5 API CHECK:', 'PASS (verified read-only connection through the service)' if connected
          else 'NOT CONNECTED (see connection.reason and diagnostics.phase)')
    return 0 if connected else 1


if __name__ == '__main__':
    raise SystemExit(main())
