# Dashboard — consegna Persona 2, 7 novembre 2026

Branch: `feature/dashboard-ui`. Backend integrato con fast-forward al commit
`1a68d5bbc25f3e1b6eceb0235f9ea2fdfa033240`, senza modificare i suoi moduli.
Contratti di riferimento: [BACKEND_HANDOFF.md](BACKEND_HANDOFF.md).

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
un rerun completo. Una regressione invoca ripetutamente il corpo reale del
fragment; non verifica il timer nel browser.

I test UI usano Streamlit AppTest, broker finti e DB temporanei; i grafici
verificano oggetti Plotly e configurazione di navigazione. I risultati puntuali
sono nel WORKLOG. Nessun server, ordine, automazione o credenziale autentica è
stato utilizzato. Windows e resa visuale/interazioni nel browser non sono stati
eseguiti per questa consegna. L'automazione non viene certificata sicura dai test.

Prova manuale successiva: avviare il launcher Demo, inizializzare due capitali
diversi nei due contesti offline, registrare una sola operazione locale e
controllare l'isolamento; controllare grafico/zoom su desktop e schermo stretto.
Per Paper usare una prova separata autorizzata, senza avviare l'automazione.
