# Handoff tecnico per Codex Mac — correzioni audit macOS

Da: Claude Code (verifica indipendente). Fonte: `docs/MACOS_QA_AUDIT.md` (branch
`agents/claude-macos-audit-20261124`, commit `3c65242`). Base del codice: `8a4d740`.
Stato al 24 novembre 2026: **nessuna correzione Codex presente su GitHub**.

Regole: lavora su un tuo branch (es. `agents/codex-macos-audit-fixes-2026112x`) partendo da
`origin/agents/claude-macos-audit-20261124` così hai i test di regressione. Non modificare
`tests/test_qa_macos_audit.py` tranne per togliere `xfail` da M1 **dopo** che passa davvero.
Nessuna soglia finanziaria, regola di rischio o timeout broker va cambiata.
Env per i test: `TRADING_MODE=demo AUTO_TRADE=false PAPER_EXECUTION_SCOPE=disabled PYTHON_DOTENV_DISABLED=1`.

Quando consegni, indica: branch, SHA, file toccati, comandi eseguiti con output, SHA256 di
sidecar e `.app`. Claude rieseguirà tutto in modo indipendente.

## 1. AUDIT-M1 (MEDIUM, priorità assoluta) — lock globale

**Dove:** `src/api/local_app.py`, `lock = threading.RLock()` dentro `create_local_app`, usato da
`get_state`, `market`, `local_account`, `local_trade`, `backtest`, `proposal`, `automation`,
`connect_paper`, `connect_mt5`, preferenze.

**Difetto:** il lock resta preso durante l'I/O Alpaca (`paper.get_paper_snapshot`,
`get_market_data`, `get_latest_quote`, `verify_connection`; timeout (3.05, 10) s per richiesta,
più 2 retry in lettura su 429/504). Ogni richiesta Demo/Simulazione aspetta; oltre i 12 s del
client (`frontend/src/api.ts`) tutta la UI va in errore.

**Riproduzione:** `python -m pytest -q tests/test_qa_macos_audit.py::test_slow_paper_read_does_not_block_demo --runxfail`
→ `Demo state waited 2.70s behind a Paper network read`.

**Correzione attesa (indicativa, scegli tu la forma minima):**
- un lock per contesto (`demo`, `simulation`, `paper`, `mt5`) al posto del lock unico;
- `paper` (variabile `nonlocal`) letto/scritto sotto un lock breve dedicato, mentre l'I/O di rete
  avviene **fuori** dai lock di Demo/Simulazione;
- serializzazione invariata delle scritture ledger **per contesto** (`local_account`, `local_trade`,
  `automation`): niente doppio conto, idempotenza invariata (`BEGIN IMMEDIATE` resta);
- preferenze: lock proprio;
- nessun fallback: un errore Paper resta `unavailable`, mai dati Demo al suo posto.

**Accettazione:**
1. il test M1 passa **senza** `--runxfail`; solo allora togli il decoratore `xfail`;
2. aggiungi un test simmetrico "Paper lento non blocca Simulation" (stesso schema);
3. `tests/test_qa_macos_audit.py` intero verde, nessuna asserzione indebolita;
4. `pytest -q tests/test_local_service.py tests/test_simulation_ledger.py tests/test_offline_executor.py` verdi;
5. suite completa: nessuna regressione rispetto a 994 passed / 1 skipped.

## 2. AUDIT-L1 (LOW) — messaggio timeout WebKit

**Dove:** `frontend/src/api.ts`, `request()`, ramo `catch`: rilancia ogni `AbortError`.
In WKWebView il timeout di `AbortSignal.timeout(12000)` arriva come `AbortError`, la UI mostra
"Fetch is aborted" (riprodotto due volte sull'app reale).

**Correzione:** rilancia l'errore originale solo se `options.signal?.aborted` (annullamento del
chiamante); altrimenti `ApiError` localizzato, es. "Il servizio locale non ha risposto in tempo".

**Accettazione:** test Vitest per (a) `AbortError` con signal del chiamante abortito → rilanciato,
(b) `AbortError`/`TimeoutError` senza abort del chiamante → messaggio italiano.

