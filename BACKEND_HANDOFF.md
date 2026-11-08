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

## Fase 2 — impatto documentato prima della correzione

Base della revisione: `f36f9e2021ae10793a6289ffdd231c62b462334f`.
Nessuna modifica alle firme delle API broker o ai tipi dei risultati.

Correzioni riprodotte con test, circoscritte ai file della Persona 1:

1. `fetch_eur_usd_rate`: un booleano JSON era convertito in 1.0; la data della
   risposta poteva essere futura. Verranno rifiutati con RuntimeError già previsto
   dall'API. Nessuna nuova soglia di età per i fixing ECB, che possono essere
   legittimamente precedenti nei weekend/festività. Confronto della data in UTC.
2. `select_completed_bars`: accettava provenienza sintetica o mancante e flag
   is_synthetic discordanti. Le firme restano invariate; il gate operativo
   richiederà attrs quality=real e, se presente, ogni flag is_synthetic esplicitamente
   False. I frame reali minimali senza quella colonna restano supportati.
   I chiamanti Paper già controllano quality; questo consolida il contratto del
   helper condiviso, senza attestare che la pipeline precedente inviasse ordini Demo.
3. `describe_error`: se la chiave più corta era contenuta nel segreto più lungo,
   la prima sostituzione lasciava una parte del segreto visibile. Redazione dal
   valore più lungo al più corto, stesso tipo str ed eccezioni già esistenti.

La prova con SDK reale e HTTP simulato ha invece dimostrato che 200 {}, JSON
vuoto/null e 204 su ordini/posizioni sono già rifiutati: nessuna modifica
ridondante al trasporto. Una risposta esplicita 200 [] resta una lista vuota
valida; non certifica da sola completezza globale o coerenza del conto.

### Impatto aggiuntivo sulla finestra storica limitata

Revisione dello SDK installato: BaseTimeseriesDataRequest.sort usa ASC per default;
_get_marketdata interrompe la paginazione quando raggiunge il limite. Il chiamante
Paper chiede period=3M e limit=1000 per l'intraday; il budget effettivo del backend
può arrivare a 10000 barre, ma ASC seleziona la parte più vecchia del periodo e
può lasciare il selettore senza barre fresche. Nessun test autentico del feed è
implicito in questa osservazione del contratto SDK.

Impatto prima della modifica: a firma invariata, per limit finito e start_time
assente il backend richiederà sort=desc (finestra più recente); restituirà sempre
un DataFrame ordinato crescente. Con limit=None resta sort=asc per lo storico
completo; con start_time esplicito resta sort=asc per non saltare il backfill.
Il calcolo preesistente del budget, incluso il tetto 10000, non viene modificato;
limit non è una promessa di cardinalità esatta o di copertura dell'intero periodo.

## Fase 2 — contratti per Persona 2 e Persona 3

Le sezioni precedenti mantengono la descrizione delle API broker. Le validazioni
aggiuntive sopra sono implementate; non cambiano firme o forme dei risultati.

| API dati | Input e output | Contratto/errore |
| --- | --- | --- |
| `generate_demo_prices(symbol="AAPL", periods=200, start_price=100.0, drift=0.0005, volatility=0.012)` | DataFrame con symbol, timestamp UTC, OHLCV, is_synthetic=True e data_quality=synthetic-demo | Generazione esplicita Demo; mai fallback di un errore Alpaca. Non idonea al gate operativo. |
| `generate_synthetic_market_data(symbol="AAPL", periods=200)` | Stesso DataFrame del generatore Demo | Alias compatibile; il generatore non certifica provenienza reale tramite attrs. |
| `fetch_eur_usd_rate(timeout=4.0)` | dict rate: float positivo finito, timestamp: data ISO, source: Frankfurter API (ECB reference rate) | RuntimeError su rete/JSON/valori invalidi. La data è quella del fixing, non un timestamp di negoziazione. Booleani e date future UTC rifiutati. Nessuna conversione implicita nelle quote Alpaca. |
| `utc_timestamp(value, label)` | pandas.Timestamp timezone-aware, convertito UTC | BarTimingError su NaT, assenza di fuso o valore invalido. Non localizzare automaticamente timestamp ricevuti senza fuso. |
| `bar_timing(symbol, interval, bar_timestamp, as_of, minimum_age_seconds)` | tuple is_forming: bool, timestamp_age_seconds: float, freshness_age_seconds: float | Helper analitico, non attestazione operativa o di provenienza. ValueError/BarTimingError su date/calendario invalidi. |
| `select_completed_bars(data, symbol, now, require_market_open=True)` | DataFrame crescente con sole barre temporalmente chiuse; attrs originali e excluded_incomplete, excluded_outside_session, last_completed_at se non vuoto | BarTimingError su provenienza non reale/contraddittoria, dati invalidi, vecchi, futuri o contratto non dimostrabile. Può restituire un DataFrame vuoto senza autorizzare nulla. |

Regole comuni per l'integrazione:

- Le quote richiedono timestamp UTC e 0..120 secondi di età; un midpoint non è
  un fill e un fixing FX non è una quote corrente. Un errore non restituisce un
  prezzo precedente come aggiornamento riuscito.
