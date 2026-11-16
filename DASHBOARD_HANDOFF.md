# Dashboard — contratti di integrazione Persona 2

Branch: `feature/dashboard-ui`. Backend integrato con fast-forward al commit
`1a68d5bbc25f3e1b6eceb0235f9ea2fdfa033240`, senza modificare i suoi moduli.
Contratti di riferimento: [BACKEND_HANDOFF.md](BACKEND_HANDOFF.md).

## Architettura e componenti

- `app.py`: orchestrazione Streamlit e fragment indipendenti di 15 secondi
  per conto, quote/grafico e segnale; nessun nuovo percorso di invio.
- `src/ui/workspaces.py`: percorsi isolati e verifica alias tra contesti.
- `src/ui/dashboard_metrics.py`: trasformazioni pure per metriche e quote,
  senza mutare risposte broker o concedere permessi.
- `src/ui/dashboard_panels.py` e `dashboard_style.py`: schede e tema.
- `src/ui/charts.py`: figure Plotly, volume, SMA/RSI, marker e navigazione.
- Backend, strategie, rischio e motore preesistenti restano invariati.

## Presentazione compatta

Il tema usa una palette scura ardesia con accenti viola, spaziature ridotte e
grafico OHLC più compatto (420 px, 500 px con RSI). Gli avvisi restano visibili
e i valori assenti restano N/D: la UI non li trasforma in zeri. Non vengono
aggiunti bot, profili o azioni di creazione non supportati dal backend.

## Contesti e persistenza

Il selettore **Contesto** offre tre ambienti. Cambiare contesto ferma
l'automazione della sessione e cancella snapshot, selezione, quote, risultati
e autorizzazioni della sessione precedente. Non annulla ordini già accettati.

| Ambiente | Dati e capitale | Percorso |
| --- | --- | --- |
| Demo | Serie sintetica esplicitamente selezionata, conto virtuale proprio | `AI_TRADINGBOT_DEMO_DB_PATH` |
| Simulazione | Ledger SQLite e storico propri; serie sintetica esplicita per la prova offline | `AI_TRADINGBOT_SIMULATION_DB_PATH` |
| Alpaca Paper | Solo conto, posizioni e ordini broker; nessun conto locale inizializzato | `AI_TRADINGBOT_PAPER_DB_PATH` |

Demo e Simulazione rimuovono le credenziali dalle impostazioni runtime e non
costruiscono client SDK Alpaca. Deselezionare la serie sintetica non attiva
fallback: senza un provider reale disponibile appare un errore. Paper richiede
configurazione Paper valida e impedisce la selezione della serie sintetica.

Usare percorsi assoluti, fuori dal DB personale. Alias, symlink risolti e hard
link fra contesti sono rifiutati prima di creare risorse. Se manca il percorso
Simulazione, viene usato `workspace-simulation.sqlite3` accanto al DB Demo;
su Windows è disponibile anche la cartella dedicata in LOCALAPPDATA. I database
esistenti non vengono migrati o cancellati. Nessun capitale di backtest viene
trasferito al ledger o al conto Paper.

## Contratto con backend e strategie (Persona 1 / Persona 3)

- Le API backend restano invariate. Le risposte monetarie SDK vengono convertite
  solo per la presentazione; valori mancanti/non finiti sono N/D, non zero.
- OHLCV reali richiedono `attrs.quality=real` e `attrs.interval` uguale alla
  selezione. La UI conserva `source`, `fetched_at` e metadati del calendario;
  il refresh non rimpiazza l'ora di acquisizione con l'ora di rendering.
- Bid/ask devono essere finiti, positivi e ordinati. Solo le fonti quote
  `Alpaca IEX latest quote` e `Alpaca Crypto latest quote` sono riconosciute.
  Timestamp con timezone, convertiti UTC, età fra 0 e 120 secondi.