## 3. AUDIT-L4 (LOW) — form "Crea conto virtuale" durante il blocco

**Dove:** `frontend/src/App.tsx`, `LocalLedger`, condizione `!state?.account`.
Con stato non disponibile (`state === null`) mostra il form di creazione e resta visibile la nota
"Conto virtuale disponibile…". Il server risponde 409, ma la UI è fuorviante.

**Correzione:** se `state === null` mostrare "Stato del conto non disponibile" e nessun form;
form solo se `state` presente e `state.account === null`; azzerare la nota dell'ultima azione
quando lo stato non è disponibile.

**Accettazione:** test in `App.test.tsx` con API che fallisce: nessun pulsante "Crea conto virtuale".

## 4. AUDIT-L2 (LOW) — busy timeout SQLite 15 s

**Dove:** `src/simulation/ledger.py:86` `sqlite3.connect(..., timeout=15)`.
Misura: DB in `BEGIN EXCLUSIVE` esterno → `GET /state?context=demo` 503 dopo 15.6 s.

**Correzione:** timeout < 12 s (es. 5 s) e, con M1, il blocco riguarda solo il contesto colpito.
Restare fail-closed (503, nessun dato inferito).

**Accettazione:** test che tiene `BEGIN EXCLUSIVE` sul DB demo: risposta 503 entro il nuovo limite,
Simulation risponde subito, dopo lo sblocco Demo torna 200 con dati intatti.

## 5. AUDIT-L3 (LOW) — worker orfano se bloccato alla chiusura forzata

**Dove:** `src-tauri/src/service.rs`, `start()` (timeout 15 s) e `shutdown()` (scadenza 20 s):
`child.kill()` colpisce solo il bootloader PyInstaller; il worker diventa figlio di launchd e tiene
la porta finché resta bloccato.

**Correzione suggerita:** su Unix `std::os::unix::process::CommandExt::process_group(0)` allo spawn e,
alla scadenza, SIGKILL al gruppo (`kill(-pid, SIGKILL)`); su Windows lasciare l'attuale Job/kill.
Non uccidere mai PID non posseduti.

**Accettazione:** `python scripts/qa_sidecar_lifecycle.py <sidecar>` invariato verde; test Rust che
avvia `sh -c 'sh -c "trap \"\" TERM; sleep 60" & wait'` e verifica che dopo `shutdown()` nessun
figlio resti vivo.

## 6. AUDIT-L5 (LOW) — percorsi home nel binario release

**Dove:** build release di `src-tauri` (343 stringhe con la home dello sviluppatore, dai percorsi
del registry Cargo).

**Correzione:** in build release passare `RUSTFLAGS="--remap-path-prefix=$HOME=~"` (o `trim-paths`
se supportato dal toolchain pinnato), senza cambiare il profilo debug.

**Accettazione:** `strings aitradingbot-desktop | grep -c "$HOME"` = 0 sul bundle release.

## 7. AUDIT-L6 (LOW) — qualità e CI

- F841 in `src/broker/alpaca_client.py:485` e `:537` (`except Exception as exc` inutilizzato).
- Con `ruff check . --isolated --select F`: altri 10 rilievi (F401 in `providers/hub.py` e in 5 file
  di test, F841 in `tests/test_local_service.py:222`). Nessuna config ruff nel repository: decidere
  se aggiungerla (proposta minima: `[lint] select = ["E9","F"]`).
- `npm run test:e2e` non esiste: **non** inventarlo senza un framework adeguato.
- Job CI `local-app (macos-latest)` cancellato due volte su `e06d29f`: rilanciare sul nuovo SHA.

## 8. Gate di distribuzione (separati, non bloccano le correzioni sopra)

Firma ad-hoc, `spctl` rifiuta il bundle, nessun ticket di notarizzazione, nessuna identità
Developer ID su questo Mac, Intel/x86_64 mai verificato, licenza/notice del progetto assenti.
Servono decisione e credenziali dell'utente: non usare certificati personali senza autorizzazione.
