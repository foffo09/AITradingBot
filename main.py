from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import portalocker
import uvicorn

from core.runtime import Runtime
from config.providers import ProviderSettings
from ui.control_box import create_app


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()}, ensure_ascii=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Omega synthetic paper research console")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--tui", action="store_true", help="Enable Rich terminal controls alongside web UI")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for name in ("httpx", "httpx2", "httpcore", "httpcore2", "ib_insync"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root = Path(__file__).resolve().parent
    process_lock = (root / "config" / ".omega.lock").open("a+b")
    try:
        portalocker.lock(process_lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.AlreadyLocked:
        parser.exit(1, "Omega is already running for this state file.\n")
    settings = ProviderSettings.from_env(root / ".env")
    if settings.omega_data_mode == "live":
        from core.live_runtime import LiveRuntime
        runtime = LiveRuntime(root / "config" / "paper_live_state.json", settings)
    else:
        runtime = Runtime(root / "config" / "live_state.json")
    uvicorn.run(create_app(runtime, args.tui), host="127.0.0.1", port=args.port, loop="auto", access_log=False)
