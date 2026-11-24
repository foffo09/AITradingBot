# Release readiness — 24 novembre 2026

Branch `agents/claude-emergency-delivery-20261124` (sopra `agents/claude-macos-complete-fix-20261124`, a sua volta sopra `agents/claude-complete-modernization-20261124`, PR #10).
Nessun merge, nessuna release, nessun artefatto pubblicato.

## RISOLTO (corretto e verificato con test e CI)
- **Causa del fallimento MT5 via servizio**: il thread che attende `shutdown` su stdin bloccava l'avvio del worker spawn su Windows (I/O sincrono serializzato sulla stessa pipe). Dimostrato con prova A/B sul runner Windows e corretto (`shutdown_stream`); il servizio reale ora avvia il worker in ~0,1 s.
- Deadline che includeva avvio del worker e `initialize`: separate (riprodotto con test RED).
- Crash del worker riportato come timeout su Windows: exit code letto dopo la raccolta.
- Incoerenza stato worker / snapshot MT5: stato guidato dall'esito verificato.
- Spawn del worker che re-importava FastAPI, pandas e alpaca: import pigri, test dedicato.
- Messaggi generici: fase, codice MT5, worker, tempi e id richiesta nella diagnostica e nei log.
- Endpoint di scrittura irraggiungibili per i contesti MT5 e Paper; isolamento dei 4 contesti testato.
- Dashboard MT5 con campi del conto e N/D; errore di lettura distinto da conto vuoto; conto MT5 anche in Panoramica.

Windows CI run 45455628867: `windows-tests` e `macos-tests` verdi (pytest Windows 907 passati, 2 saltati; `MT5 API CHECK: PASS`).

## MIGLIORATO
- Primo avvio Demo/Simulazione: invito esplicito a creare il conto virtuale invece di sole metriche N/D.
- Selettore indicatori del grafico leggibile (in linea, a capo su schermi stretti).
- L'app non avvia più il terminale MT5 (fase `terminal_not_running` esplicita).
- Uscita del worker riportata con exit code; worker terminato su esito negativo; `close` senza falsi errori.

## DA VERIFICARE SU WINDOWS
- Connessione MT5 reale tramite servizio (il blocco è corretto e provato su Windows senza terminale; manca la prova con terminale e conto Demo): `python -m scripts.check_mt5_api` con terminale aperto (procedura nel report MT5).
- Stessa verifica sul sidecar confezionato (`--binary`) e nell'app desktop (Connessioni → Verifica MetaTrader 5).
- Tempi reali di avvio del worker sul PC (`worker.startup_ms`).
- Prova manuale dell'app su Windows 11.

## ANCORA APERTO
- Firma Developer ID e notarizzazione macOS, firma Authenticode Windows: servono account e certificati del proprietario.
- Licenza del progetto: decisione del proprietario (inventario terze parti in `THIRD_PARTY_NOTICES.md`).
- Revisione indipendente di Codex sulle modifiche MT5: Codex ha raggiunto il limite d'uso in questa sessione.
- Notion: non accessibile da questa sessione; nessuna attività o report Notion letto o aggiornato.
