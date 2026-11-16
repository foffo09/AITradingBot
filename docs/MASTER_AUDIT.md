# Audit e integrazione applicazione locale — 16 novembre 2026

## Stato corrente dopo aggiornamento compatibile

Le sezioni seguenti conservano la cronologia delle prove. Il conflittoPillow è
stato successivamente risolto: Streamlit1.66.1 ammette pillow<14, Pillow13.0.0
è ora fissato. Ambiente .venv isolato nel worktree, nessun cambiamento alla venv
condivisa. Installazione/pipcheck riusciti e pip-audit sul nuovo requirements-dev:
**No known vulnerabilities found**, senza ignore o resolverforzato. L’audit iniziale
42advisory resta evidenzaRED, non lo stato attuale.

Il bundle precedente includevaPIL eArrow senza uso nei percorsiJSON/OHLC. Esclusi
soltanto dal sidecar, legacy invariato: archivioPyInstaller senza moduliPIL/pyarrow,
smokeHTTPfrozenPASS. Misura prima/dopo5.6624s contro15.229s, health0.0079s,
shutdown0.2602s,RSS121168KiB,CPUidle0% su2s. Startup15s invariato; nessuna garanzia
universale da un campione. Gli artifact finali sono ricostruiti nella nuova venv.

PRdraftseparata#8 basata sull’integrazione: https://github.com/foffo09/AITradingBot/pull/8.
Primo run43970361875 su03200f7: suiteWindowsPASS, wrapperPSFAIL da indagare con
nuovo diagnostico sanitizzato. RegressioneRED→GREEN: ConnectionReset durante
shutdown non è prova di chiusura; ora si continua a leggere fino a refusal o
scadenza, senza terminare altri processi. Nessun testWindows dichiarato dalMac.
Release restaBLOCKED per licenza/notice, Windows11GUI e altre prove native mancanti.


Mandato master dell'utente: implementare e verificare React/TypeScript/Vite,
FastAPI/Pydantic, Tauri e integrazione dei servizi Python; Streamlit resta
legacy. Nuova autorizzazione supera il precedente perimetro solo documentale
P4. Vietati merge su main, ordini reali, deploy/release, costi e credenziali
personali. Commit/branch/PR autorizzati. Nessun valore .env letto.

## Ricognizione iniziale

Host reale macOS arm64, non il PC Windows del percorso storico. Main remoto
fe988394d6ecdcb56763a81c627943b4cbe684e1; checkout principale locale 2b2d35a
con lavoro non committato (incluso esecutore Paper), preservato. Nessun conflitto
unmerged rilevato. I branch di migrazione P1/P2/P3 indicati non esistevano.
PR aperte #5/#6: CI draft e dipendenti; PR storiche #1..#4 già merged.
La base QA 3df4f82 includeva documenti locali della precedente missione:
conservati nel commit 1542dce prima di iniziare implementazioni.

Suite baseline Python 3.11 su Mac: 747 passati, 1 skip Proactor atteso,
1 warning websockets.legacy, 34,62 s; guard rete/credenziali 0/0.
Node 22.23.3, npm 10.9.9. Rust inizialmente assente da PATH; installato da
fonte ufficiale con SHA256 verificato in directory temporanea isolata,
senza cambiare profili o installazioni globali.

## Coordinamento e componenti

Letti Team Hub, direttiva migrazione e aree P1/P2/P3/P4 in Brave. La ricerca
Notion non ha trovato Agent Operating Guide né ArbitraBot; sono riferimenti
non accessibili/non reperiti, non ne viene inventato contenuto. Nessun MCP
Notion disponibile: non si aggiungono parametri instructions_version a tool
che non li supportano. Notion usato via UI, senza cambiare condivisioni.

- P1: React e Tauri in worktree dedicato dalla base e1bd306, conservando il
  lavoro legacy già committato.
- P2: FastAPI, sessione locale, quattro contesti, provider, packaging, dalla base main.
- P3: riuso motore puro e contratto versionato. Riprodotto un cap BUY troppo
  alto quando equity scende sotto capitale configurato; corretto in modo
  restrittivo, senza alzare soglie. Servizio non invia ordini.
- Coordinatore: worktree integration/local-web-desktop-20261116 da 1542dce;
  launcher cross-platform, integrazione, audit e prove.

