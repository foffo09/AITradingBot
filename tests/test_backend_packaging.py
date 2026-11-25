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


def test_local_sidecar_excludes_unused_image_and_arrow_runtimes():
    path = Path(__file__).parents[1] / 'scripts' / 'build_backend.py'
    spec = importlib.util.spec_from_file_location('backend_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = module.build_command(Path('/tmp/backend-output'))
    excluded = {command[index + 1] for index, item in enumerate(command[:-1]) if item == '--exclude-module'}
    assert {'PIL', 'pyarrow'} <= excluded


def test_local_sidecar_excludes_build_only_runtime_hooks():
    path = Path(__file__).parents[1] / 'scripts' / 'build_backend.py'
    spec = importlib.util.spec_from_file_location('backend_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = module.build_command(Path('/tmp/backend-output'))
    excluded = {command[index + 1] for index, item in enumerate(command[:-1]) if item == '--exclude-module'}
    assert {'setuptools', 'pkg_resources'} <= excluded


def test_frozen_diagnostics_publish_module_names_only():
    from scripts.check_local_service import startup_failure
    diagnostic = startup_failure("secret-key-value\nModuleNotFoundError: No module named 'backports'\nprivate traceback")
    assert diagnostic == 'Frozen startup failed: missing module backports.'
    assert startup_failure('sensitive unknown error') == 'Frozen startup failed; detailed diagnostics withheld.'


def test_windows_build_refuses_to_ship_without_the_mt5_sdk(monkeypatch):
    path = Path(__file__).parents[1] / 'scripts' / 'build_backend.py'
    spec = importlib.util.spec_from_file_location('backend_build', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.importlib.util, 'find_spec', lambda name: None)
    monkeypatch.setattr(module, 'native_target', lambda: 'x86_64-pc-windows-msvc')
    assert module.mt5_sdk_missing()
    monkeypatch.setattr(module, 'native_target', lambda: 'aarch64-apple-darwin')
    assert not module.mt5_sdk_missing()
    monkeypatch.setattr(module, 'native_target', lambda: 'x86_64-pc-windows-msvc')
    monkeypatch.setattr(module.importlib.util, 'find_spec', lambda name: object())
    assert not module.mt5_sdk_missing()
