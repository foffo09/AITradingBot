import io
import json

import pytest


def test_readiness_requires_child_identity_and_valid_loopback_port():
    from scripts.start_local import parse_identity
    valid = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    assert parse_identity(valid, expected_pid=123) == valid
    for changed in ({'pid': 124}, {'port': True}, {'port': 0}, {'port': 65536},
                    {'instance_id': ''}, {'instance_id': '../private'}):
        with pytest.raises(ValueError):
            parse_identity(dict(valid, **changed), expected_pid=123)


def test_readiness_rejects_malformed_or_closed_stdout_without_echoing_payload():
    from scripts.start_local import wait_ready
    for content in ('', 'private-sentinel\n', 'null\n'):
        with pytest.raises((RuntimeError, ValueError)) as caught:
            wait_ready(io.StringIO(content), expected_pid=123, timeout=1)
        assert 'private-sentinel' not in str(caught.value)


def test_ready_line_preserves_identity():
    from scripts.start_local import wait_ready
    data = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    assert wait_ready(io.StringIO(json.dumps(data) + '\n'), expected_pid=123, timeout=1) == data


def test_stop_never_posts_to_a_reused_or_wrong_process():
    from scripts.start_local import stop_instance
    requests = []
    info = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    def request(url, method='GET'):
        requests.append((url, method))
        return {'pid': 124, 'instance_id': 'b' * 32}
    with pytest.raises(RuntimeError, match='Identit'):
        stop_instance(info, request=request)
    assert len(requests) == 1
    assert requests[0][1] == 'GET'


def test_stop_uses_session_then_shutdown_only_after_identity_matches():
    from scripts.start_local import stop_instance
    calls = []
    info = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    def request(url, method='GET'):
        if len(calls) == 3:
            from urllib.error import URLError
            raise URLError(ConnectionRefusedError())
        calls.append((url, method))
        return info if url.endswith('/identity') else {}
    stop_instance(info, request=request)
    assert [url.rsplit('/', 1)[1] for url, _ in calls] == ['identity', 'session', 'shutdown']
    assert calls[-1][1] == 'POST'
    assert all(url.startswith('http://127.0.0.1:8765/api/v1/') for url, _ in calls)


def test_shutdown_terminates_only_the_owned_process_after_timeout():
    from scripts.start_local import shutdown_child
    events = []
    class Child:
        stdin = io.StringIO()
        def poll(self): return None
        def wait(self, timeout):
            import subprocess
            events.append(('wait', timeout))
            if len(events) == 1: raise subprocess.TimeoutExpired('owned', timeout)
            return 0
        def terminate(self): events.append(('terminate',))
        def kill(self): events.append(('kill',))
    child = Child()
    shutdown_child(child, timeout=1)
    assert child.stdin.getvalue() == 'shutdown\n'
    assert ('terminate',) in events
    assert ('kill',) not in events


def test_timeout_does_not_wait_forever_for_a_child_that_never_reports_ready():
    import threading
    from scripts.start_local import wait_ready
    released = threading.Event()
    class QuietStream:
        def readline(self, limit):
            released.wait(1)
            return ''
    try:
        with pytest.raises(RuntimeError, match='Timeout'):
            wait_ready(QuietStream(), expected_pid=123, timeout=0.01)
    finally:
        released.set()


def test_launcher_with_missing_frontend_does_not_start_process_or_create_data(tmp_path, monkeypatch):
    from scripts import start_local
    def forbidden(*args, **kwargs):
        pytest.fail('No child may start before the frontend build exists')
    monkeypatch.setattr(start_local.subprocess, 'Popen', forbidden)
    directory = tmp_path / 'new-data'
    assert start_local.main(['--no-browser', '--ui-dir', str(tmp_path / 'missing-ui'),
                             '--data-dir', str(directory)]) == 1
    assert not directory.exists()