- Senza quote valida: bid/ask/spread N/D; il close storico eventualmente
  disponibile è denominato **Ultimo close storico**, mai prezzo corrente.
  La variazione mostrata confronta le ultime due chiusure, non il rendimento
  giornaliero del conto. Prezzi/importi in USD, esposizione/drawdown in %.
- La provenienza sintetica è sempre esplicita. Il grafico può mostrare barre
  in formazione. Il segnale reale usa le barre ammesse da
  `select_completed_bars`; se il gate fallisce diventa **ANALISI STORICA — NON
  OPERATIVA**. Nessun segnale costituisce autorizzazione a inviare un ordine.
- Lo snapshot conto scade dopo 45 secondi: timestamp mancante, futuro o scaduto
  elimina i valori precedenti, la verifica Paper e l'attivazione di sessione.
  Errori broker restano visibili; non sostituiamo il saldo con quello locale.
- Capitale iniziale, P/L cumulativo, commissioni e drawdown Paper sono N/D
  senza storico contabile broker verificato. Il P/L giornaliero Paper confronta
  equity e last_equity; quello locale è il realizzato UTC del ledger.
- I limiti di rischio e il coordinatore esistenti restano obbligatori.
  Le nuove schede rischio sono informative e non concedono permessi.

## Grafici e operazioni

Candlestick, volume, SMA e RSI opzionale; selettori di intervallo, zoom,
pan, reset e tooltip sincronizzato. Il range visuale è conservato per
strumento/intervallo durante il refresh. Posizioni, ordini pending, fill
confermati e storico locale restano distinti. Commissioni broker non fornite
sono N/D. Il backend REST limita gli ordini a 500 e non fornisce uno storico
contabile completo: non presentare questi elenchi come riconciliazione esaustiva.

## Verifica e limiti

La scheda segnale rilegge frame e calendario ogni 15 secondi, anche senza
un rerun completo. Quando cambia lo stato/verifica o il contenuto Paper
(account, posizioni, ordini), oppure quote/storico modificano i dati visibili,
viene richiesto un singolo rerun dell'app per riallineare le superfici esterne
ai fragment. Un aggiornamento del solo timestamp Paper non provoca un rerun:
il fragment mostra comunque il nuovo timestamp. Flag monouso fanno saltare la
lettura del fragment durante il rerun e impediscono richieste duplicate; i flag
sono limitati ai fragment attivi e rimossi al cambio contesto. La frequenza
dichiarata resta 15 secondi.

Il rerun non rende atomiche le fonti: account, storico e quote sono acquisiti
separatamente e possono avere timestamp diversi. Ogni pannello continua a
mostrare la propria fonte/freschezza; dopo errori o dati scaduti/futuri i valori
non verificati vengono invalidati, non ri-etichettati come correnti. Una
regressione invoca ripetutamente i corpi reali dei fragment; non verifica il
timer nel browser.

I test UI usano Streamlit AppTest, broker finti e DB temporanei; i grafici
verificano oggetti Plotly e configurazione di navigazione. I risultati puntuali
sono nel WORKLOG. Nessun server, ordine, automazione o credenziale autentica è
stato utilizzato. Windows e resa visuale/interazioni nel browser non sono stati
eseguiti per questa consegna. L'automazione non viene certificata sicura dai test.

Prova manuale successiva: avviare il launcher Demo, inizializzare due capitali
diversi nei due contesti offline, registrare una sola operazione locale e
controllare l'isolamento; controllare grafico/zoom su desktop e schermo stretto.
Per Paper usare una prova separata autorizzata, senza avviare l'automazione.


## Storico, backtest e idoneità operativa

1. **Storico**: barre conservate per analisi, con timestamp e provenienza. Un
   errore di refresh non le rende aggiornate e non rinnova fetched_at.
2. **Backtest**: elaborazione storica nel componente esistente, con capitale
   teorico distinto. Dati vecchi possono essere utili per questo uso; un
   risultato di backtest non attesta freschezza, chiusura o idoneità operativa.
