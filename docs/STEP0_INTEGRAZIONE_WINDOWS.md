# Passo 0 — Integrazione preparata, prova Windows ancora mancante

## Stato reale e perimetro

- Sorgente Windows pubblicata: origin/mie-modifiche, 52d65db.
- Aggiornamento integrato: origin/main, 2b2d35a.
- Worktree separato sul Mac, branch locale mie-modifiche; checkout principale
  con modifiche executor preesistenti preservato. Nessun accesso al PC Windows
  o a eventuali modifiche non pubblicate di quel PC.
- Merge senza commit: le sette voci unmerged sono state risolte e aggiunte
  esplicitamente all'indice. Nessun commit, push o PR di questa fase.

## Risoluzioni

- app.py: UI Windows e selettore conservati; renderer comune src/ui/charts.py
  preferito alla copia obsoleta con history non inizializzata. Confermata la
  firma dei chiamanti e l'isolamento dei marker Demo/Paper. Anteprima singola
  forza dry-run anche se la checkbox fosse disattivata.
- paper_automation.py: execute_auto_paper_cycle resta disponibile con default
  dry_run=True. La valutazione/invio del segnale conserva il coordinatore main,
  intento durevole, controllo finale di tempo/quote e rifiuto degli esiti
  incerti. L'API as_of analitica non sovrascrive il clock finale: regressione
  dedicata dimostra zero submit per feed diventato vecchio.
- bar_timing.py: entrambe API conservate; helper analitico Windows separato
  dall'idoneità operativa select_completed_bars. Tutte le funzioni main restano
  invariate. Fail-closed anche nell'helper senza calendario.
- requirements.txt: pin main include pandas-market-calendars 5.5.0, che
  soddisfa anche il vincolo Windows >=4.4, e tutte le dipendenze condivise.
- Test calendario: unione dei casi dei due branch, nessuna funzione duplicata.
  Fixture Paper adattate al contratto temporale esplicito main e all'ID conto
  fittizio richiesto dal coordinatore, conservando le prove di no-submit.
- Test dashboard: nomi dei pulsanti e avvisi allineati al testo effettivo;
  nessuna asserzione o caso eliminato.
- Test TUI: skipif(sys.platform == 'win32') richiesto dall'utente, con motivo
  esplicito pipe POSIX. Su Mac il test viene eseguito. Nessun altro skip aggiunto.
- alpaca_client.py integrato automaticamente: controllati endpoint Paper,
  property paper_client_is_paper Windows, lease main, limite storico 500 e
  metadati temporali. Nessuna rimozione delle protezioni a seguito del merge.
- Flag omega_enable_live_orders e omega_enable_native_orders restano False.

## Prove effettive su Mac

Python 3.12.14, ambiente requirements-dev.txt installato; nessun --ignore.

- Calendario + selettore: 55 passati, 1,06 s.
- Dashboard: 40 passati, 13,87 s.
- Paper dopo ultima regressione: 42 passati, 0,54 s.
- python -m compileall -q app.py config src tests: output vuoto, exit 0.
- python -m pytest -q: 437 passati, 0 falliti, 0 saltati, 1 warning, 23,93 s.
- TEST ISOLATION: {'network': 0, 'credentials': 0}.
- python -m pip check: No broken requirements found.
- git diff --check e git diff --cached --check: output vuoto, exit 0.
- Nessun marcatore di conflitto nel codice; git diff --name-only --diff-filter=U
  vuoto. AST: ogni test dei due lati nei file conflittuali è presente e non ci
  sono definizioni top-level duplicate che possano nascondere dei casi.

La prima suite dopo la risoluzione iniziale aveva 29 fallimenti e 407 passati:
label dashboard obsolete (26 casi), chiamata utc_timestamp senza label (2)
e fixture senza identità conto (1). Corretti gli adattamenti senza ridurre le
protezioni. Il warning finale resta websockets.legacy deprecato.

