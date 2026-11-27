# Compatibilità macOS / Windows

Riferimenti: [CROSS_PLATFORM_QA.md](CROSS_PLATFORM_QA.md) (cosa è stato eseguito dove),
[MT5_CONNECTION_FIX_REPORT.md](MT5_CONNECTION_FIX_REPORT.md), [ARCHITECTURE.md](ARCHITECTURE.md).

| Area | macOS | Windows | Note |
|---|---|---|---|
| Interprete del servizio | `.venv/bin/python` | `.venv\Scripts\python.exe` | Su Windows lo `spawn` di `multiprocessing` usa il Python *base* con `__PYVENV_LAUNCHER__` verso il venv: due processi Python nella catena sono normali. Il worker MT5 riporta il proprio interprete nella diagnostica. |
| Worker MT5 | non avviato (`unsupported`, nessuna simulazione) | spawn, avvio con limite proprio | Il figlio re-importa il `__main__` del padre: tenerlo leggero (import pesanti dentro `main()`). |
| SDK MetaTrader5 | mai installato | `packaging/backend/requirements-mt5.txt` (solo AMD64) | Va installato nello **stesso** ambiente del servizio; altrimenti fase `import`. |
| Terminale MT5 | — | deve essere già aperto | L'app non lo avvia (eviterebbe la sua chiusura insieme al job dell'app desktop). |
| Terminazione processi | process group + SIGKILL del gruppo | Job Object (sidecar creato sospeso, poi assegnato) + shell in job protettivo | Nessun kill per nome o porta. |
| Segnali | SIGTERM / EOF stdin | EOF stdin; niente SIGTERM | Lo shutdown passa sempre da stdin. |
| Directory dati | `~/Library/Application Support/...` | `%LOCALAPPDATA%\AITradingBot\...`, desktop `%APPDATA%\it.aitradingbot.desktop` | Percorsi assoluti, symlink/alias rifiutati. |
| File lock | `portalocker` (flock) | `portalocker` (LockFileEx) | Stesso codice. |
| Porte | loopback, porta 0 (scelta dal sistema) | uguale | Socket legato una sola volta e passato a uvicorn. |
| Launcher | `python -m scripts.start_local` | `avvia_web.ps1` / `arresta_web.ps1` | Stesso `start_local`. |
| Pacchetto | `.app` + DMG (arm64 locale, x86_64 in CI) | NSIS | Firma/notarizzazione assenti. |
| Log | `<data-dir>/logs`; stderr solo errori | uguale | Nessun segreto (test dedicati). |

Regole per non rompere una piattaforma correggendo l'altra:
- niente import pesanti a livello di modulo nei moduli che il worker MT5 importa (test
  `test_spawn_child_does_not_reimport_the_heavy_api_stack`);
- codice specifico di piattaforma solo dietro `cfg(windows)`/`cfg(unix)` o `sys.platform`, con test su entrambe
  in CI (`windows-latest`, `macos-latest`, `macos-15-intel`);
- MT5 reale si verifica solo su Windows con `scripts/check_mt5_api.py`; un mock non è una verifica.