- I limiti esistenti delle barre sono 600/1200/2700/10800/345600 secondi per
  1Min/5Min/15Min/1Hour/1Day, più contratto feed e margine di pubblicazione 30 s.
  Nessuna soglia è stata allargata. Weekly e aggregati non verificati restano bloccati.
- Nel gate operativo quality deve essere real. Se esiste is_synthetic, ogni
  cella deve essere un booleano False; True, None e stringhe sono rifiutati.
  La colonna può mancare per compatibilità con frame minimali già supportati.
- Preservare attrs durante cache/copy/concat e mantenere associati simbolo,
  intervallo e fonte. Non cambiare un flag di provenienza per far passare il gate.
- Lista ordini vuota è una risposta valida solo se effettivamente ricevuta come
  tale. Non prova coerenza globale, fine della paginazione o risoluzione di un
  intento persistito. Dopo un errore di lettura account/posizioni/ordini il
  backend invalida lo stato verificato; il successivo snapshot richiede nuova
  verifica e non riusa il saldo precedente.
- Un guasto market data non implica necessariamente guasto al conto, ma blocca
  il dato richiesto. is_connected() non autorizza l'uso di una quote scaduta.

### Richieste proposte alle altre persone, senza modifiche ai loro file

| Destinatario | Evidenza del codice attuale | Proposta da concordare |
| --- | --- | --- |
| Persona 2 / dashboard | Il refresh cancella la quote dopo BrokerConnectionError, conserva lo storico con avviso e può continuare a calcolare signal_view su quello storico. Il controllo temporale è mostrato separatamente. | Mantenere questa separazione: segnali su storico vecchio o non operativo vanno presentati come analisi storica, non come indicazioni correnti. Usare il gate condiviso per un'etichetta di idoneità, senza cancellare dati utili al backtest. |
| Persona 2 / cache | Il refresh aggiorna attrs dopo concat. | Conservare i metadati del backend, in particolare provenienza e acquisizione; non rinnovare fetched_at a seguito di un errore o del solo refresh della UI. Controllare coerentemente simbolo/intervallo. |
| Persona 3 / selettore | _prepare_data verifica quality e tempo con bar_timing, ma non usa il medesimo gate operativo select_completed_bars, né verifica is_synthetic/fetched_at. La funzione di esecuzione rivalida poi il dato e blocca gli invii non idonei. | Chiarire che SELECTED è una proposta analitica. Per proporre un segnale operativo applicare il gate condiviso agli stessi frame, gestire BarTimingError come indisponibilità/NO_TRADE e controllare i marker di provenienza. Nessuna rimozione dei controlli finali. |
| Persona 3 / finestre dati | Il chiamante usa period=3M, limit=1000 e poi tail(1000). | La correzione backend richiede ora la finestra più recente quando limit è finito. Conservare il tail su timestamp crescenti; usare limit=None per copertura storica completa e start_time esplicito per backfill. |
| Coordinatore | Snapshot REST sequenziali e storico ordini a tetto 500 non costituiscono una riconciliazione atomica. | Conservare il blocco dopo esiti ambigui; non sbloccare il coordinatore solo perché il monitor risponde nuovamente. |

Queste sono richieste di integrazione, non modifiche già effettuate a dashboard,
strategie o runner. Il backend non può impedire a un chiamante che ignora il
contratto di rietichettare arbitrariamente un dato; non è una sandbox ostile.

### Verifiche Fase 2 — 2026-11-06

- Commit iniziale: f36f9e2; checkout pulito e branch dedicato verificati prima
  dell'intervento. Nessuna modifica preesistente sovrascritta.
- Solo quattro correzioni: fixing FX invalido, provenienza del gate operativo,
  redazione di segreti sovrapposti e finestra recente nelle richieste limitate.
- 33 nuovi casi in tests/test_backend_integration.py, compresi i controlli già
  corretti sulle risposte HTTP incomplete/204, body troncati, liste vuote valide,
  disconnessione e riverifica senza riutilizzo del vecchio saldo.
- SDK reale con Session.send simulato; nessuna chiamata autenticata. La prova
  iniziale sul presunto problema 200 {} è passata: nessuna modifica al trasporto.
- Il confronto con sorgente SDK ha confermato sort ASC di default e limite della
  paginazione; test di stock e crypto dimostravano la finestra obsoleta prima del fix.
- Nessun test esistente modificato, rimosso o disattivato; conftest invariato.
- Mac/Python 3.12.14: 205 mirati passati in 1,72 s; suite completa 535 passati,
  1 saltato, 0 falliti, 1 warning in 24,51 s. Guard rete 0, credenziali 0.
  Skip Windows Proactor e warning websockets.legacy preesistenti.
- Sicurezza: 142 passati, 1 skip Proactor e un warning in 1,30 s;
  compilazione, pip check e diff-check exit 0. Non sono una prova di sicurezza assoluta del trading.
- Windows e broker/feed autentici di questa versione NON ESEGUITI. Nessun server,
  automazione, ordine broker, file di credenziali o database personale aperto.

Per ripetere i nuovi casi su PowerShell, dopo l'installazione già descritta:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_integration.py tests/test_backend_contract.py tests/test_bar_timing.py tests/test_fx_rates.py tests/test_paper_automation.py tests/test_paper_safety.py
.\.venv\Scripts\python.exe -m pytest -q -rs
```
