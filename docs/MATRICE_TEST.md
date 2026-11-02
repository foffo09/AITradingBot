# Matrice dei test e dell'evidenza

Legenda: **CODICE** = ispezionato; **TEST** = esecuzione automatica locale; **MOCK** = integrazione sostituita; **NON VERIFICATO** = manca una prova; **FUTURO** = proposta non implementata.

Piattaforma eseguita: macOS, `.venv` Python 3.12.14. I numeri puntuali di ciascuna esecuzione sono nel [WORKLOG](WORKLOG.md). Windows non è implicitamente coperto da questi risultati.

| Area | Test principali | Casi/evidenza | Limiti |
| --- | --- | --- | --- |
| Policy test offline | `test_test_isolation.py`, `conftest.py` | Eventi rete e file vietati, contatori e fixture consentite; ambiente ripulito prima della raccolta | Policy testata con eventi simulati; non è sandbox contro codice ostile |
| Numeri e formule UI | `test_ui_presentation.py` | Zero/None distinti, stringhe invalide, bool, NaN/infinito, denominatore zero, overflow, aggregati broker | Nessun servizio autentico |
| Dati e segnale UI | `test_ui_presentation.py`, `test_dashboard_validation.py` | Fresh/stale/future/invalid, SMA, dati insufficienti, fonte sintetica, timestamp della quotazione | Calendario NYSE/intraday verificato con fixture; protocollo autentico e aggregati non supportati esclusi |
| Grafico | Sei casi parametrizzati in `test_dashboard_validation.py`, test helper | Ledger vuoto/chiuso, pending/fill, prezzi dei marker, SMA/volume/RSI; dati vuoti/incompleti; Demo senza overlay Paper | Resa visuale manuale e responsive NON VERIFICATE |
| Snapshot Paper | `test_dashboard_validation.py`, `test_paper_safety.py` | Campi broker e N/D; errore aggiornamento elimina anche la vecchia equity | MOCK; nessuna verifica contabile autentica |
| Isolamento DB | `test_dashboard_validation.py`, `test_simulation_ledger.py` | Percorso personale rifiutato, modalità diverse, hard link e inizializzazione bloccata prima del broker | File esclusivamente temporanei |
| Ledger | `test_simulation_ledger.py` | Costi, uscite parziali, duplicati letterali, riavvio, timestamp fuori ordine e dati legacy | Crescita di mesi e stress concorrente prolungato FUTURI |
| Cambio | `test_fx_rates.py` | Risposte simulate, valori/date invalidi, timeout richiesto, valore/data mantenuti | Fonte live NON interrogata |
| Client Alpaca | `test_broker.py`, `test_paper_safety.py` | Client Paper, OHLCV, quote, errori e limite ordini saturo | MOCK; paginazione completa FUTURA |
| Rischio | `test_risk_manager.py`, `test_paper_automation.py` | Cash, limiti, esposizione, perdita, vendita senza short, incrementi | Esclusione locale e intenti testati; multi-host e riconciliazione fill FUTURI |
| Anteprima DRY-RUN | `test_paper_automation.py`, test UI avvio/arresto | BUY ed EXIT dimensionati senza chiamare submit; dati sintetici/stale rifiutati; preview non attiva il loop | MOCK; non è loop DRY-RUN continuo |
| Invio Paper preesistente | `test_paper_automation.py` | Fake broker, verifica, pending, duplicati, errori e stato distinto dal fill | Nessun ordine autentico eseguito |
| Strategia SMA | `test_strategy.py` | Incrocio, hold, finestre e dati insufficienti | Nessuna prova di redditività |
| Backtest | `test_backtest_execution.py`, `test_backtesting.py` | Open successivo, costi, posizioni aperte, benchmark, metriche | Costi configurati, non misurati da esecuzioni reali |
| Walk-forward | `test_walk_forward.py` e test UI | Separazione temporale, parametri dal training, fold esclusi, invalidazione risultati | Portafoglio OOS continuo non implementato |
| Console/TUI | `test_omega.py` | Runtime locale, controlli e cancellazione TUI su pipe | Windows, fcntl e uvloop NON VERIFICATI come flusso portabile |
| Provider aggiuntivi | `test_providers.py` | Errori, fallback, quote e interfacce AI con transport fittizi | MOCK; nuovi feed live non provati |
| Hyperliquid nativo | `test_hyperliquid_testnet.py` | Mainnet/redirect bloccati, fill parziali, timeout, riavvio, stop/panic con broker simulato | Ordini autentici testnet NON VERIFICATI |

