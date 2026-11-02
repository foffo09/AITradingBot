# Guida completa del progetto AITradingBot

Questa guida descrive il codice locale revisionato, non un servizio già validato su un conto autentico. Per i passi pratici leggere [Come usare la dashboard](COME_USARE_LA_DASHBOARD.md); per prove e lacune leggere [Matrice test](MATRICE_TEST.md) e [Revisione e roadmap](REVIEW_QUALITA_E_ROADMAP.md).

## Che cosa fa

AITradingBot permette di osservare prezzi, calcolare incroci tra medie mobili semplici, simulare operazioni e confrontare risultati storici. Può monitorare Alpaca Paper e dispone di un percorso di automazione separato, arrestato all'avvio. Non è una previsione di mercato e non dimostra redditività.

I tre entry point non sono intercambiabili:

| Percorso | Compito | Capitale/stato |
| --- | --- | --- |
| `app.py` | Dashboard Streamlit, analisi SMA, ledger, backtest, monitor/anteprima Alpaca | Database isolato della modalità; account broker separato |
| `main.py` | Console aggiuntiva di ricerca con provider pubblici | Paper locale proprio, non il conto mostrato dalla dashboard |
| `src/hyperliquid_testnet_cli.py` | Motore nativo Hyperliquid testnet | Journal dedicato; non controllato dai pulsanti Streamlit |

Gli stop del motore Hyperliquid non sono regole della strategia SMA Streamlit. Non si copiano percentuali o livelli da un sistema all'altro.

## Flusso e moduli

1. `config/settings.py` valida modalità, finestre SMA e limiti; assenza di credenziali comporta fallback Demo. Live trading è rifiutato.
2. `src/data/instruments.py` è un catalogo, non una conferma di negoziabilità.
3. `src/broker/alpaca_client.py` fornisce dati OHLCV/quote, verifica Paper e legge account/posizioni/ordini. La risposta ordini satura a 500 viene rifiutata prudenzialmente.
4. `src/data/market_data.py` produce prezzi deterministici per prove Demo, marcati sintetici. Il tempo della serie è generato al caricamento; non è un feed.
5. `src/strategy/moving_average.py` produce medie, incroci e motivazione. Non accede al broker.
6. `src/risk/risk_manager.py` verifica quantità, cash, esposizione e perdita. Non garantisce il prezzo di esecuzione.
7. `src/trading/paper_automation.py` collega dati, account, strategia e rischio. L'anteprima `dry_run=True` termina prima di `submit_order`; l'invio preesistente resta una funzione distinta attivata esplicitamente.
8. `src/simulation/ledger.py` registra operazioni virtuali con transazioni SQLite, chiavi idempotenti e prezzi ordinati temporalmente.
9. `src/backtesting/engine.py` esegue simulazioni storiche; `walk_forward.py` sceglie parametri sul training e li valuta sul periodo successivo.
10. `src/ui/presentation.py` prepara valori/stati senza accesso a broker o DB; `src/ui/charts.py` disegna solo i dati ricevuti. `app.py` resta responsabile della composizione e del caricamento.

`src/data/bar_timing.py` è ora il contratto temporale operativo per Alpaca Paper: calendario NYSE e intraday crypto continuo, con blocchi espliciti per gli aggregati non verificati. `auto_selector.py` resta assente; non esiste un selettore autonomo di strategie economicamente approvate.

## Modalità e origine dei numeri

- **Demo:** fonte sintetica scelta esplicitamente, dati non autentici; la scelta è visibile nella sezione Mercato. Il grafico e il segnale riportano SYNTHETIC / DEMO.
- **Ledger locale:** capitale virtuale e operazioni registrate nel DB isolato. Non è il saldo del broker, anche quando usa prezzi storici reali.
- **Backtest:** simulazione sulla serie selezionata, con capitale e costi propri. Non scrive operazioni sul ledger.
- **Alpaca Paper:** conto broker simulato separato. Verifica della connessione, disponibilità dati e negoziabilità dell'asset sono controlli diversi.

