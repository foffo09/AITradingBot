# Applicazione locale React / FastAPI / Tauri

Questa interfaccia si aggiunge a Streamlit, che resta disponibile come legacy.
Non è una release e non introduce invii di ordini al broker.

## Primo avvio Windows 11 / PowerShell

Dalla radice del checkout del branch `agents/codex-completion-20261116`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\avvia_web.ps1 -Build
```

Servono Python 3.11 e Node >=22.12/npm >=10. Il launcher verifica ambiente,
asset e porta. `-Build` installa dal lock npm e compila la UI; per gli avvii
successivi basta `./avvia_web.ps1`. Aprire l'URL `http://127.0.0.1:<porta>/`
stampato dal launcher: la porta è assegnata dal sistema, non pubblica.
Non utilizzare una vecchia URL salvata come se fosse sempre valida.

Arrestare con Ctrl+C nella finestra di avvio, oppure in un'altra PowerShell:

```powershell
.\arresta_web.ps1
```

Il file di controllo contiene solo PID/porta/identità, nessuna credenziale.
L'arresto verifica l'identità corrente e la sessione prima di richiederlo;
non termina processi trovati soltanto in base alla porta. Un record rimasto
dopo un crash non viene sovrascritto implicitamente. `./avvia_web.ps1 -RecoverStale`
(o `python -m scripts.start_local --recover-stale`) recupera solo un record valido
quando il PID non esiste e la porta rifiuta la connessione. Record corrotto, timeout,
PID esistente o altra identità restano bloccati; nessun processo arbitrario viene ucciso.
Un lock OS esclude due launcher simultanei. Arresto attende la chiusura del listener.
I database non vengono eliminati o azzerati dagli script.

Su macOS/Linux, dopo aver preparato Python e installato i requisiti:

```sh
npm ci
npm run build
python -m scripts.start_local
# altra finestra, stesso ambiente:
python -m scripts.start_local --stop
```

L'endpoint `/api/v1/health` restituisce `status: ready`; non prova che un broker
sia connesso. Impostazioni e Connessioni mostrano gli stati effettivi.
Non avviare `main.py` per questa UI: è la console legacy con un diverso lifecycle.

## Dati e funzionalità effettive

- Demo e Simulazione: account virtuali creati con un POST esplicito; prezzi
  sintetici dichiarati, ledger SQLite separati, acquisto/vendita locale tramite
  il ledger e i controlli di rischio esistenti. Nessun broker. Un conto esistente
  non viene azzerato da «Crea conto». Le fee e le posizioni sono persistenti.
- Alpaca Paper: connessione esplicita e letture account/ordini/posizioni/mercato;
  solo endpoint Paper autorizzato. Chiavi dall'ambiente del processo, mai da
  campi React, URL o file committati. Nessun fallback Demo se mancano.
- MT5: adattatore opzionale Windows, sola lettura; terminale/account devono
  essere disponibili sul PC. macOS dichiara unsupported. Installazione opzionale:
  `python -m pip install -r packaging/backend/requirements-mt5.txt` su Windows.
  L’SDK resta in un processo spawn posseduto. Ogni scambio completo ha deadline
  5s, anche se send/recv o lettura nativa si bloccano; errore/crash invalida i dati
  e richiede riconnessione esplicita. Cleanup ordinario limitato al figlio posseduto.
  SIGKILL del padre e assenza di orfani frozen Windows durante native hang restano
  NON VERIFICATI; non si termina il terminale MT5 dell’utente. La CI standard
  non include l’SDK opzionale MT5: provider assente viene dichiarato indisponibile.
- Mercati: candlestick/volume, zoom e intervalli, fonte e timestamp. Le barre
  storiche non sono una quota corrente. Le quote mancanti/scadute non autorizzano
  segnali. Valuta MT5 sconosciuta resta N/D, volume MT5 espresso in tick/lotti
  secondo il tipo di dato, senza convertirlo arbitrariamente.
- Strategie: il wrapper puro riusa gate, indicatori, rischio e DTO esistenti.
  Demo/Simulazione non producono proposte operative; nell'API Paper manca ancora
  lo snapshot rischio completo verificato (peak/counter/ledger), quindi NO_TRADE.
  BUY/SELL e livelli sono testati con fixture controllate nel motore, non
  dichiarati operativi sul conto reale Paper.
- Backtest: esegue il motore esistente, barre giornaliere, costi separati,
  curva equity e operazioni; non modifica conti. Il dataset Demo è sintetico;
  il suo rendimento non è una misura della redditività di mercato.
