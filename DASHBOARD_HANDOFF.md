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
