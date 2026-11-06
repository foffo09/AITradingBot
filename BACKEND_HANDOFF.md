# Backend e market data — consegna al coordinatore

## Base e perimetro

Base concordata: `67f6a47085905b523ff11828866efdb653ccb744`.
Branch: `feature/backend-market-data`. Worktree dedicato: `AITradingBot-backend`.
Nessuna modifica a main, UI, strategie, risk manager, backtesting o file di credenziali.
Nessuna dipendenza aggiunta. Le firme pubbliche esistenti sono conservate.

File della consegna:
- `src/broker/alpaca_client.py`: validazione, invalidazione dello stato ed errori.
- `src/broker/alpaca_transport.py`: trasporto HTTP dei tre client SDK esistenti.
- `tests/test_backend_contract.py`: regressioni deterministiche/offline.
- `tests/test_paper_safety.py`: una fixture dichiara anche account_blocked=False,
  come un account realmente verificabile; le asserzioni esistenti sono conservate.
- `BACKEND_HANDOFF.md`: contratti, decisioni, comandi, risultati e limiti.

## Contratto pubblico AlpacaClient

Le credenziali continuano a essere lette da AppSettings; non passarle a logger,
serializzazioni o file di consegna. I test usano esclusivamente valori fittizi.
`AlpacaClient(settings=None)` conserva la configurazione esistente; una
configurazione Demo non costruisce un client trading anche in presenza di chiavi.

| API | Parametri e risultato | Errori e significato |
| --- | --- | --- |
| `verify_connection()` | dict con status, connected, message, mode | Verifica account attivo e blocchi conosciuti. In Paper un SDK non disponibile produce error/connected=False/mode=paper; non diventa un conto Demo. |
| `is_connected()` | bool | Stato dell'ultima verifica, non attestazione di freschezza permanente o permesso di invio. Gli errori account/posizioni/ordini azzerano anche l'account memorizzato. |
| `paper_client_configured`, `paper_client_is_paper` | proprietà bool | Configurazione e provenienza Paper; non attestano che feed e conto siano utilizzabili in questo istante. |
| `paper_coordinator` | coordinatore oppure None | Richiede scope single_host esplicito, directory assoluta comune e identità conto; default operativo disabilitato. |
| `get_account()` | modello TradingAccount SDK oppure dict | Formato monetario SDK conservato, anche stringhe decimali e None. Importi non finiti, booleani o non numerici causano BrokerConnectionError; un dato mancante non diventa zero. |
| `get_positions()` | lista di modelli Position SDK o dict | None, scalari o contenitori malformati sono errori. Lista vuota è accettata solo se restituita come lista valida, oppure come placeholder Demo senza SDK. |
| `get_orders()` | lista di modelli Order SDK o dict | Status ALL, limite 500. Saturazione, None e risposte malformate causano errore; nessuna supposizione di assenza ordine dopo timeout. |
| `get_paper_snapshot()` | dict: account, positions, orders, updated_at | Richiede verifica Paper riuscita; le letture sono sequenziali, non una transazione broker coerente né una riconciliazione completa. |
| `safe_account_summary()` | dict dei campi monetari disponibili, status, updated_at e account_number mascherato | Nessun saldo inventato; propaga l'indisponibilità invece di riutilizzare uno snapshot precedente. |
| `get_instrument_availability(symbol)` | dict: visible, data_available, paper_tradable, fractionable, min_order_size, min_trade_increment, message | Stato unknown/unverified quando non dimostrabile. Non è prova di abbonamento ai dati né autorizzazione di invio. |
| `describe_error(exc)` | str con chiavi configurate oscurate | Gli errori SDK incapsulati sopprimono la causa originale nel traceback standard per non ristampare credenziali presenti nell'errore remoto. |

La dicitura connected serve al monitoraggio. Al submit trading_blocked e
account_blocked devono essere entrambi **esplicitamente False**: valori mancanti,
None, zero o stringhe non autorizzano invii. I dati monetari None rimangono
mostrabili come N/D, ma non attestano disponibilità per il dimensionamento.

### Storico OHLCV

Firma conservata:

```python
get_market_data(symbol: str, timeframe: str = "1Day", period: str = "3M",
                limit: int | None = 1000, start_time: datetime | None = None)
```

Restituisce un DataFrame ordinato per timestamp con open/high/low/close/volume,
colonne `is_synthetic=False`, `data_quality` e metadati attrs:
`source`, `quality="real"`, `interval`, `bar_time_contract="alpaca-start-v1"`,
`bar_calendar`, `session_scope`, `fetched_at`, `requested_start`.

