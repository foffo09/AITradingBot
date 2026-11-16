# Piano QA end-to-end unico — December QA & Release

Owner QA: Persona 4. Direttiva prioritaria Notion del 16 novembre 2026.
Base documentale (BASE): `3df4f8260fcbb85ea8ccf2c2b680f672adc89af4`.
Audit: 16 novembre 2026, macOS 27.2.1 arm64, sessione iniziata alle 11:55:10 UTC.
**Nessun candidato React/FastAPI/Tauri/MT5 integrato identificato dal responsabile.**
I nuovi scenari runtime non sono eseguiti; presenza di codice/test non equivale a PASS.
Questo è l'unico piano; [architettura](ARCHITETTURA_APP.md) contiene decisioni e
confini, [matrice](MATRICE_TEST.md) evidenze, [gate](RELEASE_GATES.md) autorizzazioni.

## 1. Perimetro, ownership ed evidenze

Non implementare prodotto, test o CI; non modificare branch/PR degli altri.
P1/P2/P3 sono i referenti target della direttiva (UI/API/engine), non nuove
assegnazioni. P4 possiede esecuzione QA e report. Una dipendenza non confermata
va al responsabile, senza creare task paralleli. Nessun broker/feed, ordine,
server o automazione avviati per questa fase documentale.

Evidenze della sessione, con comando/ambiente/output in [WORKLOG](WORKLOG.md):

- **E-GIT**: fetch, rev-parse, for-each-ref, ls-tree e ancestry sulla BASE.
- **E-SRC**: ispezione AST/import e sorgenti alla BASE, senza importarli/eseguirli.
- **E-CI**: API GitHub PR/check correnti rilette il 16 novembre; run storici
  `42921890791` (head `5e759404ef574c1dacc22a79a417f29362a8a2ef`) e
  `43121098415` (head `97ff2966b9d8d82d6c6f10d30e9da125656e5259`).
- **E-DOC**: validatore documentale e diff-check della sessione; non prove di prodotto.

Per ciascuna futura esecuzione, sostituire CANDIDATO NON ASSEGNATO con SHA
applicativo e base di integrazione confermati; registrare OS/versione/arch,
Python/Node/Rust/WebView, comandi esatti, data UTC/fuso, output redatto, run/job,
hash artifact e risultato effettivo. Le fixture devono usare account fittizi,
clock controllato, SQLite temporanei e transport mock; nessun `.env` personale.
Un futuro test qui nominato è una proposta, non un file presente o un run eseguito.

## 2. Audit indipendente delle consegne P1/P2/P3

| Riferimento remoto ricontrollato | SHA | Osservazione e report |
| --- | --- | --- |
| `feature/backend-market-data` storico | `1a68d5bbc25f3e1b6eceb0235f9ea2fdfa033240` | Antenato main; handoff Python/Alpaca storico. Nuovo report P2 API/MT5 non ricevuto nei materiali P4 letti. |
| `feature/dashboard-ui` storico | `432ecdd7d9e997dcd4efdef3b55880caee51d493` | Antenato main; Streamlit. Nuovo report P1 React/Tauri non ricevuto. |
| `feature/strategy-engine` | `93fde78da232ffe7d8ede01ac4f9d20c6df920d0` | Antenato main; proposta pura esistente. Nuova specifica P3/API non ricevuta. |
| `agents/p1-dashboard-refresh-20261109` | `e1bd306d2f1e6c5b7db9b90bf1fdacf9ad4d7b24` | Non antenato main; 9 file UI/docs/test legacy, nessun manifest React/Tauri/MT5. Non integrato e non modificato. |

GitHub ha solo PR aperte #5/#6 nella lettura completa (limite 100, 2 risultati).
I tree dei riferimenti sopra non contengono manifest della nuova migrazione.
“Report non ricevuto” non significa task non iniziato: attività locali/private
non sono osservabili da questo audit. Non aspettare indefinitamente: il blocco
contratti/candidato è esplicito, da rivalutare al prossimo report/SHA verificato.

Contratti reali preservati: [backend](../BACKEND_HANDOFF.md),
[dashboard storica](../DASHBOARD_HANDOFF.md), [engine](../STRATEGY_HANDOFF.md).
Il DTO proposto da P3 contiene direction, validation_state, signal_id, symbol,
reference/entry/TP/SL, rischio, quality non calibrata, reason, UTC/expiry e
provenance. P2 deve conservarlo senza inventare peak/counter/zero o perdere attrs;
P1 lo presenta senza submit dal rendering. Nuovo schema API/sessione non consegnato.

## 3. Milestone unificate

La direttiva prioritaria web+desktop del 16 novembre sostituisce le precedenti
scadenze 20/27 novembre e 4/11 dicembre; non esiste un secondo piano.

