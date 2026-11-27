"""Inventory of third-party components shipped in the desktop bundle, with declared licenses.

Python: distributions whose modules PyInstaller actually bundled (run after scripts/build_backend.py).
npm: production dependency tree. Rust: `cargo metadata` for the host target.
This is a metadata inventory, not legal clearance. Usage: python scripts/third_party_notices.py > THIRD_PARTY_NOTICES.md
"""
from __future__ import annotations

import ast
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def python_components():
    tocs = list((ROOT / 'dist' / 'backend' / 'build').glob('*/PYZ-00.toc')) + list((ROOT / 'dist' / 'backend' / 'build').glob('*/PKG-00.toc'))
    if not tocs:
        raise SystemExit('Build the sidecar first: python scripts/build_backend.py')
    modules = set()
    for toc in tocs:
        # A TOC file is one Python literal: a tuple holding the list of (name, path, kind) entries.
        for part in ast.literal_eval(toc.read_text(encoding='utf-8')):
            if isinstance(part, list):
                modules.update(str(entry[0]).split('.')[0].split('/')[0] for entry in part)
    owners = metadata.packages_distributions()
    names = {dist for module in modules for dist in owners.get(module, [])}
    rows = []
    for name in sorted(names, key=str.lower):
        meta = metadata.metadata(name)
        license_ = meta.get('License-Expression') or next(
            (c.split('::')[-1].strip() for c in meta.get_all('Classifier') or [] if c.startswith('License ::')), None
        ) or next(iter((meta.get('License') or '').splitlines()), '')[:80] or 'UNKNOWN'
        rows.append((meta['Name'], meta['Version'], license_))
    return rows


def npm_components():
    npm = shutil.which('npm')  # npm.cmd on Windows, which subprocess does not resolve by itself
    if npm is None:
        raise SystemExit('npm not found on PATH')
    tree = json.loads(subprocess.run([npm, 'ls', '--omit=dev', '--all', '--json'], cwd=ROOT,
                                     capture_output=True, text=True, check=True).stdout)
    found = {}
    def walk(deps):
        for name, info in (deps or {}).items():
            package = json.loads((ROOT / 'node_modules' / name / 'package.json').read_text(encoding='utf-8'))
            found[name] = (name, package['version'], package.get('license', 'UNKNOWN'))
            walk(info.get('dependencies'))
    walk(tree.get('dependencies'))
    return sorted(found.values())


def rust_components():
    data = json.loads(subprocess.run(['cargo', 'metadata', '--locked', '--format-version', '1',
                                      '--filter-platform', subprocess.run(['rustc', '-vV'], capture_output=True, text=True, check=True)
                                      .stdout.split('host: ')[1].split()[0], '--manifest-path', str(ROOT / 'src-tauri' / 'Cargo.toml')],
                                     capture_output=True, text=True, check=True).stdout)
    used = {node['id'] for node in data['resolve']['nodes']}
    return sorted((p['name'], p['version'], p.get('license') or 'UNKNOWN') for p in data['packages']
                  if p['id'] in used and p['source'] is not None)


MT5_LICENSE = 'Copyright 2000-2025 MetaQuotes Ltd.\r\n\r\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:\r\n\r\nThe above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.\r\n\r\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.'

WINDOWS_NOTE = ("Inventario della piattaforma di build. Il sidecar Windows x64 include anche `MetaTrader5` 5.0.6231 "
                "(MetaQuotes Ltd., modulo binario nativo `_core.cp311-win_amd64.pyd`). Licenza MIT: testo verificato il "
                "27/11/2026 nel wheel `metatrader5-5.0.6231-cp311-cp311-win_amd64.whl` (sha256 1e0fb5e4…918f918d), "
                "riportato sotto e copiato anche nel sidecar (`--copy-metadata`). Il proprietario ha deciso di includerlo "
                "nell'installer (25/11/2026); rigenerare questo file su Windows prima di pubblicare l'installer.\n\n"
                + '\n'.join('> ' + line if line else '>' for line in MT5_LICENSE.splitlines()))


def table(title, rows):
    lines = [f'## {title} ({len(rows)})', '', '| Componente | Versione | Licenza dichiarata |', '|---|---|---|']
    lines += [f'| {name} | {version} | {license_} |' for name, version, license_ in rows]
    return '\n'.join(lines) + '\n'


def main():
    rows = {'Interfaccia (npm, produzione)': npm_components(),
            'Servizio locale (Python, moduli inclusi dal sidecar)': python_components(),
            'Shell desktop (Rust, piattaforma host)': rust_components()}
    unknown = [name for group in rows.values() for name, _, license_ in group if license_ == 'UNKNOWN']
    print('# Componenti di terze parti\n')
    print('Inventario generato da `scripts/third_party_notices.py` dai metadati dei pacchetti. **Non è una verifica legale**: '
          'licenze, NOTICE e obblighi di redistribuzione vanno controllati prima della distribuzione. '
          f'Componenti con licenza non dichiarata nei metadati: {", ".join(unknown) or "nessuno"}.\n')
    print(WINDOWS_NOTE + '\n')
    print('\n'.join(table(title, group) for title, group in rows.items()), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
