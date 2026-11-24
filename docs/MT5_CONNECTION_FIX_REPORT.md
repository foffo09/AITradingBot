# MT5 via servizio — report di correzione (24 novembre 2026)

Branch `agents/claude-macos-complete-fix-20261124`. Ambiente dell'agente: macOS (MT5 non disponibile),
più runner Windows di GitHub Actions **senza** terminale MT5. La connessione reale va verificata sul PC
Windows con la procedura in fondo: questo report non la dichiara verificata.

## Sintomo

Su Windows, con terminale MT5 aperto e conto Demo: `MetaTrader5.initialize()` diretto funziona, un test
multiprocessing spawn con un piccolo script funziona, ma `POST /api/v1/connections/mt5` restituisce
`unavailable` con *"Terminal worker failed or exceeded its deadline; reconnect explicitly."*

## Causa

Quel messaggio nasceva **solo** da `MT5Process._request`, quando il worker non rispondeva entro la deadline o
la pipe si interrompeva: non era mai un errore di MT5. Nel percorso API la prima richiesta `connect` aveva
5 s complessivi per:

1. avviare un nuovo interprete. Con un venv su Windows `multiprocessing` avvia apposta il Python *base*
   (`Python311\python.exe`) con `__PYVENV_LAUNCHER__` che punta al venv: è l'alternanza
   `.venv\Scripts\python.exe` → `Python311\python.exe` osservata, **normale** e non causa di per sé;
2. re-importare il `__main__` del padre come `__mp_main__`: nel servizio è `src.runtime.local_service`, che
   importava a livello di modulo FastAPI, `local_app`, pandas, alpaca-py e strategie; inoltre
   `src/broker/__init__.py` importava `AlpacaClient` (alpaca + pandas) a ogni import di `mt5_process`;
3. importare `MetaTrader5` ed eseguire `initialize(timeout=5000)`, `terminal_info()`, `account_info()`.

Il budget esterno (5 s) non superava neanche il timeout interno di `initialize` (5 s). Uno script autonomo ha un
`__main__` leggero e rientra nel budget; il servizio no.

Prove:
- **Riproduzione:** `test_slow_worker_startup_is_not_charged_to_the_mt5_deadline` simula un avvio lento del
  worker; sul codice precedente fallisce con *esattamente* il messaggio dell'utente, sul nuovo passa.
- **Misura Windows** (runner CI, run 45450273480, codice prima della correzione, senza MT5): risposta del worker
  in 0,8 s con `__main__` leggero e 1,2 s con quello del servizio, su una macchina pulita senza venv e con
  disco caldo. Sul PC dell'utente il tempo reale sarà visibile nella diagnostica (`worker.startup_ms`).
- Limite: non è dimostrato che sul PC dell'utente il totale superi sempre 5 s; è dimostrato che il disegno
  rendeva il fallimento dipendente dalla velocità della macchina.

Altra incoerenza segnalata, `worker.state = disconnected` con snapshot `connected`: lo stato si aggiornava solo
chiamando `snapshot()` di `MT5Process`, mai all'esito di `connect`.

## Correzione

| File | Modifica |
|---|---|
| `src/broker/mt5_process.py` | Macchina a stati `disconnected → starting → connecting → connected / unavailable`, un worker al massimo, tutto sotto lock. Il worker invia `ready` (pid, interprete, versione) appena parte; avvio con limite proprio (30 s), `connect` con budget `initialize + 5 s` (10 s), letture 5 s. Esito negativo → worker terminato e motivo preciso conservato. Uscita del worker riportata con exit code, timeout distinto da risposta non valida. Diagnostica (fase, tipo errore, codice MT5, worker, tempi, id richiesta) e log senza segreti. `close` silenzioso su worker già uscito. |
| `src/broker/mt5_readonly.py` | `connect` restituisce l'esito per fase: `import` (SDK assente nell'interprete del servizio), `terminal_not_running`, `initialize` (con `last_error()` di MT5), `terminal_info`, `account` (solo Demo). Non avvia mai il terminale. pandas/numpy importati solo dove servono. Snapshot con balance, equity, profit, margin, margin_free, margin_level, server, valuta (login escluso). |
| `src/broker/__init__.py` | `AlpacaClient` caricato in modo pigro (PEP 562). |
| `src/runtime/local_service.py` | `create_local_app` importato dentro `main()`. |
| `src/api/local_app.py`, `schemas.py` | `GET /api/v1/diagnostics/mt5` (sessione locale richiesta). |
| `frontend/src/App.tsx`, `api.ts`, `styles.css` | Pannello conto MT5 in Portafoglio (N/D; errore di lettura dichiarato, mai "conto vuoto"); diagnostica dopo "Verifica MetaTrader 5". |
| `scripts/check_mt5_api.py` | Verifica sul servizio reale (sorgente o sidecar) con report senza credenziali, numero di conto o saldi. |
| `.github/workflows/windows-ci.yml` | Sonda dei tempi di avvio e check API su Windows (fase `import`, worker avviato). |

