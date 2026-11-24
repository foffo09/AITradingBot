# Dismissione di Streamlit — report (issue #9)

Data: 24 novembre 2026. Autore: Claude Code. Branch `agents/claude-complete-modernization-20261124`.
L'issue assegnava il lavoro a Codex; Codex non raggiungeva il proprio servizio da questa rete
(TLS verso `chatgpt.com` intercettato da un firewall Fortinet), quindi l'utente ha chiesto a Claude
di eseguirlo. Nessun merge, nessuna release.

## 1. Matrice di parità funzionale

Classi: **1** = coperto e testato nella nuova UI · **2** = completato in questo lavoro · **3** = escluso deliberatamente.

| Flusso del vecchio `app.py` | Nuova UI / API | Classe | Prova |
|---|---|---|---|
| Selettore workspace Demo/Paper, DB isolati | Selettore **Contesto** (demo, simulation, paper, mt5), file SQLite per contesto | 1 | `test_local_accounts_are_explicit_separate_and_persistent`, `test_qa_macos_audit::test_modes_keep_separate_capital_ledger_and_automation` |
| Stato del sistema | Pagina **Stato sistema**, `GET /api/v1/system` | 2 | `test_system_status_is_read_only_secret_free_and_never_waits_for_paper`, test Vitest "Stato sistema …" |
| Mercato: strumento, intervallo, grafico, fonte/timestamp | **Mercati** (candlestick, volume, SMA/EMA/RSI dal backend, zoom, crosshair) | 1 | `test_market_provenance_backtest_and_proposal`, `test_market_indicators_and_backtest_sample_are_explicit`, MarketChart.test |
| Confronto fino a 4 strumenti | **Watchlist** (fino a 20, ultima chiusura e variazione dal backend) | 2 | `test_watchlist_is_validated_persistent_and_never_reset`, Vitest "Watchlist mostra N/D …" |
| Link esterno TradingView | — | 3 | La shell Tauri blocca la navigazione fuori origine; nessun dato utile al prodotto |
| Segnale SMA, monitor quote | **Segnali** (proposta analitica, `NO_TRADE` di default, mai un ordine) | 1 | `test_demo_proposal_reaches_pure_service…`, `test_incomplete_operational_proposal_is_not_published_as_valid` |
| Monitor conto Alpaca Paper (verifica, snapshot, ordini, posizioni) | **Connessioni → Verifica Alpaca Paper**, stato Paper in sola lettura | 1 | `test_paper_is_opt_in_read_only_and_errors_do_not_leak`, `test_failed_paper_connection_is_explicit_unavailable_without_old_values`, `test_paper_refresh_failure_hides_previous_values` (portato da AppTest) |
| Filtro ordini Paper per stato | Tabella ordini senza filtro | 3 | Rinviato: solo comodità di visualizzazione |
| **Automazione Paper** (invio ordini moving-average) | — | 3 | Vincolo dell'issue: nessuna capacità di esecuzione finanziaria nella nuova UI. I moduli `src/trading/paper_*` restano, non raggiungibili |
| Anteprima DRY-RUN | **Automazione** (dry-run locale, parte STOPPED) | 1 | `test_automation_is_explicit_offline_idempotent_and_context_isolated`, Vitest dry-run |
| Conto simulazione in EUR con cambio Frankfurter/ECB | Conto virtuale in USD (cambio identità dichiarato) | 3 | Scelta già presente nel servizio locale (`local_account`: "Local USD identity (no FX conversion)"): nessuna chiamata FX esterna, nessun tasso inventato |
| Entry/uscita simulate con rischio e costi | **Portafoglio** (acquisto/vendita virtuale, idempotenza, rischio esistente) | 1 | `test_api_trade_replay_is_idempotent_across_restart…`, `test_definitive_risk_rejection_is_distinct…` |
| Storico completo operazioni | **Storico** | 1 | `test_local_equity_and_profitable_sell_have_json_safe_metrics` |
| Azzera simulazione locale | — | 3 | Nessuna operazione distruttiva sui dati (vincolo dell'issue) |
| Market Review / Bot Accuracy | Panoramica (metriche contabili del ledger) | 3 | Bot Accuracy dipendeva dal log dell'automazione Paper esclusa |
| Backtesting | **Backtesting** | 1 | `test_market_provenance_backtest_and_proposal`, Vitest backtest |
| Walk-forward fuori campione | **Backtesting → Walk-forward**, `POST /api/v1/walk-forward` (stessa griglia 2/4, 3/6, 5/10) | 2 | `test_walk_forward_*` (3 test), Vitest walk-forward |
| Strategia e rischio nella sidebar (parametri) | Finestre SMA nel backtest; rischio da `AppSettings` | 3 | Modificare soglie di rischio dall'UI non è nel mandato |
| Tema scuro compatto | Tema chiaro predefinito + scuro, densità, larghezza grafico (**Impostazioni**) | 1/2 | `tests/test_ui_preferences.py`, Vitest preferenze |

## 2. File e dipendenze rimossi

| Elemento | Motivo |
|---|---|
| `app.py` (2520 righe) | Dashboard Streamlit; flussi coperti o esclusi come da §1 |
| `avvia_demo.ps1`, `avvia_paper.ps1`, `avvia_bot.bat` | Eseguivano `python -m streamlit run app.py`; unico entrypoint ora `avvia_web.ps1` (Windows) / `scripts.start_local` (macOS/Linux) e il pacchetto desktop |
| `src/ui/` (charts, dashboard_panels, dashboard_style, dashboard_metrics, presentation, workspaces) | Importati solo da `app.py` (verificato con `git grep`) |
| `streamlit==1.66.1` | Non più usato |
| `plotly==7.1.0` | Importato solo da `app.py` e `src/ui/charts.py` |
| `pillow==13.0.0` | Pin di sicurezza richiesto solo da streamlit (`Required-by: streamlit`) |
| altair, pyarrow, pydeck (transitive) | `Required-by: streamlit`; spariscono da soli |

Restano intenzionalmente: guardie su `.streamlit/secrets.toml` in `conftest.py` e nei test di isolamento
(proteggono credenziali), `--exclude-module streamlit/PIL` nel build del sidecar (difensivo),
`main.py` + `ui/control_box.py` (console OMEGA basata su FastAPI, non Streamlit, fuori dal perimetro).

Prova: ambiente pulito da `requirements-dev.txt` + `packaging/backend/requirements.txt`
(105 pacchetti, `uv pip check` coerente) senza streamlit/plotly/PIL/altair/pyarrow/pydeck;
in quell'ambiente 880 test passano, smoke HTTP sorgente e frozen PASS, sidecar e DMG costruiti.

## 3. Test rimossi e copertura che li sostituisce

Totale rimossi: **129** (eseguivano `app.py` con `AppTest`, ne compilavano frammenti AST o testavano
figure Plotly di `src/ui`). Nessun test di dominio, broker, rischio, ledger o backtest è stato rimosso.

| File rimosso | Test | Cosa verificava | Copertura nella nuova architettura |
|---|---|---|---|
| `test_dashboard_validation.py` | 48 | DB isolati, N/D, dati sintetici etichettati, invalidazione backtest/walk-forward, marker grafico, barre future, metadati backend | API: `test_local_service`, `test_local_contracts`, `test_local_modernization` (walk-forward); UI: App.test/api.test/MarketChart.test. L'invalidazione per cambio selezione è strutturale in React (`key` per contesto/simbolo) |
| `test_dashboard_contexts.py` | 7 | Saldi indipendenti, cambio contesto pulisce lo stato, Paper senza ledger locale, nessun fallback Demo | `test_local_accounts_are_explicit_separate…`, `test_modes_keep_separate…`, Vitest "rifiuta snapshot di un altro contesto", "Paper non espone comandi di ledger locale" |
| `test_signal_refresh.py` | 21 | Frammenti di refresh Streamlit (quote, snapshot Paper, segnale) | Polling React con `AbortController` (App.test "invalida equity e proposta dopo un errore di refresh"); gate del segnale in `test_strategy_*` |
| `test_ui_charts.py`, `test_ui_presentation.py` | 15 | Figura Plotly, formattazione money/N/D, dedup ordini | MarketChart.test (Lightweight Charts), `format.ts` (`number` → N/D), Vitest "conserva account assente e liste reali vuote" |
| `test_ui_workspaces.py`, `test_dashboard_metrics.py` | 30 | Helper puri di `src/ui` (percorsi workspace, riepiloghi) | Codice rimosso con `app.py`; percorsi dati ora in `create_local_app` (`test_ledger_alias_created_after_startup_is_rejected`) |
| 1 test in `test_paper_safety.py` | 1 | Refresh Paper fallito nasconde i valori precedenti (AppTest) | **Portato** in `test_local_modernization.py::test_paper_refresh_failure_hides_previous_values` |

Limite dichiarato: la mappatura è per gruppo di comportamento, non 1:1 per ciascuno dei 129 test.
Alcuni dettagli specifici del vecchio dashboard (es. marker di fill Paper sul grafico, filtro ordini)
non hanno un equivalente perché la funzione non esiste più nella nuova UI.

## 4. Guardia contro il ritorno di Streamlit

`tests/test_streamlit_retired.py` (4 test, gira in CI): entrypoint legacy assenti; nessun manifest
runtime con streamlit/plotly/pillow; nessun comando ufficiale (README, AGENTS, guide, script, workflow)
che avvii Streamlit o citi i launcher rimossi; `src.api.local_app`, `src.runtime.local_service` e
`scripts.start_local` importabili senza caricare streamlit/plotly/PIL. RED verificato su README prima
della riscrittura.
