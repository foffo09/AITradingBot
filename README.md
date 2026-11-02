# AI Trading Bot

Dashboard locale per analisi, backtest, simulazione locale e monitoraggio Alpaca Paper. L'automazione Paper è disattivata all'avvio e richiede avvio esplicito dalla dashboard; live trading non è supportato.

La [revisione di qualità e roadmap](docs/REVIEW_QUALITA_E_ROADMAP.md) distingue correzioni verificate, limiti operativi e interventi ancora necessari.

## Avvio in tre passaggi

1. In PowerShell, dalla cartella del progetto, prepara l'ambiente solo se non esiste:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. Avvia la dashboard:
   ```powershell
   .\avvia_demo.ps1
   ```
   Per una connessione Alpaca Paper isolata usa invece `.\avvia_paper.ps1`; il comando Streamlit diretto richiede la variabile DB isolata della modalità selezionata.
3. Apri l'indirizzo locale mostrato da Streamlit.

## Avvio demo con ledger isolato

Per provare la dashboard senza credenziali e senza usare il ledger personale, apri PowerShell nella cartella del progetto ed esegui:

```powershell
.\avvia_demo.ps1
```

Lo script forza `TRADING_MODE=demo` e `AUTO_TRADE=false`, non carica `.env` né credenziali Alpaca e configura un database dedicato in `%LOCALAPPDATA%\AITradingBot\demo\simulation.sqlite3`. Verifica il percorso prima di avviare Streamlit; se la cartella isolata non è disponibile o il percorso non è sicuro, l'avvio si interrompe senza ricadere su `data\simulation.sqlite3`. La serie sintetica va selezionata esplicitamente nell'interfaccia ed è sempre etichettata come demo. Streamlit ascolta solo su `127.0.0.1`; premi **Ctrl+C** nella finestra PowerShell per arrestare l'app.

Per uno smoke test con storage e porta temporanei, puoi specificarli senza modificare il comportamento normale:

```powershell
$demoDb = Join-Path $env:TEMP ("AITradingBot-demo-smoke-" + [guid]::NewGuid().ToString("N") + "\simulation.sqlite3")
.\avvia_demo.ps1 -DatabasePath $demoDb -Port 8765
```

Il percorso DB passato deve essere assoluto. Lo script controlla la porta loopback prima dell'avvio e fallisce se è già occupata.

## Avvio Paper isolato

1. Usa `.env.example` come riferimento per la configurazione pubblica. Fornisci `ALPACA_API_KEY` e `ALPACA_SECRET_KEY` tramite l'ambiente del processo, senza salvarle nel repository o inserirle in chat.
2. Avvia con:
   ```powershell
   .\avvia_paper.ps1
   ```
   Il launcher imposta `TRADING_MODE=paper`, lascia l'automazione disattivata, controlla porta e percorso e usa `%LOCALAPPDATA%\AITradingBot\paper\simulation.sqlite3`. Per un database temporaneo puoi passare `-DatabasePath` assoluto e `-Port`. Il file paper non può coincidere con `data\simulation.sqlite3`.
3. Verifica l'account nella scheda Panoramica. Il monitor aggiorna account, posizioni e ordini ogni 15 secondi finché la dashboard resta aperta. Quote e barre OHLC recenti sono aggiornate con polling incrementale ogni 15 secondi: il mid-price è una linea separata e non viene inventata una candela o un volume dalle quote. Lo storico più ampio si ricarica manualmente; non è attivo uno stream WebSocket.
4. La Panoramica Paper distingue cash, equity, buying power, valore investito, P/L non realizzato e variazione equity rispetto alla chiusura precedente. Il P/L totale e realizzato sono `N/D` con motivazione quando l'API non fornisce dati affidabili. Il prezzo medio, prezzo corrente, valore, P/L e quantità disponibile per ciascuna posizione sono mostrati solo se restituiti dall'account.
5. La disponibilità dati e la negoziabilità sono controlli separati. Prima di inviare un ordine automatico il bot verifica che l'asset sia negoziabile Paper, usa ask per l'acquisto e bid per la vendita, rispetta frazionabilità, quantità minima e incremento comunicati dal broker e blocca l'ordine se le regole non sono verificabili. Il buying power e i limiti RiskManager sono verificati separatamente; saldo ridotto non implica che ogni titolo sia acquistabile.
6. L’invio è disabilitato per default senza un coordinatore esclusivo del conto. L’anteprima DRY-RUN rimane separata e richiede dati con contratto temporale verificato. **Avvia automazione Paper** richiede anche una configurazione single_host esplicita e non supporta deployment distribuiti; non attivarlo durante prove di sola lettura. Lo stato non è memorizzato nella configurazione e parte arrestato a ogni nuova sessione. **Arresto immediato** impedisce i cicli successivi, ma non annulla ordini già inviati: gli ordini pending o parziali vanno gestiti separatamente sul conto Paper. Timestamp, segnale, decisione, stato ordine e motivo sono registrati nel log SQLite locale della modalità Paper, senza credenziali.

