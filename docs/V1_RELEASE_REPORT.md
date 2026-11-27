# AITradingBot v1.0 — report di release (aggiornato al 27 novembre 2026)

**Decisione: V1.0 NON APPROVATA per la release pubblica; candidata privata pronta per il collaudo del
proprietario.** I controlli tecnici eseguibili dagli agenti sono PASS (sotto). Restano aperti:
1. la prova MT5 Demo reale su Windows 11 (BLOCKED: solo il proprietario);
2. le revisioni indipendenti di Codex e Gemini (NON VERIFICATO: richieste, nessuna risposta);
3. licenza del progetto, firma Authenticode / Developer ID, notarizzazione, approvazione del merge
   (BLOCKED: decisioni del proprietario).

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
  - `49079ab`: build Windows che rifiuta di produrre l'installer senza l'SDK MetaTrader5.
- **Stabilizzazione del 27/11** (stessa PR, senza nuovi branch): conto MT5 con broker (`company`) e tipo conto
  verificato; licenza MIT di MetaTrader5 verificata nel wheel e spedita nel sidecar (`--copy-metadata`);
  `THIRD_PARTY_NOTICES.md` incluso nell'installer.
- **Non integrati:** commit Codex `11696c1` (handshake versionato) e `b7eb4b3` (migrazioni SQLite). Il 27/11
  non esistono né nel clone né su GitHub ("No commit found for SHA"); il branch
  `agents/codex-v1-integration-20261124` non è sul remote. La candidata copre gli stessi temi
  (`api_version`, identità del processo; `user_version`, backup e rifiuto delle versioni future).
- **Branch:** audit dei 27 branch remoti in `MASTER_AUDIT.md`. 26 sono già interamente nella candidata;
  `mie-modifiche` (Streamlit/OMEGA con automazione Paper) resta escluso e intatto.

## Correzioni del 25/11
| Problema | Correzione | Prova |
|---|---|---|
| Prezzi arrotondati a 4 decimali: EURUSD 1,08345 e 1,08347 entrambi "1,0835"; 0,00015 → "0,0002" | MT5 dichiara `symbol_info.digits` per strumento (EURUSD 5, USDJPY 3), Demo/Simulazione dichiarano 2; `price()` usa quei decimali, zeri finali compresi. Se la precisione è ignota usa 10 cifre significative. La scala del grafico usa la stessa precisione. | `format.test.ts` (forex, JPY, valori nulli, precisione non valida), `test_bars_carry_only_broker_declared_price_digits` |
| Test Windows instabile: `'100'` cercato nell'intera diagnostica (corrispondeva al PID 10044) | controllo strutturato: nessun campo conto e nessun valore del saldo nella diagnostica, PID escluso; controllo provato da un test dedicato | `test_leak_check_flags_account_values_but_not_a_pid_containing_the_same_digits` |
| Ora del server MT5 diversa da UTC (R8) | nessun offset inventato: tick e candele "nel futuro" sono scartati, con lo scarto misurato nel messaggio. Senza dati verificati la proposta resta `NO_TRADE`. | `test_server_time_ahead_of_utc_is_reported_not_converted` |
| Verifica Windows senza quotazioni né orari | `check_mt5_api`: 9 passi read-only con PASS/FAIL, età della quota e della candela rispetto a UTC, codice di uscita del servizio | `tests/test_check_mt5_api.py`; su macOS si ferma alla fase `platform` |
| Ledger SQLite senza versione né backup | `PRAGMA user_version = 1`, `quick_check` e backup SQLite prima di migrare; un ledger più recente viene rifiutato senza toccarlo | `tests/test_ledger_schema.py` |
| MetaTrader5 assente dai NOTICE | nota nel generatore e nel file: licenza dichiarata MIT su PyPI, modulo binario nativo, redistribuzione da confermare | `THIRD_PARTY_NOTICES.md` |