3. **Dati operativi verificati**: nella sola scheda segnale reale,
   `operational_data=True` richiede barre ammesse da `select_completed_bars`,
   fonte backend coerente con il mercato e colonna data_quality (se presente),
   più una quota corrente riconosciuta. Non autorizza un ordine: account,
   rischio, coordinatore e verifica finale restano responsabilità del motore.

La UI non implementa un calendario alternativo né modifica le soglie del gate.
Usa il gate condiviso con require_market_open=True per il segnale; una chiamata
con False serve soltanto a mostrare la chiusura temporale a fini analitici.
Quote mancanti/scadute/future, fonte storica assente/contraddittoria, flag
sintetici o errori del gate producono **ANALISI STORICA — NON OPERATIVA**.
Metadati di origine, calendario e sessione discordanti nel refresh sono
rifiutati: il vecchio storico resta esplicito e il nuovo dato non è rietichettato.

La quota conserva timestamp, fonte e tutti i campi aggiuntivi ricevuti. Il
midpoint numerico è normalizzato per la presentazione; la verifica non modifica
la risposta originale. La freschezza viene rivalutata durante ogni rendering
periodico del segnale, non solo quando la quota arriva.

## Indicazioni a Persona 3

Integrare questo branch in un branch di prova secondo il flusso del coordinatore;
non copiare file o riapplicare separatamente i commit backend già antenati.
Conservare gli attrs del DataFrame e la relazione simbolo/intervallo/fonte.
Usare il medesimo gate sulle barre usate dal segnale; SELECTED o una scheda
con dati idonei restano proposte analitiche. Un errore del gate/quote è
indisponibilità/NO_TRADE, senza fallback sintetico o sblocco del coordinatore.
Rivalidare sempre prima dell'invio; nessun retry dopo conferma ambigua.
Eseguire suite offline su Windows prima dell'integrazione finale e poi una
prova manuale separata dei contesti e dei grafici, senza attivare automazioni.

## Comandi di verifica (ambiente attivo, Mac o PowerShell)

```text
python -m compileall -q app.py config src tests
python -m pytest -q tests/test_dashboard_validation.py tests/test_dashboard_contexts.py tests/test_dashboard_metrics.py tests/test_signal_refresh.py tests/test_ui_charts.py tests/test_ui_workspaces.py tests/test_ui_presentation.py
python -m pytest -q tests/test_backend_contract.py tests/test_backend_integration.py tests/test_broker.py tests/test_config.py tests/test_fx_rates.py tests/test_bar_timing.py
python -m pytest -q tests/test_paper_safety.py tests/test_paper_coordinator.py tests/test_native_store.py tests/test_test_isolation.py
python -m pytest -q
python -m pip check
git diff --check
```

Il conftest protegge i test da rete e credenziali personali. I test della scheda
usano anche il gate backend reale con barre crypto e quote sintetiche controllate.
AppTest verifica che timestamp, fonte e metadati aggiuntivi delle quote non
vadano persi e che un refresh contraddittorio non aggiorni lo storico.
Risultati osservati e limiti di piattaforma nel [WORKLOG](docs/WORKLOG.md).

Verifica di questa revisione (macOS, Python 3.12.14): suite completa 601 passati,
1 saltato, zero falliti; dashboard 120 passati, backend 172 passati, sicurezza
39 passati e 1 saltato. Compilazione, pip check e diff-check riusciti. Tutti i
gruppi con guard rete/credenziali a zero; un warning websockets.legacy.
Lo skip riguarda Windows Proactor sul Mac. Windows e broker autentico non
verificati; nessun ordine, server o automazione attivati.

# Migrazione React / Tauri 2 — 16 novembre 2026

Branch `agents/p1-react-tauri-migration-20261116`, base `e1bd306`.
Questa aggiunta conserva integralmente dashboard e refresh Streamlit storici:
nessuna modifica ad `app.py`, backend Python o strategie.

## Frontend effettivo

