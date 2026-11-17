# Matrice dei test e dell'evidenza

## Missione master 17 novembre — nuova verifica locale

- Python completo seriale969PASS/1skipProactor/1warning39.33s,guard0/0;
  API57PASS2.19s, frontend42PASS, Rust3PASS3.05s.
- Compileall/pipcheck/lint/typecheck/build/diffcheckPASS; source/frozenHTTP e
  Tauri.app51.44MiB costruiti sul Mac. Nessun PASS trasferito a Windows11.
-4timeoutAppTest15s durante esecuzioni concorrenti, elencati in MASTER_AUDIT;
 9casi interessatiPASS5.96s e suite serialePASS senza alterazioni dei test.
- Nuovi28casi test_local_contracts:14routeOpenAPI,4snapshotmalformati,indicatori,
  idempotenzadopofill,SDKJSON,BUYSELLincompleti,equitynull,Paperincompleto,
 2shapecomplete. Review ha riprodotto5RED aggiuntivi prima delle correzioni.
-8casiApp.test nuovi: preferenza/persistenza,noPOST,6valori corrotti e storage
  negato. Browserreale puntatore/tastiera/reload/390px/console[]PASS.
- Backup/ripristino/integrità e isolamento provati ad hoc con SQLite temporaneo
  e modelloledger esistente; non test di disinstallazione/retention personale.
- CI nuova: consultare run sullo SHA pubblicato del branch master, mai dedurre
  da queste proveMac un risultato Windows. Broker/MT5autentici non eseguiti.


## Rilettura delle prove sul candidato a6d3f60 — 17 novembre 2026

I risultati seguenti sono run già eseguiti sullo stesso SHA, ricontrollati senza
riavviarli inutilmente. Owner QA P4; mock e dati temporanei, nessuna credenziale.
Le sei prove manuali W11 del piano E2E sono BLOCKED, non eseguite sul Mac.

| ID / descrizione | OS / SHA | Prerequisiti e comando effettivo | Atteso | Effettivo / evidenza / stato |
| --- | --- | --- | --- | --- |
| R17-PY-WIN: regressioni offline | Windows Server2025/Python3.11.9, a6d3f60 | Venv CI senza segreti; `python -m pytest -q -rs --junitxml=windows-test-results.xml` | Nessun fail, skip Proactor vietato, guard0/0 | 942PASS/0skip/1warning134.48s; run43976031716/job133680126181, **PASS** |
| R17-PY-MAC: regressioni offline | macOS CI/Python3.11.9, a6d3f60 | Venv CI; `python -m pytest -q -rs --junitxml=macos-test-results.xml` | Nessun fail, solo skip OS previsto, guard0/0 | 941PASS/1skip/1warning117.66s; stesso run/job133680125993, **PASS** |
| R17-APP: componenti/build/smoke | Runner Windows/macOS, a6d3f60 | `npm ci`, lint/typecheck/test/build; `cargo test --locked --manifest-path src-tauri/Cargo.toml`; smoke source/frozen e build del workflow | Componenti e artifact nativi funzionanti nel perimetro CI | Frontend34/Rust3 ciascuno, build/smoke PASS; job133680126056/133680125535, **PASS** |
| R17-NSIS: installer CI | Windows Server2025, a6d3f60 | Build NSIS unsigned; `scripts/check_windows_installer.ps1` | Risorse installate, UI/sidecar HTTP smoke, uninstall e sentinella esterna intatta | Stringa NSIS PASS nei log del job Windows; **PASS** limitato, nessuna prova retention app-data reale |
| R17-LOCAL: suite Mac privata | macOS27.2.1arm64/Python3.11.18, candidato a6d3f60 | `python -m pytest -q`; gruppo mirato esistente | Nessun fail, guard0/0 | Log locali:941PASS/1skip/1warning38.61s; mirati160PASS4.82s; **PASS** |
| R17-LIC: integrità inventario | Mac, manifest a6d3f60 | Metadata ambiente/npm lock/Cargo metadata, lettura soli testi legali | Identità uniche, lock Cargo coerente, nessun percorso personale | 819 record unici; hash manifest/testi; assert passate; **PASS** raccolta, licenze distribuibili ancora BLOCKED |

