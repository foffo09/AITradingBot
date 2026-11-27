# Emergency delivery — 24 novembre 2026

Branch: `agents/claude-emergency-delivery-20261124` (da `agents/claude-macos-complete-fix-20261124`).
Nessun merge su `main`, nessuna release. Trading reale disattivato; MT5 solo lettura; `order_submission = disabled`;
automazione `STOPPED`.

## Stato iniziale
- App React/TS + FastAPI + Tauri 2 già unica (Streamlit dismesso), test verdi su macOS e Windows.
- **Blocker:** su Windows `POST /api/v1/connections/mt5` falliva con *"Terminal worker failed or exceeded its
  deadline"* mentre la connessione Python diretta funzionava.
- Primo avvio Demo: tutte le metriche N/D senza indicazione di cosa fare.

## Problemi trovati, cause e correzioni

| # | Problema | Causa | Correzione | File |
|---|---|---|---|---|
| 1 | Worker MT5 mai avviato dal servizio su Windows | thread `watch_stdin` in `ReadFile` sincrono sulla pipe di stdin; il figlio spawn eredita la pipe come stdin e si blocca all'avvio (I/O serializzato per file object) | `shutdown_stream()`: pipe su descrittore privato non ereditabile, fd 0 / `STD_INPUT_HANDLE` = NUL | `src/runtime/local_service.py` |
| 2 | Crash del worker riportato come timeout su Windows | exit code letto prima della raccolta del processo | `join` breve prima di leggere l'exit code | `src/broker/mt5_process.py` |
| 3 | Due test MT5 fallivano su Windows reale | patch dell'SDK ma non del controllo `tasklist` | patch di `_terminal_running` nei test | `tests/test_local_service.py`, `tests/test_mt5_process.py` |
| 4 | Primo avvio Demo/Simulazione: solo N/D | nessun invito alla creazione del conto | avviso con pulsante "Crea conto virtuale →" in Panoramica | `frontend/src/App.tsx`, `styles.css` |
| 5 | Panoramica MT5 con metriche del ledger (sempre N/D) | metriche generiche anche per MT5 | pannello Conto MT5 (N/D, errore ≠ conto vuoto) in Panoramica | `frontend/src/App.tsx` |
| 6 | Selettore indicatori illeggibile | stile `label` in colonna applicato alle checkbox | checkbox in linea, a capo su schermi stretti | `frontend/src/styles.css` |

Già corretti nel branch di partenza (stessa giornata): deadline separate per avvio/connect/letture, macchina a stati
del worker, diagnostica `GET /api/v1/diagnostics/mt5`, import pigri nel figlio spawn, dashboard conto MT5,
`scripts/check_mt5_api.py` (dettagli in `MT5_CONNECTION_FIX_REPORT.md`).

## Prova della causa MT5 (runner Windows, senza terminale MT5)

| Prova | Prima | Dopo |
|---|---|---|
| Sonda A/B `tests/probes/stdin_spawn.py` | thread su stdin: **nessun avvio in 10 s** | `shutdown_stream`: avvio in 0,08 s |
| Servizio reale `scripts/check_mt5_api --expect-phase import` | FAIL, nessun `ready` in 30 s (run 45452590605) | PASS, worker avviato in 125 ms (run 45454479694) |

La connessione al terminale MT5 reale **non** è verificata: né macOS né i runner CI hanno MT5. Va eseguita sul PC
Windows (sotto).

## Stato delle funzionalità

| Funzionalità | Stato |
|---|---|
| Avvio servizio + UI, sessione locale, salute API | funziona (macOS provato nel browser; Windows in CI con app installata) |
| Demo / Simulazione: conto virtuale, ledger, registrazioni virtuali | funziona (provato end-to-end nel browser) |
| Market data Demo/Simulazione | funziona con dati **sintetici dichiarati** |
| Grafici (Lightweight Charts, candele, volume, indicatori) | funziona |
| Watchlist, storico, backtesting, walk-forward | funzionano (test frontend e API) |
| Proposte / gate di rischio | funziona in sola analisi; nessun ordine |
| Automazione | solo dry-run, ferma di default |
| Alpaca Paper | sola lettura; richiede credenziali dell'utente, non provato in questa sessione |
| MT5 read-only | percorso API corretto e provato fino al terminale; connessione reale da verificare su Windows |
| Notifiche | solo avvisi in pagina; nessun modulo di notifiche dedicato |
| Diagnostica (sistema, MT5) | funziona |

Isolamento: Demo, Simulazione, Alpaca Paper e MT5 hanno ledger e stato separati; i contesti broker non possono
raggiungere alcun endpoint di scrittura (test parametrizzati).

## Librerie e integrazioni
Nessuna dipendenza aggiunta: quelle utili (Lightweight Charts, Vitest, ESLint, Ruff, audit) erano già integrate.
Motivazioni e alternative scartate in `EXTERNAL_TOOLS_AND_LIBRARIES.md`. Notion non è connesso a questa sessione.

## Test eseguiti (macOS, 24/11/2026)
- pytest: 907 passati, 2 saltati (solo Windows)
- Vitest: 69 passati; `tsc --noEmit` ok; ESLint ok; `npm run build` ok
- Ruff ok; `pip check` ok; pip-audit 0 vulnerabilità; npm audit 0 vulnerabilità
- Rust (`cargo test`): 4 passati
- Prova manuale nel browser sul servizio reale: Demo (creazione conto, grafico), MT5 non collegato, layout 375 px
- Windows CI run 45455628867 (`windows-tests`): pytest 907 passati / 2 saltati, sonda A/B riprodotta (0,09 s / timeout 10 s / 0,08 s), `MT5 API CHECK: PASS`; job `macos-tests` verde

## Avvio

macOS / sviluppo:
```bash
npm ci && npm run build
python -m src.runtime.local_service --port 8765 --ui-dir frontend/dist --data-dir ./.local-data
```
Poi aprire `http://127.0.0.1:8765/`. App desktop: `npm run desktop` (sviluppo) o `npm run desktop:build`.

Windows (PowerShell): `.\avvia_web.ps1 -Build`.

## Verifica MT5 su Windows (terminale aperto, conto Demo)

```powershell
git fetch origin
git worktree add ..\AITradingBot-mt5-check origin/agents/claude-emergency-delivery-20261124
Set-Location ..\AITradingBot-mt5-check
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r packaging/backend/requirements.txt -r packaging/backend/requirements-mt5.txt
.\.venv\Scripts\python.exe -m scripts.check_mt5_api
```
Atteso: `MT5 API CHECK: PASS`. Altrimenti `diagnostics.phase` indica il punto esatto (guida nel report MT5).

## Ancora aperto
- Connessione MT5 reale da confermare sul PC Windows.
- Firma/notarizzazione macOS e firma Windows: servono certificati del proprietario.
- Licenza del progetto: decisione del proprietario.
- Notion e Codex non disponibili in questa sessione.