Un'unica applicazione React/TypeScript/Vite in `frontend/`, usata dal browser
e dal WebView Tauri. Pagine: panoramica, mercati, proposte analitiche, portafoglio,
storico, backtesting, connessioni e impostazioni. Sidebar responsive, palette
scura/chiara e densità salvate localmente; nessuna credenziale nello storage.
Non ci sono fixture, conti o grafici di fallback nel codice applicativo.
Demo/Simulazione dichiarano dati sintetici e capitale virtuale; Paper e MT5
richiedono dati reali o mostrano indisponibilità. I numeri assenti restano N/D.
L'automazione è ferma e la UI non espone endpoint di avvio o submit broker.

Lightweight Charts 5.3.0 (Apache 2.0) mostra candlestick e volume in due pannelli,
crosshair, intervalli, zoom, trascinamento e adattamento. Il range viene conservato
per contesto/strumento/intervallo durante il polling. Fonte, acquisizione, ultimo
close storico e quota bid/ask restano distinti. Licenza e NOTICE della release
sono in `frontend/public/`; il logo/link TradingView e l'attribuzione sono visibili.
Fonte licenza: https://github.com/tradingview/lightweight-charts/tree/v5.3.0.

## Contratto HTTP concordato con P2

Base relativa `/api/v1`; fetch `credentials: include` e `X-Local-Request: 1`
su tutte le richieste, inclusa GET `/session`. Sessione solo tramite cookie
HttpOnly: il frontend non riceve, legge o conserva token. Ogni POST JSON usa
Content-Type application/json; errori `{detail: string}` sono mostrati senza
trasformarli in successo. Risposte/versioni non riconosciute sono rifiutate.

- GET `/session`, `/state?context=...`, `/instruments`.
  Instruments: `{api_version:'1', instruments:[{symbol,name}]}`.
- GET `/market?context=...&symbol=...&interval=...`: barre epoch seconds,
  fonte, as_of e quota nullable. Contesto/simbolo/intervallo discordanti,
  barre duplicate/non ordinate o OHLCV incoerenti sono rifiutati.
- GET `/proposal?...`: contratto P3 direction BUY/SELL/WAIT e validation_state
  PAPER_PROPOSAL/NO_TRADE; livelli, rischio/rendimento, quantità, ID, fonte,
  istanti ed expiry sono solo proposta. La scadenza viene rivalutata ogni secondo.
- POST `/local-account` `{context, initial_cash}` crea solo il ledger fittizio,
  senza reset; POST `/local-trades` `{context,symbol,side,quantity}` è esposto
  solo in Demo/Simulazione. Nessun ledger locale viene inizializzato implicitamente.
- POST `/backtest` `{context,symbol,short_window,long_window}` usa il motore;
  risultato `{api_version,context,symbol,source,metrics,trades,equity:[{time,value}]}`.
  Metriche `return_pct`, `max_drawdown_pct`, `total_trades`,
  `total_transaction_costs` e curva equity arrivano dal backend.
- POST `/connections/paper` e `/connections/mt5`, senza body: sola verifica
  del connettore configurato esternamente. Nessun modulo password/chiavi.

Le tabelle accettano campi SDK e ledger concordati: posizioni qty/quantity,
avg_entry_price/average_entry, current_price/market_price. Il ledger non fornisce
P/L di posizione o valore di mercato: restano N/D. Fee ingresso/uscita sono
colonne distinte `entry_fee_alloc`, `exit_fee`; non viene inventato un totale.

Refresh ogni 15 secondi, timeout HTTP 12 secondi. Cambio contesto, strumento o
intervallo invalida subito i pannelli precedenti e annulla le richieste in volo.
Errori di snapshot, mercato, proposta e bootstrap sessione rimuovono i rispettivi
valori precedenti. L'ora dell'ultimo tentativo UI non viene presentata come ora
di acquisizione del mercato o del conto.

## Browser e sviluppo

