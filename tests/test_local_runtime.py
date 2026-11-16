import io
from unittest.mock import Mock


def test_bound_socket_is_held_until_server_uses_it(monkeypatch, tmp_path):
    from src.runtime import local_service
    sock = Mock()
    sock.getsockname.return_value = ('127.0.0.1', 32123)
    factory = Mock(return_value=sock)
    monkeypatch.setattr(local_service.socket, 'socket', factory)
    result = local_service.bind_loopback(0)
    assert result is sock
    sock.bind.assert_called_once_with(('127.0.0.1', 0))
    sock.listen.assert_called_once()
    sock.close.assert_not_called()


def test_stdin_only_shutdown_stops_own_server():
    from src.runtime.local_service import watch_stdin
    server = Mock(should_exit=False)
    watch_stdin(server, io.StringIO('unrelated\nshutdown\n'))
    assert server.should_exit is True


def test_stdin_eof_requests_exit():
    from src.runtime.local_service import watch_stdin
    server = Mock(should_exit=False)
    watch_stdin(server, io.StringIO(''))
    assert server.should_exit is True
