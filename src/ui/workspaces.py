"""UI workspace paths; no broker construction or database reads."""
from pathlib import Path

from src.simulation.ledger import resolve_simulation_database_path


WORKSPACES = {'Demo': 'demo', 'Simulazione': 'simulation', 'Alpaca Paper': 'paper'}


def workspace_database(root, scope, environ):
    if scope not in WORKSPACES.values():
        raise ValueError('Unknown workspace.')
    demo = environ.get('AI_TRADINGBOT_DEMO_DB_PATH')
    paper = environ.get('AI_TRADINGBOT_PAPER_DB_PATH')
    simulation = environ.get('AI_TRADINGBOT_SIMULATION_DB_PATH')
    local = environ.get('LOCALAPPDATA')
    if local:
        paper = paper or str(Path(local) / 'AITradingBot' / 'paper' / 'simulation.sqlite3')
    if not simulation:
        if demo:
            simulation = str(Path(demo).with_name('workspace-simulation.sqlite3'))
        elif local:
            simulation = str(Path(local) / 'AITradingBot' / 'simulation' / 'simulation.sqlite3')
    paths = {name: resolve_simulation_database_path(root, path)
             for name, path in [('demo', demo), ('simulation', simulation), ('paper', paper)] if path}
    for name, path in paths.items():
        for other_name, other in paths.items():
            if name < other_name and (path == other or (path.exists() and other.exists() and path.samefile(other))):
                if {name, other_name} == {'demo', 'paper'}:
                    raise RuntimeError('Paper and demo modes must use separate database files.')
                raise RuntimeError('Demo, Simulazione and Paper must use separate database files.')
    if scope not in paths:
        raise RuntimeError(f'{scope.capitalize()} mode requires an isolated database path. '
                           'Use the isolated launcher or configure its workspace database environment variable.')
    return paths[scope]