Demo e Paper non possono usare lo stesso file, neppure con percorsi diversi collegati tramite hard link. `data/simulation.sqlite3` è il ledger personale storico e non è accettato dai percorsi isolati.

## Come leggere le metriche

| Termine | Significato e provenienza |
| --- | --- |
| Cash | Contanti del ledger oppure campo `cash` del broker; non è l'equity |
| Equity Paper | Campo `equity` ricevuto dal broker; nessuna somma di valori locali |
| Buying power | Campo broker di capacità di acquisto; può differire dal cash |
| Valore di mercato posizioni | Nella vista Paper, somma dei valori assoluti `market_value` forniti; non è il costo storico d'acquisto |
| P/L non realizzato Paper | Somma di `unrealized_pl` del broker; N/D se qualche valore necessario manca |
| Variazione equity vs close | `equity - last_equity`; percentuale divisa per `last_equity` solo se positivo. Flussi esterni possono alterarla: non è il solo P/L realizzato |
| P/L locale | Risultato della contabilità virtuale con i costi configurati; il riepilogo distingue realizzato e posizione aperta con stime di uscita |
| P/L totale/realizzato Paper | N/D nel riepilogo se mancano base iniziale e storico affidabili |
| Win rate | Quota delle operazioni chiuse con risultato netto positivo; va letto con N operazioni, non come rendimento o probabilità futura |

Un valore zero è noto. N/D significa dato assente, invalido o non ricostruibile. NaN, infinito e stringhe invalide non sono denaro. Un elenco posizioni assente non equivale a un elenco vuoto confermato.

Gli importi del flusso attuale sono in USD. Le conversioni del ledger verso EUR usano il cambio di riferimento registrato all'avvio, con fonte e data, non il cambio corrente. Le commissioni, lo spread e lo slippage di ledger/backtest sono ipotesi dichiarate, non costi autentici del broker.

## Segnale tecnico SMA

Una SMA è la media degli ultimi N close. Esempio didattico, non prezzi reali: la media di 10, 12 e 14 è 12.

- BUY: SMA breve sopra quella lunga, mentre sulla barra precedente era sotto o uguale.
- EXIT: SMA breve sotto quella lunga, mentre sulla barra precedente era sopra o uguale.
- Nessun segnale: nessun nuovo incrocio; non è automaticamente un blocco del rischio.
- Dati insufficienti: le medie richieste non sono disponibili. Servono almeno N barre per la media lunga, una ulteriore per osservare l'incrocio e una successiva per l'esecuzione del backtest.

La dashboard mostra simbolo, timeframe, parametri, close, medie e timestamp. La barra tecnica mostrata può essere in formazione: non viene dichiarata chiusa. I controlli operativi sono separati e usano il calendario per i contratti supportati; aggregati non verificati restano bloccati.

Dato obsoleto, futuro, assente, asset non verificato e rischio bloccato sono motivi distinti di mancata operazione. NO_TRADE è una descrizione generale, non il nome di un nuovo modello: il codice restituisce stati come `no_signal`, `blocked` o `duplicate` con motivo.

## Grafico e proposta

Il candlestick è OHLC; la linea della quotazione recente è distinta dal close. Il marker dell'ordine usa un close di riferimento esplicitamente etichettato, non inventa un fill. Un fill necessita dei dati di esecuzione; timestamp/prezzi invalidi non sono disegnati come fill. I record con lo stesso ID non producono marker duplicati. La UI Demo non sovrappone fill Paper ai prezzi sintetici.

Volume e SMA restano visibili anche quando lo storico è corto. L'RSI visuale è opzionale, usa medie mobili dei guadagni/perdite su 14 variazioni: 100 senza perdite, 0 senza guadagni, convenzione neutra 50 su finestra piatta. Non entra nella decisione SMA.