## Blocco residuo e prossimo passo

Windows 11/Python 3.11.9 NON ESEGUITO: questo host è macOS. Non chiudere il
passo 0 come suite Windows verde. La prova TUI risulterà saltata esplicitamente
su win32; è un limite noto, non una verifica del supporto stdin Windows.
Non sono stati avviati server, automazioni, ordini o feed e non sono stati letti
segreti o database personali. Nessuna conclusione quantitativa sulla strategia.

Proposta successiva da confermare: commit di integrazione e pubblicazione solo
su mie-modifiche, prova dell'utente su una copia Windows, poi eventuale passo 1
con PR verso main. Nessun push diretto su main. CI e runner non implementati qui.

## File interessati dall'intero merge rispetto a 52d65db

Include le modifiche integrate automaticamente da main, oltre ai conflitti.

- `.env.example`
- `.gitignore`
- `AGENTS.md`
- `HYPERLIQUID_TESTNET.md`
- `README.md`
- `README_OMEGA.md`
- `agent/__init__.py`
- `agent/coder_brain.py`
- `app.py`
- `config/hyperliquid_testnet.py`
- `config/live_state.example.json`
- `config/providers.py`
- `config/settings.py`
- `conftest.py`
- `core/__init__.py`
- `core/ingestor.py`
- `core/live_runtime.py`
- `core/market_router.py`
- `core/runtime.py`
- `core/state.py`
- `docs/COME_USARE_LA_DASHBOARD.md`
- `docs/DECISIONI_TECNICHE.md`
- `docs/GUIDA_COMPLETA_PROGETTO.md`
- `docs/INSTALLAZIONE_WINDOWS.md`
- `docs/MATRICE_TEST.md`
- `docs/REVIEW_QUALITA_E_ROADMAP.md`
- `docs/WORKLOG.md`
- `engine/__init__.py`
- `engine/sandbox.py`
- `execution/__init__.py`
- `execution/providers.py`
- `execution/vanguard.py`
- `how --format= --name-only HEAD`
- `main.py`
- `providers/__init__.py`
- `providers/ai.py`
- `providers/common.py`
- `providers/crypto.py`
- `providers/hub.py`
- `providers/solana.py`
- `providers/tradfi.py`
- `requirements-dev.txt`
- `requirements-omega.txt`
- `requirements.txt`
- `src/broker/alpaca_client.py`
- `src/broker/hyperliquid_testnet.py`
- `src/broker/native.py`
- `src/data/bar_timing.py`
- `src/data/fx_rates.py`
- `src/data/market_data.py`
- `src/hyperliquid_testnet_cli.py`
- `src/simulation/ledger.py`
- `src/trading/native_engine.py`
- `src/trading/native_store.py`
- `src/trading/paper_automation.py`
- `src/trading/paper_coordinator.py`
- `src/ui/__init__.py`
- `src/ui/charts.py`
- `src/ui/presentation.py`
- `tests/test_bar_timing.py`
- `tests/test_broker.py`
- `tests/test_dashboard_validation.py`
- `tests/test_fx_rates.py`
- `tests/test_hyperliquid_testnet.py`
- `tests/test_native_store.py`
- `tests/test_omega.py`
- `tests/test_paper_automation.py`
- `tests/test_paper_coordinator.py`
- `tests/test_paper_safety.py`
- `tests/test_providers.py`
- `tests/test_simulation_ledger.py`
- `tests/test_test_isolation.py`
- `tests/test_ui_presentation.py`
- `tests/test_windows_installation.py`
- `ui/__init__.py`
- `ui/control_box.html`
- `ui/control_box.py`

Aggiunti a questo inventario il presente rapporto e gli aggiornamenti di guida,
decisioni, matrice e worklog. La rimozione dell'artefatto di nome
`how --format= --name-only HEAD` proviene dalla cronologia main già pubblicata;
non è una nuova cancellazione decisa durante questa fase.
