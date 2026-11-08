from pathlib import Path

import pytest

from src.ui.workspaces import workspace_database


def test_workspace_databases_are_distinct_and_keep_configured_paths(tmp_path):
    env = {'AI_TRADINGBOT_DEMO_DB_PATH': str(tmp_path / 'demo.sqlite3'),
           'AI_TRADINGBOT_PAPER_DB_PATH': str(tmp_path / 'paper.sqlite3')}
    root = tmp_path / 'project'
    demo = workspace_database(root, 'demo', env)
    simulation = workspace_database(root, 'simulation', env)
    paper = workspace_database(root, 'paper', env)
    assert demo == Path(env['AI_TRADINGBOT_DEMO_DB_PATH'])
    assert paper == Path(env['AI_TRADINGBOT_PAPER_DB_PATH'])
    assert len({demo, simulation, paper}) == 3
    assert not any(p.exists() for p in (demo, simulation, paper))


@pytest.mark.parametrize('scope', ['demo', 'simulation', 'paper'])
def test_alias_between_any_workspaces_is_rejected_before_opening(tmp_path, scope):
    env = dict(AI_TRADINGBOT_DEMO_DB_PATH=str(tmp_path / 'same.sqlite3'),
               AI_TRADINGBOT_PAPER_DB_PATH=str(tmp_path / 'paper.sqlite3'),
               AI_TRADINGBOT_SIMULATION_DB_PATH=str(tmp_path / 'same.sqlite3'))
    with pytest.raises(RuntimeError, match='separate database'):
        workspace_database(tmp_path / 'project', scope, env)


def test_hard_link_alias_is_rejected(tmp_path):
    demo = tmp_path / 'demo.sqlite3'
    demo.write_bytes(b'synthetic sentinel, not a database')
    alias = tmp_path / 'alias.sqlite3'
    alias.hardlink_to(demo)
    env = dict(AI_TRADINGBOT_DEMO_DB_PATH=str(demo), AI_TRADINGBOT_SIMULATION_DB_PATH=str(alias))
    with pytest.raises(RuntimeError, match='separate database'):
        workspace_database(tmp_path / 'project', 'simulation', env)
    assert demo.read_bytes() == b'synthetic sentinel, not a database'


def test_simulation_accepts_explicit_unicode_absolute_path(tmp_path):
    path = tmp_path / 'Simulazione è' / 'ledger.sqlite3'
    assert workspace_database(tmp_path / 'project', 'simulation',
                              {'AI_TRADINGBOT_SIMULATION_DB_PATH': str(path)}) == path


def test_demo_without_isolated_path_preserves_existing_fail_closed_guard(tmp_path):
    with pytest.raises(RuntimeError, match='requires an isolated database path'):
        workspace_database(tmp_path / 'project', 'demo', {})


def test_personal_database_is_never_a_workspace(tmp_path):
    with pytest.raises(ValueError):
        workspace_database(tmp_path / 'project', 'simulation', {
            'AI_TRADINGBOT_SIMULATION_DB_PATH': str(tmp_path / 'project' / 'data' / 'simulation.sqlite3')})