- Prezzi float finiti e positivi nella valuta dello strumento; catalogo attuale
  azioni USA e coppie crypto /USD. Nessuna conversione FX implicita.
- Volume numerico finito non negativo; high/low coerenti con open/close.
- Timestamp ricevuti obbligatoriamente con timezone, restituiti UTC; NaT,
  duplicati e timestamp futuri vengono rifiutati. fetched_at è l'istante UTC di
  ricezione della risposta, non il timestamp della barra.
- Per compatibilità, un start_time fornito dal chiamante senza fuso continua a
  essere interpretato come UTC. Per nuovi chiamanti usare datetime con timezone.
- Intervalli: 1Min, 5Min, 15Min, 1Hour, 1Day, 1Week. Periodi: 1M, 3M, 6M, 1Y, 5Y.
  Richieste non supportate o limite non positivo vengono rifiutati.
- La paginazione storico resta quella dello SDK. Un'eccezione non restituisce
  un risultato parziale né attiva un generatore sintetico.
- Storico non significa prezzo corrente o barra completata: una barra vecchia
  può essere corretta per un backtest. L'idoneità operativa resta in
  `src/data/bar_timing.py::select_completed_bars`, con controlli di calendario,
  contratto, acquisizione e freschezza preesistenti, non modificati.
- Azioni: Alpaca IEX, copertura venue parziale; crypto: Alpaca Crypto, 24/7.
  I daily grezzi/all_sessions e gli aggregati non verificati non diventano
  automaticamente idonei al trading. I metadati non vanno eliminati o riscritti.

### Quotazione bid/ask

`get_latest_quote(symbol: str) -> dict` conserva esattamente i campi pubblici:
`bid`, `ask`, `price` (midpoint), `timestamp`, `source`.

Bid/ask sono float finiti, positivi, non booleani, con bid <= ask. Il midpoint
usa una formula che evita overflow e lo zero artificiale ai limiti dei float.
Timestamp obbligatoriamente timezone-aware, normalizzato in ISO 8601 UTC.
Età consentita: **0 <= età <= 120 secondi**, in accordo con il controllo Paper
esistente. Quote future, più vecchie, senza fuso o mancanti causano
BrokerConnectionError. Non viene sostituita una quote assente con un close storico.
Le fonti sono Alpaca IEX latest quote e Alpaca Crypto latest quote.

### Invio e risposta ambigua

`submit_order` conserva i campi nominati symbol, side, quantity, client_order_id
ed il lease coordinato esistente. Le chiamate posizionali e i percorsi senza
lease valido restano bloccati. I limiti finanziari e gli intenti durevoli non
sono modificati. Non è stata aggiunta alcuna automazione operativa.

Una risposta deve avere id e status, ed un eventuale client_order_id deve
coincidere con quello richiesto. Errori, ack vuoti, non interpretabili, non
serializzabili o con identità discordante invalidano la verifica del conto.
Non si ripete l'invio: l'intento rimane da riconciliare. Ack non significa fill.
Il coordinatore esistente resta prudenziale dopo ordini pendenti o fill;
questa consegna non implementa un nuovo executor o lo sblocco dopo esiti incerti.

## Trasporto, retry e logging

Lo stesso SDK Alpaca 0.44.0 viene riutilizzato. La sua sessione HTTP interna
viene configurata all'inizializzazione; il legame con questi campi privati è
coperto da test col vero SDK ed un trasporto simulato. Prima di aggiornare SDK,
rieseguire tutti i test di contratto.

- Trading: solo HTTPS su `paper-api.alpaca.markets`, nessun retry SDK, anche
  sulle letture. Al submit una riattivazione dei retry invalida il conto e blocca
  la richiesta. Non si ritentano POST/DELETE/PATCH su 429.
- Market data: solo HTTPS su `data.alpaca.markets`, soli GET/HEAD. Al massimo
  tre tentativi per singola richiesta HTTP su 429/504, con pausa di un secondo.
  401/403/503 ed errori di trasporto/timeout non sono ritentati automaticamente.
- Ogni richiesta: timeout connessione 3,05 s, timeout lettura 10 s; redirect
  disabilitati e risposte 3xx rifiutate. Non sono deadline globali di una query
  paginata: il timeout di lettura limita l'attesa fra dati, non il tempo totale.
- Session trust_env=False: nessuna lettura implicita di netrc o proxy/certificati
  dall'ambiente requests. Le credenziali esplicite SDK continuano a funzionare.
  Proxy aziendali o CA personalizzate richiedono un accordo d'integrazione;
  non è stato aggiunto un bypass TLS o un fallback su un altro endpoint.
