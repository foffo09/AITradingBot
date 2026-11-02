"""Session-wide protection against accidental external access during pytest."""
import os
from pathlib import Path
import re
import socket
import sys


class AuditGuard:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.credentials = {self.root / ".streamlit/secrets.toml", Path.home() / ".streamlit/secrets.toml"}
        self.attempts = {"network": 0, "credentials": 0}

    @staticmethod
    def _is_windows_proactor_self_pipe(event, args):
        if os.name != "nt" or event != "socket.connect" or len(args) < 2:
            return False
        address = args[1]
        if not isinstance(address, tuple) or not address or address[0] != "127.0.0.1":
            return False

        frame = sys._getframe()
        has_socketpair = False
        has_proactor_self_pipe = False
        while frame is not None:
            if frame.f_code is socket.socketpair.__code__:
                has_socketpair = True
            if (
                frame.f_code.co_name == "_make_self_pipe"
                and frame.f_globals.get("__name__") == "asyncio.proactor_events"
            ):
                has_proactor_self_pipe = True
            if has_socketpair and has_proactor_self_pipe:
                return True
            frame = frame.f_back
        return False

    def audit(self, event, args):
        network = event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}
        if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
            network = args[0].family in {socket.AF_INET, socket.AF_INET6}
        if self._is_windows_proactor_self_pipe(event, args):
            network = False
        if network:
            self.attempts["network"] += 1
            raise RuntimeError("Tests prohibit network access; use a mock")
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.path.abspath(os.fsdecode(args[0])))
            local_env = path.parent == self.root and (path.name == ".env" or path.name.startswith(".env."))
            if path in self.credentials or (local_env and path.name != ".env.example"):
                self.attempts["credentials"] += 1
                raise RuntimeError("Tests prohibit local credential files; use a temporary fixture")


guard = AuditGuard(Path(__file__).parent)
sys.addaudithook(guard.audit)


def pytest_sessionstart(session):
    for name in list(os.environ):
        if re.search(r"KEY|SECRET|TOKEN|PASSWORD|ACCOUNT|RPC_URL|WS_URL", name, re.I):
            os.environ.pop(name, None)
    os.environ.update(TRADING_MODE="demo", AUTO_TRADE="false", PYTHON_DOTENV_DISABLED="1")
    os.environ["PAPER_EXECUTION_SCOPE"] = "disabled"
    os.environ.pop("PAPER_COORDINATOR_DIRECTORY", None)


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("TEST ISOLATION: " + str(guard.attempts))
    if any(guard.attempts.values()):
        session.exitstatus = 1