| Termine obiettivo | Gate/evidenza da produrre | Stato alla BASE |
| --- | --- | --- |
| 18 novembre | Architettura e piano QA disponibili; contratti P1/P2/P3 da confermare | Documenti preparati; contratti BLOCKED |
| 24 novembre | Revisione documentale servizi React/FastAPI e confini | BLOCKED: consegne mancanti |
| 30 novembre | Primo E2E browser e Tauri dev sul candidato identificato | BLOCKED |
| 7 dicembre | Funzionale e isolamento quattro contesti | NON VERIFICATO |
| 14 dicembre | Build native, security review e regressioni OS | BLOCKED |
| 18 dicembre | Rapporto release readiness sul candidato esatto | BLOCKED |
| 19–31 dicembre | Solo blocker, con nuova verifica SHA dopo ogni fix | Futuro, NON VERIFICATO |

Nessuna automazione programmata o promessa di completamento dei task altrui.

## 4. Catalogo scenari riproducibili

Stati: PASS = solo evidenza delimitata; FAIL = prova eseguita negativa;
BLOCKED = prerequisito mancante; NON VERIFICATO = prova non eseguita.
Nessun FAIL runtime viene inventato se il prodotto non è presente.
Ogni caso include owner QA, referente contratto, piattaforma e SHA.

### QA-AUD-01 — Verificare base, branch e scope senza distruggere lavoro

- **Requisito / owner:** Verificare base, branch e scope senza distruggere lavoro. Owner QA P4; referente contratto P4.
- **Piattaforma / SHA / data:** macOS 27.2.1 arm64; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Accesso Git/GitHub in lettura. Fixture: Riferimenti remoti; nessun dato conto.
- **Passi:** Fetch senza prune; confrontare SHA; ls-tree e ancestry dei branch.
- **Risultato atteso:** Base attesa, worktree nuovo; fonti e divergenze registrate.
- **Test esistente:** Nessuno: verifica Git documentale. **Test futuro:** Rieseguire audit a ogni nuovo SHA (non implementato qui).
- **Evidenza / stato:** E-GIT: BASE corretta, branch nuovi creati, feature storiche antenate main; ramo refresh P1 separato. **PASS**. Nessun nuovo run runtime in questa missione documentale.

### QA-AUD-02 — Engine senza import diretti UI/API/broker

- **Requisito / owner:** Engine senza import diretti UI/API/broker. Owner QA P4; referente contratto P3, verifica P4.
- **Piattaforma / SHA / data:** Analisi statica Python su macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Sorgenti src/strategy alla BASE. Fixture: AST di tutti i sei moduli, senza import runtime.
- **Passi:** Estrarre Import/ImportFrom e cercare framework/SDK/UI/broker.
- **Risultato atteso:** Nessun import vietato; prova limitata agli import diretti, non a tutta la catena transitiva.
- **Test esistente:** tests/test_strategy_engine.py. **Test futuro:** Test architetturale transitivo sul candidato (non implementato qui).
- **Evidenza / stato:** E-SRC: STRATEGY_DIRECT_IMPORTS 6 modules; violations=[]. **PASS**. Nessun nuovo run runtime in questa missione documentale.

### QA-WEB-01 — Launcher browser → loopback → React → servizi/SQLite

- **Requisito / owner:** Launcher browser → loopback → React → servizi/SQLite. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Browser locale Windows e macOS, due esecuzioni distinte; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Candidato e launcher consegnati; A01/A03 approvati. Fixture: Profilo pulito, mock backend, DB temporanei.
- **Passi:** Lanciare in test isolato; attendere readiness; aprire pagina; leggere contesto.
- **Risultato atteso:** UI servita localmente, automazione ferma, nessuna rete esterna o lettura personale.
- **Test esistente:** tests/test_dashboard_contexts.py (solo Streamlit). **Test futuro:** Smoke browser del launcher nuovo (non implementato qui).
- **Evidenza / stato:** Mancano launcher/API/React migrati e candidato. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-WEB-02 — UI e API condivise tra browser e WebView

- **Requisito / owner:** UI e API condivise tra browser e WebView. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Browser e Tauri su entrambi gli OS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Bundle e schema API versionati. Fixture: Stesso DTO con null, provenance e UTC.
- **Passi:** Eseguire gli stessi casi UI via due host; confrontare contract hash e risultati.
- **Risultato atteso:** Stessi componenti/bundle e semantica API; nessun fork UI o alias dati inventato.
- **Test esistente:** tests/test_strategy_engine.py (solo DTO Python). **Test futuro:** Contract test React/API/Tauri (non implementato qui).
- **Evidenza / stato:** Nessun bundle o schema nuovo nel tree. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-WEB-03 — Funzioni locali senza internet e servizi esterni indisponibili

- **Requisito / owner:** Funzioni locali senza internet e servizi esterni indisponibili. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Windows/macOS, browser e desktop; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Artifact e fixture offline consegnati. Fixture: Rete applicativa negata, cache vuota, feed/broker mock indisponibili.
- **Passi:** Installare fixture; avviare offline; aprire Demo/Sim; tentare sola lettura esterna mock.
- **Risultato atteso:** Asset senza CDN/download; Demo/Sim funzionanti; Paper/feed N/D con errore, niente fallback sintetico.
- **Test esistente:** tests/test_dashboard_contexts.py. **Test futuro:** Cold-start offline browser/desktop (non implementato qui).
- **Evidenza / stato:** Artifact nuovo assente. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-SEC-01 — Bind, porta, Host e Origin restrittivi