- Gli avvisi usano il logger esistente, già UTF-8; non registrano payload conto,
  chiavi o risposte HTTP grezze. La stringa dell'eccezione pubblica è oscurata;
  il traceback SDK originale viene soppresso nei wrapper BrokerConnectionError.

Errori dei dati non sono confusi con disconnessioni del conto: un account può
restare verificato mentre la quote è indisponibile. Il ciclo deve fermarsi sul
relativo errore, senza interpretare is_connected() come prova di dati freschi.

## Integrazione e limiti da mantenere

- Demo è esplicita e distinta da Paper. Inizializzazione Paper fallita non
  restituisce un saldo Demo o liste fittizie di ordini/posizioni.
- SimulationLedger, backtest, conto Paper e journal Hyperliquid restano separati.
  Nessun provider aggiuntivo è stato attivato o usato come fallback.
- Snapshot REST non atomici, paginazione globale dello storico, coordinamento
  multi-host e riconciliazione autentica rimangono limiti esistenti. Il tetto
  ordini di 500 fa fallire la lettura, non attesta una pagina finale completa.
- Questi controlli proteggono i percorsi del backend cooperante; non isolano
  codice Python malevolo o un SDK esterno che ignori il coordinatore.
- Non cambia alcuna firma richiesta a UI/strategy; le validazioni sono più
  severe sugli input e sulle risposte invalidi. La sola fixture di submit
  aggiornata esplicita entrambi i flag di blocco come False.

## Prove riproducibili, senza broker o segreti

Da un checkout pulito del branch, macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m compileall -q app.py config src tests
.venv/bin/python -m pytest -q tests/test_backend_contract.py tests/test_broker.py tests/test_paper_safety.py tests/test_config.py tests/test_fx_rates.py tests/test_bar_timing.py
.venv/bin/python -m pytest -q -rs
.venv/bin/python -m pip check
git diff --check
```

PowerShell, da una copia di prova Windows senza credenziali o database personali:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m compileall -q app.py config src tests
.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_contract.py tests/test_broker.py tests/test_paper_safety.py tests/test_config.py tests/test_fx_rates.py tests/test_bar_timing.py
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Non servono .env, autorizzazioni di trading, server o feed per questi test.
conftest non è modificato; nessun test esistente viene rimosso o disattivato.
Requests/SDK sono simulati prima del trasporto; i test di percorso usano solo
SQLite temporaneo e pathlib, con spazi e caratteri Unicode. Nessun subprocess
specifico di macOS è aggiunto al backend.

## Registro di verifica — 2026-11-06

Base Mac osservata: 435 passati, 1 saltato (Windows Proactor), un warning.
Le nuove regressioni sono state eseguite prima delle correzioni: dimostravano
retry delle scritture, timeout assente, destinazione errata, risposte invalide,
clock/quote incoerenti, flag incerti, ack ambiguo e credenziali nel traceback.
La fixture HTTP è stata corretta per simulare anche il consumo del body.
Il confronto finale, inclusi conteggi ed esiti, è riportato sotto.
Windows per queste modifiche NON ESEGUITO; broker/feed autentici NON ESEGUITI.
Non sono stati aperti file personali di credenziali o database né inviati ordini.

### Esito finale osservato sul Mac

- Python 3.12.14; installazione requirements-dev.txt riuscita in venv separata.
- `python -m compileall -q app.py config src tests`: output vuoto, exit 0.
- Gruppo broker/Paper/market data/config/FX/calendario/percorso: **152 passati**,
  un warning, **1,47 s**; include 67 casi in test_backend_contract.py.
- `python -m pytest -q -rs`: **502 passati, 1 saltato, 0 falliti, 1 warning**,
  **24,62 s**, exit 0. Rispetto alla baseline: 67 nuovi casi, nessun test eliminato.
- Skip preesistente: tests/test_test_isolation.py:21, self-pipe Windows Proactor
  non applicabile su Mac. Warning preesistente: websockets.legacy deprecato.
- `TEST ISOLATION: {'network': 0, 'credentials': 0}`.
- `python -m pip check`: `No broken requirements found.`, exit 0.
- `git diff --check`: output vuoto, exit 0.
- Scope finale: solo i cinque file elencati all'inizio; controlli Paper
  preservati o resi più restrittivi. Nessuna nuova soglia finanziaria.

Queste prove riguardano codice e trasporti simulati su macOS. La prova di questa
versione su Windows 11/Python 3.11, su feed autentici e su account Paper reale
resta **NON ESEGUITA**. Richiede i comandi PowerShell sopra, senza credenziali per
la suite. I test verdi non attestano sicurezza del trading automatico.