I worktree sono distinti; nessun agente lavora simultaneamente nello stesso
checkout. Nessun ramo altrui cancellato o riscritto. Le integrazioni sono sul
ramo dedicato, mai su main.

## Contratto deciso

API /api/v1, UI stessa origine (backend serve asset React compilati), cookie
HttpOnly effimero, Host/Origin restrittivi e X-Local-Request; nessun token
esposto a JS/URL/CLI. Desktop carica la stessa UI loopback dopo handshake del
sidecar. Identità processo e socket sono verificati prima di stop. Il backend
non riusa il lifespan della console Omega che avviava un worker.

GET non invia ordini o attiva bot. Apertura conto e operazioni locali sono
POST espliciti, solo Demo/Simulazione e ledger distinti. Alpaca solo letture
Paper dopo connessione esplicita env-only. MT5 opzionale e read-only Windows;
nessun ordine MT5/Paper dall'API. Fonte sintetica non autorizza una proposta
operativa. Dati mancanti restano null/N/D, non capitale o prezzi inventati.

## Verifiche in corso

I risultati finali sono registrati a fine integrazione. La baseline non prova
la nuova applicazione. Windows 11 e conti autentici richiedono prove separate;
nessun esito Mac è attribuito a Windows. Non sono promessi profitti o sicurezza
assoluta.

## Esito integrazione verificato — candidato applicativo 85453ce

Il mandato master ha prodotto implementazione reale, non solo il piano QA.
Base main fe98839; base documentale 3df4f82; P4 conservato1542dce.
Commit originali preservati: P1 8f642f1+0598b57; P2 89a6e5b/49f5a8e/
116c92c/27a4979/1f1389b; P3 cf5910b+37afa86; launcher1cb938f e CIadfc6f7.
L'unico conflitto d'integrazione era un'append di WORKLOG: confrontati gli
stage base/ours/theirs e conservate entrambe le aggiunte in ordine cronologico.
Nessun conflitto applicativo risolto scegliendo indiscriminatamente una versione.

### COMPLETATO E VERIFICATO su macOS27.2.1 arm64 / Python3.11.18

- API locale, UI React e motore puro integrati. Bootstrap cookie HttpOnly,
  rifiuto richieste non autenticate/origini esterne, ledger Demo/Sim separati,
  backtest esistente e runtime senza worker trading.
- Riprodotto e corretto sizing BUY con equity sotto capitale configurato:
  limite più restrittivo, soglie non aumentate. Paginazione ordini Alpaca con
  overlap/deduplica e rifiuto di gruppi/cursori incompleti o ambigui.
- MT5 mock: account/denaro/quote/OHLC validati, timestampUTC e freschezza,
  dati stale/future/mancanti azzerati nel DTO. Nessun order_send.
- Frontend: quote/fonte/valuta, quattro contesti, capitale/posizioni/storico,
  grafici, proposta, backtest, connessioni/impostazioni. Corrette colonne
  direction/entry_fee, valutaMT5 e hover che conservava dati del contesto vecchio.
- Test completi: `python -m pytest -q`: **870passed,1skipped,1warning in37.58s**,
  `TEST ISOLATION: {'network': 0, 'credentials': 0}`. Skip solo WindowsProactor;
  warning websockets.legacy preesistente.
- Mirati backend/API/runtime/launcher/MT5/paginazione/strategia/Paper/contratti:
  **225passed,1warning in1.92s**, guard0/0. Un primo comando mirato aveva un
  nome file inesistente: nessun test eseguito, corretto il comando senza
  modificare o disabilitare test. Il risultato riportato è della riesecuzione.
- `python -m compileall -q app.py config src tests`: exit0, output vuoto.
  `python -m pip check`: exit0, «No broken requirements found.»
- npm lint/typecheck/build exit0; vitest **17passed/3files**; npm audit0vulnerabilità.
  Lock npm/Cargo presenti; PyInstaller6.16.0 nativo e Tauri2.12.6 pinned.
- HTTP reale sorgente e binario frozen: smokePASS (sessione/Origin/account/fill
  Demo/isolamento/200barre/NO_TRADE/backtest/shutdown). Ambiente senza chiavi,
  soli database temporanei. Non sono test con connessione broker.
- Brave reale: conto Demo10000 e fill locale, Simulation inizialmenteN/D,
  Paper scollegatoN/D senza fallback, NO_TRADE e backtest reale su dati sintetici;
  layout390px clientWidth=scrollWidth390, consoleerrori/warning[]; screenshot locale.
