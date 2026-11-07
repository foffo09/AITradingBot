# Persona 2 — piano dashboard e integrazione

Base UI: 67f6a47. Backend integrato con fast-forward a 1a68d5b.
Esecuzione autonoma richiesta dall'utente; conservare Streamlit e Plotly.

## Scelte

Evolvere l'interfaccia esistente: header compatto, metriche leggibili, mercato e
rischio con fonte/unità, grafico pulito con navigazione, dettagli in expander.
Nessuna riscrittura del backend o del motore. Dati assenti=N/D. Nessuna metrica
Paper ricostruita da conti locali, drawdown senza curva storica=N/D.

## Passi

1. Test baseline dashboard. Leggere BACKEND_HANDOFF e i chiamanti.
2. Helper puro src/ui/dashboard_metrics.py:
   dashboard_summary(scope, account, overview, positions, history, now)
   per campi capital/equity/cash/daily_pnl/cumulative_pnl/drawdown/exposure_value/exposure_pct/fees;
   market_summary(quote, data, quality, now) per quote/spread/provenienza/freschezza.
   Test di fonti, dati mancanti e nessuna commissione/drawdown inventati.
3. src/ui/charts.py: conservare firma/rendering e marker, migliorare tema,
   zoom/pan/range selector, stato zoom mantenuto e legenda essenziale. Test Plotly.
4. app.py e helper UI dei contesti: tre workspace separati con database distinti,
   chiavi di sessione isolate e nessun accesso broker nei workspace offline.
   Conservare percorsi protetti, nessuna migrazione o lettura DB personale.
5. Ricollegare metriche/mercato/rischio agli helper; quote vecchie/cause di errore
   chiare, cached fetched_at preservato da backend, proposte storiche non operative.
   Nessuna soglia o permesso di invio cambiato. Niente automazioni avviate.
6. AppTest offline su tre contesti, cambio contesto, errori broker/quote, marker,
   dati assenti, conti indipendenti e divieto broker nei contesti offline.
7. Compileall, gruppi mirati, suite completa, pip check, diff-check, review.
   Aggiornare guida e worklog; commit e push esclusivamente feature/dashboard-ui.

## Limiti della consegna

Nessun server, feed autenticato o ordine; AppTest e trasporti simulati.
Windows/responsive manuale non saranno dichiarati verificati senza esecuzione.
Il messaggio dell'utente termina al punto 6: leggere BACKEND_HANDOFF come documento
obbligatorio, senza presumere istruzioni ulteriori non ricevute.
