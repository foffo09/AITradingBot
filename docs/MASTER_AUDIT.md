# Audit e integrazione applicazione locale — 16 novembre 2026

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