- Rust:1testPASS; buildrelease e bundle .app90.72MiB riusciti. Individuato con
  prova reale PID diverso del bootloaderonefile: aggiunto supervisor_pid OS
  soltanto frozen e validazione sul Child posseduto. Mai kill su PID dalla rete.
- .app Mac aperta realmente con ambiente ripulito/HOMEtemporanea: UI resa,
  navigazione e backtest sintetico (14chiuse, costi0.6543USD) verificati nella
  finestra nativa; closefinestra → exit0, processi confezionati assenti e porta
  loopback chiusa. Numeri sintetici sono fixture, non risultati di mercato.
- Scansione letterali credenziali sui file cambiati:0candidati; nessun .env,
  database/cache/log/binario generato tracciato. Controllo euristico limitato,
  non una certificazione o un CodexSecurityscan completo.

### PARZIALMENTE COMPLETATO

Applicazione browser e primo bundle Mac utilizzabili per analisi/simulazione.
AlpacaPaper/MT5 sono connettori di lettura espliciti, coperti da mock: nessuna
connessione autentica eseguita. Strategie BUY/SELL/WAIT riusano i test esistenti;
API restituisce NO_TRADE finché manca snapshot rischio completo verificato.
La migrazione non equivale alla parità di tutte le funzioni Streamlit.

### NON COMPLETATO / limiti di rilascio

- Nessun test manuale Windows11, terminaleMT5 o broker/feed autentico.
- Nessun avvio automazione, invio/cancel/panic o riconciliazione ordini dalla
  nuova UI. Il lavoro sull'esecutore nel checkout principale preesistente è
  rimasto intatto e non viene dichiarato integrato/verificato qui.
- Nessun installerWindows distribuito, firma/notarizzazione, release o deploy.
  CI nativa in preparazione non sostituisce test GUIWindows11.
- Deadline non garantita dalle letture nativeMT5 successive a initialize.
  Paginazione failclosed quando un gruppo timestamp occupa500record o non
  sono verificabili progressione/overlap; non si restituisce una lista parziale.
- Nessuno studio di redditività/OOS nuovo. Backtest sintetico non valida una strategia.
- Nessuna SBOM/licenza transitiva completa o audit di sicurezza indipendente.
  LightweightCharts Apache2 con notice/attribution conservati; nessun canone
  obbligatorio introdotto. Non cambiate protezioni GitHub o credenziali.

Guida operativa: [LOCAL_APPLICATION.md](LOCAL_APPLICATION.md). Il file elenca
comandi PowerShell, API, stati, storage, packaging e controlli riproducibili.
Gli esiti CI e la PR sullo SHA pubblicato sono aggiunti dopo la lettura del run.

### Ultimo consolidamento: metadati e conto Demo MT5

La revisione d'integrazione ha riprodotto due lacune con test rossi: attrs delle
barre persi dal DTO/consumer e mancato controllo del tipo conto MT5. Correzioni:
metadata originale conservato e mostrato (quality/calendario/contratto), svuotato
su errore; MT5 accetta solo trade_modeDemo verificato a connessione e ogni lettura,
blocca real/contest/unknown/bool/stringa senza pubblicare saldi o quote.

Dopo queste correzioni: **876passed,1skipped,1warning in34.78s**, guard0/0;
API/MT5 mirati61PASS; frontend **18PASS**, lint/typecheck/build0. Compileall0
senza output, pipcheck«No broken requirements found.», diffcheck0; smokeHTTP
sorgentePASS. Nuovo sidecar nativo ricostruito; le prove di packaging finali
sono associate a questo consolidamento, quelle870/17 sopra restano storiche.

## Inventario file del candidato

Percorsi relativi al repository; la PR conserva il diff completo.

