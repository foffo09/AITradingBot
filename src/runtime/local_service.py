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

from src.api.local_app import create_local_app


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
        app = create_local_app(data_dir=args.data_dir, port=sock.getsockname()[1], ui_dir=args.ui_dir)
        config = uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], access_log=False, log_level='warning', proxy_headers=False, server_header=False, ws='none')
        server = LocalServer(config)
        app.state.request_shutdown = lambda: setattr(server, 'should_exit', True)
        threading.Thread(target=watch_stdin, args=(server, sys.stdin), daemon=True).start()
        asyncio.run(server.serve(sockets=[sock]))
    finally:
        if app is not None:
            app.state.close()
        sock.close()


if __name__ == '__main__':
    main()