Link run: https://github.com/foffo09/AITradingBot/actions/runs/43976031716.
Compilazione e pip check nello stesso run riusciti; nessun nuovo test applicativo
aggiunto o rimosso dalla presente revisione documentale. Il warning noto è
`websockets.legacy`; lo skip Mac è Windows Proactor. I documenti nuovi sono
controllati separatamente, senza attribuirgli una nuova esecuzione di pytest.

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
| Windows Server 2025 x64 / Python 3.11.9 / GitHub Actions | PASS esecuzione nativa dell’11 novembre | [Run 42920818052](https://github.com/foffo09/AITradingBot/actions/runs/42920818052): 152 mirati (6,59 s), suite 748 passati (193,30 s), 0 falliti e 0 saltati. Guard rete/credenziali 0/0 in entrambi i gruppi; Proactor presente e superato senza skip. Compilazione, pip check e diff-check PASS. |
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

Evidenza Windows: [PR #5](https://github.com/foffo09/AITradingBot/pull/5),
head `065859dced4db1253172ea1f8c01081ad20cd496`, job `windows-tests`.
Il label richiesto è `windows-latest`; il run ha usato l’immagine reale
`windows-2025-vs2026`, versione `20261103.298.1`, Microsoft Windows Server 2025.
Python effettivo `3.11.9`, verificato anche mediante `sys.platform == win32`.
Il controllo JUnit riporta `Windows Proactor executed: PASS`; tutti gli step
conclusi con successo. Un warning preesistente `websockets.legacy` per gruppo.
Non è una prova dell’interfaccia su Windows 11 desktop o di broker autentici.
Questa evidenza aggiorna la precedente assenza di CI: la pipeline ora è
riconosciuta da GitHub Actions ed è stata eseguita su una PR senza merge.
Il dispatch manuale è configurato ma non provato, poiché il workflow non è
ancora sul branch predefinito e il merge resta fuori ambito.

## Sprint 03 — CI multipiattaforma / Python 3.11 (12 novembre 2026)

Base impilata: `5e759404ef574c1dacc22a79a417f29362a8a2ef`, branch remoto
`agents/p4-windows-ci-20261110`, [PR #5](https://github.com/foffo09/AITradingBot/pull/5)
ancora in bozza e non integrata. Nuovo branch
`agents/p4-cross-platform-ci-20261112`; nessun merge su main.
Solo workflow e questa matrice possono cambiare.

Il job `windows-tests` e tutti i suoi step sono conservati integralmente.
Aggiunto `macos-tests` indipendente su `macos-latest`, Python 3.11, shell Bash
con `-e -o pipefail` fornita da Actions: un errore pytest non viene nascosto da
`tee`. Stessi SHA ufficiali checkout/setup-python, permessi minimi, nessuna
credenziale persistita e stesse impostazioni conservative dello Sprint 02.
Il trigger PR verso `main` resta presente; è aggiunto esclusivamente il branch
base della PR impilata per poter provare entrambi i job prima del merge della
PR #5. `workflow_dispatch` resta presente, senza dichiararne una prova manuale.

Controlli macOS: compilazione, sei file mirati, suite completa con JUnit,
report rete/credenziali 0/0 in entrambi i gruppi, verifica dello skip Proactor
con la motivazione condizionale originale, pip check e diff del delta base/head
PR. Nessun test, requisito, guard, codice trading o soglia finanziaria modificati.
I conteggi storici dello Sprint 02 non sostituiscono le nuove esecuzioni.

| Sistema / nuova prova Sprint 03 | Stato | Evidenza |
| --- | --- | --- |
| Windows Server 2025 x64 / Python 3.11.9 | PASS | [Job windows-tests](https://github.com/foffo09/AITradingBot/actions/runs/43120507994/job/130859457869): 152 mirati, 0 falliti/skip, 1 warning, 4,38 s; suite 748 passati, 0 falliti/skip, 1 warning, 93,98 s. Guard 0/0 nei due gruppi; Proactor eseguito PASS. Compileall, pip check e diff-check PASS. |
| macOS 26.7.2 arm64 / Python 3.11.9 | PASS | [Job macos-tests](https://github.com/foffo09/AITradingBot/actions/runs/43120507994/job/130859457482): 152 mirati, 0 falliti/skip, 1 warning, 6,26 s; suite 747 passati, 0 falliti, 1 skip, 1 warning, 97,81 s. Guard 0/0 nei due gruppi; solo skip Windows Proactor condizionale previsto. Compileall, pip check e diff-check PASS. |

Limiti: Windows 11 desktop/UI, broker autentici, feed, trading, multi-host e
dispatch manuale non sono verificati da questo incarico. Nessuna release o
integrazione della PR #5 autorizzata.

Nuova evidenza Sprint 03, 12 novembre 2026 Europe/Rome:
[run 43120507994](https://github.com/foffo09/AITradingBot/actions/runs/43120507994)
concluso SUCCESS, evento `pull_request` sulla
[PR #6 impilata](https://github.com/foffo09/AITradingBot/pull/6).
Head verificato `1e4346672a0508d5fb6a54187dbd49bd9112bc50`;
checkout effettivamente testato da entrambi i job:
`e3ac5e53717b57614b49308428ca636d226ee3d9`, ref temporaneo `refs/pull/6/merge`
creato da GitHub per la prova PR. Non è un merge effettuato sul branch o su main.

Runner Windows: label `windows-latest`, immagine `windows-2025-vs2026`,
versione `20261103.298.1`, OS `10.0.26100`, Python AMD64.
Runner macOS: label `macos-latest`, immagine `macos-26-arm64`, versione
`20261102.0473.1`, OS build `25G332`, Python arm64.
Tutti gli step dei due job sono conclusi SUCCESS; `pip check` riporta
`No broken requirements found.`. Warning noto `websockets.legacy`, uno per
gruppo su ciascuna piattaforma. Il JUnit macOS conferma la motivazione originale
`Windows Proactor uses an IPv4 loopback self-pipe`; nessuno skip aggiunto.

Ricontrollo locale dello Sprint 03: macOS/Python 3.11.18, 152 mirati (2,02 s),
747 completi (33,44 s), 0 falliti, 1 skip Proactor solo nella suite completa e
1 warning per gruppo; guard 0/0. Compileall, pip check e diff-check exit 0.
Confronto testuale: intero job Windows invariato. YAML e Bash controllati;
prova sintetica del nuovo checker: guard zero/skip atteso accettati, guard
nonzero e skip con motivazione diversa rifiutati. Un primo avvio di questa
prova locale mancava di Python nel PATH della shell figlia: ripetuto con il
PATH della venv, senza modifiche al workflow o ai test.

Il trigger `main` è verificato nel file; il run reale usa la base impilata
prescritta. Nessuna ulteriore PR verso main aperta per questa prova. La nuova
copertura è provata sui runner indicati, non sul desktop Windows 11. Le
modifiche restano limitate ai due file autorizzati; PR #5 invariata e nessun
merge/release. Il commit documentale successivo registra questa esecuzione:
i numeri qui sopra restano attribuiti al relativo head e checkout, non a un
commit futuro.


## Missione December QA & Release — 16 novembre 2026

Base documentale `3df4f8260fcbb85ea8ccf2c2b680f672adc89af4`; data/host audit:
16 novembre, macOS 27.2.1 arm64, sessione iniziata 11:55:10 UTC.
Unico [piano end-to-end](END_TO_END_QA_PLAN.md), **35 scenari**, con
ID/owner/piattaforma/SHA/prerequisiti/fixture/passi/atteso/test/evidenza/stato.
[Architettura target e decisioni](ARCHITETTURA_APP.md). Nessun candidato
React/FastAPI/Tauri/MT5 integrato identificato: non attribuire al nuovo
prodotto i PASS storici di Python/Streamlit.

| Gruppo ID nel piano | Perimetro | Stato osservato in questa sessione |
| --- | --- | --- |
| QA-AUD-01 | Base, worktree, branch, ancestry, manifest | PASS solo audit documentale Git alla BASE |
| QA-AUD-02 | Import diretti dei sei moduli src/strategy | PASS statico: nessun framework UI/API/broker; non prova transitiva/runtime |
| QA-WEB-01..03 | Launcher, stessa UI/API, avvio offline | BLOCKED: nuovo stack non consegnato |
| QA-SEC-01..04 | Bind/Host/Origin/CORS/CSRF/sessione/capabilities/segreti | BLOCKED, salvo SEC-04 NON VERIFICATO; manca artifact nuovo |
| QA-LIF-01..03 | Start/health/timeout/crash/shutdown/cleanup | BLOCKED |
| QA-CTX-01..03 | Demo/Sim/Paper/MT5 separati | BLOCKED per nuova UI/API; test legacy mappati, non rieseguiti qui |
| QA-MT5-01..03 | Unsupported/unavailable/unverified/connected/stale, read-only | BLOCKED: nessun adattatore MT5 |
| QA-DAT-01..02 | Dati/provenienza/tempi e risposte incomplete | BLOCKED sul nuovo contratto API |
| QA-ORD-01..03 | Pagine, idempotenza, fill e panic | BLOCKED; recupero pieno post-fill non certificato |
| QA-STR-01..02, QA-UI-01 | P3→P2 API→P1 UI e refresh | BLOCKED; proposta pura non è consumer integrato |
| QA-BKT-01..02 | Causalità, costi, stop-first, OOS | BLOCKED per adapter nuovo; nessuna attestazione di profitti |
| QA-PKG-01..03 | Build/installer nativi Windows/macOS | BLOCKED: manifest/artifact assenti |
| QA-OSS-01 | Licenze, SBOM, lock e canoni | NON VERIFICATO; pin diretti Python non bastano |
| QA-CI-01 | Stato dei run Python storici su head noti | PASS storico ricontrollato via GitHub, non build web/desktop |
| QA-MAN-01, QA-REL-01 | UX Windows11/macOS e candidato esatto | BLOCKED |

### Evidenza CI storica distinta dalla nuova release

PR #5 OPEN/DRAFT, head `5e759404ef574c1dacc22a79a417f29362a8a2ef`, base
main `fe988394d6ecdcb56763a81c627943b4cbe684e1`; check `windows-tests` SUCCESS:
[run 42921890791](https://github.com/foffo09/AITradingBot/actions/runs/42921890791).
PR #6 OPEN/DRAFT, head `97ff2966b9d8d82d6c6f10d30e9da125656e5259`, base
branch #5 a `5e75940`; `windows-tests` e `macos-tests` SUCCESS:
[run 43121098415](https://github.com/foffo09/AITradingBot/actions/runs/43121098415).
Stati PR/check ricontrollati il 16 novembre; zero review e richieste review.
I conteggi già documentati sono **storici**, non esecuzioni di oggi:
Windows Server 2025 x64/Python 3.11.9 152 mirati/748 completi, 0 fail/skip;
macOS 26.7.2 arm64/Python 3.11.9 152 mirati/747 completi, un solo skip Proactor.
Guard 0/0 e compileall/pip/diff-check PASS nei run indicati, warning noto
websockets.legacy. Nessuna build React/Tauri/Python sidecar in quel workflow.

Per il prodotto nuovo, browser locale/desktop Windows/desktop macOS/build
native/Windows11 manuale/MT5 autentico hanno SHA candidato NON ASSEGNATO e
stato BLOCKED o NON VERIFICATO come nel piano. Le prove autentiche richiedono
consenso separato e non possono inviare ordini. Il guard pytest esistente
non viene indebolito per consentire E2E loopback: servirà harness distinto.

## 16 novembre — nuovo candidato React/FastAPI/Tauri (85453ce)

Questa esecuzione sostituisce lo stato «artifact assente» della ricognizione
precedente per i soli casi sotto, preservandone lo storico.

| Area | Ambiente / prova effettiva | Esito |
|---|---|---|
| Suite offline completa | Macarm64/Python3.11.18 |870PASS/1skipProactor/1warning; guard0/0|
| API/runtime/launcher/provider/rischio/contratti | Mac, mock |225PASS/1warning; guard0/0|
| Frontend | Node22.23.3, lint/TS/build/vitest |17PASS; audit0vulnerabilità|
| HTTP sorgente + frozen | Macloopback, SQLite temporanea |PASS sessione/Origin/fill/contesti/backtest/shutdown|
| Browser | Brave, Demo sintetica e Paper scollegato |PASS rendering/ledger/contesti/backtest;390px senza overflow|
| Rust | nativo Macarm64 |1PASS;release/bundle.app riusciti|
| Desktop | .app reale, ambiente temporaneo |PASS rendering/navigazione/backtest/close/porta chiusa|
| Compile/pip/diff | Mac |PASS; nessun requisito rotto|
| Windows11 GUI | PC non disponibile |NON VERIFICATO|
| Alpaca/MT5 autentici | non collegati |NON VERIFICATO|
| NuovaUI esecuzione/ripristino ordini | nessuna route ordine |NON COMPLETATO; automazione ferma|

Output, limiti e SHA dei componenti in MASTER_AUDIT.md. Smoke reale separato
negli script, non mescolato alla guard offline. Nessun invio broker nei test.

Consolidamento successivo f737455: **876PASS/1skip/1warning** nella suiteMac,
**18PASSfrontend**, **61PASS API/MT5**; guard0/0. Nuovi casi rossi→verdi:
metadati persistiti API/consumer e cinque tipi contoMT5 nonDemo/nonverificabili.
Smoke sorgente/frozen e build.app ripetuti con successo. La seconda rilettura
GUI dell'ultimo bundle è temporaneamente bloccata dallo schermoMac bloccato;
la provaGUI precedente sullo stesso lifecycle è documentata, non sostituisce
una provaWindows11. CI corrente e SHA sono registrati nell'audit al completamento.

Chiusura successiva: **877PASS/1skip/1warning36.10s**, API25PASS e18frontendPASS;
Rust1PASS. Nuovo test verifica che NO_TRADE venga realmente dal motore con
provenienza, non da fallback d'errore. SmokeHTTP sorgente/frozen rafforzatoPASS.
Fault nativo: sidecar mancante→exit1 senzapanic; bundlegenerato ripristinato.
SbloccoMacrisolto; finale LaunchServices + GUI con metadata/proposta corretti,
chiusura normale/porta chiusa/processi assentiPASS. Dettagli e timeout15s
residuo nell'audit; nessun PASSWindows11 o brokerautentico dedotto.


## Completion — evidenze locali del 16 novembre

Base37a3840 + diff isolato; gli SHA dei commit e runCI successivi vanno riferiti
al candidato effettivo, senza attribuire la baseline storica al nuovoSHA.

| Prova | macOS27.2.1arm64 | WindowsCI nuovoSHA | Windows11GUI |
|---|---|---|---|
| compileall/Python3.11.18 | PASS exit0 | NON VERIFICATO | NON VERIFICATO |
| Suite Python | PASS929/skip1/warn1;40.09s;guard0/0 | NON VERIFICATO | NON VERIFICATO |
| API/ledger/readonly mirati | PASS113 | NON VERIFICATO | NON VERIFICATO |
| Frontend/Node22.23.3 | PASS34;lint/typecheck/build0 | NON VERIFICATO | NON VERIFICATO |
| Rust/Tauri | PASS3 e bundle.app90.77MiB | NON VERIFICATO | NON VERIFICATO |
| HTTPsource/frozen | PASS;loopback/temp/no broker | NON VERIFICATO | NON VERIFICATO |
| pipcheck/diffcheck | PASS | NON VERIFICATO | NON VERIFICATO |
| npm audit | PASS0 advisory | NON VERIFICATO | NON VERIFICATO |
| pip-audit | FAIL42 advisoryPillow;releaseBLOCKED | NON VERIFICATO | NON VERIFICATO |
| PSwrapper/NSIS | NON VERIFICATO | NON VERIFICATO | NON VERIFICATO |
| MT5autentico/nativehang frozen | NON VERIFICATO | NON VERIFICATO | NON VERIFICATO |

Regressioncases: idempotency/payload/restart/concurrency, ownershipprocesso,
stati dry-run, partial/filled/canceled/rejected/expired/unknown, pagine incomplete/
overlap, dati mancanti/futuri, timeout/crashMT5, staleproposal/pollsingleflight.
Test nuovi non sostituiscono né rimuovono quelli esistenti.


### Aggiornamento dopo dipendenze compatibili e bundle minimo

Nuova venv privataPython3.11.18: **931PASS,1skip,1warning in48.69s**, guard0/0.
compileall exit0; pipcheck `No broken requirements found.` Streamlit1.66.1,
Pillow13.0.0: pip-audit `No known vulnerabilities found`; npm audit0.
Frontend34PASS/Rust3PASS; coldstartfrozen prima15.229s/dopo5.6624s, health0.0079s,
idle0% su2s, RSS121168KiB,shutdown0.2602s. Misure locali non attestano altriOS.
RunCI43970361875 su03200f7: suiteWindowsPASS, wrapperPSFAIL; candidato aggiornato
con testresetTCP e diagnostico. Risultato finale del nuovoSHA nella PR8/Actions.
La vecchia riga FAILPillow è storica, superata da upgradecompatibile+auditzero.


Ultimo controllo dopo protocolloWindows/buildhook:936PASS/1skip/1warning38.53s,
guard0/0. La confermaWindows del redirector e del pacchetto rimane demandata alla
CI del prossimoSHA. Cargo-audit0vulnerabilità/2warning non soppressi. GUIcorrente
Maclocked NON VERIFICATO; backend nativo privato healthy e stop con porta chiusa.


### CI nativa completa e GUI finale (16–17 novembre)

Codice `daa5b86`, run43973548981: quattrojobSUCCESS. WindowsServer2025/Python3.11.9:
937PASS/0skip/1warning165.19s; Mac26.7.2arm64/Python3.11.9:936PASS/1skip/1warning109.86s,
guard0/0. TargetCI152PASS, frontend34 eRust3 su entrambi. Source/frozenHTTP,
wrapperPS/doppioavvio/stop/restart e NSISunsigned install/installedUI/uninstallPASS.
GUI suMaclocale27.2.1: Demo/fillvirtuale privato, Simulazione separata, backtest,
dry-run echiusura/portachiusaPASS. Bundle51.43MiB, primo probehealthy13.4164s;
non una garanzia coldstart universale o misura paintUI.
IDfill rafforzato dopo questaCI: locale941PASS/1skip/1warning38.89s guard0/0.
Il nuovoHEAD ha checkCI propri nella PR8. Windows11GUI/brokerautentici restano
NON VERIFICATI, licenza/notice BLOCKED. Niente release o ordini.