Read-only invariato: `_OPERATIONS` = connect, snapshot, latest_quote, market_data, close; nessuna chiamata di
scrittura MT5 nel codice (test statico); `order_submission = disabled`; automazione `STOPPED`; tutti gli
endpoint di scrittura rifiutano i contesti `mt5` e `paper` (422).

Perché l'app non avvia più il terminale: `initialize()` lo lancerebbe come figlio del worker, quindi dentro il
Job Object dell'app desktop; alla chiusura dell'app Windows lo terminerebbe insieme al job.

## Test

| Test | Cosa dimostra |
|---|---|
| `test_mt5_process.py::test_slow_worker_startup_is_not_charged_to_the_mt5_deadline` | avvio lento non consuma il budget MT5 (RED sul codice precedente) |
| `…::test_connect_budget_covers_the_initialize_timeout_not_the_short_read_deadline` | budget connect > timeout di initialize |
| `…::test_state_and_diagnostics_follow_the_verified_connect_outcome` | stato coerente con l'esito; diagnostica senza saldi |
| `…::test_worker_crash_is_reported_with_its_exit_code` | crash del worker, exit code, riconnessione |
| `…::test_spawn_child_does_not_reimport_the_heavy_api_stack` | il figlio non carica fastapi/pandas/numpy/alpaca |
| `test_mt5_readonly.py::test_connect_reports_every_phase_with_a_precise_reason` | import, terminale assente, initialize con codice, terminal_info, conto reale, errore nativo, successo |
| `…::test_reader_and_worker_expose_no_write_operation` | nessuna API di scrittura MT5 nel codice |
| `test_local_modernization.py` (diagnostica, endpoint di scrittura, isolamento 4 contesti) | API protetta, nessun segreto, contesti separati |
| `App.test.tsx` (3 casi MT5) | N/D, errore ≠ conto vuoto, diagnostica |

Test esistenti: fake worker aggiornati al protocollo `ready`; nessuna asserzione indebolita.

## Procedura di verifica su Windows (PowerShell)

Prerequisiti: terminale MetaTrader 5 **aperto e collegato a un conto Demo**.

Usare una cartella separata, così il checkout personale e le sue modifiche restano intatti:

```powershell
git fetch origin
git worktree add ..\AITradingBot-mt5-check origin/agents/claude-macos-complete-fix-20261124
Set-Location ..\AITradingBot-mt5-check
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r packaging/backend/requirements.txt -r packaging/backend/requirements-mt5.txt
.\.venv\Scripts\python.exe -m scripts.check_mt5_api
```

Esito atteso: `MT5 API CHECK: PASS`, `connection.status = connected`, `diagnostics.phase = connected`.
Il report mostra `worker.startup_ms` (avvio dell'interprete) e `elapsed_ms` (durata di connect): sono le misure
reali che confermano o smentiscono la causa sul PC.

Se non è connesso, `diagnostics.phase` dice dove si ferma:
- `import`: MetaTrader5 non installato nell'ambiente del servizio (il comando sopra lo installa);
- `terminal_not_running`: aprire il terminale;
- `initialize`: vedere `mt5_error` (codice e descrizione MT5);
- `terminal_info`: il terminale non è collegato al server;
- `account`: il conto non è Demo (bloccato per scelta);
- `startup` con `error_type = timeout`: il worker non è partito in 30 s (riportare `worker` e il log).

Prova completa con l'interfaccia: `.\avvia_web.ps1 -Build`, poi Connessioni → **Verifica MetaTrader 5** (mostra
la diagnostica) e Contesto **MetaTrader 5** → Portafoglio.