La SMA Streamlit non definisce stop-loss, take-profit o rischio monetario fino allo stop. Questi campi restano N/D. L'anteprima Paper può riportare quantità, bid/ask di riferimento, timestamp e controvalore teorico dopo i controlli; non crea un ordine né un'esecuzione. Gap, spread, liquidità e slippage possono cambiare qualsiasi risultato futuro.

## Automazione e anteprima

`Esegui anteprima DRY-RUN` valuta un ciclo con dati reali e conto verificato. Non avvia l'automazione e non chiama submit. Può restituire nessun segnale, blocco, duplicato o proposta dimensionata. I risultati sono registrati come decisioni, non fill.

`Avvia automazione Paper` è un'altra azione e può inviare ordini Paper: non va premuta durante una prova di sola lettura. Il comportamento preesistente di invio non è stato reso più permissivo. `Arresto immediato` ferma i cicli successivi ma non annulla ordini già inviati.

I controlli includono modalità, account attivo, dati reali, età, segnale, asset, quota ordini, posizioni, incrementi quantità, cash ed esposizione. Il backend Paper ora rifiuta anche una quotazione futura di un solo secondo e richiede timestamp con fuso esplicito. Usa il contratto temporale descritto sotto. Il coordinamento distribuito e una modalità DRY-RUN continua restano lavori separati.

Il log mostra al massimo gli ultimi 25 eventi, filtrabili ed esportabili in CSV. Campi non registrati, come parametri storici completi/versione, restano N/D; non vengono riempiti con i parametri correnti.

## Backtest e walk-forward

Il backtest calcola il segnale sul passato e simula l'ingresso all'open della barra successiva. Se resta una posizione aperta, la valuta con costi stimati di liquidazione: il risultato non è tutto realizzato. Il benchmark buy-and-hold usa capitale e costi coerenti.

Leggere insieme periodo, strumento, timeframe, capitale, costi, operazioni e drawdown. Lo Sharpe annualizzato assume campionamento regolare e tasso privo di rischio dichiarato; non è una garanzia. Un win rate elevato con pochi trade non è una prova robusta.

Il walk-forward sceglie tra SMA 2/4, 3/6 e 5/10 sul training e valuta nel test successivo. Fold indipendenti ripartono da capitale e warm-up propri; non sono un portafoglio continuo e non vanno sommati come rendimento composto. Cambiare dati o parametri invalida la visualizzazione dei vecchi risultati.

## Test e limiti

Da `.venv`, `python -m pytest -q` carica il guard in `conftest.py`: rete e file locali delle credenziali sono vietati; l'ambiente ereditato viene ripulito solo nel processo dei test. Le fixture usano credenziali fittizie e SQLite temporaneo. I test della policy usano eventi simulati; il guard globale segnala tentativi accidentali e fallisce anche se l'errore viene intercettato.

L'assenza di tentativi in un'esecuzione non certifica sicurezza contro codice ostile. Non disabilitare il guard per eseguire un'integrazione autentica. Le prove reali richiedono un incarico distinto.

Verificato su macOS con Python 3.12; Windows, resa visuale manuale e servizi autenticati non verificati. Non sono presenti ML addestrato o confidence predittiva. L'eventuale AI della console aggiuntiva propone parametri limitati, non trasforma la SMA in una previsione.

## Aggiornamento P1: esecuzione Paper coordinata

L'invio ora è disabilitato per default, oltre agli altri controlli già esistenti. Una connessione verificata non basta: occorrono scope single_host esplicito, directory assoluta comune a tutte le sessioni e un ID conto stabile. La UI disabilita l'avvio senza coordinatore; l'anteprima DRY-RUN rimane consultabile con i propri prerequisiti.

Ogni valutazione operativa mantiene un lock OS sul conto, rilegge stato/posizioni/ordini e registra un intento persistente prima di raggiungere il submit. Un secondo processo non può valutare mentre il primo possiede il lock. Dopo un timeout o crash, il journal impedisce di assumere che l'ordine non sia stato ricevuto. Anche snapshot vuoti e obsoleti non autorizzano un secondo segnale.

