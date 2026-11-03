# Istruzioni per AITradingBot

- Leggi `docs/WORKLOG.md`, `docs/DECISIONI_TECNICHE.md` e `docs/REVIEW_QUALITA_E_ROADMAP.md` prima di intervenire. La guida è `docs/GUIDA_COMPLETA_PROGETTO.md`; i test sono mappati in `docs/MATRICE_TEST.md`.
- Verifica root Git, branch, status, diff e file non tracciati. Non equiparare checkout macOS e Windows. Conserva le modifiche preesistenti e descrivi separatamente quelle nuove.
- Non aprire o copiare file di credenziali, non esporre segreti o dati personali. Non aprire database personali: usa schemi nel codice e database temporanei nei test.
- Non avviare trading, automazione operativa, server Streamlit o richieste operative ai broker. `AppTest` con mock è consentito. Demo, ledger, backtest e conti Paper devono mantenere capitali e persistenza distinti.
- Non fare reset, clean, checkout, stash, commit o push senza istruzioni esplicite per quell'attività. Non cancellare dati o annullare lavoro esistente.
- Mantieni la modifica più piccola che risolve la causa. Prima leggi chiamanti e test. Niente nuove strategie, livelli finanziari o autorizzazioni implicite. Non indebolire i controlli per far passare i test.
- Un dato mancante è `N/D`, non zero. Ogni numero deve dichiarare origine e unità; dati sintetici, stime, proposte, ordini e fill devono essere distinguibili. Segnale SMA non significa previsione o autorizzazione di invio.
- I test devono essere offline, con credenziali fittizie e file temporanei. Il `conftest.py` protegge l'esecuzione; non disabilitarlo per ottenere test verdi. Un'integrazione autentica richiede un incarico separato e non fa parte di pytest.
- Dopo ciascun gruppo: compilazione, test mirati e revisione del diff. Alla fine esegui `python -m compileall -q app.py config src tests`, `python -m pytest -q`, `git diff --check`, status e stat. Riporta passati, falliti, saltati e limiti di piattaforma effettivi.
- Aggiorna guida e decisioni insieme ai cambiamenti di comportamento; aggiungi una voce al worklog senza riscrivere risultati storici. Chiudi attività solo con prove osservate e lascia il prossimo passo concreto.
- Rispondi in italiano semplice. Non dichiarare sicurezza assoluta, prestazioni migliorate o redditività non misurate.
