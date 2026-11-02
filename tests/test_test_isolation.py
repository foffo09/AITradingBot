import asyncio
import socket
import sys
from types import SimpleNamespace

import pytest

from conftest import AuditGuard, guard


def test_audit_blocks_network_even_when_caller_catches_the_error(tmp_path):
    policy = AuditGuard(tmp_path)
    for event, args in [("socket.getaddrinfo", ("example.invalid",)),
                        ("socket.connect", (SimpleNamespace(family=socket.AF_INET), ("127.0.0.1", 1)))]:
        with pytest.raises(RuntimeError, match="network"):
            policy.audit(event, args)
    assert policy.attempts["network"] == 2
    policy.audit("socket.connect", (SimpleNamespace(family=getattr(socket, "AF_UNIX", -1)), "local-pipe"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Proactor uses an IPv4 loopback self-pipe")
def test_windows_proactor_self_pipe_is_not_counted_as_external_network():
    before = guard.attempts["network"]
    loop = asyncio.new_event_loop()
    try:
        assert loop.__class__.__name__ == "ProactorEventLoop"
    finally:
        loop.close()
    assert guard.attempts["network"] == before


def test_audit_blocks_project_credentials_but_allows_test_fixture_paths(tmp_path):
    policy = AuditGuard(tmp_path)
    for name in [".env", ".env.production", ".streamlit/secrets.toml"]:
        with pytest.raises(RuntimeError, match="credential"):
            policy.audit("open", (str(tmp_path / name), "r"))
    policy.audit("open", (str(tmp_path / ".env.example"), "r"))
    policy.audit("open", (str(tmp_path / "fixture" / ".env"), "r"))
    assert policy.attempts["credentials"] == 3