- Automazione: parte STOPPED. Start arma unicamente il dry-run locale; ogni
  ciclo analitico è richiesto esplicitamente, senza scheduler e senza operazioni
  sul capitale. Pause/Stop rispettano gli stati. Il diario di controllo separato
  conserva comandi/intent/eventi, non replica il ledger. Un riavvio inatteso o
  snapshot ambiguo impone RECOVERY_REQUIRED: Stop non cancella il blocco.
  Il protocollo di riconciliazione Python è collaudato con adattatori sintetici,
  senza endpoint HTTP di importazione snapshot o sblocco. Non è riconciliazione
  autentica Alpaca. Demo/Simulazione restano NO_TRADE per il gate operativo.

Contabilità locale browser: `%LOCALAPPDATA%/AITradingBot/local-service` su Windows,
`~/Library/Application Support/AITradingBot/local-service` su Mac. Desktop usa
la directory applicativa Tauri distinta `it.aitradingbot.desktop/local-service`.
Browser e desktop condividono UI/API, ma non condividono automaticamente il
capitale: è una separazione intenzionale, non una sincronizzazione contabile.

## Contratti e sicurezza

API v1 in `src/api/local_app.py`; consumatore in `frontend/src/api.ts`.
Gli input POST sono Pydantic con campi extra proibiti e numeri finiti positivi.
Contesti ammessi: demo, simulation, paper, mt5. Errori input 422, assenza sessione
401, origine vietata403, operazione locale/rischio/dati indisponibili409.
I messaggi di errore non ripetono input, credenziali o traceback.
`POST /local-trades` richiede `idempotency_key` UUID: tutti i chiamanti devono
riutilizzarla con lo stesso contesto/simbolo/lato/quantità dopo un esito incerto.
Il ledger verifica il payload nella stessa transazione delle scritture. Un 409
con header `X-Request-Outcome: rejected` prova il rifiuto prima del commit e libera
il form; timeout, 5xx o 409 senza tale header mantengono la richiesta incerta.
La UI conserva chiave/payload in localStorage fino a conferma: una porta diversa
cambia origine e storage. Dopo un riavvio controllare lo storico prima di creare
una nuova richiesta; non esiste un retry automatico con nuova chiave.
`POST /automation` accetta solo context demo/simulation, command start/pause/stop/cycle,
request_id UUID e restituisce State completo. GET non avvia cicli.
Indicatori SMA10/30, EMA9/21/50 e RSI14 derivano dalle strategie Python esistenti,
con metodo/unità/parametri e null durante warm-up. Nessuna formula JS duplicata.
Il P/L giornaliero esposto è soltanto il realizzato UTC dai closes; totale
giornaliero non ricostruibile resta N/D. Backtest è SMA su singolo campione 1Day,
con intervallo/date/parametri espliciti: out-of-sample non eseguito.

La stessa origine serve asset e API su127.0.0.1. Bootstrap `/api/v1/session`,
cookie HttpOnly/SameSiteStrict effimero; Origin/Host e X-Local-Request controllati.
Non è una barriera contro malware già in esecuzione con l'identità dell'utente.
Le API GET non inviano ordini né creano capitale. Dati mancanti null/N/D,
nessuna cache di vecchie equity/proposte dopo una disconnessione.
Handoff dettagliati: BACKEND_HANDOFF.md, DASHBOARD_HANDOFF.md, STRATEGY_HANDOFF.md.

## Build desktop nativa (sviluppatori)

Servono Rust stable >=1.90 e i prerequisiti Tauri della piattaforma
(Windows: strumenti C++ MSVC e WebView2). Build sul sistema di destinazione,
non cross-compilazione di PyInstaller:

```powershell
.\.venv\Scripts\python.exe -m pip install -r packaging/backend/requirements.txt
npm ci
npm run build
.\.venv\Scripts\python.exe scripts/build_backend.py
Copy-Item dist/backend/aitradingbot-service-*.exe src-tauri/binaries/
npm run desktop:build -- --no-bundle
```

Mac: copiare `dist/backend/aitradingbot-service-aarch64-apple-darwin` in
`src-tauri/binaries/`, quindi `npm run desktop:build -- --bundles app`.
La shell possiede il sidecar e il suo stdin. Handshake con port/PID/instance_id,
più supervisor_pid OS nel binario onefile, perché il bootloader ha un processo
Python figlio. Non si termina un PID arbitrario ricevuto dalla rete.
Chiusura finestra → shutdown stdin → attesa massima20s per due letture native5s
più close5s/cleanup → eventuale kill del solo Child posseduto. Il monitor chiude
la shell con exit1 se il backend muore; non riavvia automazioni. Il limite di
avvio15s resta invariato.
Bundle locale non firmato/notarizzato per distribuzione; nessuna release pubblicata.

