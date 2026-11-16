"""Fault-test a generated desktop bundle, never an installed or personal app."""
from pathlib import Path
import os
import subprocess
import tempfile
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    # Native macOS bundle check; Windows compilation and GUI tests are separate.
    bundle = root / 'src-tauri/target/release/bundle/macos/AITradingBot.app/Contents/MacOS'
    desktop, sidecar = bundle / 'aitradingbot-desktop', bundle / 'aitradingbot-service'
    assert desktop.is_file() and sidecar.is_file(), 'Build the native macOS .app first.'
    assert not desktop.is_symlink() and not sidecar.is_symlink()
    assert sidecar.resolve().is_relative_to(root / 'src-tauri/target')
    held = bundle / ('aitradingbot-service.fixture-' + uuid.uuid4().hex)
    assert not held.exists()
    with tempfile.TemporaryDirectory(prefix='aitrading-startup-failure-') as folder:
        env = {key: value for key, value in os.environ.items()
               if not any(word in key.upper() for word in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'ALPACA', 'MT5'))}
        env.update(HOME=folder, PYTHON_DOTENV_DISABLED='1', AUTO_TRADE='false', PAPER_EXECUTION_SCOPE='disabled')
        sidecar.rename(held)
        try:
            result = subprocess.run([str(desktop)], env=env, capture_output=True, text=True, timeout=20)
            assert result.returncode == 1, f'Expected controlled failure, received exit {result.returncode}.'
            assert 'panicked' not in result.stderr
            assert 'Impossibile avviare AITradingBot' in result.stderr
            print('DESKTOP FAULT PASS: missing sidecar, controlled exit1, no panic; generated bundle restored.')
        finally:
            held.rename(sidecar)


if __name__ == '__main__':
    main()
