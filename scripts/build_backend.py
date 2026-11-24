"""Build the local sidecar on this host; never cross-compiles or starts a server."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def native_target() -> str:
    machine = platform.machine().lower()
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}.get(machine)
    if arch is None:
        raise RuntimeError(f'Unsupported native architecture: {machine}')
    suffix = {'darwin': 'apple-darwin', 'win32': 'pc-windows-msvc', 'linux': 'unknown-linux-gnu'}.get(sys.platform)
    if suffix is None:
        raise RuntimeError(f'Unsupported native platform: {sys.platform}')
    return f'{arch}-{suffix}'


def build_command(output: Path) -> list[str]:
    return [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile',
            '--name', f'aitradingbot-service-{native_target()}',
            '--paths', str(ROOT), '--distpath', str(output),
            '--workpath', str(output / 'build'), '--specpath', str(output / 'spec'),
            '--hidden-import', 'uvicorn.logging', '--hidden-import', 'uvicorn.loops.auto',
            '--hidden-import', 'uvicorn.protocols.http.h11_impl', '--hidden-import', 'uvicorn.lifespan.on',
            '--hidden-import', 'src.strategy.service', '--hidden-import', 'MetaTrader5',
            '--collect-data', 'exchange_calendars', '--collect-data', 'pandas_market_calendars',
            '--exclude-module', 'streamlit', '--exclude-module', 'matplotlib',
            # Local JSON/OHLC routes do not use image codecs or Arrow serialization.
            '--exclude-module', 'PIL', '--exclude-module', 'pyarrow',
            '--exclude-module', 'setuptools', '--exclude-module', 'pkg_resources',
            '--exclude-module', 'torch', '--exclude-module', 'tensorflow',
            # Test framework reached only through pandas' optional test helpers; never used at runtime.
            '--exclude-module', 'pytest', '--exclude-module', '_pytest',
            str(ROOT / 'packaging/backend/entrypoint.py')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist' / 'backend')
    parser.add_argument('--print-command', action='store_true')
    args = parser.parse_args()
    command = build_command(args.output_dir.resolve())
    if args.print_command:
        import shlex
        print(shlex.join(command))
        return
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
