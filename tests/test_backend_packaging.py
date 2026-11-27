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


def test_installer_ships_third_party_notices_and_the_metaquotes_license(monkeypatch):
    import json
    root = Path(__file__).parents[1]
    resources = json.loads((root / 'src-tauri/tauri.conf.json').read_text())['bundle']['resources']
    assert resources.get('../THIRD_PARTY_NOTICES.md') == 'THIRD_PARTY_NOTICES.md'
    assert 'Copyright 2000-2025 MetaQuotes Ltd.' in (root / 'THIRD_PARTY_NOTICES.md').read_text()
    spec = importlib.util.spec_from_file_location('backend_build', root / 'scripts' / 'build_backend.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'native_target', lambda: 'x86_64-pc-windows-msvc')
    command = module.build_command(Path('/tmp/backend-output'))
    assert command[command.index('--copy-metadata') + 1] == 'MetaTrader5'
    monkeypatch.setattr(module, 'native_target', lambda: 'aarch64-apple-darwin')
    assert '--copy-metadata' not in module.build_command(Path('/tmp/backend-output'))
