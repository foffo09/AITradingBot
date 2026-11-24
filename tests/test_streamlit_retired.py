"""Issue #9 guard: the React/FastAPI/Tauri app is the only product; Streamlit must not come back."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFESTS = ['requirements.txt', 'requirements-dev.txt', 'requirements-omega.txt', 'packaging/backend/requirements.txt', 'package.json']
# Entry points and instructions a user or CI would follow. Historical audit/worklog docs are excluded on purpose.
OFFICIAL_SURFACES = ['README.md', 'AGENTS.md', 'docs/LOCAL_APPLICATION.md', 'docs/ARCHITECTURE.md', 'docs/DESKTOP_RELEASE_GUIDE.md']


def official_files():
    yield from (ROOT / name for name in OFFICIAL_SURFACES if (ROOT / name).exists())
    for pattern in ('*.ps1', '*.bat', '*.sh', '*.cmd', 'scripts/*', '.github/workflows/*'):
        yield from (path for path in ROOT.glob(pattern) if path.is_file())


def test_legacy_streamlit_entrypoints_are_gone():
    for name in ('app.py', 'avvia_demo.ps1', 'avvia_paper.ps1', 'avvia_bot.bat', 'src/ui'):
        assert not (ROOT / name).exists(), name


def test_no_runtime_manifest_requires_streamlit():
    for name in RUNTIME_MANIFESTS:
        text = (ROOT / name).read_text(encoding='utf-8').lower()
        assert not re.search(r'^\s*"?(streamlit|plotly|pillow)\b', text, re.MULTILINE), name


def test_no_official_command_launches_streamlit():
    pattern = re.compile(r'streamlit\s+run|-m\s+streamlit|avvia_demo\.ps1|avvia_paper\.ps1|avvia_bot\.bat|\bapp\.py\b', re.IGNORECASE)
    offenders = [str(path.relative_to(ROOT)) for path in official_files()
                 if path.name != 'test_streamlit_retired.py' and pattern.search(path.read_text(encoding='utf-8', errors='ignore'))]
    assert offenders == []


def test_new_runtime_imports_without_streamlit():
    code = ('import sys, src.api.local_app, src.runtime.local_service, scripts.start_local; '
            'bad = sorted(m for m in sys.modules if m.split(".")[0] in {"streamlit", "plotly", "PIL"}); '
            'print(bad); sys.exit(1 if bad else 0)')
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
                            env={'PYTHON_DOTENV_DISABLED': '1', 'PATH': '', 'SYSTEMROOT': __import__('os').environ.get('SYSTEMROOT', '')})
    assert result.returncode == 0, result.stdout + result.stderr