```text
.github/workflows/windows-ci.yml
.gitignore
BACKEND_HANDOFF.md
DASHBOARD_HANDOFF.md
README.md
STRATEGY_HANDOFF.md
app.py
arresta_web.ps1
avvia_web.ps1
docs/ARCHITETTURA_APP.md
docs/DECISIONI_TECNICHE.md
docs/END_TO_END_QA_PLAN.md
docs/GUIDA_COMPLETA_PROGETTO.md
docs/LOCAL_APPLICATION.md
docs/MASTER_AUDIT.md
docs/MATRICE_TEST.md
docs/RELEASE_GATES.md
docs/REVIEW_QUALITA_E_ROADMAP.md
docs/WORKLOG.md
eslint.config.js
frontend/.gitignore
frontend/index.html
frontend/public/lightweight-charts-LICENSE.txt
frontend/public/lightweight-charts-NOTICE.txt
frontend/src/App.test.tsx
frontend/src/App.tsx
frontend/src/MarketChart.test.tsx
frontend/src/MarketChart.tsx
frontend/src/api.test.ts
frontend/src/api.ts
frontend/src/format.ts
frontend/src/main.tsx
frontend/src/styles.css
frontend/src/test-setup.ts
frontend/src/vite-env.d.ts
package-lock.json
package.json
packaging/backend/README.md
packaging/backend/entrypoint.py
packaging/backend/requirements-mt5.txt
packaging/backend/requirements.txt
scripts/__init__.py
scripts/build_backend.py
scripts/check_desktop_startup.py
scripts/check_local_service.py
scripts/start_local.py
src-tauri/.gitignore
src-tauri/Cargo.lock
src-tauri/Cargo.toml
src-tauri/binaries/.gitkeep
src-tauri/build.rs
src-tauri/icons/icon.icns
src-tauri/icons/icon.ico
src-tauri/icons/icon.png
src-tauri/icons/mark.svg
src-tauri/src/main.rs
src-tauri/src/service.rs
src-tauri/tauri.conf.json
src/api/__init__.py
src/api/local_app.py
src/broker/alpaca_client.py
src/broker/mt5_readonly.py
src/risk/trade_plan.py
src/runtime/__init__.py
src/runtime/local_service.py
src/strategy/service.py
src/ui/charts.py
src/ui/dashboard_style.py
src/utils/logging_config.py
tests/test_backend_packaging.py
tests/test_dashboard_contexts.py
tests/test_local_launcher.py
tests/test_local_runtime.py
tests/test_local_service.py
tests/test_mt5_readonly.py
tests/test_order_pagination.py
tests/test_service_logging.py
tests/test_signal_refresh.py
tests/test_strategy_risk.py
tests/test_strategy_service.py
tests/test_ui_charts.py
tsconfig.json
vite.config.ts
```

## Pubblicazione e chiusura operativa