In assenza di credenziali utilizzabili, la configurazione ricade su demo e il launcher Paper non riutilizza il database locale personale: l'avvio si interrompe in assenza del percorso DB demo isolato, invece di aprire un conto o un ledger inatteso.

## Strumenti e dati

In **Mercati e strumenti** cerca o seleziona SPY, QQQ, GLD, AAPL, MSFT, NVDA oppure le criptovalute BTC/USD ed ETH/USD. La verifica di negoziabilità dell'asset paper e la richiesta dei dati sono controlli distinti; dati e strumenti effettivamente disponibili dipendono da account e permessi Alpaca. La dashboard distingue i dati Alpaca reali, la serie sintetica locale esplicitamente richiesta e i dati non disponibili, mostrando fonte e timestamp della barra e dell'acquisizione quando disponibili.

Scegli l'intervallo e il periodo, quindi premi **Aggiorna dati**. Le azioni/ETF usano il feed IEX di Alpaca (copertura parziale); le criptovalute usano l'API dati crypto. Se una richiesta reale fallisce, la dashboard mostra l'errore e non sostituisce i prezzi con prezzi inventati. La casella **Usa serie sintetica demo** è un'azione esplicita e genera una serie giornaliera chiaramente etichettata come sintetica. Puoi confrontare fino a quattro strumenti; il grafico TradingView è un collegamento esterno e non è collegato al bot.

## Conto locale e operazioni

Il conto virtuale SQLite usa il percorso isolato configurato dal launcher Demo o Paper ed è indipendente dal saldo Alpaca. `data/simulation.sqlite3` è il percorso del ledger personale storico e non viene accettato come destinazione delle istanze isolate. Alla prima inizializzazione il capitale predefinito è 100 EUR: serve un EUR/USD ottenuto con **Recupera cambio EUR/USD** (Frankfurter/ECB) oppure un valore verificato inserito manualmente. Fonte e timestamp vengono salvati. In assenza del cambio, non si inventa un tasso e il conto non viene creato.

Carica dati freschi e usa la scheda **Simulazione** per inviare un acquisto long o vendere una quantità già detenuta. Ogni conferma dell'utente applica cash, esposizione, limite per operazione, perdita giornaliera, commissione, spread e slippage stimati. Non sono previsti leva o short selling. Entry, uscite parziali, prezzi, motivi, costi e P/L lordo/netto vengono persistiti; le posizioni ancora aperte sono mostrate come non realizzate. Il comando di azzeramento richiede una checkbox di conferma.

La traduzione del P/L in EUR usa il cambio di riferimento registrato all'avvio del conto, non un cambio corrente. Il valore è mostrato come tale.

## Backtest

Seleziona simbolo, timeframe e periodo nella sezione **Mercato** della **Dashboard**, poi scegli esplicitamente i dati storici Alpaca oppure la serie sintetica demo. I dati storici non passano mai automaticamente alla serie sintetica in caso di errore. La copertura è quella del feed disponibile per il conto (per azioni/ETF è richiesto il feed IEX); controlla fonte, simbolo, timeframe, numero di barre e date mostrate prima di eseguire il backtest. Apri **Backtest**, inserisci il capitale in USD, modifica i periodi delle medie e premi **Esegui backtest**. I segnali sono calcolati alla chiusura della barra e l'esecuzione simulata avviene all'apertura della barra successiva. I risultati vengono mostrati solo se serie, fonte e parametri corrispondono ancora alla selezione corrente; modificandoli, riesegui il backtest. P/L lordo, P/L netto realizzato, P/L non realizzato, commissioni, spread e slippage stimati sono distinti; il capitale finale valuta l'eventuale posizione aperta al valore netto stimato di liquidazione. Il benchmark buy-and-hold usa lo stesso capitale, entra al primo open disponibile e viene valutato al close finale, con le stesse ipotesi di costo.

I costi sono ipotesi esplicite modificabili nella dashboard: per default la commissione e lo slippage sono ciascuno 5 bps per esecuzione, mentre il backtest applica 10 bps di spread completo (circa 5 bps per lato, circa 10 bps round trip). Sono stime, non dati storici di esecuzione; impostare un costo a zero equivale a escluderlo deliberatamente dal modello.

Volatilità e Sharpe sono annualizzati in base all'intervallo selezionato: 252 sessioni USA per azioni/ETF, oppure 365 giorni per crypto (52 settimane per dati settimanali). Sharpe assume tasso privo di rischio annuo pari a 0%; i rendimenti barra-su-barra sono trattati come campionamento regolare. Se il campione è insufficiente o la volatilità è zero, il valore non viene presentato come significativo. Queste convenzioni sono approssimazioni e possono non rappresentare sessioni mancanti o irregolari. I risultati sono separati dal conto locale e dall'account Alpaca, e non prevedono rendimenti futuri.