- **Requisito / owner:** Bind, porta, Host e Origin restrittivi. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows/macOS, browser/WebView; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** A02/A03 e allowlist concordati. Fixture: Host ostile, Origin ostile/null/assente, porta occupata, processo estraneo fittizio.
- **Passi:** Testare richieste fake e collisione; verificare socket e identità istanza.
- **Risultato atteso:** Solo loopback; niente processo sbagliato; richieste non autorizzate rifiutate anche in lettura.
- **Test esistente:** tests/test_omega.py (solo API legacy). **Test futuro:** Negative suite HTTP/Origin/port ownership (non implementato qui).
- **Evidenza / stato:** API applicativa e handshake mancanti. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-SEC-02 — Token effimero, CORS e CSRF senza segreti nel frontend

- **Requisito / owner:** Token effimero, CORS e CSRF senza segreti nel frontend. Owner QA P4; referente contratto P2/P1.
- **Piattaforma / SHA / data:** Browser/WebView Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Bootstrap A03 approvato. Fixture: Sessione scaduta, cookie/header mancanti, richieste cross-site; chiavi-esca fittizie.
- **Passi:** Tentare read/write mock da origini diverse; riavviare; esaminare bundle/storage/log/URL/argv.
- **Risultato atteso:** CORS non sostituisce auth; CSRF respinto; vecchia sessione invalida; nessun segreto in UI o log.
- **Test esistente:** tests/test_backend_contract.py (redazione backend). **Test futuro:** Session/CSRF/browser tests e scansione artifact (non implementato qui).
- **Evidenza / stato:** Token legacy inserito in HTML non certifica A03; nuova soluzione non consegnata. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-SEC-03 — Capabilities Tauri e navigazione minime

- **Requisito / owner:** Capabilities Tauri e navigazione minime. Owner QA P4; referente contratto P1.
- **Piattaforma / SHA / data:** Tauri Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Manifest e build Tauri presenti. Fixture: Finestra remota, iframe, path fuori scope, comando shell fittizio.
- **Passi:** Confrontare capabilities e comandi custom; richiedere azioni fuori scope senza eseguirle.
- **Risultato atteso:** Niente shell/filesystem globali, navigation/remote privilege respinti.
- **Test esistente:** Nessuno Tauri esistente. **Test futuro:** Capability e WebView security tests (non implementato qui).
- **Evidenza / stato:** Manifest Tauri assente. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-SEC-04 — Segreti, credenziali e rete esclusi da test e log

- **Requisito / owner:** Segreti, credenziali e rete esclusi da test e log. Owner QA P4; referente contratto P2/P4.
- **Piattaforma / SHA / data:** Tutti gli OS e artifact; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Candidato e log redatti disponibili. Fixture: Sentinel fittizi, transport mock, DB temporanei.
- **Passi:** Applicare guard offline; cercare sentinel in output e bundle; non aprire file personali.
- **Risultato atteso:** Contatori rete/credenziali zero e nessun valore sensibile; interrompere su violazione.
- **Test esistente:** tests/test_test_isolation.py; tests/test_backend_integration.py. **Test futuro:** Redaction e artifact checks della nuova API (non implementato qui).
- **Evidenza / stato:** Nessun nuovo artifact eseguito; vecchio guard non attesta tutto il prodotto. **NON VERIFICATO**. Nessun nuovo run runtime in questa missione documentale.

### QA-LIF-01 — Start/health/versione/timeout e collisioni

- **Requisito / owner:** Start/health/versione/timeout e collisioni. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Contratto lifecycle e deadline finite. Fixture: Sidecar mock lento, health errato, bind occupato, versione errata.
- **Passi:** Start; simulare errori e seconda istanza; osservare stato fino alla deadline.
- **Risultato atteso:** starting/ready/error distinti; niente connessione o readiness falsa.
- **Test esistente:** Nessuno sidecar esistente. **Test futuro:** Lifecycle start/health native tests (non implementato qui).
- **Evidenza / stato:** Entrypoint sidecar e health nuovi mancanti. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-LIF-02 — Crash, riavvio e recupero senza reinvii

- **Requisito / owner:** Crash, riavvio e recupero senza reinvii. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Sidecar e journal contrattualizzati. Fixture: Crash prima invio mock e dopo ack perso; intenti fittizi persistiti.
- **Passi:** Arrestare solo processi fixture; riavviare e confrontare journal/mock broker.
- **Risultato atteso:** Snapshot invalidi, automazione ferma, incertezza conservata; nessun duplicato.
- **Test esistente:** tests/test_paper_coordinator.py; tests/test_paper_automation.py. **Test futuro:** Sidecar crash/restart E2E con broker mock (non implementato qui).
- **Evidenza / stato:** Nuovo lifecycle assente; recupero pieno post-fill non attestato. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-LIF-03 — Shutdown, timeout, cleanup e DB persistente

