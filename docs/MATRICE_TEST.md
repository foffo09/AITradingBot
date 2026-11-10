# Matrice dei test e dell'evidenza

Legenda: **CODICE** = ispezionato; **TEST** = esecuzione automatica locale; **MOCK** = integrazione sostituita; **NON VERIFICATO** = manca una prova; **FUTURO** = proposta non implementata.

Piattaforme effettivamente provate: macOS (`.venv` Python 3.12.14, esecuzioni storiche) e Windows (Python 3.11.9, suite completa del 2026-11-02). I numeri puntuali sono nel [WORKLOG](WORKLOG.md). I risultati sono specifici per piattaforma; la suite automatica Windows non certifica l'UX interattiva completa né integrazioni autentiche.

| Area | Test principali | Casi/evidenza | Limiti |
| --- | --- | --- | --- |
| Policy test offline | `test_test_isolation.py`, `conftest.py` | Eventi rete e file vietati, contatori e fixture consentite; ambiente ripulito prima della raccolta; su Windows, self-pipe Proactor interna distinta dalle connessioni applicative | Eccezione circoscritta a `socket.socketpair` → `_make_self_pipe` su loopback IPv4; le altre connessioni loopback restano vietate. Policy non è sandbox contro codice ostile |
| Numeri e formule UI | `test_ui_presentation.py` | Zero/None distinti, stringhe invalide, bool, NaN/infinito, denominatore zero, overflow, aggregati broker | Nessun servizio autentico |
| Dati e segnale UI | `test_ui_presentation.py`, `test_dashboard_validation.py` | Fresh/stale/future/invalid, SMA, dati insufficienti, fonte sintetica, timestamp della quotazione | Calendario NYSE/intraday verificato con fixture; protocollo autentico e aggregati non supportati esclusi |
| Grafico | Sei casi parametrizzati in `test_dashboard_validation.py`, test helper | Ledger vuoto/chiuso, pending/fill, prezzi dei marker, SMA/volume/RSI; dati vuoti/incompleti; Demo senza overlay Paper | Resa visuale manuale e responsive NON VERIFICATE |
| Snapshot Paper | `test_dashboard_validation.py`, `test_paper_safety.py` | Campi broker e N/D; refresh riuscito mostra `Verificata`; errore mostra `Errore`, rimuove la vecchia equity e arresta l'automazione; rerun app di sincronizzazione senza snapshot duplicato | MOCK; nessuna verifica contabile autentica |
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
| Console/TUI | `test_omega.py` | Runtime locale; regressione stdin/cancellazione TUI su Windows passa con pipe | UX interattiva completa e uvloop Windows NON VERIFICATI; suite offline, nessun servizio |
| Provider aggiuntivi | `test_providers.py` | Errori, fallback, quote e interfacce AI con transport fittizi | MOCK; nuovi feed live non provati |
| Hyperliquid nativo | `test_hyperliquid_testnet.py` | Mainnet/redirect bloccati, fill parziali, timeout, riavvio, stop/panic con broker simulato | Ordini autentici testnet NON VERIFICATI |

## Comandi supportati

```sh
python -m compileall -q app.py config src tests
python -m pytest -q tests/test_dashboard_validation.py tests/test_ui_presentation.py tests/test_paper_safety.py tests/test_paper_automation.py tests/test_test_isolation.py
python -m pytest -q
git diff --check
```

Il `conftest.py` viene importato da pytest anche se non è nell'elenco del comando compileall. Errori del guard non devono essere aggirati: correggere il mock o il percorso. Il report `TEST ISOLATION` deve avere contatori zero per la suite; i test della policy usano una propria istanza per gli eventi simulati, mentre il caso Proactor costruisce un event loop locale e non interroga servizi esterni.

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

## Portabilità dei journal — 2026-10-30

`test_native_store.py`: esclusione tra handle e processi spawn, rilascio dopo
crash, close ripetuto, errori connect/schema/scope/backend/unlock, URI panic
con spazi e #. `test_paper_coordinator.py` conserva i test di esclusione,
deadline e incertezza e aggiunge errore backend senza autorità.
Esecuzione effettiva su macOS; Windows NON ESEGUITO. Procedura e limiti in
[INSTALLAZIONE_WINDOWS](INSTALLAZIONE_WINDOWS.md). Nessun test preesistente rimosso.

## Consolidamento dashboard Persona 2 — 7 novembre 2026

| Test | Casi nuovi |
| --- | --- |
| `test_dashboard_metrics.py` | Metriche locali/Paper separate, N/D, quote stale/future/invalide, provenienza, storico esplicito |
| `test_signal_refresh.py` | Invocazioni ripetute del fragment senza full rerun: nuovo frame, gate scaduto e selezione cambiata; timer browser non provato |
| `test_ui_charts.py` | Candele/volume/SMA/RSI, range intraday/daily, zoom/pan/reset, uirevision |
| `test_ui_workspaces.py` | Tre percorsi distinti, alias/hard link rifiutati, percorsi Unicode, DB personale escluso |
| `test_dashboard_contexts.py` | AppTest: cambi contesto, azzeramento stato, zero SDK offline, saldi e storico separati, snapshot scaduti/futuri |
| `test_dashboard_validation.py` | Metadati non reinterpretati, acquisizione backend conservata, segnale filtrato sulle barre concluse |

