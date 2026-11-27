"""Native sidecar entry point: one owned loopback socket, no trading workers."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import threading

import uvicorn



def bind_loopback(port: int) -> socket.socket:
    if not 0 <= port <= 65535:
        raise ValueError('Invalid loopback port.')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Bind once and hand this same open socket to uvicorn; no free-port race.
        sock.bind(('127.0.0.1', port))
        sock.listen()
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock


def watch_stdin(server, stream):
    for line in stream:
        if line.strip() == 'shutdown':
            server.should_exit = True
            return
    # Parent closed its pipe: do not leave an orphaned service.
    server.should_exit = True


def quiet_connection_reset(loop, context):
    """A client dropping its socket (ConnectionResetError) is routine on Windows Proactor; anything else is logged."""
    if isinstance(context.get('exception'), ConnectionResetError):
        return
    loop.default_exception_handler(context)


async def serve(server, sock):
    asyncio.get_running_loop().set_exception_handler(quiet_connection_reset)
    await server.serve(sockets=[sock])


def shutdown_stream():
    """The parent's control pipe, kept off the standard input that child processes receive.

    Windows serializes synchronous I/O per file object: while ``watch_stdin`` waits in ReadFile on the pipe,
    a spawned child (the MT5 worker) that gets the same pipe as its stdin blocks in interpreter start-up until
    a line arrives, so the worker never answers. The pipe moves to a private, non-inheritable descriptor and
    descriptor 0 / STD_INPUT_HANDLE become NUL. Elsewhere stdin is returned unchanged.
    """
    if sys.platform != 'win32' or sys.stdin is None:
        return sys.stdin
    try:
        sys.stdin.fileno()
    except (OSError, ValueError):
        return sys.stdin
    import ctypes
    import msvcrt
    control = os.dup(0)  # non-inheritable (PEP 446)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    # A windowed (frozen) process does not update STD_INPUT_HANDLE in _dup2: set it explicitly.
    ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(0))
    sys.stdin = open(0, closefd=False, encoding='utf-8')
    return open(control, encoding='utf-8', errors='replace')


class LocalServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            app = self.config.app
            print(json.dumps({'port': sockets[0].getsockname()[1], 'pid': os.getpid(), 'supervisor_pid': os.getppid() if getattr(sys, 'frozen', False) or sys.platform == 'win32' else None, 'instance_id': app.state.instance_id}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='AITradingBot local read-only desktop backend')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--ui-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    sock = bind_loopback(args.port)
    app = None
    try:
        from src.utils import logging_config
        logging_config.LOG_DIR = args.data_dir / 'logs'
        # Imported here, not at module level: the MT5 spawn worker re-imports this module as __mp_main__
        # and must not pay for FastAPI, pandas and broker SDKs before answering (MT5 fix report).
        from src.api.local_app import create_local_app
        app = create_local_app(data_dir=args.data_dir, port=sock.getsockname()[1], ui_dir=args.ui_dir)
        # 'error': uvicorn's protocol warnings (e.g. a request cut off while the socket closes on shutdown) are not
        # actionable for users and made the Windows launcher job fail on benign stderr; real errors stay logged.
        config = uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], access_log=False, log_level='error', proxy_headers=False, server_header=False, ws='none')
        server = LocalServer(config)
        app.state.request_shutdown = lambda: setattr(server, 'should_exit', True)
        threading.Thread(target=watch_stdin, args=(server, shutdown_stream()), daemon=True).start()
        asyncio.run(serve(server, sock))
    finally:
        if app is not None:
            app.state.close()
        sock.close()


if __name__ == '__main__':
    main()