- **Requisito / owner:** Shutdown, timeout, cleanup e DB persistente. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Ownership PID e policy stop approvate. Fixture: Worker bloccato, subprocess fixture, DB con intento incerto.
- **Passi:** Chiudere finestra/supervisore; simulare stop lento; ispezionare risorse possedute.
- **Risultato atteso:** Nessun orfano; solo proprio processo terminato; journal preservato; niente cancellazione DB.
- **Test esistente:** tests/test_native_store.py. **Test futuro:** Shutdown/cleanup smoke nativo (non implementato qui).
- **Evidenza / stato:** Supervisore e pacchetto mancanti. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-CTX-01 — Demo e Simulazione con capitali e ledger distinti

- **Requisito / owner:** Demo e Simulazione con capitali e ledger distinti. Owner QA P4; referente contratto P2/P1.
- **Piattaforma / SHA / data:** Windows/macOS, browser/desktop; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** API contesti e storage consegnati. Fixture: DB temporanei distinti, alias/hard link e path Unicode/spazi.
- **Passi:** Cambiare contesto; aggiornare saldo locale; riaprire processo.
- **Risultato atteso:** Nessuna contaminazione; niente SDK; alias rifiutati; nessuna migrazione implicita.
- **Test esistente:** tests/test_dashboard_contexts.py; tests/test_ui_workspaces.py. **Test futuro:** Isolation tests React/API/sessione (non implementato qui).
- **Evidenza / stato:** Prova nuova UI/API non eseguita. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-CTX-02 — Paper separato dai ledger locali e default fermo

- **Requisito / owner:** Paper separato dai ledger locali e default fermo. Owner QA P4; referente contratto P2/P1.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Account snapshot mock e contesto Paper contrattuale. Fixture: Equity/cash null, errori conto, snapshot vecchio, Demo con saldi diversi.
- **Passi:** Entrare Paper senza credenziali reali; simulare timeout; tornare Demo/Sim.
- **Risultato atteso:** Solo snapshot Paper o N/D; niente saldo Demo, automazione arrestata, rendering senza submit.
- **Test esistente:** tests/test_paper_safety.py; tests/test_dashboard_contexts.py. **Test futuro:** Paper context API/UI mock tests (non implementato qui).
- **Evidenza / stato:** Adapter nuovo assente. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-CTX-03 — MT5 non condivide capitale, ordini o permessi

- **Requisito / owner:** MT5 non condivide capitale, ordini o permessi. Owner QA P4; referente contratto P2/P1.
- **Piattaforma / SHA / data:** Windows e macOS unsupported; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Schema contesto MT5 approvato. Fixture: Account MT5 fittizio distinto da Alpaca, DB/path diversi.
- **Passi:** Cambiare contesto e account; confrontare cache, stato e repository.
- **Risultato atteso:** Nessuna fusione conti/credenziali, nessun trading MT5 o fallback Paper.
- **Test esistente:** Nessuno MT5 esistente. **Test futuro:** MT5 context isolation fixture suite (non implementato qui).
- **Evidenza / stato:** Adattatore MT5 assente. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-MT5-01 — Terminale assente e piattaforma unsupported

- **Requisito / owner:** Terminale assente e piattaforma unsupported. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows terminale assente; macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Adapter importabile senza SDK/terminale dove non supportato. Fixture: Import SDK fallito e terminale inesistente simulati.
- **Passi:** Aprire stato MT5 con mock; non lanciare terminale reale.
- **Risultato atteso:** Windows unavailable; macOS unsupported; niente crash o dati finti.
- **Test esistente:** Nessuno MT5 esistente. **Test futuro:** MT5 unsupported/unavailable tests (non implementato qui).
- **Evidenza / stato:** Nessun modulo o contratto MT5 ricevuto. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-MT5-02 — Account unverified/connected e dati stale

- **Requisito / owner:** Account unverified/connected e dati stale. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows mock; autentico solo con consenso separato; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Schema letture e clock controllato. Fixture: Account mancante/cambiato, tick valido/scaduto/futuro, timeout.
- **Passi:** Simulare initialize/read/disconnect; aggiornare clock e identità.
- **Risultato atteso:** Stati distinti, timestamp/provenienza mantenuti, stale non segnale valido.
- **Test esistente:** Nessuno MT5 esistente. **Test futuro:** MT5 read-state tests; prova Windows autentica separata (non implementato qui).
- **Evidenza / stato:** Manca adattatore; nessun consenso o terminale autentico usato. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-MT5-03 — MT5 strettamente read-only, nessun order_send

