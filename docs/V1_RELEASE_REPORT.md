# AITradingBot v1.0 — report di release (aggiornato al 25 novembre 2026)

**Decisione: V1.0 NON APPROVATA.** Il software è pronto per il collaudo del proprietario. Mancano tre
condizioni che nessun agente può soddisfare da solo:
1. la prova MT5 reale su Windows 11;
2. la revisione di Codex sulle modifiche di Claude;
3. la licenza del progetto, la firma e l'approvazione del merge da parte del proprietario.

L'SDK MetaTrader5 viene incluso nell'installer Windows (decisione del proprietario, 25/11/2026).

Nessun merge su `main`, nessuna release. Trading reale disattivato, MT5 solo lettura,
`order_submission = disabled`, automazione `STOPPED`.

## Candidata
- **Branch:** `agents/claude-v1-review-20261124` (PR draft #11 verso `main`, contiene #7, #8 e #10). La
  storia è conservata, senza force-push. Coordinamento nell'issue #9.
- **Stabilizzazione del 25/11:** branch `agents/claude-v1-stabilization-20261125`, integrato nella PR #11 con
  fast-forward. Commit:
  - `b288890`: formatter di Codex (numeri piccoli, orari senza offset), applicato invariato dal suo diff
    pubblicato nell'issue;
  - `9db868d`: precisione dei prezzi dello strumento;
  - `47f91d0`: test diagnostica;
  - `a404e82`: script di verifica MT5 in 9 passi;
  - `f54279d`: versione di schema e backup del ledger;
  - `9e0898d`: NOTICE con MetaTrader5;
  - `1aeba37`: chiusura del servizio su Windows senza traceback;
  - build Windows che rifiuta di produrre l'installer senza l'SDK MetaTrader5.
- **Non integrati**, perché non pubblicati sul remote e quindi non revisionabili: branch Codex
  `agents/codex-v1-integration-20261124`, commit `11696c1` (handshake versionato UI/sidecar) e `b7eb4b3`
  (migrazioni SQLite Codex).

## Correzioni del 25/11
| Problema | Correzione | Prova |
|---|---|---|
| Prezzi arrotondati a 4 decimali: EURUSD 1,08345 e 1,08347 entrambi "1,0835"; 0,00015 → "0,0002" | MT5 dichiara `symbol_info.digits` per strumento (EURUSD 5, USDJPY 3), Demo/Simulazione dichiarano 2; `price()` usa quei decimali, zeri finali compresi. Se la precisione è ignota usa 10 cifre significative. La scala del grafico usa la stessa precisione. | `format.test.ts` (forex, JPY, valori nulli, precisione non valida), `test_bars_carry_only_broker_declared_price_digits` |
| Test Windows instabile: `'100'` cercato nell'intera diagnostica (corrispondeva al PID 10044) | controllo strutturato: nessun campo conto e nessun valore del saldo nella diagnostica, PID escluso; controllo provato da un test dedicato | `test_leak_check_flags_account_values_but_not_a_pid_containing_the_same_digits` |
| Ora del server MT5 diversa da UTC (R8) | nessun offset inventato: tick e candele "nel futuro" sono scartati, con lo scarto misurato nel messaggio. Senza dati verificati la proposta resta `NO_TRADE`. | `test_server_time_ahead_of_utc_is_reported_not_converted` |
| Verifica Windows senza quotazioni né orari | `check_mt5_api`: 9 passi read-only con PASS/FAIL, età della quota e della candela rispetto a UTC, codice di uscita del servizio | `tests/test_check_mt5_api.py`; su macOS si ferma alla fase `platform` |
| Ledger SQLite senza versione né backup | `PRAGMA user_version = 1`, `quick_check` e backup SQLite prima di migrare; un ledger più recente viene rifiutato senza toccarlo | `tests/test_ledger_schema.py` |
| MetaTrader5 assente dai NOTICE | nota nel generatore e nel file: licenza dichiarata MIT su PyPI, modulo binario nativo, redistribuzione da confermare | `THIRD_PARTY_NOTICES.md` |

Correzioni precedenti (R1–R7: worker MT5 su Windows, SDK nel `.venv` e nel sidecar, crash/timeout,
`tasklist` localizzato, profilo utente nella diagnostica): in `MT5_CONNECTION_FIX_REPORT.md` e
`EMERGENCY_DELIVERY_REPORT.md`.

## Test sull'albero candidato (macOS ARM, 25/11/2026)
- **Python:** pytest 926 passati / 2 saltati (solo Windows) · Ruff ok.
- **Frontend:** Vitest 82 · `tsc` ok · `npm run lint` ok · `npm run build` ok.
- **CI Windows/macOS:** sullo SHA finale della PR #11, risultato nell'issue #9. Non si usano risultati di
  commit precedenti.

## Criteri di accettazione
| # | Criterio | Stato |
|---|---|---|
| 1 | Frontend e backend insieme | ✅ test API, prova nel browser |
| 2 | Desktop si avvia | ✅ CI su macOS ARM e Intel e su Windows Server; ⏳ Windows 11 |
| 3 | Sidecar | ✅ smoke frozen in CI, incluso il controllo MT5 |
| 4 | Dati coerenti | ✅ ledger per contesto, idempotenza |
| 5 | Prezzi frazionari | ✅ precisione dello strumento (test); ⏳ resa grafica con dati MT5 reali |
| 6 | Timezone | ✅ API: tutti gli orari con offset; ✅ MT5: nessuna conversione, scarto visibile; ⏳ ora reale del broker del proprietario |
| 7 | SQLite aggiornabile | ✅ versione, integrità, backup e rifiuto delle versioni future per il ledger. Gli altri database (controller dry-run, preferenze) restano con creazione idempotente. |
| 8 | Contesti isolati | ✅ test parametrizzati |
| 9 | MT5 read-only su Windows | ⏳ solo il proprietario può provarlo (`INSTALLATION_WINDOWS.md`) |
| 10 | Sicurezza | ✅ nessun segreto, nessun endpoint di scrittura broker, diagnostica senza dati del conto |
| 11 | CI verde sul candidato finale | vedi issue #9 |
| 12 | Revisione reciproca | ⏳ Claude ha revisionato e integrato il diff Codex pubblicato; Codex non ha ancora revisionato R1–R8 né le correzioni del 25/11 |
| 13 | Documentazione | ✅ questo report, `ARCHITECTURE.md`, `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`, `MT5_CONNECTION_FIX_REPORT.md`, `WORKLOG.md` |

## Cosa serve per approvare
1. **Proprietario, su Windows 11 con MT5 Demo aperto:** `.\.venv\Scripts\python.exe -m scripts.check_mt5_api --symbol EURUSD`,
   poi l'output incollato nell'issue #9. Se il passo 8 mostra uno scarto (es. +7200 s), si decide la
   correzione dell'ora del server su quella prova.
2. **Codex:** revisione del branch di stabilizzazione e di R1–R8; pubblicazione di `11696c1`/`b7eb4b3` se
   ancora utili.
3. **Proprietario:** licenza del progetto; firma; approvazione del merge.

Installazione, aggiornamento e backup: `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`.
