# Audit QA indipendente macOS — Claude, 24 novembre 2026

Revisore: Claude Code (audit indipendente, non implementazione).
Branch: `agents/claude-macos-audit-20261124` (worktree `AITradingBot-claude-macos-audit`),
creato da `origin/agents/master-consolidation-20261117`, senza upstream, nessun push/merge.
Main, PR7/PR8 e branch di Codex non toccati.

**Esito release macOS: NON APPROVATO per la distribuzione** — il codice a `8a4d740`
supera le verifiche funzionali e di ciclo di vita essenziali su arm64, ma mancano
artefatto Codex verificabile, firma/notarizzazione, licenza e verifica Intel.
Nessun problema CRITICAL o HIGH trovato.

## 1. Ambiente

| Voce | Valore |
|---|---|
| macOS | 27.2.1 (26B131) |
| Architettura | arm64, Apple M5 — **Intel/x86_64 NON verificato** |
| Python | 3.11.18 (uv, venv nel worktree); sistema solo 3.9.6 |
| Node / npm | 22.23.3 / 10.9.9 |
| Rust / Cargo | 1.100.0 stable (rustup, installato per l'audit) |
| Tauri CLI | 2.12.4 (npm) |
| Xcode | Command Line Tools |
| Disco libero | 292 GiB |

Python 3.11 e Rust non erano presenti: installati con autorizzazione dell'utente.

## 2. Fonti consultate e limiti

- Notion / Agent Operating Guide: **non accessibile** (nessun connettore Notion in questa sessione).
- `docs/DEVELOPER_ENVIRONMENT.md`, `AI_AGENTS_SETUP.md`, `BUILD_WINDOWS_MACOS.md`,
  `INSTALLATION_REPORT.md`: **non esistono su nessun branch** del repository.
  Usati invece AGENTS.md, WORKLOG, LOCAL_APPLICATION, MASTER_AUDIT, CODEX_MASTER_PROGRESS.
- Lavoro Codex individuato: `agents/codex-completion-20261116` (PR8) e
  `agents/master-consolidation-20261117` (ultimo, HEAD `8a4d740`, codice `e06d29f`).
- Artefatti Codex: **nessuno** (nessuna release, nessun artifact Actions). CI `44113161618`
  su `e06d29f`: windows-tests/macos-tests/local-app Windows SUCCESS, **local-app macOS
  CANCELLED in entrambi i tentativi** (runner non assegnato).

## 3. Commit e artefatti verificati

Commit verificato: `8a4d740e412ca04f6bf445706ff08b3224b20da0`.
Artefatti costruiti da me dal sorgente (non da Codex):

| Artefatto | SHA256 | Note |
|---|---|---|
| `dist/backend/aitradingbot-service-aarch64-apple-darwin` (40.2 MiB) | `7a91d154…48c05265` | PyInstaller 6.16 onefile |
| `AITradingBot.app/Contents/MacOS/aitradingbot-desktop` | `2ecbb4f7…7042f8b` | firma ad-hoc, non notarizzato |
| `AITradingBot.app` | 51.46 MiB | coerente con i 51.43 MiB dichiarati da Codex |

Contenuto bundle: `MacOS/{aitradingbot-desktop, aitradingbot-service}`, `Resources/{icon.icns, ui/}`.

## 4. Test eseguiti

Env QA: `TRADING_MODE=demo AUTO_TRADE=false PAPER_EXECUTION_SCOPE=disabled PYTHON_DOTENV_DISABLED=1`.

| Comando | Esito |
|---|---|
| `python -m compileall -q app.py config src tests` | PASS |
| `pytest -q -rs --cov=src` | **989 passed, 1 skipped** (Proactor Windows), guard rete/credenziali 0/0, coverage 88% |
| `pytest tests/test_qa_macos_audit.py` (nuovi) | 5 passed, 1 xfail strict (AUDIT-M1) |
| `pip check` / `uv pip check` | PASS |
| `pip-audit` (dev + backend) | 0 vulnerabilità |
| `ruff check .` | E9/F63/F7/F82 PASS; 2× F841 in `src/broker/alpaca_client.py`; nessuna config ruff nel progetto |
| `npm run lint` / `typecheck` / `test` / `build` | PASS / PASS / **51 passed** / PASS |
| `npm audit` | 0 vulnerabilità |
| `npm run test:e2e` | **NON ESEGUITO: script inesistente** |
| `cargo test --locked` | 3 passed (richiede il sidecar in `src-tauri/binaries/`) |
| `cargo check --locked` | PASS |
| `scripts.check_local_service` sorgente / binario frozen | PASS / PASS |
| `scripts/qa_sidecar_lifecycle.py` (nuovo) | 5/5 PASS (vedi §6) |

## 5. Test funzionali dell'app (.app, HOME temporanea, solo Demo)

Avvio diretto del binario con `env -i HOME=<tmp>`: dati in `<tmp>/Library/Application Support/
it.aitradingbot.desktop/local-service`. La directory dati personale esistente non è stata aperta.

| Verifica | Esito |
|---|---|
| Apertura app, 3 processi (shell, bootloader, worker), listener solo 127.0.0.1 | PASS |
| Avvio a freddo fino al listener | ~8 s (limite 15 s) |
| Panoramica, Mercati, Segnali, Portafoglio, Storico, Automazione, Connessioni | PASS, valori assenti = N/D |
| Conto Demo fittizio 10.000 USD creato | PASS |
| Automazione | STOPPED, nessun avvio |
| Paper/MT5 | non collegati, nessuna chiave presente |

### Timeout e recupero (test prioritario)

Riproduzione: con l'app aperta su Portafoglio, `kill -STOP <worker>` per 32 s, poi `kill -CONT`.

- Durante il blocco: tutte le card N/D, posizioni "Snapshot non disponibile", sidebar
  "Automazione N/D". **Nessun dato falso mostrato.** Messaggio: `Fetch is aborted` (AUDIT-L1).
- Dopo la ripresa, **stessa istanza**: Panoramica e Portafoglio di nuovo in Demo con 10.000 USD,
  "Automazione ferma". **PASS.**

### Chiusura e riavvio

| Scenario | Processi residui | Porta | Esito |
|---|---|---|---|
| Menu "Quit AITradingBot" (⌘Q) | 0 dopo ≤200 ms, exit 0 | 50584 chiusa | PASS |
| Riavvio stessa HOME | nuova porta 50726, conto Demo persistito, nessun conflitto | — | PASS |
| Chiusura finestra (pulsante rosso) | 0 dopo ≤600 ms | 50726 chiusa | PASS |
| `kill -9` della shell Tauri (crash) | sidecar uscito in ≤400 ms (EOF stdin) | 50748 chiusa | PASS |

⌘Q è stato attivato tramite la voce di menu che ⌘Q richiama, non con la scorciatoia fisica.

## 6. Ciclo di vita del sidecar (`scripts/qa_sidecar_lifecycle.py`)

Avvia il binario frozen come `service.rs` (stdin/stdout pipe, `--port 0`):
stdin `shutdown` 0.44 s · EOF 0.43 s · SIGTERM bootloader 0.33 s ·
SIGKILL bootloader dopo EOF 0.34 s · worker bloccato + SIGKILL bootloader: **orfano (ppid 1)
con porta aperta finché resta bloccato**, esce in 0.23 s appena riprende (AUDIT-L3).

## 7. SQLite (database temporanei)

| Scenario | Esito |
|---|---|
| Nuovo / vuoto (nessun conto) | `account: null`, N/D — PASS |
| Con dati, riavvio | persistito — PASS |
| Corrotto | 503 senza dati, altri contesti OK, recupero senza riavvio — PASS |
| Directory sola lettura | 503, nessun conto inferito — PASS |
| Transazione interrotta (trigger ABORT) | rollback completo, 503 senza `rejected`, retry stessa chiave = 1 sola operazione — PASS |
| Bloccato (`BEGIN EXCLUSIVE` esterno) | 503 dopo **15.6 s**, recupero dopo sblocco — vedi AUDIT-L2 |
| Concorrenza scritture | `BEGIN IMMEDIATE` + lock globale; nessuna doppia scrittura osservata |
| Backup | non previsto dall'app (procedura manuale documentata) — non testato |

## 8. Sicurezza e modalità

- Middleware: Host/Origin, cookie HttpOnly SameSite=Strict, `X-Local-Request`, CSP, `no-store`: test esistenti + verifica codice.
- Nessuna route ordine nel servizio desktop; trasporto Alpaca `read_only=True`, solo host atteso,
  niente redirect, timeout (3.05, 10) s. Retry SDK 2 solo in lettura (429/504); submit rifiuta se `_retry != 0`.
- Idempotenza `local-trades`: risposta persa → retry con stessa chiave = duplicato riconosciuto;
  payload diverso → 409 **senza** `X-Request-Outcome: rejected` (resta incerto). Errore DB → 503, mai conferma.
- Errori: nessun traceback/input/segreto nelle risposte (test esistenti + nuovi).
- Modalità: Demo/Simulazione file SQLite distinti, capitale e posizioni separati, automazione per contesto,
  Paper `account: null` senza connessione, automazione Paper rifiutata (422). PASS.
- Paper autentico, MT5 (non supportato su macOS) e riconciliazione reale: **non testati** (nessuna credenziale, per mandato).

## 9. Problemi

Nessun CRITICAL, nessun HIGH.

### AUDIT-M1 — MEDIUM — una lettura Paper lenta blocca Demo e Simulazione
- File: `src/api/local_app.py` — un solo `threading.RLock()` (`lock`) avvolge `state()`, `market`, `proposal`,
  `connect_paper`, incluse le chiamate di rete Alpaca (fino a 3.05+10 s per richiesta, più retry 429/504).
- Effetto: con Paper lento, ogni richiesta Demo attende; oltre i 12 s del client (`frontend/src/api.ts`)
  tutte le sezioni vanno in errore anche se Demo è locale. Probabile causa dei "timeout" storici.
- Riproduzione: `pytest tests/test_qa_macos_audit.py::test_slow_paper_read_does_not_block_demo --runxfail`
  → `Demo state waited 2.71s behind a Paper network read`.
- Correzione richiesta: non tenere il lock durante I/O broker (lock per contesto, o snapshot fuori lock),
  mantenendo la serializzazione del ledger per contesto. Rimuovere poi `xfail`.

### AUDIT-L1 — LOW — messaggio di timeout grezzo in WebKit
- `frontend/src/api.ts` `request()`: in WKWebView il timeout di `AbortSignal.timeout(12000)` arriva come
  `AbortError` e viene rilanciato; la UI mostra "Fetch is aborted" invece di "Servizio locale non raggiungibile".
- Correzione: rilanciare solo se `options.signal?.aborted`; altrimenti `ApiError` localizzato. Aggiungere test vitest con AbortError.

### AUDIT-L2 — LOW — busy timeout SQLite (15 s) maggiore del timeout UI (12 s)
- `src/simulation/ledger.py:86` `timeout=15`, sotto il lock globale: un DB bloccato blocca tutti i contesti ~15.6 s.
  Fail-closed corretto (503). Suggerito timeout < 12 s o risolto insieme a M1.

### AUDIT-L4 — LOW — form "Crea conto virtuale" mostrato quando lo stato non è disponibile
- `frontend/src/App.tsx` (`LocalLedger`, `!state?.account`): con backend irraggiungibile il conto esistente
  appare inesistente; resta visibile anche la nota "Conto virtuale disponibile…". Il server risponde 409, nessun danno.
- Correzione: distinguere "stato non disponibile" da "conto assente".

### AUDIT-L3 — LOW — worker orfano se bloccato quando Tauri forza la chiusura
- `src-tauri/src/service.rs` `shutdown()`/`start()`: `child.kill()` colpisce solo il bootloader PyInstaller.
  Limite limitato nel tempo (il worker esce appena si sblocca). Possibile mitigazione: process group e kill del gruppo.

### AUDIT-L5 — LOW — percorsi della macchina di sviluppo nel binario release
- `aitradingbot-desktop` contiene 343 stringhe con la home dello sviluppatore (percorsi registry Cargo nei panic).
  Nessun percorso del worktree. Mitigazione: `--remap-path-prefix` / `trim-paths` in build release.

### AUDIT-L6 — LOW — qualità/processo
- 2× F841 (`src/broker/alpaca_client.py`), nessuna config ruff; `test:e2e` assente;
  documenti richiesti dal mandato inesistenti; CI local-app macOS mai completata su `e06d29f`.

## 10. Handoff per Codex Mac

Priorità: M1 → L1 → L4 → L2 → L3 → L5. Per ciascuno: test RED già presente o indicato sopra,
correzione minima, nessuna soglia finanziaria cambiata. Dopo M1 togliere `xfail` da
`tests/test_qa_macos_audit.py`. Ripetere `scripts/qa_sidecar_lifecycle.py <sidecar>` e il test
SIGSTOP/SIGCONT descritto in §5 sul bundle ricostruito. Non modificare questo file: rispondere nel WORKLOG.

## 11. Stato finale

| Area | Stato |
|---|---|
| App (arm64, build locale) | Funzionante, dati N/D corretti, recupero timeout OK |
| Installazione | Bundle `.app` locale avviato dalla cartella di build; **nessun artefatto Codex**; non firmato/notarizzato; installazione in /Applications non provata |
| Ciclo di vita | ⌘Q, chiusura finestra, crash shell: nessun orfano, porta liberata |
| Release | **NON APPROVATO** per distribuzione: artefatto Codex assente, Intel non verificato, firma/notarizzazione/licenza mancanti (gate già noti), M1 aperto |