- **Requisito / owner:** MT5 strettamente read-only, nessun order_send. Owner QA P4; referente contratto P2/P3.
- **Piattaforma / SHA / data:** Windows mock e controllo statico cross-platform; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Adapter consegnato e whitelist letture. Fixture: Spy che fallisce su qualunque API di scrittura/trading.
- **Passi:** Analizzare import/call graph; invocare tutti i percorsi UI/API di sola lettura sui mock.
- **Risultato atteso:** Zero order_send/modifiche; nessuna scorciatoia da strategia/rendering.
- **Test esistente:** Nessuno MT5 esistente. **Test futuro:** Read-only boundary tests e spy negativo (non implementato qui).
- **Evidenza / stato:** Assenza attuale non prova la futura whitelist. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-DAT-01 — Provenienza, timestamp, calendario e gate condiviso

- **Requisito / owner:** Provenienza, timestamp, calendario e gate condiviso. Owner QA P4; referente contratto P2/P3.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Adapter API con metadati e clock fisso. Fixture: Quote stale/future/crossed, barre incomplete, synthetic/missing/contradictory.
- **Passi:** Passare frame/quote via API al motore e alla UI; verificare gli attrs serializzati.
- **Risultato atteso:** Gate esistente riusato; NO_TRADE e N/D espliciti; niente rietichettatura operativa.
- **Test esistente:** tests/test_backend_contract.py; tests/test_bar_timing.py; tests/test_signal_refresh.py. **Test futuro:** Provenance serialization API/UI tests (non implementato qui).
- **Evidenza / stato:** Nuovo DTO/consumer API non ricevuto. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-DAT-02 — HTTP incompleto, errori e riconnessione

- **Requisito / owner:** HTTP incompleto, errori e riconnessione. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Transport API mock. Fixture: JSON troncato, liste mancanti, timeout/disconnessione e risposta vuota esplicita.
- **Passi:** Interrompere lettura; riconnettere; confrontare stato verificato e tempi.
- **Risultato atteso:** Vuoto valido distinto da risposta mancante; niente vecchia equity o fallback sintetico.
- **Test esistente:** tests/test_backend_integration.py. **Test futuro:** New API failure-contract tests (non implementato qui).
- **Evidenza / stato:** Nuova API non consegnata. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-ORD-01 — Paginazione ordini completa e coerente

- **Requisito / owner:** Paginazione ordini completa e coerente. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows/macOS mock; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Contratto paginazione nuova consegnato. Fixture: Pagine duplicate/mancanti, cursore ripetuto, saturazione500 e timeout a metà.
- **Passi:** Leggere più pagine mock; deduplicare ID; provare pagina mancante e fine ambigua.
- **Risultato atteso:** Incompletezza dichiarata e blocco operativo; nessun falso snapshot completo o doppio ordine.
- **Test esistente:** tests/test_broker.py. **Test futuro:** Pagination completeness and cursor tests (non implementato qui).
- **Evidenza / stato:** Legacy limita500 e rifiuta saturazione: non implementa pagina finale verificata. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-ORD-02 — Idempotenza, pending/ack/fill/timeout/uncertain

- **Requisito / owner:** Idempotenza, pending/ack/fill/timeout/uncertain. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows/macOS mock; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Ledger/coordinatore e DTO broker conservati. Fixture: Client ID stabile, ack perso, fill parziale, aggiornamenti duplicati/fuori ordine.
- **Passi:** Simulare invio solo al fake; riavvio; confrontare intenti/fill/saldo/posizioni.
- **Risultato atteso:** Nessun invio duplicato o doppio fill; risposta vuota/timeout non provano assenza ordine.
- **Test esistente:** tests/test_paper_automation.py; tests/test_paper_coordinator.py. **Test futuro:** API reconciliation E2E e recovery controllato (non implementato qui).
- **Evidenza / stato:** Riconciliazione piena post-fill e API nuove non verificate. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-ORD-03 — Panic/stop/uscite gestiscono pending e posizioni

- **Requisito / owner:** Panic/stop/uscite gestiscono pending e posizioni. Owner QA P4; referente contratto P2.
- **Piattaforma / SHA / data:** Windows/macOS mock; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Contratto Paper e comandi espliciti autorizzati nel fake. Fixture: Pending, parziali, cancellazione rifiutata, posizione nativa fittizia.
- **Passi:** Richiedere panic solo al fake; ripetere e riavviare; verificare ack e residui.
- **Risultato atteso:** UI non dichiara flat prima della conferma; blocco se stato incerto; nessun ordine autentico.
- **Test esistente:** tests/test_hyperliquid_testnet.py (altro adattatore, non prova Alpaca). **Test futuro:** Alpaca API panic/pending mock suite (non implementato qui).
- **Evidenza / stato:** Protezione full-stack Alpaca non attestata da test di altro provider. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-STR-01 — BUY/SELL/WAIT/NO_TRADE, rischio, sizing, livelli

