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

---

# Fase 2 — verifica correzioni, 24 novembre 2026

## Stato del coordinamento

- `git fetch` ripetuto due volte: **nessun nuovo commit Codex** dopo `8a4d740`, nessun branch
  Codex Mac o Windows nuovo, nessuna nuova PR. La CI più recente resta `44113161618` su `e06d29f`.
- Nessun canale diretto con Codex disponibile in questa sessione; Notion ancora non accessibile.
- Handoff tecnico dettagliato, con criteri di accettazione per ogni problema:
  `docs/HANDOFF_CODEX_MACOS_AUDIT.md`. Da inoltrare a Codex dall'utente.
- Claude non ha modificato codice applicativo (ruolo di verifica).

## Ripetizione delle verifiche sul commit `3c65242`

Il codice applicativo è identico a `8a4d740` (`git diff 8a4d740 3c65242 -- src frontend src-tauri` vuoto).

| Verifica | Prima (fase 1) | Ora (fase 2) |
|---|---|---|
| `pytest tests/test_qa_macos_audit.py` | 5 passed, 1 xfail | 5 passed, 1 xfail |
| M1 con `--runxfail` | FAIL, 2.71 s | **FAIL, 2.70 s** — non risolto |
| `pytest -q -rs --cov=src` | 989 passed, 1 skipped | 994 passed, 1 skipped, 1 xfail (include i 6 test audit), coverage 88% |
| compileall / pip check / pip-audit | PASS / PASS / 0 | PASS / PASS / 0 |
| `ruff --isolated --select F` | — | 12 rilievi (2 in `src`, 4 in `providers`, 6 nei test) |
| npm lint / typecheck / test / build / audit | PASS / PASS / 51 / PASS / 0 | invariato |
| cargo test / check | 3 passed / PASS | invariato |
| `qa_sidecar_lifecycle.py` | 5/5 PASS, limite L3 | 5/5 PASS, limite L3 ancora presente |
| App: sospensione 32 s + ripresa, stessa istanza | PASS | PASS; L1 e L4 riprodotti di nuovo |
| ⌘Q (voce di menu) | 0 processi in ≤200 ms, porta chiusa | 0 processi in ≤200 ms, porta 51321 chiusa |

Artefatti (build Claude, non Codex), invariati:
sidecar `7a91d15438c583d60b64f3a5d2ca918717a31f79ec55341450fbc2bd48c05265`,
desktop `2ecbb4f7ac77777141c781ee4eef5fffd109081c028bd5293c868bc007042f8b`.

## Firma, notarizzazione, architetture

- `codesign`: `Signature=adhoc`, `TeamIdentifier=not set`.
- `spctl -a -vv`: rifiutato ("code has no resources but signature indicates they must be present").
- `stapler validate`: nessun ticket. `security find-identity -p codesigning`: 0 identità.
- Architetture verificate: solo arm64. Intel/x86_64: **non verificato**.
- Per distribuire servono: identità Developer ID dell'utente, firma del bundle completo
  (`--deep`/hardened runtime con entitlements per il sidecar), notarizzazione e stapling,
  build e prova x86_64 (o universal) su macchina o CI Intel, licenza e notice.

## Problemi — stato aggiornato

| ID | Gravità | Stato |
|---|---|---|
| M1 lock globale | MEDIUM | **APERTO**, riprodotto |
| L1 messaggio WebKit | LOW | APERTO, riprodotto |
| L2 busy timeout SQLite | LOW | APERTO |
| L3 worker orfano se bloccato | LOW | APERTO, limitato nel tempo |
| L4 form conto durante blocco | LOW | APERTO, riprodotto |
| L5 percorsi home nel binario | LOW | APERTO |
| L6 qualità/CI | LOW | APERTO (12 rilievi F, CI Mac non completata, e2e assente) |

Nessun CRITICAL o HIGH.

## Esito fase 2

**NON APPROVATO.** M1 non è risolto e il suo test passa solo come `xfail`; non esiste
alcuna build Codex da verificare. Firma, notarizzazione e Intel restano gate di distribuzione
separati, tutti aperti. Prossimo passo: correzioni Codex secondo l'handoff, poi riverifica
completa di Claude sul nuovo SHA e sul nuovo artefatto.

---

# Fase 3 — correzione AUDIT-M1, 24 novembre 2026

## Chi ha corretto e perché

Codex Mac è stato avviato con `codex exec` in un worktree dedicato, ma non ha potuto lavorare:
la rete corrente intercetta il TLS verso `chatgpt.com` e `api.openai.com` (certificato emesso da un
firewall Fortinet), quindi Codex non raggiungeva il suo servizio. Nessuna modifica Codex.
Su decisione dell'utente **la correzione M1 è stata scritta da Claude**, sul branch separato
`agents/claude-macos-m1-fix-20261124`, commit `513a45f`. **Limite: correzione e verifica sono dello
stesso agente**; serve una revisione di un secondo agente (Codex o umano) prima del merge.

## Correzione

