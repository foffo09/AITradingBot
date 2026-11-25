# AITradingBot v1.0 — report di release (25 novembre 2026)

**Decisione: V1.0 NON ANCORA APPROVATA.** La candidata è pronta per il collaudo del proprietario su Windows.
Mancano prove che solo il PC del proprietario o la pubblicazione del lavoro Codex possono dare (tabella sotto).
Nessun merge su `main`, nessuna release. Trading reale disattivato, MT5 solo lettura,
`order_submission = disabled`, automazione `STOPPED`.

## Candidata
- Branch `agents/claude-v1-review-20261124`, PR draft #11 verso `main` (contiene #7, #8, #10; storia conservata,
  nessun force-push). Coordinamento: issue #9.
- Catena: `integration/local-web-desktop-20261116` (#7) → `agents/codex-completion-20261116` (#8, Codex) →
  `agents/claude-complete-modernization-20261124` (#10) → `agents/claude-macos-complete-fix-20261124` →
  `agents/claude-emergency-delivery-20261124` (`e2ccaca`) → `agents/claude-v1-review-20261124`.
- Non integrati (non pubblicati sul remote, quindi non revisionabili): branch Codex
  `agents/codex-v1-integration-20261124`, formatter numeri/date, commit locali Codex `11696c1` (handshake
  versionato UI/sidecar) e `b7eb4b3` (migrazioni/backup SQLite).

## Funzionalità
| Area | Stato |
|---|---|
| Servizio FastAPI + UI React stessa origine, sessione locale (cookie HttpOnly SameSite=Strict, Host/Origin esatti) | funziona, testato |
| App desktop Tauri 2 + sidecar PyInstaller (avvio, handshake, chiusura, crash) | funziona su macOS ARM/Intel e Windows Server in CI; Windows 11 non provato |
| Demo / Simulazione: conto virtuale, ledger SQLite separati, registrazioni virtuali | funziona |
| Grafici Lightweight Charts (candele, volume, indicatori), watchlist, storico, backtest, walk-forward | funziona |
| Proposte: con `risk_snapshot=None` restano `NO_TRADE`, nessun ordine | verificato |
| Alpaca Paper | sola lettura, credenziali solo da ambiente; non provato con chiavi reali |
| MT5 | percorso React → FastAPI → MT5Process → worker → MT5ReadOnly → SDK provato fino al terminale (CI senza terminale); connessione reale **da provare** |
| Notifiche | solo avvisi in pagina |

## Bug corretti (dettagli in `MT5_CONNECTION_FIX_REPORT.md`, `EMERGENCY_DELIVERY_REPORT.md`, issue #9)
- R1 worker MT5 bloccato dalla pipe stdin su Windows (causa dimostrata con sonda A/B).
- R2 SDK `MetaTrader5` assente da `.venv` Windows e dal sidecar desktop.
- R3 crash del worker riportato come timeout. R4 `tasklist` su Windows non inglese.
- R5 percorso del profilo utente nella diagnostica (ora `~`). R6 test MT5 falliti solo su Windows reale.
- R8 (25/11) ora del server MT5 trattata come UTC: ora l'errore riporta lo scarto misurato e lo script di
  verifica legge quota e barre; correzione definitiva in attesa della prova reale.
- Primo avvio Demo, pannello conto MT5 in Panoramica, selettore indicatori.

## Test (macOS ARM, 25/11/2026, albero di questo commit)
pytest 909 passati / 2 saltati (solo Windows) · Ruff ok · Vitest 69 · `tsc` ok · `npm run lint` ok ·
`npm run build` ok. CI Windows/macOS: vedi commento finale nell'issue #9 (il run va sull'ultimo SHA, non su
commit precedenti). Ultimo run completo verde: 45489597831 su `9caedc6` (5/5).

## Criteri di accettazione
| # | Criterio | Stato |
|---|---|---|
| 1 | Frontend e backend insieme | ✅ test API + prova nel browser |
| 2 | Desktop si avvia | ✅ CI macOS ARM/Intel, Windows Server; ⏳ Windows 11 |
| 3 | Sidecar | ✅ smoke frozen in CI, incluso controllo MT5 |
| 4 | Dati coerenti | ✅ ledger per contesto, idempotenza |
| 5 | Prezzi frazionari | ⚠️ formato a 4 decimali: 1,08345 → "1,0835", bid/ask forex indistinguibili. Correzione Codex non pubblicata e ancora insufficiente (vedi #9) |
| 6 | Timezone | ✅ API: tutti i timestamp con offset (sonda su tutte le risposte); ⚠️ MT5 ora server (R8) |
| 7 | SQLite aggiornabile | ⚠️ migrazioni solo additive e idempotenti; nessuna versione di schema, nessun backup automatico (procedura manuale nelle guide) |
| 8 | Contesti isolati | ✅ test parametrizzati |
| 9 | MT5 read-only su Windows | ⏳ solo il proprietario può provarlo |
| 10 | Sicurezza | ✅ pip-audit/npm audit 0, nessun segreto, nessun endpoint di scrittura broker |
| 11 | CI verde sul candidato finale | vedi issue #9 |
| 12 | Revisione reciproca | ⏳ Claude ha revisionato il diff Codex pubblicato nell'issue; Codex non ha ancora revisionato R1–R8 |
| 13 | Documentazione | ✅ questo report, `ARCHITECTURE.md`, `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`, `MT5_CONNECTION_FIX_REPORT.md`, `WORKLOG.md` |

## Cosa serve per approvare
1. Proprietario, Windows 11 con MT5 Demo aperto: `.\.venv\Scripts\python.exe -m scripts.check_mt5_api --symbol EURUSD`
   → `PASS` e `MT5 MARKET READ: OK` (o il report con lo scarto, per chiudere R8).
2. Codex: pubblicare il branch con formatter e `b7eb4b3`/`11696c1`; revisionare R1–R8.
3. Proprietario: licenza del progetto e redistribuzione dell'SDK `MetaTrader5`; firma; approvazione del merge.

Installazione, aggiornamento e backup: `INSTALLATION_WINDOWS.md`, `INSTALLATION_MACOS.md`.
