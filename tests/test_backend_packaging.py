import importlib.util
from pathlib import Path


def test_native_build_command_contains_sidecar_and_explicit_runtime():
    path = Path(__file__).parents[1] / 'scripts' / 'build_backend.py'
    spec = importlib.util.spec_from_file_location('backend_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = module.build_command(Path('/tmp/backend-output'))
    assert '--onefile' in command
    assert 'uvicorn.logging' in command
    assert any(item.startswith('aitradingbot-service-') for item in command)
    assert str(Path(__file__).parents[1] / 'packaging/backend/entrypoint.py') in command