## Comandi supportati

```sh
python -m compileall -q app.py config src tests
python -m pytest -q tests/test_dashboard_validation.py tests/test_ui_presentation.py tests/test_paper_safety.py tests/test_paper_automation.py tests/test_test_isolation.py
python -m pytest -q
git diff --check
```

Il `conftest.py` viene importato da pytest anche se non è nell'elenco del comando compileall. Errori del guard non devono essere aggirati: correggere il mock o il percorso. Il report `TEST ISOLATION` deve avere contatori zero per la suite; i test della policy usano una propria istanza non collegata a socket o file reali.

Prima di chiudere una fase servono lettura del diff, test pertinenti, provenienza dei dati e documentazione. Prima di dichiarare compatibilità Windows o correttezza di un conto autentico servono esecuzioni separate effettive.

## P1 — Coordinatore Paper

`test_paper_coordinator.py` copre tre processi simultanei con snapshot vuoto, proprietà non scadibile, decisione scaduta, rilascio su eccezione, crash con intento persistito, recupero limitato a terminali zero-fill, account/thread errati, journal corrotto e piattaforma senza flock. Nessun ordine nel worker: solamente intenti fittizi su SQLite temporanei.

`test_paper_automation.py` aggiunge tre sessioni con snapshot indipendenti obsoleti: solo un submit sul fake broker, le altre bloccate. Identità cambiata e coordinatore assente non arrivano al submit. Il test client conserva la prova del request builder sotto lease e aggiunge il rifiuto del submit diretto e del riuso del permesso. Non è una prova su Alpaca.

NON VERIFICATO / BLOCCATO: multi-host, directory divergenti, Windows operativo e riconciliazione automatica di fill. Invii disabilitati per default.

## P1 — Calendario e integrazione delle barre

`test_bar_timing.py`: 29 casi deterministici su apertura regolare, cambio DST primavera/autunno, festività, weekend, early close, daily RTH prima/dopo chiusura, acquisizione precedente alla chiusura, margine di pubblicazione, pre/post-market, crypto intraday 24/7, barre future/duplicate/fuori ordine/senza fuso/invalide/stale/disallineate, close zero/NaN, aggregati non verificati e dipendenza assente.

`test_paper_automation.py`: ulteriori integrazioni verificano rifiuto dei dati invalidi prima di leggere l'account e di quote future di un solo secondo. Il clock dei test è fissato alla seduta del 28 ottobre 2026. `test_paper_safety.py` controlla gli attrs di contratto prodotti dall'adattatore su risposta fittizia.

Le durate in UI/ledger sono limiti di freschezza della presentazione o simulazione; non sostituiscono il calendario operativo Paper. Le durate per query/lookback non autorizzano barre. Restano NON VERIFICATI autenticazione/feed reale, eventi eccezionali del calendario dopo la release, immutabilità del feed e deployment Windows/multi-host.

Ulteriore regressione integrata: la seduta chiude durante l'ultima verifica broker. Il clock controllato porta la decisione fuori seduta prima dell'autorizzazione; il test falliva prima del ricontrollo finale e deve ora dimostrare zero submit. Il test del request builder usa una validazione no-op dichiarata perché verifica soltanto la serializzazione della richiesta fittizia, non sostituisce il test integrato.

Esito finale P1: 124 casi mirati passati; suite completa 386 passati, zero falliti/saltati, un warning in 24,01 s. Incremento rispetto a inizio sessione: 13 casi coordinatore + 29 calendario + 8 integrazioni = 50. Il dettaglio dei comandi e dei tentativi falliti intermedi resta nel WORKLOG.
