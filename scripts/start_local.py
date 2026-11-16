"""Run/stop the local web service on an owned loopback socket, without .env reads."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser


def parse_identity(value, *, expected_pid=None):
    if not isinstance(value, dict):
        raise ValueError('Identità del servizio non valida.')
    pid, port, instance = value.get('pid'), value.get('port'), value.get('instance_id')
    if (type(pid) is not int or pid <= 0 or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(instance, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', instance)
            or (expected_pid is not None and pid != expected_pid)):
        raise ValueError('Identità del servizio non valida.')
    return {'pid': pid, 'port': port, 'instance_id': instance}


def wait_ready(stream, *, expected_pid, timeout=30):
    result = queue.Queue(maxsize=1)
    def read():
        try:
            result.put(stream.readline(4097))
        except (OSError, ValueError):
            result.put('')
    threading.Thread(target=read, daemon=True).start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty:
        raise RuntimeError('Timeout di avvio del servizio locale.') from None
    if not line or len(line) > 4096:
        raise RuntimeError('Il servizio non ha confermato un avvio valido.')
    try:
        return parse_identity(json.loads(line), expected_pid=expected_pid)
    except (ValueError, TypeError):
        raise ValueError('Conferma di avvio non valida; servizio arrestato.') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Redirect del servizio locale rifiutato.')


def _requester(info):
    origin = f"http://127.0.0.1:{info['port']}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())
    def request(url, method='GET'):
        req = urllib.request.Request(url, data=b'{}' if method == 'POST' else None,
            method=method, headers={'Origin': origin, 'X-Local-Request': '1',
                                    'Content-Type': 'application/json'})
        with opener.open(req, timeout=5) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise RuntimeError('Risposta locale troppo grande.')
        return json.loads(body)
    return request


def stop_instance(info, *, request=None):
    info = parse_identity(info)
    request = request or _requester(info)
    base = f"http://127.0.0.1:{info['port']}/api/v1"
    identity = request(base + '/identity')
    if not isinstance(identity, dict) or any(identity.get(k) != info[k] for k in ('pid', 'instance_id')):
        raise RuntimeError('Identità del processo cambiata: nessun arresto eseguito.')
    request(base + '/session')
    request(base + '/shutdown', method='POST')


def shutdown_child(child, *, timeout=10):
    if child.poll() is not None:
        return
    try:
        child.stdin.write('shutdown\n')
        child.stdin.flush()
    except (OSError, ValueError, AttributeError):
        pass  # The owned child may already be closing its input pipe.
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=timeout)


def default_data_dir():
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA')
        if not base:
            raise RuntimeError('LOCALAPPDATA assente: percorso dati sicuro non disponibile.')
        return Path(base) / 'AITradingBot' / 'local-service'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'AITradingBot' / 'local-service'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'AITradingBot' / 'local-service'


def _read_control(path):
    if path.is_symlink() or path.stat().st_size > 4096:
        raise RuntimeError('File di controllo locale non valido.')
    return parse_identity(json.loads(path.read_text(encoding='utf-8')))


def main(argv=None):
    parser = argparse.ArgumentParser(description='AITradingBot locale: nessun trading automatico.')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--ui-dir', type=Path)
    args = parser.parse_args(argv)
    child = None
    identity = None
    control = None
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError('Porta non valida.')
        data_dir = args.data_dir or default_data_dir()
        if not data_dir.is_absolute() or data_dir.is_symlink():
            raise ValueError('La directory dati deve essere assoluta e non un link.')
        control = data_dir / 'web-service.json'
        if args.stop:
            stop_instance(_read_control(control))
            print('Arresto richiesto al servizio locale verificato.')
            return 0
        root = Path(__file__).resolve().parents[1]
        ui_dir = (args.ui_dir or root / 'frontend' / 'dist').resolve()
        if not (ui_dir / 'index.html').is_file():
            raise RuntimeError('Frontend non compilato. Esegui npm ci e npm run build nella radice del progetto.')
        if control.exists() or control.is_symlink():
            raise RuntimeError('File di controllo già presente: verifica/arresta la precedente istanza; non viene sovrascritto.')
        data_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHON_DOTENV_DISABLED='1', AUTO_TRADE='false', PAPER_EXECUTION_SCOPE='disabled')
        child = subprocess.Popen([sys.executable, '-m', 'src.runtime.local_service',
            '--port', str(args.port), '--ui-dir', str(ui_dir), '--data-dir', str(data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, cwd=root, env=env)
        identity = wait_ready(child.stdout, expected_pid=child.pid)
        # O_EXCL refuses an instance that appeared while this child was starting.
        descriptor = os.open(control, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            json.dump(identity, file)
        url = f"http://127.0.0.1:{identity['port']}/"
        print(f'AITradingBot locale: {url}\nAutomazione arrestata. Ctrl+C per chiudere.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        child.wait()
        return child.returncode
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        print('Avvio/arresto non riuscito. Verifica build, directory e istanza locale; nessun ordine inviato.', file=sys.stderr)
        return 1
    finally:
        if child is not None:
            shutdown_child(child)
        if identity is not None and control is not None:
            try:
                if _read_control(control) == identity:
                    control.unlink()  # Only this launcher's generated control record.
            except (OSError, ValueError, RuntimeError):
                pass


def _interrupt(*_):
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _interrupt)
    raise SystemExit(main())