Solo un rifiuto/cancellazione/scadenza terminale con quantità eseguita nota e zero permette nuove decisioni; fill parziali, eseguiti o mancanti richiedono riconciliazione e rimangono bloccati. Non eliminare lock/journal per aggirare il blocco. Il file del lock può restare sul disco senza proprietario: conta il lock OS, non l'esistenza del file.

È un contratto locale fra processi cooperanti: Windows, NFS, altri host e directory diverse non sono coordinati. P1 distribuito resta aperto e richiede un servizio unico che possieda le credenziali e rifiuti accessi concorrenti. Le prove attuali usano esclusivamente broker fittizi.

## Aggiornamento P1: contratto temporale operativo

La nuova dipendenza `pandas-market-calendars==5.5.0` fornisce regole di seduta NYSE locali, fuso America/New_York, festività e chiusure anticipate. Non interroga un servizio al caricamento. Le regole possono richiedere aggiornamenti per eventi straordinari: non è un calendario live né una garanzia di finalità del feed. È stata necessaria perché pandas non contiene i calendari degli exchange e nessuna dipendenza equivalente era presente.

Il feed deve dichiarare in attrs contratto `alpaca-start-v1`, calendario, scope della sessione, timeframe e acquisizione con fuso. I timestamp sono inizi dell'intervallo. Vengono rifiutati timestamp mancanti, senza fuso, futuri, duplicati e non ordinati; i close devono essere finiti e positivi.

Per azioni/ETF, l'operatività è limitata alla sessione regolare NYSE; pre/post-market non sono autorizzati, anche con `allowed_market_hours_only=False`, perché non esiste un contratto operativo per gli orari estesi. Le barre intraday usate devono ricadere interamente nella seduta effettiva. La chiusura anticipata non viene sostituita da 16:00 o da 24 ore.

Una barra è temporalmente utilizzabile solo se il termine previsto è trascorso sia rispetto all'ora di valutazione sia rispetto all'acquisizione dei dati, con un margine prudenziale di pubblicazione di 30 secondi. Questo margine non garantisce assenza di rettifiche tardive e non certifica che il feed abbia un flag finale. I limiti massimi di età preesistenti restano invariati; vengono ricontrollati anche sull'ultima barra conclusa selezionata.

Contratti attuali: intraday azionario 1/5/15 minuti e 1 ora, filtrato sulla seduta regolare; intraday crypto continuo UTC con griglia coerente. I daily RTH con contratto esplicito sono gestiti e testati sul calendario; l'adattatore Alpaca grezzo non dichiara quel contratto, perciò daily azionari reali, daily crypto e weekly restano visualizzabili ma bloccati per gli ordini. Serve verificare o costruire l'aggregazione prima di abilitarli. Non vengono inventate conferme del broker.

Le soglie temporali di `src/ui/presentation.py` sono etichette di freschezza, non autorizzazioni. Il ledger è una simulazione locale con i propri limiti di età; backtest e walk-forward mantengono il loro contratto storico e non inviano ordini. I giorni usati per le query storiche e il lookback incrementale in app/client non determinano la chiusura operativa. Il motore nativo Hyperliquid usa un flusso distinto, non queste barre SMA.

Riferimenti di contratto: [aggregazione Alpaca](https://docs.alpaca.markets/us/docs/market-data-faq), [barre e rettifiche](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), [calendari e sedute](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html). Le prove del codice sono offline; il protocollo autenticato non è stato interrogato.

Prima del submit il lease esegue di nuovo il controllo temporale dopo la riverifica dell'account: mercato ancora aperto, stessa ultima barra utilizzabile e quotazione non scaduta. Una nuova barra conclusa invalida la vecchia decisione e richiede rivalutazione. Questo non rende atomico l'istante di ricezione del broker, che dipende dalla rete. Un intento già persistito resta prudenzialmente bloccato anche se il controllo finale fallisce prima dell'API; il recupero completo dei casi noti come non inviati rimane da progettare senza inferire un rifiuto dall'assenza.