def test_launcher_lock_excludes_second_owner_and_releases_after_exit(tmp_path):
    from scripts.start_local import launcher_lock
    with launcher_lock(tmp_path):
        with pytest.raises(RuntimeError, match='istanza'):
            with launcher_lock(tmp_path):
                pytest.fail('Second launcher acquired ownership')
    with launcher_lock(tmp_path):
        assert (tmp_path / 'web-launcher.lock').is_file()


def test_stale_recovery_requires_explicit_request_and_dead_pid(tmp_path, monkeypatch):
    from scripts import start_local
    control = tmp_path / 'web-service.json'
    data = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    control.write_text(json.dumps(data))
    monkeypatch.setattr(start_local, 'process_exists', lambda pid: False)
    def refused(*args, **kwargs):
        import urllib.error
        raise urllib.error.URLError(ConnectionRefusedError())
    with pytest.raises(RuntimeError):
        start_local.recover_control(control, requested=False, request=refused)
    assert control.exists()
    monkeypatch.setattr(start_local, 'process_exists', lambda pid: True)
    with pytest.raises(RuntimeError):
        start_local.recover_control(control, requested=True, request=refused)
    assert control.exists()
    monkeypatch.setattr(start_local, 'process_exists', lambda pid: False)
    start_local.recover_control(control, requested=True, request=refused)
    assert not control.exists()


@pytest.mark.parametrize('response', ['different', 'timeout', 'corrupt'])
def test_recovery_preserves_unverifiable_record(tmp_path, monkeypatch, response):
    from scripts import start_local
    control = tmp_path / 'web-service.json'
    control.write_text('broken' if response == 'corrupt' else json.dumps(
        {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}))
    monkeypatch.setattr(start_local, 'process_exists', lambda pid: False)
    def request(*args, **kwargs):
        if response == 'timeout':
            raise TimeoutError()
        return {'pid': 999, 'instance_id': 'b' * 32}
    with pytest.raises((RuntimeError, ValueError, TimeoutError)):
        start_local.recover_control(control, requested=True, request=request)
    assert control.exists()


def test_shutdown_waits_for_closed_listener_and_rejects_still_running():
    from scripts.start_local import stop_instance
    from urllib.error import URLError
    info = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    calls = []
    def request(url, method='GET'):
        calls.append((url, method))
        if len(calls) > 4:
            raise URLError(ConnectionRefusedError())
        return info
    stop_instance(info, request=request, timeout=1)
    assert len(calls) == 5
    with pytest.raises(RuntimeError, match='Timeout'):
        stop_instance(info, request=lambda *a, **k: info, timeout=0)


def test_process_exists_recognizes_our_current_process():
    import os
    from scripts.start_local import process_exists
    assert process_exists(os.getpid())


def test_recovery_preserves_control_when_launcher_lock_has_an_owner(tmp_path, monkeypatch):
    from scripts import start_local
    ui = tmp_path / 'ui'
    ui.mkdir()
    (ui / 'index.html').write_text('fixture')
    control = tmp_path / 'web-service.json'
    record = json.dumps({'pid': 123, 'port': 8765, 'instance_id': 'a' * 32})
    control.write_text(record)
    with start_local.launcher_lock(tmp_path):
        assert start_local.main(['--recover-stale', '--no-browser', '--data-dir', str(tmp_path),
                                 '--ui-dir', str(ui)]) == 1
        assert control.read_text() == record


def test_shutdown_keeps_polling_after_connection_reset_until_refused():
    from scripts.start_local import stop_instance
    from urllib.error import URLError
    from http.client import RemoteDisconnected
    info = {'pid': 123, 'port': 8765, 'instance_id': 'a' * 32}
    replies = iter([info, info, info, URLError(ConnectionResetError()), RemoteDisconnected(), URLError(ConnectionRefusedError())])
    def request(*args, **kwargs):
        value = next(replies)
        if isinstance(value, Exception): raise value
        return value
    stop_instance(info, request=request, timeout=2)
