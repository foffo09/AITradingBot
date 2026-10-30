"""Import and dependency regressions; actual Windows execution is separate."""
from pathlib import Path
import runpy
import sys

import pytest


def test_console_help_imports_without_opening_state_or_starting_server(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['main.py', '--help'])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'main.py'), run_name='__main__')
    assert caught.value.code == 0
    assert 'Omega synthetic paper research console' in capsys.readouterr().out
