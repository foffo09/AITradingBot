# Come usare la dashboard senza inviare ordini

Queste sono istruzioni per una prova successiva dell'utente. Durante la revisione non è stato avviato alcun server. Per il significato delle metriche leggere la [guida completa](GUIDA_COMPLETA_PROGETTO.md).

## 1. Avvio Demo isolato

Su Windows esiste il launcher:

```powershell
.\avvia_demo.ps1
```

Richiede un ambiente `.venv` già preparato e configura un DB Demo separato. Il launcher Windows esiste nel repository, ma non è stato eseguito in questa revisione macOS.

Su macOS/Linux, dalla radice del repository con `.venv` già disponibile, una prova usa un percorso temporaneo assoluto:

```sh
demo_dir="$(mktemp -d "${TMPDIR:-/tmp}/aitrading-demo.XXXXXX")"
TRADING_MODE=demo AUTO_TRADE=false ALPACA_API_KEY= ALPACA_SECRET_KEY= \
AI_TRADINGBOT_DEMO_DB_PATH="$demo_dir/simulation.sqlite3" \
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Non riutilizzare un database Paper o personale. Il comando sopra non è stato lanciato durante l'incarico. Aprire l'indirizzo locale stampato; Ctrl+C arresta il server. Il link pubblico temporaneo di altre sessioni non fa parte di questo avvio.

## 2. Mercato e strumento

Nella Dashboard scegliere categoria, strumento, intervallo e periodo. Il catalogo include azioni/ETF e crypto; la presenza nel menu non prova la negoziabilità Paper.

Per iniziare senza credenziali, attivare esplicitamente **Usa serie sintetica demo**, scegliere **1Day** e premere **Aggiorna dati**. Non scegliere dati sintetici per valutare redditività.

Senza fonte reale disponibile e senza Demo esplicita, l'app mostra indisponibilità: non sostituisce un feed fallito con prezzi inventati.

## 3. Fonte, tempo e grafico

Controllare origine, qualità, intervallo e timestamp. SYNTHETIC / DEMO significa dati generati. L'ora di acquisizione non è l'ora della barra né la prova che il mercato sia aperto.

DATI OBSOLETI o FUTURI non sono dati utilizzabili. La quotazione corrente può mancare mentre lo storico rimane visibile. In caso di errore, aggiornare la selezione e leggere il motivo, senza premere comandi operativi.

Candlestick = prezzi OHLC; linee SMA = medie; triangoli = incroci tecnici; stelle/uscite = ledger locale. Gli ordini e i fill Paper hanno nomi diversi e non compaiono sovrapposti alla Demo. Un prezzo di riferimento non è un fill.

Il menu **Impostazioni avanzate** contiene ricerca e RSI. La legenda Plotly permette di nascondere serie; non cambiano per questo i segnali o il rischio.

## 4. Segnale e proposta

Leggere **Segnale tecnico (SMA crossover)**: stato, strumento, timeframe, parametri, close, medie e timestamp. Aprire i dettagli per limiti e dati disponibili.

BUY non è un ordine. EXIT non significa posizione già venduta. Nessun segnale non è sinonimo di dati insufficienti o rischio bloccato. La barra mostrata può essere in formazione.

Stop, target e rapporto rischio/rendimento sono N/D quando la SMA non li definisce. Non ricavare livelli dalla distanza delle linee del grafico.

## 5. Conto virtuale

La scheda **Simulazione** usa un conto locale distinto. Prima di crearlo serve un cambio con fonte/data, recuperato o inserito consapevolmente dall'utente. Non viene inventato un cambio corrente.

Durante una prova esclusivamente di lettura evitare **Conferma acquisto simulato**, **Conferma vendita simulata** e **Azzera simulazione locale**: modificano il ledger, anche se non inviano ordini al broker.

## 6. Monitor e anteprima Paper

Questo passo richiede un conto Paper e credenziali fornite separatamente nell'ambiente. Non inserire segreti nella documentazione o in chat. Usare il launcher esistente `avvia_paper.ps1` soltanto dopo aver predisposto l'isolamento; la sua esecuzione non è verificata qui su Windows.

**Verifica e aggiorna conto Alpaca Paper** legge uno snapshot; non invia un ordine. Leggere cash, equity e buying power come campi diversi. P/L non disponibile resta N/D. Il valore delle posizioni è valore di mercato, non costo storico.

**Esegui anteprima DRY-RUN** effettua una sola valutazione senza submit e lascia l'automazione arrestata. Una proposta valida mostra quantità e prezzo bid/ask di riferimento; dati, rischio o segnale mancanti producono un motivo, non un ordine.

Evitare **Avvia automazione Paper** durante queste prove: è un comando distinto che può abilitare invii Paper. Non eseguire i comandi firmati della CLI Hyperliquid per provare la dashboard.

## 7. Attività, log ed errori

Posizioni, ordini pending e quantità eseguite non sono la stessa cosa. Filtrare gli ordini nel monitor e leggere l'elenco delle esecuzioni confermate quando disponibile. Una conferma parziale non chiude automaticamente tutto l'ordine.

Nel pannello Paper filtrare le decisioni ed esportare gli eventi mostrati in CSV. Il log è limitato agli ultimi 25 eventi nella UI; non rappresenta uno storico completo. Campi assenti non vengono inventati.

Se lo snapshot fallisce, i valori verificati vengono nascosti e la connessione va riverificata. Con una risposta ordini di 500 elementi l'app si blocca prudentemente: non azzerare lo storico per aggirare il controllo. **Arresto immediato** non cancella ordini già presenti sul broker.

## 8. Backtest e walk-forward

Caricare prima dati e scegliere SMA, capitale e costi. In **Backtest** premere **Esegui backtest**. Leggere rendimento insieme a periodo, costi, capitale e numero di operazioni. Su Demo serve solo a provare il software.

Il walk-forward distingue training e test successivo. Peggioramenti fuori campione e campioni piccoli sono limiti informativi; non vanno nascosti scegliendo a posteriori il periodo migliore. I fold non vengono composti come conto continuo.

## 9. Controlli automatici

```sh
python -m compileall -q app.py config src tests
python -m pytest -q
git diff --check
```

Usare l'interprete della `.venv`. Il guard pytest vieta rete e file locali delle credenziali; non lo disabilitare per ottenere test verdi. Non occorre aprire il browser o un conto per questi test.

Restano da verificare manualmente leggibilità su finestre strette e resa visuale, oltre a Windows e servizi autentici. Consultare [WORKLOG](WORKLOG.md), [decisioni](DECISIONI_TECNICHE.md) e [roadmap](REVIEW_QUALITA_E_ROADMAP.md) prima di proseguire.

## Blocchi P1 introdotti

Una connessione Paper verificata non abilita più da sola l'invio: per default l'esecutore operativo è disabilitato. Il pulsante di avvio resta bloccato senza coordinatore di conto. L'anteprima non acquisisce alcun permesso di invio.

La configurazione tecnica comprende `PAPER_EXECUTION_SCOPE` (default `disabled`, unico scope operativo supportato `single_host`) e `PAPER_COORDINATOR_DIRECTORY` (directory assoluta locale comune a tutti i processi). Non sono stati attivati durante questa revisione. Non configurarli come scorciatoia per un deployment su più macchine: occorre prima il servizio esecutore unico descritto nella roadmap.

Se compare un intento incerto, pending o con fill, l'operatività rimane bloccata. Non cancellare file lock o journal e non ricreare un DB per ripartire. Solo un terminale con zero fill verificato permette il recupero automatico previsto. La riconciliazione completa dei fill è ancora da realizzare.

Per l'anteprima con dati reali occorre anche un contratto temporale supportato. Daily grezzi/weekly non verificati rimangono utilizzabili per analisi, ma non per generare ordini. I dati intraday equity operativi sono filtrati alla seduta regolare; crypto intraday resta continuo. Un errore di calendario o un mercato chiuso è un blocco, non un invito a cambiare l'orologio o ad allargare le soglie.