## Verifica riproducibile senza broker

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py config src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
npm run lint
npm run typecheck
npm test
npm run build
.\.venv\Scripts\python.exe -m scripts.check_local_service
# dopo build sidecar:
.\.venv\Scripts\python.exe -m scripts.check_local_service --binary dist/backend/aitradingbot-service-x86_64-pc-windows-msvc.exe
cargo test --locked --manifest-path src-tauri/Cargo.toml
git diff --check
```

Lo smoke HTTP è separato da pytest: usa davvero solo loopback, ambiente privato
senza chiavi e database temporanei sintetici; controlla sessione, rifiuto Origin,
fill Demo, separazione Simulation/Paper, NO_TRADE, backtest e shutdown. Non apre
connessioni esterne. La suite pytest mantiene guard rete/credenziali0/0.

Checklist manuale Windows11 ancora richiesta: avvio/stop PowerShell, apertura UI,
creazione conto Demo, fill locale, Simulazione inizialmente N/D, Paper scollegato
N/D, backtest giornaliero, finestra ridimensionata, chiusura desktop e assenza
sidecar orfano. Non premere connessioni autentiche durante questa prova.
Windows Server CI non sostituisce questa prova GUI Windows11.

MT5 richiede anche un conto terminale **Demo verificato**: real/contest/tipo
mancante sono rifiutati a ogni lettura. Non cambiare o collegare un conto reale
per aggirare questo blocco. L'API conserva gli attrs originali delle barre nel
campo `metadata`; la UI mostra qualità, calendario e contratto senza inferirli.

Verifica nativa Mac aggiuntiva, solo sul bundle generato:
`python -m scripts.check_desktop_startup`. Simula sidecar assente, verifica
uscita controllata1 senzapanic e ripristina il file. Lo smokeHTTP controlla anche
motivo/provenienza della proposta, per distinguere NO_TRADE previsto da errore.
Avvio desktop limitato a15s: dialoghiOS/avvio lento possono impedirlo; chiudere
un eventuale ripristino finestre di macOS prima di riprovare. Il fallimento non
abilita esecuzione né dati di ripiego. Nessuna provaWindowsGUI è implicita.

## Installer Windows e blocker di distribuzione

CI costruisce NSIS non firmato, installa in percorso temporaneo con spazi,
prova sidecar e UI installati, disinstalla. WebView2 già presente nel runner;
nessun download/installazione WebView2 nella prova. La sentinella esterna prova
solo che una directory distinta non è stata rimossa: non certifica retention
appdata reale Tauri o aggiornamento di un’installazione personale. Nessun artifact
pubblicato. Windows Server CI e Windows11 GUI sono prove distinte.

L’audit iniziale aveva segnalato42 advisory in Pillow12.3.0, incompatibile con
il fix13 usando Streamlit1.65. Risolto con aggiornamento mirato Streamlit1.66.1
(`pillow<14`) e pin Pillow13.0.0: resolver/pipcheck coerenti, pip-audit ripetuto0.
Non viene forzata alcuna incompatibilità. Il sidecar esclude PIL e pyarrow,
non usati dai percorsi JSON/OHLC: archivio e smoke frozen verificati. Dopo questa
riduzione l’avvio misurato è5.6624s rispetto a15.229s del bundle precedente;
health0.0079s, shutdown0.2602s, RSS121168KiB, CPUidle0% nel campione2s.
Questa singola misura non garantisce cold start sotto15s su ogni macchina.

Release ancora BLOCCATA: licenza progetto/notice complete assenti, Windows11GUI,
retentionappdata/upgrade reali, firma e cleanup frozenWindows durante nativehang
non verificati. npm audit e pip-audit0; cargo-audit:0 vulnerabilità e2warning (proc-macro-error non mantenuto,
glib iterator unsound nello stack opzionaleLinux), da valutare prima della release.
Non distribuire prima di risolvere i gate. Nessun artifact o release pubblicato.


Verifica17novembre: NSISunsigned install/smoke/uninstall e wrapperPowerShellPASS
suWindowsServer2025CI (run43973548981/daa5b86); GUIlocaleMac privataPASS, bundle51.43MiB.
Non sostituisce Windows11GUI. Per includere MT5, installare l’SDKopzionale **prima**
della build Windows; installarlo in un Python esterno non modifica un bundle già
confezionato. Consenso/proveautentiche e verifica dei terminiSDK restano separati.