- **Requisito / owner:** BUY/SELL/WAIT/NO_TRADE, rischio, sizing, livelli. Owner QA P4; referente contratto P3/P2.
- **Piattaforma / SHA / data:** Windows/macOS mock; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** DTO P3 reale e RiskSnapshot verificabile. Fixture: Long posseduto/non posseduto, peak/counter mancanti, spread/ATR invalidi.
- **Passi:** Valutare setup controllati; attraversare P3→API→UI e confrontare JSON.
- **Risultato atteso:** SL<Entry<TP BUY e TP<Entry<SL SELL analitico; SELL riduce long; rischio fallito NO_TRADE, niente submit.
- **Test esistente:** tests/test_strategy_engine.py; tests/test_strategy_risk.py; tests/test_trade_levels.py. **Test futuro:** Strategy API contract integration tests (non implementato qui).
- **Evidenza / stato:** Motore puro presente; adapter e contabilità richiesti non consegnati. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-STR-02 — Expiry e deduplica persistente del segnale

- **Requisito / owner:** Expiry e deduplica persistente del segnale. Owner QA P4; referente contratto P3/P2.
- **Piattaforma / SHA / data:** Windows/macOS mock; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Persistenza ID consumati e clock controllato. Fixture: Stessa barra/account, cambio config, evento scaduto e riavvio.
- **Passi:** Ripetere evaluate, cambiare rischio/quote, riavviare consumer e ripresentare ID.
- **Risultato atteso:** Nessun rinnovo artificiale o doppio consumo; ID non sostituisce client_order_id.
- **Test esistente:** tests/test_strategy_engine.py. **Test futuro:** Consumer restart/expiry API tests (non implementato qui).
- **Evidenza / stato:** Consumer persistente nuovo non ricevuto. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-UI-01 — Refresh, cambio contesto ed errori senza side effect

- **Requisito / owner:** Refresh, cambio contesto ed errori senza side effect. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Browser/WebView Windows/macOS; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** UI React con adapter API e mock di rete. Fixture: Refresh concorrenti, contesto/account cambiati, risposte vecchie/errore.
- **Passi:** Navigare e rieseguire render; ritardare risposte; cambiare contesto e verificare cache.
- **Risultato atteso:** Risposta vecchia non sovrascrive nuovo contesto; nessun invio dal render; N/D e stato fermo.
- **Test esistente:** tests/test_signal_refresh.py; tests/test_dashboard_contexts.py (Streamlit). **Test futuro:** React rendering/cancellation/interaction tests (non implementato qui).
- **Evidenza / stato:** React non presente. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-BKT-01 — Backtest causale, costi e stop-first

- **Requisito / owner:** Backtest causale, costi e stop-first. Owner QA P4; referente contratto P3.
- **Piattaforma / SHA / data:** Windows/macOS offline; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Adapter analitico sul motore esistente. Fixture: OHLC sintetici controllati con gap e barra ambigua.
- **Passi:** Segnale al bar t, esecuzione next-open; alterare barre future e ricalcolare.
- **Risultato atteso:** Nessun look-ahead; stop-first; commissioni/spread/slippage separati; equity/DD riproducibili.
- **Test esistente:** tests/test_backtest_execution.py; tests/test_strategy_backtest.py. **Test futuro:** API backtest result contract tests (non implementato qui).
- **Evidenza / stato:** Adapter nuovo non presente; test storici non rieseguiti sul candidato. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-BKT-02 — Training/validation/OOS separati e barre complete

- **Requisito / owner:** Training/validation/OOS separati e barre complete. Owner QA P4; referente contratto P3.
- **Piattaforma / SHA / data:** Windows/macOS offline; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Contratto periodo/versione dati conservato. Fixture: Tranche disgiunte e ultima barra incompleta.
- **Passi:** Modificare solo OOS; confrontare training/validation, costi e capitale.
- **Risultato atteso:** Nessuna contaminazione; barre incomplete escluse, risultati non garanzia di profitto.
- **Test esistente:** tests/test_strategy_partitions.py. **Test futuro:** API partition provenance tests (non implementato qui).
- **Evidenza / stato:** Nuovo contratto analitico P2/P3 non ricevuto. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-PKG-01 — Build Windows nativa Tauri e backend confezionato

- **Requisito / owner:** Build Windows nativa Tauri e backend confezionato. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Runner Windows x64 nativo, poi Windows11 desktop; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Manifest/lock/toolchain/entrypoint e candidato presenti. Fixture: Workspace pulito senza credenziali e fixture offline.
- **Passi:** Eseguire comandi build consegnati; hash artifact; install/start/stop senza Python globale.
- **Risultato atteso:** Artifact contiene sidecar corretto, UI comune e risorse; nessun download operativo o ordine.
- **Test esistente:** Nessun build Tauri esistente. **Test futuro:** Native Windows packaging CI/manual smoke (non implementato qui).
- **Evidenza / stato:** Nessun manifest/sidecar/artifact; CI pytest non è build desktop. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-PKG-02 — Build macOS nativa distinta per architettura