Node >=22.12, npm >=10. Dipendenze dirette fissate e lockfile versionato.
`npm ci`; `npm run dev` espone solo `127.0.0.1:5173`; backend locale di sviluppo
su `127.0.0.1:8765`. Il proxy cambia Host e riscrive Origin solo se corrisponde
esattamente all'origine Vite locale, mantenendo gli altri Origin per il rifiuto
backend. Per produzione `npm run build` genera `frontend/dist`, servita dal
backend con `--ui-dir <percorso assoluto frontend/dist>`: API e cookie sono
sullo stesso origin. Non usare un server statico separato per la produzione.

## Shell desktop e pacchetto

`src-tauri/` contiene Tauri 2.12.6/tauri-build 2.7.5, Cargo.lock e icone generate
dalla CLI ufficiale da SVG locale. Rust minimo dichiarato 1.90, coerente con le
dipendenze risolte. Non è necessario JavaScript Tauri o un plugin shell.
Capabilities vuote, nessun comando IPC e navigazione limitata al solo origin
loopback del backend posseduto. Non sono concessi shell arbitraria, filesystem
o comandi esterni alla UI.

Il bundler attende `src-tauri/binaries/aitradingbot-service-<target-triple>`
(`.exe` Windows), prodotto reale P2 e ignorato da Git. Il binario installato viene
risolto accanto all'eseguibile dell'app; in sviluppo dalla directory binaries.
Avvio con `--port 0 --ui-dir <resources/ui> --data-dir <app_data_dir>/local-service`.
Il bundle mappa `frontend/dist/` in `resources/ui/`; in debug usa frontend/dist.

Prima riga stdout JSON `{port,pid,instance_id}` entro 15 secondi e massimo 4 KiB:
porta non zero, PID uguale al processo figlio e instance_id non vuoto obbligatori.
Solo dopo questo handshake viene aperto il WebView su http://127.0.0.1:porta.
Errore/timeout interrompe solo il figlio posseduto; nessun tentativo di riusare
processi esistenti. Chiusura finestra/uscita app scrive `shutdown\n` su stdin,
attende fino a 2 secondi e, se necessario, termina esclusivamente il child handle.
Lo stdout successivo viene drenato; stderr non viene esposto nella UI.

`npm run desktop` e `npm run desktop:build` richiedono il sidecar reale per il
target e i prerequisiti OS Tauri. Non sono launcher Python alternativi. Il parent
rigenera il sidecar dopo l'integrazione finale P2/P3 prima del bundle distribuibile.

## Verifiche e limiti di questa consegna

I test client/componenti usano fetch controllato e fixture esclusivamente nei
test. Coprono cookie/header, errori, HTML/versioni sconosciute, N/D, barre,
isolamento contesti, backtest reale via API, assenza invio broker e invalidazione
valori dopo errori di refresh/sessione. I test del canvas sono sostituiti da un
componente di test: interazione reale candlestick e resa visuale richiedono la
prova browser integrata del coordinatore. Nessun broker, ordine, automazione o
credenziale reale è stato usato qui.

Rust viene verificato su macOS arm64 con toolchain ufficiale isolata del parent,
non installata globalmente. Il sidecar reale P2 è copiato solo nell'output ignorato
per compilare la shell; cargo test non avvia backend o conto. Il test Rust verifica
il rifiuto di PID diversi, porta zero/fuori range e handshake malformati.
Il primo pin Tauri precedente ha mostrato incompatibilità interna con i transitive:
risolta fissando Tauri/build correnti e Cargo.lock. Il primo check del progetto ha
inoltre rilevato sidecar/icona mancanti: ora forniti reali senza stub applicativi.