Il backtest standard usa l'intera serie fornita e non seleziona automaticamente i parametri: se vengono scelti osservando gli stessi risultati, la performance è in-sample e soggetta a overfitting. La sezione **Valutazione walk-forward — risultati fuori campione** usa invece i dati correnti già caricati e seleziona, per ogni training fold, il migliore rendimento netto dopo i costi tra tre coppie fisse di medie (2/4, 3/6, 5/10). Training e test sono cronologici e disgiunti; le dimensioni del training e di ogni test si possono impostare entro i limiti mostrati, mentre il passo coincide col test per evitare sovrapposizioni. Fonte, ticker, intervallo, periodo, costi, capitale o dimensioni cambiati invalidano/nascondono i risultati precedenti.

I risultati mostrano separatamente date di training e test, parametri selezionati nel training, performance OOS della strategia e buy-and-hold, drawdown e costi. I fold sono simulazioni indipendenti: ognuno riparte dal capitale iniziale e non trasferisce saldo o posizioni. Per questa ragione non viene prodotto un rendimento OOS aggregato o composto, che suggerirebbe continuità del portafoglio non modellata. Metriche di volatilità/Sharpe n/d indicano campione insufficiente o volatilità nulla. In un walk-forward sequenziale, dati già OOS possono entrare nel training di un fold successivo solo dopo essere diventati dati storici; non influenzano la selezione o i risultati OOS dei fold precedenti. I risultati restano analisi storiche in-sample/OOS distinte e non sono garanzia di performance future.

Se la serie è vuota o non contiene abbastanza barre per la media mobile lunga, la strategia restituisce nessun segnale e un messaggio esplicito sui dati insufficienti.

## Alpaca Paper, automazione e credenziali

Il client di trading viene costruito solo in modalità Paper con `paper=True`. L'invio richiede account attivo e verificato, dati Alpaca reali e freschi, quote recenti, cash/buying power/equity disponibili, limiti RiskManager, esposizione complessiva, limite giornaliero e assenza di ordini pendenti duplicati. Gli ordini sono market order long-only e hanno un `client_order_id` deterministico; l'app mostra lo stato API e non dichiara un fill prima della conferma del broker. La verifica automatica usa ordini mockati; l'effettiva connessione e i permessi non sono verificabili senza credenziali Paper dell'utente.

Il monitor Paper è distinto dal ledger Demo locale e dal backtest. Se una richiesta del conto fallisce, i valori dell'ultimo snapshot non vengono presentati come aggiornati; occorre riverificare la connessione. Il feed quotazioni e le barre OHLC sono aggiornati con polling incrementale; non viene promesso un feed istantaneo né viene aperto un WebSocket. Se il dato è sintetico, vecchio, mancante, il conto si disconnette o la negoziabilità/quantità non è verificabile, la generazione ordini è bloccata e l'automazione si arresta.

La lettura ordini richiede fino a 500 record. Se la risposta raggiunge questo limite, monitor e automazione si bloccano perché lo storico potrebbe essere incompleto: non viene usato per stimare il numero di ordini giornalieri o escludere pendenti. La paginazione completa rimane nella roadmap.

**Esegui anteprima DRY-RUN** valuta una volta segnale, conto, dati e rischio senza chiamare `submit_order`; una proposta valida mostra quantità e bid/ask di riferimento. L'automazione resta arrestata. **Avvia automazione Paper** è un comando separato che può inviare ordini Paper; il DRY-RUN continuo rimane da progettare. Stop, target e rischio fino allo stop sono N/D perché la SMA non definisce quei livelli.

La guida operativa è [Come usare la dashboard](docs/COME_USARE_LA_DASHBOARD.md). Per architettura, formule e limiti vedere [Guida completa](docs/GUIDA_COMPLETA_PROGETTO.md), [decisioni tecniche](docs/DECISIONI_TECNICHE.md), [matrice test](docs/MATRICE_TEST.md) e [registro del lavoro](docs/WORKLOG.md).

I dati gratuiti Alpaca possono essere limitati da piano, feed e permessi; IEX non copre l'intero mercato USA. Dati sintetici servono solo a provare grafici e flusso demo.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Protezioni P1

Il coordinatore Paper mantiene un lock OS per conto durante verifica/rischio/invio e registra un intento durevole prima del submit. Timeout, crash o fill non riconciliati bloccano altri invii; il submit diretto senza lease è rifiutato. Default: esecuzione disabilitata. I processi devono condividere host e directory; multi-host e riconciliazione piena dei fill restano aperti.

Le barre operative usano il calendario NYSE e il contratto del feed. RTH, DST, festività e chiusure anticipate sono testati offline; timestamp futuri, duplicati, fuori ordine o senza fuso bloccano la valutazione. Daily grezzi/weekly non verificati rimangono di sola analisi; nessuna chiusura è inventata. Consultare D10–D11 e la guida prima di configurare l'esecuzione.

## Verifica Windows e dipendenze test

Per installare tutti gli SDK richiesti dai test usare `python -m pip install -r requirements-dev.txt`.
La [procedura Windows e le decisioni sul locking](docs/INSTALLAZIONE_WINDOWS.md) distinguono
installazione base, suite completa e verifiche di piattaforma ancora da eseguire.