- **Requisito / owner:** Build macOS nativa distinta per architettura. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Runner macOS arm64; x64 solo se dichiarato supportato; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Manifest/lock/toolchain e candidato presenti. Fixture: Mac pulito e fixture offline.
- **Passi:** Build per target dichiarato; hash artifact; install/start/crash/stop.
- **Risultato atteso:** Sidecar target coerente; eseguibile senza Python globale; niente falsa certificazione x64 da arm64.
- **Test esistente:** Nessun build Tauri esistente. **Test futuro:** Native macOS packaging/smoke per architettura (non implementato qui).
- **Evidenza / stato:** Manifest e artifact assenti; nessun comando build inventato o lanciato. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-PKG-03 — Installer offline e aggiornamento senza perdita dati

- **Requisito / owner:** Installer offline e aggiornamento senza perdita dati. Owner QA P4; referente contratto P1/P2.
- **Piattaforma / SHA / data:** Windows11/macOS installazioni pulite; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Artifact nativi e piano migrazione disponibili. Fixture: Path spazi/Unicode, profilo senza runtime globali, DB fixture precedente.
- **Passi:** Installare offline; aggiornare/downgrade secondo policy; chiudere e disinstallare solo fixture.
- **Risultato atteso:** Prerequisiti dichiarati, dati non cancellati, niente orfani o bypass protezioni OS.
- **Test esistente:** tests/test_native_store.py (solo storage). **Test futuro:** Installer upgrade/cleanup native tests (non implementato qui).
- **Evidenza / stato:** Artifact e policy migrazione mancanti. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-OSS-01 — Licenze OSS, lock e assenza canoni obbligatori

- **Requisito / owner:** Licenze OSS, lock e assenza canoni obbligatori. Owner QA P4; referente contratto P1/P2/P4.
- **Piattaforma / SHA / data:** Artifact Windows/macOS e inventario documentale; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Dipendenze/lock/SBOM e termini distribuzione consegnati. Fixture: Inventario versioni/hashes, notice e servizi opzionali.
- **Passi:** Confrontare artifact e manifest; controllare obblighi/licenze e costi core locale.
- **Risultato atteso:** Licenze/notice completi; nessun SaaS obbligatorio per core; costi esterni espliciti.
- **Test esistente:** Nessun inventario distribuzione esistente. **Test futuro:** License/SBOM/lock verification (non implementato qui).
- **Evidenza / stato:** Pin Python diretti presenti; lock transitive, licenza root e manifest nuovi non trovati. **NON VERIFICATO**. Nessun nuovo run runtime in questa missione documentale.

### QA-CI-01 — Distinguere CI Python storica da release migrata

- **Requisito / owner:** Distinguere CI Python storica da release migrata. Owner QA P4; referente contratto P4.
- **Piattaforma / SHA / data:** Windows Server2025 x64 e macOS26.7.2 arm64; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Accesso GitHub in lettura. Fixture: Run42921890791 e43121098415, non riavviati.
- **Passi:** Leggere PR/check head e metadati; confrontare fonte matrice.
- **Risultato atteso:** PASS solo degli SHA storici; nessuna estensione a React/Tauri/MT5 o nuovo candidato.
- **Test esistente:** tests/test_test_isolation.py; .github/workflows/windows-ci.yml. **Test futuro:** Nuove prove native sul futuro candidato (non implementato qui).
- **Evidenza / stato:** E-CI: SUCCESS per windows-tests su5e75940 e windows-tests/macos-tests su97ff296; storico, non nuovi run. **PASS**. Nessun nuovo run runtime in questa missione documentale.

### QA-MAN-01 — UX reale Windows11 e macOS separata

- **Requisito / owner:** UX reale Windows11 e macOS separata. Owner QA P4; referente contratto P1/P4.
- **Piattaforma / SHA / data:** Windows11 desktop e macOS desktop, due verbali; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Candidate/artifact e fixture non personali disponibili. Fixture: Profilo UI pulito, risoluzioni diverse, keyboard, zoom/pan.
- **Passi:** Avvio, cambio contesti, errori, grafici, focus/tastiera e shutdown con account mock.
- **Risultato atteso:** UI leggibile/accessibile, N/D corretti, nessun ordine o credenziale reale; verbale per OS.
- **Test esistente:** tests/test_ui_charts.py (struttura, non UX manuale). **Test futuro:** Manual checklist browser/desktop per OS (non implementato qui).
- **Evidenza / stato:** Nessun candidato; Windows11 non testato da questo Mac. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

### QA-REL-01 — Release readiness sul candidato esatto