Test con mock e file temporanei. Browser visuale, Windows e broker autentici
non verificati per questa modifica. Restano i limiti del backend e del
coordinamento descritti nel relativo handoff.

### Contratti effettivi backend — completamento Persona 2

`test_signal_refresh.py` invoca anche il gate backend reale: quota corrente,
assente/scaduta/futura, fonti mancanti o contraddittorie, righe sintetiche,
contratto temporale assente, barre vecchie e refresh fallito. Verifica che
`operational_data` non diventi True e che gli input restino invariati.
`test_dashboard_validation.py` verifica conservazione integrale dei metadati
quote e rifiuto di refresh con fonte/calendario/sessione/contratto discordanti.
Il contratto aggiornato è [DASHBOARD_HANDOFF](../DASHBOARD_HANDOFF.md).

## Persona 3 — Motore strategie

| Test nuovo | Evidenza |
| --- | --- |
| test_trend_strategy | EMA causali, BUY/SELL/WAIT, filtro trend, no segnali ripetuti, prefissi invarianti, RSI/volume diagnostici |
| test_trade_levels | ATR/struttura, ordinamento livelli, spread, RR insufficiente, dati mancanti/invalidi |
| test_strategy_risk | Budget stop/costi, cap notional/globali, DD/perdita/counter, cash, long-only, simbolo, nessuna crescita rischio dopo perdita |
| test_strategy_engine | Gate reale e provenienza, quote, entry, expiry, ID replay/config, snapshot Paper e simbolo, JSON rifiuti, nessun submit |
| test_strategy_backtest | Next-open, TP/SL/gap/ambiguità, costi, expectancy/R e causalità, SMA default invariata |
| test_strategy_partitions | Tranche disgiunte, closed_at, barre incomplete escluse, capitale/indicatori indipendenti, nessuna contaminazione futura |

Fonte sintetica controllata, non redditività di mercato. Nessuna verifica
Windows/broker autentico in questa fase. Contratti e limiti nel
[STRATEGY_HANDOFF](../STRATEGY_HANDOFF.md); esiti delle suite nel WORKLOG.

## Sprint 02 — CI Windows / Python 3.11 (11 novembre 2026)

Base ricontrollata: `fe988394d6ecdcb56763a81c627943b4cbe684e1`.
Workflow: [windows-ci.yml](../.github/workflows/windows-ci.yml), runner
`windows-latest`, Python `3.11`. Trigger PR verso `main` e `workflow_dispatch`;
permesso unico `contents: read`, credenziali checkout non persistite, nessun
secret broker. Contesto Demo, automazione/esecuzione disabilitate e dotenv
spento. Nessuna modifica a codice, test, requisiti o guard di isolamento.

| Sistema / prova | Stato | Evidenza |
| --- | --- | --- |
| macOS 27.2.1 arm64 / Python 3.11.18 | PASS baseline locale del 10 novembre | 152 mirati; suite 747 passati, 0 falliti, 1 skip Windows Proactor; guard rete/credenziali 0/0; compilazione, pip check e diff-check PASS. Non è una nuova esecuzione Sprint 02. |
| macOS / Python 3.11.18 | PASS ricontrollo locale dell’11 novembre | Stesso codice base: 747 passati, 0 falliti, 1 skip Proactor in 34,87 s; guard 0/0. Compilazione e pip check PASS. Non è una prova Windows. |
| Windows / Python 3.11 / GitHub Actions | NON VERIFICATO — in attesa di run reale | Scrivere il workflow non prova la portabilità. Run e risultati saranno registrati dopo l'esecuzione Windows. |
| Altri sistemi/versioni, broker autentico, multi-host e UI interattiva | NON VERIFICATO in questa consegna | Nessun avvio server, feed o trading. Restano valide le sole evidenze storiche già datate sopra. |

La sequenza CI installa `requirements-dev.txt`, compila app/config/src/tests,
esegue i sei file mirati assegnati e la suite completa `pytest -q -rs`, quindi
pip check e diff-check. Il report JUnit verifica che il caso Windows Proactor
sia presente, eseguito e non saltato. I log di entrambi i gruppi devono contenere
il riepilogo del guard a zero; i controlli originali non sono alterati.
Il controllo whitespace verifica anche il delta base/head della PR (e non
solo il checkout pulito); nel dispatch verifica l’ultimo commit.
I check di isolamento, dipendenze e whitespace proseguono anche dopo errori dei
test per raccogliere evidenza, senza trasformare un fallimento in successo.

Per il primo run è necessaria una PR: il dispatch manuale richiede che il
workflow sia già presente sul branch predefinito. Questo incarico non autorizza
il merge su main. [Documentazione GitHub sul dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
Le azioni ufficiali sono bloccate ai commit delle release
[checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) e
[setup-python v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0).
