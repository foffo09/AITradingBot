# Release readiness — 24 novembre 2026

Branch `agents/claude-macos-complete-fix-20261124` (sopra `agents/claude-complete-modernization-20261124`, PR #10).
Nessun merge, nessuna release, nessun artefatto pubblicato.

## RISOLTO (corretto e verificato con test e CI)
- Causa del fallimento MT5 via servizio: deadline che includeva avvio del worker e `initialize`; riprodotto e corretto (vedi MT5_CONNECTION_FIX_REPORT).
- Incoerenza stato worker / snapshot MT5: stato guidato dall'esito verificato.
- Spawn del worker che re-importava FastAPI, pandas e alpaca: import pigri, test dedicato.
- Messaggi generici: fase, codice MT5, worker, tempi e id richiesta nella diagnostica e nei log.
- Endpoint di scrittura irraggiungibili per i contesti MT5 e Paper; isolamento dei 4 contesti testato.
- Dashboard MT5 con campi del conto e N/D; errore di lettura distinto da conto vuoto.

## MIGLIORATO
- L'app non avvia più il terminale MT5 (fase `terminal_not_running` esplicita).
- Uscita del worker riportata con exit code; worker terminato su esito negativo; `close` senza falsi errori.

## DA VERIFICARE SU WINDOWS
- Connessione MT5 reale tramite servizio: `python -m scripts.check_mt5_api` con terminale aperto (procedura nel report MT5).
- Stessa verifica sul sidecar confezionato (`--binary`) e nell'app desktop (Connessioni → Verifica MetaTrader 5).
- Tempi reali di avvio del worker sul PC (`worker.startup_ms`).
- Prova manuale dell'app su Windows 11.

## ANCORA APERTO
- Firma Developer ID e notarizzazione macOS, firma Authenticode Windows: servono account e certificati del proprietario.
- Licenza del progetto: decisione del proprietario (inventario terze parti in `THIRD_PARTY_NOTICES.md`).
- Revisione indipendente di Codex sulle modifiche MT5: Codex ha raggiunto il limite d'uso in questa sessione.
- Notion: non accessibile da questa sessione; nessuna attività o report Notion letto o aggiornato.
