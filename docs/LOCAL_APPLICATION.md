# Applicazione locale React / FastAPI / Tauri

Questa interfaccia si aggiunge a Streamlit, che resta disponibile come legacy.
Non è una release e non introduce invii di ordini al broker.

## Primo avvio Windows 11 / PowerShell

Dalla radice del checkout del branch `integration/local-web-desktop-20261116`:

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
dopo un crash non viene sovrascritto: verificare prima che l'istanza sia chiusa.
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
  Le letture native successive a initialize non hanno una deadline garantita
  dall'SDK; non equivale a un connettore certificato contro blocchi del terminale.
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
- Automazione: sempre arrestata nella nuova applicazione. Nessun pulsante di
  avvio decorativo, nessun endpoint per ordini Alpaca/MT5 o retry di scrittura.
  Gestione bot/esecuzione Paper e riconciliazione completa non sono migrate.

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
Chiusura finestra → shutdown stdin → eventuale kill del solo Child posseduto.
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
