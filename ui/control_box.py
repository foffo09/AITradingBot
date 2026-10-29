from __future__ import annotations

import asyncio
import hmac
import secrets
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict
from rich.table import Table
from rich.live import Live
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core.runtime import Runtime
from core.state import Controls


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "pause", "panic"]


async def terminal(runtime: Runtime) -> None:
    """Interactive terminal commands and web buttons share one runtime."""
    from rich.console import Console
    console = Console()
    console.print(f"[bold cyan]OMEGA — {runtime.state.source}[/] | 1–5 market | m split | s start | p pause | ! panic | q exit TUI")
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin,
    )
    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                snapshot = await runtime.snapshot()
                table = Table(title=f"{snapshot['source']} | equity {snapshot['equity']:.2f} | running {snapshot['running']}")
                table.add_column("Market")
                table.add_column("Sharpe holdout")
                table.add_column("Gate")
                for market, report in snapshot["reports"].items():
                    table.add_row(market, str(report["sharpe"]), "DEMO OK" if report["approved"] else "REJECTED")
                live.update(table)
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.5)
                except TimeoutError:
                    continue
                if not line:
                    return
                command = line.decode("utf-8").strip().lower()
                try:
                    if command == "q":
                        return
                    if command in "12345" and len(command) == 1:
                        controls = runtime.state.controls.model_copy()
                        controls.market = list(runtime.router.adapters)[int(command) - 1]
                        controls.multi_split_kelly = False
                        await runtime.configure(controls)
                    elif command == "m":
                        controls = runtime.state.controls.model_copy()
                        controls.multi_split_kelly = not controls.multi_split_kelly
                        await runtime.configure(controls)
                    elif command in {"s", "p", "!"}:
                        await runtime.command({"s": "start", "p": "pause", "!": "panic"}[command])
                    else:
                        console.print("Comando sconosciuto: usa 1–5, m, s, p, ! oppure q.", style="yellow")
                except ValueError as exc:
                    console.print(str(exc), style="red")
    finally:
        transport.close()


def create_app(runtime: Runtime, tui: bool = False) -> FastAPI:
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.initialize()
        worker = asyncio.create_task(runtime.run())
        terminal_task = asyncio.create_task(terminal(runtime)) if tui else None
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            if terminal_task is not None:
                terminal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await terminal_task
            if hasattr(runtime, "close"):
                await runtime.close()
            await runtime.command("pause")

    app = FastAPI(title="Omega — Paper Control", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(
            request.headers.get("x-control-token", ""), token
        ):
            from starlette.responses import JSONResponse
            return JSONResponse({"detail": "Control token required"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index():
        page = Path(__file__).with_name("control_box.html").read_text(encoding="utf-8")
        return page.replace("__CONTROL_TOKEN__", token)

    @app.get("/api/state")
    async def state():
        return await runtime.snapshot()

    @app.post("/api/controls")
    async def configure(controls: Controls):
        try:
            await runtime.configure(controls)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await runtime.snapshot()

    @app.post("/api/command")
    async def command(value: Command):
        try:
            await runtime.command(value.action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await runtime.snapshot()

    return app