- **Requisito / owner:** Release readiness sul candidato esatto. Owner QA P4; referente contratto P4/responsabile.
- **Piattaforma / SHA / data:** Tutte le piattaforme supportate; fonte BASE sopra; candidato NON ASSEGNATO; audit 16 novembre 2026. Per CI-01 valgono gli head storici espliciti nella sua evidenza.
- **Prerequisiti / fixture:** Contratti/report P1/P2/P3, candidato e prove complete. Fixture: Dossier SHA, build hashes, CI, guard, verbali e blocker.
- **Passi:** Applicare RELEASE_GATES e matrice; riesaminare ogni modifica; registrare decisione.
- **Risultato atteso:** STOP con prove mancanti; nessun merge/release/trading automatico.
- **Test esistente:** Nessun test sostituisce decisione responsabile. **Test futuro:** Candidate readiness review (non implementato qui).
- **Evidenza / stato:** Contratti/candidato/build nuove mancanti; PR5/6 ancora draft e senza review. **BLOCKED**. Nessun nuovo run runtime in questa missione documentale.

## 5. Protocollo quando il candidato sarà disponibile

1. Il responsabile identifica SHA/base integrati, architetture e report delle
   parti. Se cambiano, invalidare il precedente verbale e rivalidare i gate.
2. Preparare un ambiente isolato senza credenziali o dati personali; verificare
   fixture e guard prima di eseguire il prodotto. Mai importare/avviare il
   launcher legacy come scorciatoia: legge configurazione e avvia un worker.
3. Sul candidato effettivo, eseguire i comandi offline sotto con la sua Python
   verificata; conservare output e exit code. Questi comandi **non sono stati
   eseguiti sul nuovo prodotto nella fase documentale**.

```sh
python -m pytest -q
python -m compileall -q app.py config src tests
python -m pip check
git diff --check
git status --short --branch
git diff --name-only
```

4. Leggere CI Windows/macOS sullo stesso candidato. Non lanciare workflow a
   mano senza incarico e non modificare CI. L'attuale pipeline non costruisce
   React/Tauri/sidecar: una futura consegna deve fornire comandi/run nativi.
5. Eseguire casi browser/desktop su fixture; i socket loopback necessari al
   futuro E2E richiedono harness separato autorizzato. Non indebolire il guard
   della suite pytest attuale, che vieta rete applicativa anche loopback.
6. Windows11 manuale va documentato da host/collaboratore Windows. MT5 reale
   solo con consenso esplicito e terminale/account dell'utente, senza ordini.
7. Raccogliere esito per caso: pass/fail/skip/warning, guard, SHA, OS/arch, ora,
   comando, output redatto e hash artifact. Nessuna presenza di test vale PASS.
8. Classificare difetti con ID/severità/file/linea/owner del contratto e prova;
   segnalare al responsabile il minimo fix necessario, senza cambiarne i branch.

## 6. Blocker ordinati e decisione attuale

| ID | Impatto / evidenza | Destinatario della decisione | Stato |
| --- | --- | --- | --- |
| B01 | Nessuna consegna nuova React/Tauri/API applicativa/MT5 nei riferimenti osservati; candidato non identificato | Responsabile, contratti P1/P2/P3 | BLOCKED |
| B02 | Sessione/bootstrap, ciclo vita sidecar e DTO condiviso non concordati; legacy non certifica i nuovi confini | Responsabile, referenti P1/P2 | BLOCKED |
| B03 | Paginazione completa e riconciliazione post-fill non dimostrate; consumer P3 e contabilità verificata mancanti | Responsabile, referenti P2/P3 | BLOCKED |
| B04 | Build native/installer/UX Windows11, MT5 e offline del prodotto nuovo senza artifact o prove | Responsabile | NON VERIFICATO |
| B05 | Licenze/SBOM/lock transitive e costo del core locale non attestati | Responsabile/proprietario | NON VERIFICATO |
| B06 | PR5/6 draft, nessuna review; main non protetto nelle letture riuscite | Responsabile/proprietario | BLOCKED per integrazione, nessuna modifica impostazioni |

Decisione: **piano documentale pronto; release migrata BLOCKED**. Nessun ordine,
server, feed, broker, build del nuovo prodotto, merge, retarget, approvazione,
release o deploy eseguiti. Nessuna attività parallela creata o duplicata.


## Casi aggiunti per completion

- Retry stessa UUID dopo commit/risposta persa e riavvio: un solo fill/costo/posizione;
  payload differente rifiutato. Concorrenza SQLite e ownership tra processi.
- Stati dry-run: start/cycle/pause/stop, replay, crash e bloccoRECOVERY_REQUIRED.
  Snapshot offline con fill parziali/completi, duplicati/tardivi, rifiuto/cancel/expiry,
  pagine overlap/mancanti/cicliche, quantità/balance/positions divergenti, date future.
- ProcessiMT5 sintetici reali: nativehang,send/recv,crash,close,protocollo,riconnessione;
  validatori reader conservati. Nessuna connessione autentica.
- FormUI rifiuto definitivo distinto da timeout, scadenza/identità proposal, polling
  senza sovrapposizione, indicatori e pulsanti dry-run senza ordini.
- WindowsCI: scriptPS reali, secondo launcher rifiutato, stop/restart/portachiusa;
  NSISunsigned install/uninstall e smoke sidecar/UI installati. Non provaGUIWindows11,
  retentionappdata reale o nativehangSDK autentico. Non pubblicare release/artifact.