`src/api/local_app.py`: il `threading.RLock()` unico è sostituito da un `RLock` per contesto
(`demo`, `simulation`, `paper`, `mt5`) più un lock per le preferenze. Ogni route usa il lock del proprio
contesto; `paper` e `mt5` sono letti/scritti solo sotto il proprio lock. Le chiamate annidate
(`local_account`/`local_trade` → `state`, `automation` → `proposal`) restano nello stesso contesto (RLock).
I controller dry-run usano già file e mutex per contesto (`local-v1-<context>-control.sqlite3`).
Invariati: soglie, rischio, timeout broker, contratti API, messaggi, idempotenza, `BEGIN IMMEDIATE`.

## Test

| Verifica | Risultato |
|---|---|
| M1 senza `--runxfail` prima di togliere `xfail` | XPASS(strict) → `xfail` rimosso, asserzione invariata (< 1 s) |
| M1 parametrizzato Demo + Simulazione | PASS (prima: 2.70 s di attesa) |
| Nuovo: 12 thread stessa chiave idempotente, Demo + Simulazione | 1 sola fill per contesto, PASS |
| `tests/test_qa_macos_audit.py` | **8 passed** |
| API/ledger/executor/contratti | 113 passed |
| Suite completa con coverage | **997 passed, 1 skipped**, nessun xfail, coverage 88% (`local_app.py` 93%), guard 0/0 |
| compileall / diff --check / ruff F,E9 sui file toccati | PASS |
| Smoke HTTP binario frozen | PASS |
| `qa_sidecar_lifecycle.py` | 5/5 PASS (limite L3 invariato) |
| App: sospensione 32 s + ripresa, stessa istanza Demo | PASS |
| ⌘Q (voce di menu) | 0 processi in ≤200 ms, porta 52148 chiusa |

Artefatti ricostruiti da `513a45f` (build Claude, arm64, firma ad-hoc):
sidecar `3f62f5eff0df37f94c6b65cf491c4eb64f7538775dce45a14f5e04ed1cc88b43`,
desktop `2ecbb4f7ac77777141c781ee4eef5fffd109081c028bd5293c868bc007042f8b` (invariato: nessuna modifica Rust),
`.app` 51.46 MiB.

Non testato: Paper autentico (nessuna credenziale, per mandato). La lentezza Paper è simulata con un client finto.

## Stato problemi

| ID | Gravità | Stato |
|---|---|---|
| M1 | MEDIUM | **RISOLTO** in `513a45f` (da revisionare da secondo agente) |
| L1, L2, L3, L4, L5, L6 | LOW | APERTI, invariati |

## Esito fase 3

**APPROVATO CON RISERVE** per la build arm64 locale: M1 risolto e testato, ciclo di vita, timeout,
modalità e SQLite verificati, nessun CRITICAL/HIGH. Riserve: sei LOW aperti (L1 e L4 visibili all'utente
durante un blocco del backend), correzione M1 non revisionata da un secondo agente, build non prodotta da Codex.

**Distribuzione a utenti finali: NON APPROVATA** — gate separati ancora aperti: firma Developer ID,
notarizzazione e stapling, verifica Intel/x86_64, licenza/notice, CI macOS `local-app` completata.

---

# Fase 4 — correzione AUDIT-L1 e AUDIT-L4, 24 novembre 2026

Commit `fc4b2ea` sullo stesso branch `agents/claude-macos-m1-fix-20261124`, scritto da Claude
(Codex ancora irraggiungibile per il TLS intercettato). Stesso limite: serve revisione di un secondo agente.

- **L1** `frontend/src/api.ts`: si rilancia l'errore originale solo se `options.signal?.aborted`
  (annullamento del chiamante); `AbortError`/`TimeoutError` interni diventano
  "Il servizio locale non ha risposto entro 12 secondi. Nuovo tentativo al prossimo aggiornamento."
- **L4** `frontend/src/App.tsx` (`LocalLedger`): con `state === null` niente form "Crea conto virtuale",
  ma "Stato del conto non disponibile…"; la nota dell'ultima azione è nascosta finché lo stato manca.

| Verifica | Risultato |
|---|---|
| 4 nuovi test Vitest sul codice precedente | 3 falliti (comportamento), 1 passato (guardia annullamento) — RED atteso |
| `npm test` dopo la correzione | **55 passed** |
| lint / typecheck / build / diff --check | PASS |
| App ricostruita, worker sospeso 32 s | messaggio italiano mostrato, nessun form di creazione, nota nascosta — PASS |
| Ripresa nella stessa istanza | Demo 10.000 USD, automazione ferma — PASS |
| ⌘Q | 0 processi in ≤200 ms, porta 52322 chiusa — PASS |

Artefatti (arm64, ad-hoc): desktop `f2f04a7d34dfe6fadaff412a3343bbadf4b5fb823f49c248a8d98160fddc63a4`
(cambia perché include la nuova UI), sidecar invariato `3f62f5eff0df37f94c6b65cf491c4eb64f7538775dce45a14f5e04ed1cc88b43`.

| ID | Stato |
|---|---|
| M1 | RISOLTO (`513a45f`) |
| L1, L4 | **RISOLTI** (`fc4b2ea`) |
| L2, L3, L5, L6 | APERTI (LOW, non visibili in uso normale) |

**Esito invariato:** build arm64 locale APPROVATA CON RISERVE (quattro LOW aperti, correzioni
non revisionate da un secondo agente); distribuzione NON APPROVATA (firma, notarizzazione, Intel, licenza).