Per riprodurre: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`,
`npm run build`, `cargo fmt --manifest-path src-tauri/Cargo.toml --check`,
`cargo test --manifest-path src-tauri/Cargo.toml`,
`cargo check --manifest-path src-tauri/Cargo.toml`, `git diff --check`.
L'override minimatch 11.0.1 riguarda solo la dipendenza di lint e rimuove
l'advisory npm transitive senza alterare il runtime. Risultati puntuali finali
sono nella consegna del commit al coordinatore. Windows/WebView2, installazione
firmata, bundle distribuibile e avvio desktop richiedono le prove del parent;
non sono attestati da unit test o cargo check.

Esito osservato macOS arm64, Node 22.23.3/npm 10.9.9, Rust 1.100.0:
`npm ci`, lint, typecheck e build riusciti; Vitest **13 passati, 0 falliti**;
`npm audit` e audit runtime **0 vulnerabilità**; cargo test **1 passato, 0 falliti**;
cargo check, rustfmt check e diff-check riusciti. Rustfmt è stato aggiunto solo
alla toolchain temporanea isolata dopo il primo tentativo che lo segnalava assente.
Nessun test Python rieseguito in questa worktree: il perimetro non tocca Python;
la suite integrale resta al coordinatore nell'integrazione finale.

## Correzioni di integrazione osservate — 16 novembre 2026

La revisione del contratto reale ha rilevato e corretto mapping incompleti:
lo storico usa `direction` come alternativa a `side`; il backtest fornisce
`entry_fee`, mentre il ledger fornisce `entry_fee_alloc`. Entrambi ora sono
mostrati senza ricostruire costi o fill. Il backtest resta giornaliero come il
backend: il selettore intervallo è rimosso da quella pagina e la frequenza è
esplicita. Finestre ammesse allineate all'API: breve 1–198, lunga 2–199.

I valori conto usano `account.currency`; un conto MT5 EUR non è etichettato
USD. Le posizioni MT5 mostrano volume in lotti, prezzo di apertura/corrente e
profit forniti dal terminale. Gli ordini mostrano campi terminale disponibili,
volume iniziale/residuo e codici tipo/stato espliciti, senza dedurre quantità
eseguite. Per prezzi/backtest MT5 la valuta strumento non attestata resta
`valuta strumento N/D`; il volume del feed MT5 implementato è dichiarato in tick.
Le posizioni Demo non espongono valore/P&L per singola posizione: rimangono N/D,
senza attribuire il totale del conto a una riga.

Il crosshair conserva solo identità del contesto e timestamp; i valori OHLC
vengono riletti dalle barre correnti. Barre vuote, errori e cambio contesto non
lasciano più un valore del vecchio hover visibile; il refresh di una barra ne
aggiorna anche i valori nel riepilogo OHLC.

La prova nativa del coordinatore ha riprodotto la differenza PID del bootloader
PyInstaller onefile e del worker Python. L'handshake ora ammette il PID diretto
oppure `supervisor_pid` uguale al Child posseduto, sempre con worker PID positivo.
Il backend dichiara supervisor_pid soltanto nel pacchetto frozen; resta opzionale
per l'avvio script. Nessun PID ricevuto viene usato per terminare processi:
shutdown e kill restano esclusivamente sul Child handle originariamente avviato.

Regressioni RED/GREEN osservate per mapping/valuta, intervallo, hover e supervisor.
Verifiche finali di questa correzione: lint, typecheck, build riusciti; Vitest
**17 passati, 0 falliti**; cargo test **1 passato, 0 falliti**, cargo check riuscito.
La prova nativa completa del nuovo handshake e il feed MT5 autentico rimangono
separati: il primo è in corso al coordinatore, il secondo richiede Windows.

### Metadati barre preservati nell'integrazione

Market.metadata mantiene gli attrs originali restituiti dall'API; il parser
accetta assenza come oggetto vuoto per compatibilità, rifiuta array/valori
malformati e non ricostruisce calendari. Il grafico mostra quality, calendario
e contratto barre disponibili; N/D se assenti. Test di regressione API Python
e consumer TypeScript riprodotti rossi e poi verdi. MT5 è ora limitato a conti
Demo verificati oltre che read-only; errore esplicito senza dati vecchi.
