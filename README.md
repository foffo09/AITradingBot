# AI Trading Bot

Dashboard didattica per analisi, backtest e **simulazione locale**. Trading automatico disattivato; la dashboard non invia ordini ad Alpaca e il tab Alpaca è di sola lettura.

## Avvio in tre passaggi

1. In PowerShell, dalla cartella del progetto, prepara l'ambiente solo se non esiste:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
2. Avvia la dashboard:
   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```
   In alternativa fai doppio clic su `avvia_bot.bat`.
3. Apri l'indirizzo locale mostrato da Streamlit.

## Strumenti e dati

In **Mercati e strumenti** cerca o seleziona SPY, QQQ, GLD, AAPL, MSFT, NVDA oppure le criptovalute BTC/USD ed ETH/USD. La verifica di negoziabilità dell'asset paper e la richiesta dei dati sono controlli distinti; dati e strumenti effettivamente disponibili dipendono da account e permessi Alpaca.

Scegli l'intervallo e il periodo, quindi premi **Carica dati / applica selezione**. Le azioni/ETF usano il feed IEX di Alpaca (copertura parziale); le criptovalute usano l'API dati crypto. Se una richiesta reale fallisce, la dashboard mostra l'errore e non sostituisce i prezzi con prezzi inventati. La casella **Usa serie sintetica demo** è un'azione esplicita e genera una serie giornaliera chiaramente etichettata come sintetica. Puoi confrontare fino a quattro strumenti; il grafico TradingView è un collegamento esterno e non è collegato al bot.

## Conto locale e operazioni

Il conto virtuale SQLite, salvato in `data/simulation.sqlite3`, è indipendente da Alpaca. Alla prima inizializzazione il capitale predefinito è 100 EUR: serve un EUR/USD ottenuto con **Recupera cambio EUR/USD** (Frankfurter/ECB) oppure un valore verificato inserito manualmente. Fonte e timestamp vengono salvati. In assenza del cambio, non si inventa un tasso e il conto non viene creato.

Carica dati freschi e usa **Simulazione locale** per inviare un acquisto long o vendere una quantità già detenuta. Ogni conferma dell'utente applica cash, esposizione, limite per operazione, perdita giornaliera, commissione, spread e slippage stimati. Non sono previsti leva o short selling. Entry, uscite parziali, prezzi, motivi, costi e P/L lordo/netto vengono persistiti; le posizioni ancora aperte sono mostrate come non realizzate. Il comando di azzeramento richiede una checkbox di conferma.

La traduzione del P/L in EUR usa il cambio di riferimento registrato all'avvio del conto, non un cambio corrente. Il valore è mostrato come tale.

## Backtest

Carica una serie e apri **Backtesting**. Inserisci il capitale in USD, modifica i periodi delle medie e premi **Esegui backtest**. I segnali sono calcolati alla chiusura della barra e l'esecuzione simulata avviene all'apertura della barra successiva. Commissioni, spread e slippage sono ipotesi configurabili; i risultati sono distinti dal conto locale e dall'account Alpaca, e non prevedono rendimenti futuri.

## Alpaca Paper e credenziali

Per i controlli read-only Paper, crea `.env` copiando `.env.example` e aggiungi localmente le credenziali Paper. Non incollarle in chat. Non attivare modalità live. I client di trading sono costruiti con `paper=True`; il metodo di invio ordini del broker rifiuta sempre l'operazione. Senza credenziali, l'app resta utilizzabile in demo e non dichiara una connessione verificata.

I dati gratuiti Alpaca possono essere limitati da piano, feed e permessi; IEX non copre l'intero mercato USA. Dati sintetici servono solo a provare grafici e flusso demo.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