Push riuscito dei quattro branchagents dedicati e del ramo integrazione.
PR aperta in bozza: https://github.com/foffo09/AITradingBot/pull/7, basemain,
nessun merge/approvazione/release. Candidato codice f737455dce4b3d9661962e12a4cc80288960acbf.
Il commit documentale successivo non cambia codice, dipendenze o soglie.
Check remoti, run e output duraturi sono nella [PR7/checks](https://github.com/foffo09/AITradingBot/pull/7/checks);
il rapporto finale distingue il loro SHA dai test Mac locali. Mai usare il PASS
sullo SHA precedente come se certificasse modifiche successive.

Ultimo sidecar ricostruito: smokeHTTPfrozenPASS; bundle.app ricostruito90.72MiB.
Processo desktop finale avviato in ambiente privato, poi terminato dal
coordinatore con SIGTERM al solo PID posseduto/verificato: bootloader e worker
scomparsi, nessun orfano. GUI finale non riletta perché il Mac era bloccato;
sblocco manuale richiesto, senza aggirarlo. La GUI precedente resa e il backtest
nativo restano prove effettive sul lifecycle precedente, non Windows11.

NotionP4: aggiornamento master intermedio salvato e riletto dopo reload;
nuovo mandato, architettura, deleghe senza sovrapposizioni, risultati870/13
iniziali e blocchi espliciti. Report finale dipende dallo sblocco del Mac;
se ancora indisponibile resta un blocco esterno dichiarato, non un salvataggio
inventato. Nessuna impostazione/piano a pagamento o condivisione cambiata.
Il launcher browser temporaneo è stato arrestato con identità verificata;
nessun server o automazione di prova viene lasciato in esecuzione.

Checkout principale2b2d35a con modifiche preesistenti (incluso paper_executor)
lasciato intatto. Main remoto restafe98839. Gli altri worktree non vengono
cancellati o riallineati. Guida completa e D16 ora distinguono nuovaUI e legacy.

## Verifica conclusiva dopo sblocco e prova nativa

La verifica grafica ha rilevato una regressione introdotta nel consolidamento
metadata: un keywordarg non previsto arrivava al wrapperP3. Il fallback era
failclosedNO_TRADE, ma non dimostrava il passaggio nel motore. Riprodotto con
un test rosso sul motivo/provenienza; eliminato il keywordarg, senza cambiare
il contratto pubblicoP3. SmokeHTTP ora verifica anche motivo e provenienza,
così un errore interno generico non passa come rifiuto previsto.

Finale Python: **877passed,1skipped,1warning in36.10s**, guard0/0;
API25PASS, frontend18PASS, Rust1PASS. Compilazione e diffcheck0; pipcheck senza
requisiti rotti. Sidecar ricostruito e smokeHTTPfrozen rafforzatoPASS;
Tauri release/bundle.app90.62MiB riusciti.

Un avvio nativo ha raggiunto il timeout15s; misura diretta successiva del
sidecar confezionato:8.11s. Nessuna soglia finanziaria o timeout broker cambiato.
È stato osservato anche il ripristino finestre macOS dopo gli arresti forzati
precedenti. Un errore setup propagato a Tauri causava panic nel framework:
il solo handling di build non bastava (faulttest rimasto rosso), quindi il setup
ora richiede un'uscita controllata1 senza propagare l'errore al panic interno.
`scripts/check_desktop_startup.py`: backend confezionato temporaneamente
indisponibile nel solo bundle generato → exit1, nessunpanic, ripristino filePASS.
Non modifica applicazioni installate, dati personali o credenziali.

Avvio finale tramite LaunchServices, HOMEtemporanea/credenziali assenti:
finestra nativa letta realmente, qualitàsynthetic/calendarioN/D/contrattoN/D,
propostaNO_TRADE con il motivo P3 corretto e fonte synthetic-demo.
Screenshot finale salvato localmente; chiusura dalla finestra, waitexit0,
nessun processo confezionato residuo e porta65260 chiusaPASS. Il limite di
avvio15s rimane: su avvio lento/OSdialog viene rifiutato senza trading;
non si promette assenza di ritardi o robustezza assoluta su ogni macchina.

Il blocco schermo è stato risolto dall'utente. La consegna finale Notion viene
aggiornata con SHA/PR/statiCI reali; i paragrafi precedenti sono cronologia,
non il riepilogo conclusivo. Nessun server di prova lasciato attivo.


## Nuovo mandato completion — baseline e revisione

Nuova base verificata37a3840775f8be65f5683789b8e728bf563a5c0f, branch isolato
agents/codex-completion-20261116. Fetch senza prune; PR7 OPEN/DRAFT e quattro
branch consegnati invariati. Checkout personale con modifiche pregresse intatto.
Notion Hub e areePersona1–4 letti; OperatingGuide accesso negato, nessun permesso
modificato. Progresso persistente: CODEX_MASTER_PROGRESS.md.

Difetti C01–C07 corretti o implementati offline, con regressioni in ledger/API,
MT5Process, launcher, frontend e Rust. Le revisioni iniziali indipendenti hanno
identificato timeoutIPC, racepolling, payloadidempotente e lifecycle. Revisione
finale indipendente: rifiuto definitivo bloccavaUI, timestamp malformato/fill futuro
non bloccavano reconcile; tutti riprodotti RED e corretti GREEN. Retentionappdata
reale e SIGKILL/nativehang frozenWindows restano limiti, non dichiarazioni PASS.

Verifica Mac localePython3.11.18/macOS27.2.1arm64 prima del commit:
`python -m compileall -q app.py config src tests`: exit0, nessun output.
`python -m pytest -q`: **929passed,1skipped,1warning in40.09s**;
guard **network0,credentials0**. SkipProactor specificoWindows, warningwebsockets
preesistente. Mirati ledger/offlineexecutor49PASS, contrattoAPI/reader/ledger113PASS
prima degli ultimi casi aggiuntivi. npm lint/typecheck/build exit0; frontend34PASS.
Rust3PASS, incluso cleanupfiglio che richiede3s (RED sul vecchio limite2s).
pipcheck: `No broken requirements found.` Diffcheck exit0.
PyInstaller e bundleMac90.77MiB generati, smokeHTTPsource/frozenPASS prima del
collaudoGUI conclusivo. Il successo dei test non autorizza trading automatico.

### Dipendenze, licenze e vulnerabilità

Nessuna dipendenza di runtime aggiunta o aggiornata. npmci usa lock270pacchetti;
npm audit JSON:0 advisory in tutte le severità. pip-audit in un ambiente temporaneo
separato, risoluzione requirements-dev115dipendenze: **42 advisory in Pillow12.3.0**,
fix13.0.0. Streamlit1.65.0 richiede pillow<13: l’upgrade forzato sarebbe un ambiente
incoerente. Esempi advisory PYSEC-2026-4327/4328/4326/4339/4343; questa è evidenza
scanner di dipendenza, non prova di sfruttabilità dell’app. Non ignorati o soppressi.
La UI locale non richiede upload immagini e sidecar escludeStreamlit, ma ciò non
rende sicura l’installazionelegacy né certifica un artifact privo diPillow.

Inventario metadata letto: Python115 (8UNKNOWN), npm270 (0UNKNOWN), Cargo429
(inclusi target opzionali,1UNKNOWN=progetto). Nessun LICENSE del progetto trovato;
charts5.3.0 Apache2/LICENSE+NOTICE inclusi, React19.3.1 MIT, Tauri2.12.6 MIT/Apache,
FastAPI0.162 MIT, HTTPX0.28.1 BSD3, Portalocker3.2 BSD3, pandasBSD3, numpy licenze
multiple BSD/0BSD/MIT/Zlib/CC0. PyInstaller6.16 GPL con eccezione bootloader: non
si deduce una licenza per il progetto. Crate opzionali con MPL/Unicode/LGPLalternativa
richiedono scelta/notice per gli artifact effettivamente distribuiti. Audit Rust
advisories non eseguito; inventario metadata non è SBOM/clearance legale completa.

Riprodurre audit con `npm audit --json`, `pip-audit -r requirements-dev.txt --format
json` in venv separata e `cargo metadata --locked --format-version 1`. Nessun output con dati personali committato.
Release **BLOCKED** per dipendenza vulnerabile/conflitto, licenza/notice incompleti,
Windows11GUI/firma/nativehang autentico non verificati. Nessuna release/deploy.

Notion alla ripresa: due tentativi sulla pagina Persona4 restituiscono `Debugger
unattached` pur essendo il browser presente. Nessuna scrittura dichiarata riuscita;
report completo resta nel repository per successivo salvataggio.


### Collaudo grafico e incidente di isolamento

Il bundle corrente è stato realmente aperto. Il primo avvio con HOME temporanea
ha fallito al limite15s (stderr sanitizzato di avvio). La successiva selezione
tramite controllo grafico ha riaperto una seconda istanza nella directory dati
standard: verificati statiSTOPPED→RUNNING→cicloesplicito con1proposta/0intent→
PAUSED→STOPPED e indicatoriSMA/RSI. L’app è stata chiusa e la porta51555 risulta
chiusa; nessun conto/operazione finanziaria creato. Questa prova NON certifica
isolamento desktop. È stato creato un nuovo diario demo-control nella directory
dati standard; lasciato intatto, senza leggere/cancellare database personali.
Comportamento segnalato all’utente. Non ripetere getApp dopo un timeout:
può riavviare implicitamente l’app senza l’ambiente privato del launcher.

Prova browser successiva correttamente isolata: servizio sorgente con directory
applicativa temporanea e ambiente senza credenziali, UI aperta nell’IAB. Verificati
STOPPED→startdry-run→cicloesplicito(1proposta/0intent)→STOPPED, pulsanti coerenti.
SnapshotAPI reali e grafico sintetico visibili, nessun broker collegato.
La verifica visiva ha anche individuato un messaggio ingannevole: un NO_TRADE
senza scadenza mostrava “proposta scaduta” nascondendo il motivo del gate. Riprodotto
RED nel testUI, corretto senza indebolire scadenzaBUY/SELL (frontend34PASS).
Screenshotlocale `/tmp/aitradingbot-completion-browser.png`, nessun dato personale.
Servizio chiuso exit0 e porta51630 chiusa; startbackend0.5853s, health0.0074s,
shutdown0.32s. RSS al readiness139008KiB; CPU54.7% misurata durante avvio, NON idle.
Tempo desktop-to-visible/CPUidle/UIload non strumentati: NON VERIFICATI. Bundle90.77MiB.
Startupcold15s resta gate fallito; nessuna sogliaalzata o successo inventato.


## File del candidato completion

| File | Modifica | Motivo | Prova collegata |
|---|---|---|---|
| `.github/workflows/windows-ci.yml` | CI nativa e installer temporaneo | Prove Windows separate dal Mac | run Actions della PR #8 |
| `BACKEND_HANDOFF.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `DASHBOARD_HANDOFF.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `STRATEGY_HANDOFF.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `avvia_web.ps1` | Lock, recovery e stop verificato | Nessun kill per nome/porta o retry incerto | test_local_launcher + CI wrapper PS |
| `docs/ARCHITETTURA_APP.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/CODEX_MASTER_PROGRESS.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/DECISIONI_TECNICHE.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/END_TO_END_QA_PLAN.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/LOCAL_APPLICATION.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/MASTER_AUDIT.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/MATRICE_TEST.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/RELEASE_GATES.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/REVIEW_QUALITA_E_ROADMAP.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `docs/WORKLOG.md` | Aggiorna evidenze/contratti e gate | Handoff verificabile senza attestazioni inventate | diff --check |
| `frontend/src/App.test.tsx` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `frontend/src/App.tsx` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `frontend/src/MarketChart.test.tsx` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `frontend/src/MarketChart.tsx` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `frontend/src/api.test.ts` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `frontend/src/api.ts` | Stati UI, richieste e indicatori | Identità/scadenza e dry-run esplicito | App/api/MarketChart Vitest |
| `packaging/backend/entrypoint.py` | Bootstrap frozen e bundle minimo | spawn sicuro; esclude codec/Arrow inutilizzati | test_backend_packaging + frozen smoke |
| `requirements.txt` | Streamlit1.66.1/Pillow13 compatibili | Elimina42 advisory senza forzare resolver | pipcheck, pip-audit0, suite completa |
| `scripts/build_backend.py` | Bootstrap frozen e bundle minimo | spawn sicuro; esclude codec/Arrow inutilizzati | test_backend_packaging + frozen smoke |
| `scripts/check_local_service.py` | Collega contratti API e smoke | Riusa engine/ledger e difese HTTP | test_local_service + HTTP source/frozen |
| `scripts/check_windows_installer.ps1` | CI nativa e installer temporaneo | Prove Windows separate dal Mac | run Actions della PR #8 |
| `scripts/check_windows_launchers.ps1` | Lock, recovery e stop verificato | Nessun kill per nome/porta o retry incerto | test_local_launcher + CI wrapper PS |
| `scripts/start_local.py` | Lock, recovery e stop verificato | Nessun kill per nome/porta o retry incerto | test_local_launcher + CI wrapper PS |
| `src-tauri/src/main.rs` | Monitora figlio e cleanup limitato | Crash e shutdown senza processi arbitrari | cargo test (3 casi) |
| `src-tauri/src/service.rs` | Monitora figlio e cleanup limitato | Crash e shutdown senza processi arbitrari | cargo test (3 casi) |
| `src/api/local_app.py` | Collega contratti API e smoke | Riusa engine/ledger e difese HTTP | test_local_service + HTTP source/frozen |
| `src/broker/mt5_process.py` | Isola letture native e valida timeout | Nessuna lettura nativa nel processo API | test_mt5_process/readonly |
| `src/simulation/ledger.py` | Vincola UUID al payload; P/L realizzato UTC | Una registrazione per intenzione | test_simulation_ledger/local_service |
| `src/trading/offline_executor.py` | Diario dry-run, intent e snapshot sintetici | Fail-closed dopo ambiguità/riavvio | test_offline_executor |
| `tests/test_backend_packaging.py` | Bootstrap frozen e bundle minimo | spawn sicuro; esclude codec/Arrow inutilizzati | test_backend_packaging + frozen smoke |
| `tests/test_local_launcher.py` | Lock, recovery e stop verificato | Nessun kill per nome/porta o retry incerto | test_local_launcher + CI wrapper PS |
| `tests/test_local_service.py` | Collega contratti API e smoke | Riusa engine/ledger e difese HTTP | test_local_service + HTTP source/frozen |
| `tests/test_mt5_process.py` | Isola letture native e valida timeout | Nessuna lettura nativa nel processo API | test_mt5_process/readonly |
| `tests/test_mt5_readonly.py` | Isola letture native e valida timeout | Nessuna lettura nativa nel processo API | test_mt5_process/readonly |
| `tests/test_offline_executor.py` | Diario dry-run, intent e snapshot sintetici | Fail-closed dopo ambiguità/riavvio | test_offline_executor |
| `tests/test_simulation_ledger.py` | Vincola UUID al payload; P/L realizzato UTC | Una registrazione per intenzione | test_simulation_ledger/local_service |


### Riproducibilità del builder

La prima build nella venv pulita ha riprodotto un errore reale di startup frozen:
setuptools79/pkg_resources importava backports mancante. La suite source era
verde: solo lo smoke dell’eseguibile ha trovato il problema. Aggiunto pin del
builder setuptools84.2.1 (versione già usata dalla baseline funzionante), senza
modificare ambienti condivisi. La build/smoke viene ripetuta dalla venv privata.
Lo scriptCIwrapperPS ora isola il rifiuto atteso del secondo launcher in un job
separato, verificandone fallimento, ownership invariata e health del primo.
Questo evita che stderr di un rifiuto atteso venga scambiato per errore del jobCI;
nessuna asserzione viene rimossa. Aggiunto diagnostico fase/tipo sanitizzato.


Nuovo builder pinned: smokeHTTPfrozenPASS, avvio6.8239s/health0.0039s,
RSS119984KiB/CPUidle0.496% nel campione2s/shutdown0.4038s/exit0. Campione distinto
quello5.6624s; non è garanzia di15s su tutti glihost. Nessun listener residuo.

| File aggiuntivo | Modifica | Motivo | Prova |
|---|---|---|---|
| `packaging/backend/requirements.txt` | Pin setuptools84.2.1 | Elimina crash di frozen da venvpulita | RED startup→GREENsmoke |


### Seconda CI e correzioni guidate dai log

Run43972072704 su61c68d3: suiteMac eWindowsPASS, packagingMac ewrapperWindowsFAIL.
Macfrozen termina prima della readiness; presenti hookpkg_resources da ambiente
runner globale non usati dall’applicazione. Esclusi dal runtime setuptools e
pkg_resources, mantenendo i tool nel builder; aggiunto diagnostico smoke che
pubblica solo il nome del modulo mancante, mai traceback/input privati.
Windowswrapper: startupValueError. La venvWindows usa un redirector interprete:
PID del worker diverso dal PopenChild. Il protocollo riporta anche supervisor_pid
suWindows; la pipe del figlio posseduto deve attestare esattamente il supervisor
atteso, altrimenti rifiuto. Il record conserva il PID reale per identityHTTP; non
si uccide alcun PID ricevuto da rete. TestRED→GREEN per supervisorecorretto,
supervisorediverso/boolrifiutati e combinazioniWin/Mac/source/frozen.
Conferma definitiva dei nuovi percorsi demanda al prossimo run nativo.

Carg-audit eseguito sul lock:0 vulnerabilità,2warning non soppressi:
RUSTSEC-2024-0370 proc-macro-error1.0.4 non mantenuto e RUSTSEC-2024-0429 glib0.18.5
unsounditerator (stackGTK opzionaleLinux). Non si deduce assenza di rischio dal
solo contatore0; nessun aggiornamento forzato del grafoTauri. Licenze restano gate.

Nuova prova desktop con HOMEtemporanea: processo/argomenti/data-dir attestati,
servizio privato healthy su52140, ma Macbloccato impedisce verifica grafica finale.
Arrestato solo il backend posseduto tramite identity/session/shutdown; listener
chiuso, monitor della shell richiedeuscita. Non vengono riaperti app o database
standard. StatoGUI finaleNON VERIFICATO fino a sblocco manuale.


Nuovo controllo completoMacPython3.11.18:936PASS/1skip/1warning in38.53s,
guard0/0, compileall/pipcheck/diffcheck0; HTTPsourcePASS. Il controllo frozen
ora richiede sempre identitàChild/supervisor dalla pipe posseduta, eliminando
il precedente bypass expected_pid=None per il binario.

| File aggiuntivo | Modifica | Motivo | Prova |
|---|---|---|---|
| `src/runtime/local_service.py` | SupervisorWindows in readiness | Redirectorvenv con PIDworker differente | test_local_runtime/CIwrapper |
| `tests/test_local_runtime.py` | Source/frozen eWin/Mac | Mantiene identità e restrizioni | 4combinazioni readiness |