## Licenze e distribuzione (27/11)
| Controllo | Esito |
|---|---|
| Wheel distribuito `metatrader5-5.0.6231-cp311-cp311-win_amd64.whl` (sha256 `1e0fb5e4…918f918d`, 7 file, include `_core.cp311-win_amd64.pyd`) | ispezionato |
| `LICENSE.txt` nel wheel | **MIT completa**, "Copyright 2000-2025 MetaQuotes Ltd.": consente la redistribuzione se la nota di copyright e di permesso accompagna ogni copia |
| Pagine ufficiali (PyPI, documentazione MQL5 Python) | MIT su PyPI; nessuna restrizione di redistribuzione né EULA specifica del pacchetto. I "Terms and Conditions" del sito MQL5 non sono stati letti: riguardano il sito e il terminale, che l'app non distribuisce |
| Nota MIT nell'installer | prima: **assente** (nessun NOTICE nel bundle). Ora: `THIRD_PARTY_NOTICES.md` con il testo MIT di MetaQuotes nelle risorse Tauri e `LICENSE.txt` originale nel sidecar Windows |
| Dipendenze Python, npm, Rust | inventario rigenerato: nessuna licenza non dichiarata, nessuna GPL/AGPL. I testi completi delle altre licenze (MIT/BSD/Apache) **non** sono ancora inclusi: necessari prima di una release pubblica |
| Audit vulnerabilità | pip-audit 0, npm audit 0, cargo audit 0 vulnerabilità; 3 avvisi su dipendenze indirette di Tauri: `chrono` e `proc-macro-error` non mantenuti, `glib` 0.18 (solo Linux/GTK) "unsound" |
| Licenza del progetto | **manca `LICENSE`**: decisione del proprietario, non inventata |

Questo non è un parere legale. Per una candidata privata di test il blocco MetaTrader5 è risolto;
per la release pubblica servono la licenza del progetto e i testi completi delle licenze delle dipendenze.

Correzioni precedenti (R1–R7: worker MT5 su Windows, SDK nel `.venv` e nel sidecar, crash/timeout,
`tasklist` localizzato, profilo utente nella diagnostica): in `MT5_CONNECTION_FIX_REPORT.md` e
`EMERGENCY_DELIVERY_REPORT.md`.

## Test sull'albero candidato (macOS ARM, 27/11/2026)
- **Python:** compileall ok · pytest 927 passati / 2 saltati (solo Windows) / 1 warning (`websockets.legacy`
  deprecato, da uvicorn) · Ruff ok · `pip check` ok · pip-audit 0 vulnerabilità.
- **Frontend:** `npm ci` · Vitest 82 · `tsc` ok · `npm run lint` ok · `npm run build` ok · npm audit 0.
- **Rust:** `cargo test` 4 passati · `cargo check` ok · cargo audit 0 vulnerabilità, 3 avvisi (sopra).
- `git diff --check` ok. Su 25/11 (`1aeba37`, `49079ab`) i risultati restano attribuiti a quegli SHA.
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
| 12 | Revisione reciproca | NON VERIFICATO: Codex (issue #9) e Gemini (brief nell'issue #9, da consegnare) non hanno risposto. Il silenzio non vale come approvazione |
| 13 | Documentazione | ✅ questo report, `ARCHITECTURE.md`, `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`, `MT5_CONNECTION_FIX_REPORT.md`, `WORKLOG.md` |

## Cosa serve per approvare
1. **Proprietario, su Windows 11 con MT5 Demo aperto:** `.\.venv\Scripts\python.exe -m scripts.check_mt5_api --symbol EURUSD`,
   poi l'output incollato nell'issue #9. Se il passo 8 mostra uno scarto (es. +7200 s), si decide la
   correzione dell'ora del server su quella prova.
   Poi i passi 5–7 della stessa guida: Connessioni → Verifica MetaTrader 5 → conto in Panoramica.
2. **Codex e Gemini:** revisione indipendente di questo SHA (richiesta e brief nell'issue #9).
3. **Proprietario:** licenza del progetto; firma e notarizzazione (o candidata solo privata); approvazione
   esplicita del merge.

Installazione, aggiornamento e backup: `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`.
