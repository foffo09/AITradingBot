import subprocess
import sys
from pathlib import Path


def test_logging_import_does_not_create_directories():
    root = Path(__file__).parents[1]
    script = '''
from unittest.mock import patch
with patch('pathlib.Path.mkdir', side_effect=AssertionError('import writes directory')):
    import src.utils.logging_config
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_logger_creates_explicit_writable_directory(tmp_path, monkeypatch):
    from src.utils import logging_config
    import logging
    logger = logging.getLogger('aitradingbot')
    previous = logger.handlers[:]
    logger.handlers = []
    monkeypatch.setattr(logging_config, 'LOG_DIR', tmp_path / 'logs')
    try:
        logging_config.configure_logging().info('offline test')
        assert (tmp_path / 'logs/aitradingbot.log').read_text().endswith('offline test\n')
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = previous
