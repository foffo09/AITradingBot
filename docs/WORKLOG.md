# Registro del lavoro

Le voci registrano risultati osservati, non promesse. I percorsi personali sono omessi; il checkout macOS indicato è `outputs/codex_omega_bot`, distinto da quello Windows.

## 2026-10-29 — Revisione di qualità precedente

- Workspace: checkout macOS, branch `main`, base Git `f74a961`.
- Stato iniziale: correzione del grafico e sei regressioni già locali in `app.py` e `tests/test_dashboard_validation.py`; preservati.
- Interventi: isolamento DB anche per hard link/in Demo, storico ordini con blocco a saturazione, validazione FX, chiavi idempotenti letterali, dati futuri, RSI sui casi limite, mark temporali monotoni e transazione di aggiornamento.
- Verifiche osservate: compilazione exit 0; 134 test mirati passati in 14,92 s; suite completa 313 passati, 0 falliti, 0 saltati, un warning `websockets.legacy`, 23,63 s. Guard temporaneo: zero tentativi rete/credenziali.
- Documenti: creata `REVIEW_QUALITA_E_ROADMAP.md`, aggiornato README. Nessun commit, push, server o ordine.
- Aperti: calendario, coordinamento per conto, DRY-RUN, portabilità Windows e paginazione completa. Le prove autentiche e il checkout Windows non sono stati eseguiti.

## 2026-10-29 — Chiarezza dashboard e continuità del progetto

- Workspace verificato: medesimo checkout macOS e `main`; Python della `.venv`: 3.12.14.
- Stato iniziale: 8 file tracciati modificati; `docs/` e `tests/test_fx_rates.py` non tracciati. Nessuna modifica iniziale annullata.
- Piano: istruzioni permanenti e test offline riproducibili; componenti puri di presentazione e provenienza; segnale e stati operativi distinti; anteprima senza submit se verificabile; documenti e test finali.
- Primo gruppo osservato: creati `AGENTS.md`, guard pytest permanente e due test della policy. Controllo mirato con FX: 13 passati, rete 0, credenziali 0, 0,21 s.
- Interventi completati: metriche Paper con origine unica e N/D, rimozione della vecchia equity dopo errore, fonte Demo visibile e catalogo consultabile, segnale SMA spiegato, renderer con storico esplicito, isolamento dei marker Demo/Paper, deduplicazione ordini, validazione fill, filtro ordini/decisioni ed export degli eventi mostrati, anteprima DRY-RUN manuale senza submit. Soglie finanziarie, strategia e default di invio preesistenti non modificati.
- Regressioni osservate durante il lavoro: il test rafforzato sulla vecchia equity falliva prima del fix; due casi di quote future/invalide fallivano prima della correzione e sono poi passati. Quattro casi intermedi del grafico dipendevano dall'overlay Paper sulla Demo: aggiornato il setup a renderer diretto conservando le asserzioni e aggiungendo una prova UI dell'isolamento.
- Suite completa intermedia: 333 passati, un warning, 21,46 s. Dopo gli ultimi casi, gruppo mirato dashboard/presentazione/automazione/sicurezza/guard: **90 passati**, un warning, **14,37 s**.
- Verifica finale nella `.venv`: `python -m compileall -q app.py config src tests`, **exit 0 e output vuoto**. `python -m pytest -q`: **336 passati, 0 falliti, 0 saltati, 1 warning, 22,57 s; exit 0**. Warning: deprecazione di `websockets.legacy` della dipendenza installata. Nessuna dipendenza aggiornata.
- Output finale del guard: `TEST ISOLATION: {'network': 0, 'credentials': 0}`. AppTest e broker simulati, SQLite temporanei; nessun servizio autentico usato.
- Documenti: `AGENTS.md`; guida completa, guida operativa, decisioni, matrice, review e questo registro; README collegato e descrizione DRY-RUN aggiornata.
- Autocontrollo: rilette le funzioni di presentazione, renderer, anteprima e chiamanti/test; preservati i test e i controlli precedenti. `git diff --check` senza errori. Base `f74a961` invariata; nessuno staging, commit o push. Stato finale locale: 11 file tracciati modificati, più nuovi documenti, guard, componenti UI e test. Il working tree resta intenzionalmente modificato.
- Non aperti `.env` o database personali; nessun server, richiesta operativa, ordine autentico o attivazione di automazione su un conto. Il guard riguarda il processo dei test, non costituisce una sandbox ostile.
- Aperti P1: coordinamento rischio fra sessioni/processi e calendario delle barre. Aperti P2: DRY-RUN continuo e log arricchito, paginazione completa, Windows, crescita snapshot e refresh coordinato delle sezioni. Non verificati browser manuale/responsive, feed o conti autentici, ordini testnet e checkout Windows.
- Prossimo passo: definire il contratto temporale di apertura/chiusura e il singolo esecutore per conto; prima di abilitare altri flussi, dimostrare con worker simulati concorrenti esposizione globale corretta e riavvio senza reinvio ambiguo. L'anteprima manuale attuale è utilizzabile come percorso di valutazione, non come certificazione di questi requisiti.

### Inventario finale rispetto a HEAD

File tracciati modificati (comprende il lavoro già presente):

- `README.md`: documentazione e collegamenti.
- `app.py`: isolamento e presentazione dashboard, errori, anteprima e chiamanti del renderer.
- `src/broker/alpaca_client.py`: storico ordini saturo rifiutato.
- `src/data/fx_rates.py`: cambio e data validati.
- `src/simulation/ledger.py`: idempotenza e prezzi temporalmente ordinati.
- `src/trading/paper_automation.py`: ritorno dell'anteprima prima del submit.
- `tests/test_broker.py`: limite e saturazione ordini.
- `tests/test_dashboard_validation.py`: grafico, isolamento, dati, Paper e anteprima UI.
- `tests/test_paper_automation.py`: valutazioni BUY/SELL senza submit e vincoli dati.
- `tests/test_paper_safety.py`: nessuna vecchia equity dopo un errore.
- `tests/test_simulation_ledger.py`: regressioni chiavi e mark.

File non tracciati, lasciati disponibili per revisione:

- `AGENTS.md`: regole permanenti.
- `conftest.py`: guard offline della suite.
- `src/ui/__init__.py`, `src/ui/presentation.py`, `src/ui/charts.py`: package, funzioni pure e renderer.
- `tests/test_fx_rates.py`, `tests/test_test_isolation.py`, `tests/test_ui_presentation.py`: regressioni cambio, policy e presentazione.
- `docs/GUIDA_COMPLETA_PROGETTO.md`, `docs/COME_USARE_LA_DASHBOARD.md`: guida tecnica e uso pratico.
- `docs/REVIEW_QUALITA_E_ROADMAP.md`, `docs/DECISIONI_TECNICHE.md`, `docs/MATRICE_TEST.md`, `docs/WORKLOG.md`: prove, decisioni, copertura e continuità.

## 2026-10-29 — Priorità P1: proprietà Paper e calendario — perimetro locale concluso, residui aperti

- Workspace: stesso checkout macOS, `main`, HEAD `f74a961`; stato iniziale 11 file tracciati modificati e 14 non tracciati. Nessuna modifica precedente annullata.
- Piano: coordinatore di conto tra processi, intenti persistenti e blocco prudenziale; poi calendario di sessione e contratto delle barre, test deterministici e documentazione. Skill ponytail applicata per limitare refactoring e dipendenze.
- Fase 1: `paper_coordinator.py` usa flock non bloccante su file stabile, identità conto hashata, proprietà processo/thread, validità decisione 30 s senza scadenza del lock e journal SQLite con synchronous FULL prima del submit. Nessun furto del lock per timeout; file non eliminato al rilascio.
- Invii disabilitati per default: richiedono configurazione esplicita single_host, directory condivisa da tutti i processi dello stesso conto, ID account verificato e lease valido. Un submit diretto senza lease è rifiutato anche dopo verifica account. L'anteprima rimane senza submit e senza permesso operativo.
- Recupero: crash rilascia il lock OS ma conserva l'intento. Assenza da uno snapshot non significa rifiuto. Solo terminale rifiutato/cancellato/scaduto con filled_qty esplicitamente zero permette nuove decisioni; il vecchio ID resta riservato. Fill, parziali e stati incerti bloccano ogni nuovo invio. Nessun reset o sblocco manuale aggiunto.
- Limite esplicito: esclusione provata fra processi cooperanti sullo stesso host/directory. Altri host, filesystem distribuiti, SDK esterni e configurazioni con directory divergenti non sono coordinati; non sono autorizzati come deployment distribuito. Per completare P1 globale serve esecutore unico con credenziali possedute solo dal servizio e riconciliazione atomica/riservata di posizioni e saldo.
- Prime verifiche: 74 casi preesistenti di automazione/sicurezza/dashboard passati (14,53 s, un warning); 12 nuovi test coordinatore passati (0,24 s). Nessuna rete o credenziale reale. Verifiche di fase finali da registrare.

### Fase 1 — Verifica conclusa del perimetro locale

- Gruppo mirato: 88 passati, un warning, 14,65 s. Compilazione exit 0, output vuoto. Prima suite: 348 passati e 2 fallimenti di spawn dopo AppTest, 24,05 s; nessuna rete/credenziale. AppTest aveva lasciato `__main__.__file__` su app.py: i worker tentavano di rieseguire l'app e si fermavano sul requisito del DB isolato. Corretto il bootstrap in fixture, non disabilitati controlli o test; i worker caricano anche il guard offline.
- Ripetizione dashboard+processi: 52 passati, un warning, 14,55 s. Suite fase 1: **350 passati, 0 falliti, 0 saltati, un warning, 21,96 s**. Compileall e diff-check exit 0. Autocontrollo: percorso pubblico e chiamanti protetti, nessun invio fuori lease; documentati scope host/directory e blocco dopo fill. Non chiuso P1 distribuito.

### Fase 2 — Contratto calendario e dati

- Installata nella venv la nuova dipendenza diretta pandas-market-calendars 5.5.0 (fissata in requirements), con exchange-calendars 4.13.2, pyluach 2.3.0, korean-lunar-calendar 0.4.0. Installazione da PyPI e lettura documentazione ufficiale; nessuna chiamata broker. Le dipendenze preesistenti non sono state aggiornate. Il calendario non richiede rete durante i test.
- Aggiunto bar_timing.py: NYSE/RTH con fuso, DST, festività e sedute ridotte; intraday crypto UTC continuo; timestamp espliciti/unici/ordinati, acquisizione dopo fine intervallo e margine 30 s. Soglie massime di età preservate; quote future rifiutate anche dal backend.
- L'adattatore annota il contratto di inizio e lo scope all_sessions delle barre azionarie grezze. Daily grezzi, crypto daily e weekly non hanno un contratto operativo sufficientemente verificato e sono bloccati, non etichettati come chiusi. La UI spiega la differenza fra ultima barra, fine temporale e autorizzazione.
- Le fixture dei test esistenti sono state rese deterministiche e coerenti con il contratto: clock fisso in seduta, timestamp su griglia, account ID fittizio e coordinatore temporaneo. Conservate aspettative di rischio, quantità, invio, duplicati e start/stop.
- Primo gruppo calendario: 29 passati in 0,64 s. Gruppo integrato: un errore di collocazione in un nuovo test (NameError monkeypatch), corretto senza modificare il codice di produzione o le aspettative. Il gruppo successivo ha prodotto **122 passati**, un warning, **15,88 s**. Compilazione exit 0. Suite intermedia: **384 passati**, un warning, **23,81 s**. Guard: rete 0, credenziali 0.
- Autocontrollo aggiuntivo: nuovo test che fa chiudere la seduta durante l'ultima verifica broker falliva prima del fix. Il lease ora richiede un ricontrollo finale di calendario, ultima barra e quota; la stessa validazione è eseguita prima della proposta. Resta il limite inevitabile dell'istante di ricezione del broker rispetto al clock locale. Verifiche finali da registrare dopo questa correzione.

### Verifica finale della sessione P1

- Compilazione finale `.venv/bin/python -m compileall -q app.py config src tests`: **exit 0, output vuoto**.
- Gruppo mirato finale (calendario, coordinatore, automazione, sicurezza e dashboard): **124 passati, 0 falliti, 0 saltati, 1 warning, 15,65 s**.
- `.venv/bin/python -m pytest -q`: **386 passati, 0 falliti, 0 saltati, 1 warning, 24,01 s; exit 0**. Warning invariato: deprecazione `websockets.legacy`. Output guard finale: `TEST ISOLATION: {'network': 0, 'credentials': 0}`.
- Rispetto ai 336 iniziali: **50 nuovi casi** (13 coordinatore, 29 calendario, 8 integrazioni automazione). Nessun caso precedente eliminato o saltato. Le fixture preesistenti sono state aggiornate per ID/coordinatore fittizi e clock/contratto di feed espliciti, conservando le asserzioni operative.
- Il controllo finale del lease ricontrolla proprietà e deadline anche dopo la validazione temporale; un test deterministico impedisce che una validazione lenta estenda il limite di 30 s.
- Autocontrollo: rilette implementazioni, chiamanti e test modificati; nessun candidato import inutilizzato nell'analisi AST dei nuovi moduli, app, config, broker e automazione. `git diff --check`: exit 0, output vuoto. Nessuna soglia economica o strategia modificata; controlli temporali e autorizzazioni resi più restrittivi e documentati.
- Non aperti file di segreti o database personali. Nessun server, ordine autentico, richiesta operativa broker, attivazione di automazione, staging, commit o push. Solo documentazione ufficiale e PyPI interrogati fuori dai test per la dipendenza calendario.
- Stato finale: stesso HEAD `f74a961`, 13 file tracciati modificati e 18 file non tracciati; include tutto il lavoro preesistente. Modifiche lasciate locali.
- Limiti: coordinatore locale fra processi cooperanti con directory unica; niente distribuito/NFS/Windows operativo. Intenti con fill/timeout o controllo finale fallito restano bloccati; recupero automatico solo terminale zero-fill esplicito. Calendario di regole locali, non verifica live di chiusure straordinarie; daily/weekly grezzi non verificati restano esclusi dalle decisioni. Nessuna prova autentica o visuale nel browser.
- Prossimo passo concreto: servizio esecutore unico per conto, unico possessore delle credenziali, con API client priva di accesso diretto al broker, journal centrale e riconciliazione di intenti/fill/saldo/posizioni. Prova di accettazione: due host, crash prima/dopo API e snapshot ritardati senza superare limiti o ripetere invii. Separatamente servono fixture ripulite del protocollo di aggregazione per abilitare daily/weekly.

### File toccati in questa sessione

- Nuovi: `src/trading/paper_coordinator.py`, `src/data/bar_timing.py`, `tests/test_paper_coordinator.py`, `tests/test_bar_timing.py`.
- Raccordi operativi/UI/config: `src/trading/paper_automation.py`, `src/broker/alpaca_client.py`, `app.py`, `config/settings.py`, `requirements.txt`.
- Isolamento e fixture/test: `conftest.py`, `tests/test_paper_automation.py`, `tests/test_paper_safety.py`, `tests/test_dashboard_validation.py`.
- Documentazione: README e i sei documenti esistenti in docs (guida completa, uso dashboard, review, decisioni, matrice, worklog).
- Preservati senza nuove modifiche di questa sessione gli altri file già locali: AGENTS, helper/renderer UI e relativi test, FX, ledger e test del broker/ledger/FX.

### Output Git finale

Gli output seguenti comprendono il lavoro precedente; la stat non include i file non tracciati.

`git status --short --branch`

```text
## main...origin/main
 M README.md
 M app.py
 M config/settings.py
 M requirements.txt
 M src/broker/alpaca_client.py
 M src/data/fx_rates.py
 M src/simulation/ledger.py
 M src/trading/paper_automation.py
 M tests/test_broker.py
 M tests/test_dashboard_validation.py
 M tests/test_paper_automation.py
 M tests/test_paper_safety.py
 M tests/test_simulation_ledger.py
?? AGENTS.md
?? conftest.py
?? docs/
?? src/data/bar_timing.py
?? src/trading/paper_coordinator.py
?? src/ui/
?? tests/test_bar_timing.py
?? tests/test_fx_rates.py
?? tests/test_paper_coordinator.py
?? tests/test_test_isolation.py
?? tests/test_ui_presentation.py
```

`git diff --stat`

```text
 README.md                          |  28 ++-
 app.py                             | 450 +++++++++++++------------------------
 config/settings.py                 |  10 +
 requirements.txt                   |   1 +
 src/broker/alpaca_client.py        |  29 ++-
 src/data/fx_rates.py               |   8 +-
 src/simulation/ledger.py           |  22 +-
 src/trading/paper_automation.py    | 100 ++++++---
 tests/test_broker.py               |  20 ++
 tests/test_dashboard_validation.py | 185 ++++++++++++++-
 tests/test_paper_automation.py     | 144 +++++++++++-
 tests/test_paper_safety.py         |  27 ++-
 tests/test_simulation_ledger.py    |  48 ++++
 13 files changed, 703 insertions(+), 369 deletions(-)
```

`git diff --cached --stat`

```text
(output vuoto)
```


## 2026-10-29 — Preparazione pubblicazione autorizzata

- Nuova istruzione esplicita dell'utente: creare e pubblicare su foffo09/AITradingBot tutti i cambiamenti successivi al precedente commit. Questa autorizzazione riguarda il versionamento e supera il divieto di commit/push delle precedenti attività, che rimaneva valido per quelle sessioni. Nessuna autorizzazione al trading o all'avvio del server.
- Checkout macOS confermato, branch main, base f74a961; remote origin HTTPS su foffo09/AITradingBot. Fetch effettuato senza merge/pull; base locale e origin/main coincidenti prima dei nuovi commit.
- Esaminati i 31 file cambiati/nuovi: nessun file di credenziali, database, cache, log o artefatto generato candidato. Scansione di assegnazioni credenziali, prefissi di token, chiavi private e stringhe esadecimali: nessun segreto rilevato; soltanto 38 placeholder esplicitamente fittizi nei test. I file .env e i database personali non sono stati aperti.
- Verifica ripetuta: compileall exit 0, output vuoto; pytest 386 passati, nessun fallimento o skip, un warning websockets.legacy, 24,10 s. Guard: rete 0, credenziali 0. Corretto soltanto un newline vuoto aggiuntivo a fine charts.py segnalato dal controllo del diff staged; nessuna logica cambiata durante la preparazione.
- File aggiunti per nome esplicito, mai git add indiscriminato. Commit logici creati: a769578 (FX e ledger), 57e7ec7 (guard dei test), e29fbcc (dashboard e protezioni Paper/calendario); documenti e istruzioni riuniti nel commit conclusivo della pubblicazione.
- Pubblicazione richiesta su origin/main con push ordinario, senza force o riscrittura della storia. L'esito remoto e gli hash conclusivi vengono verificati dopo il push e riportati nella risposta della sessione; questa voce registra la preparazione già eseguita.
- Restano invariati i limiti tecnici documentati: niente multi-host garantito, recupero completo dei fill o aggregati daily/weekly non verificati. Invio operativo disabilitato per default.

## 2026-10-30 — Preparazione compatibilità Windows

- Repository verificato: main, HEAD 175b88e, origin foffo09/AITradingBot;
  fetch senza avanzamenti. Presenti 17 file tracciati modificati e due nuovi
  file dell'esecutore Paper: conservati, esclusi da questo commit.
- Cause: import fcntl diretto in NativeStore e console, dipendenza POSIX nel
  coordinatore; FastAPI/HTTPX e altri import condivisi solo nel file opzionale.
  Inventario AST di codice/test e confronto con i metadata delle dipendenze.
- Portalocker 3.2.0 sostituisce i tre lock diretti; proprietà esclusiva non
  bloccante e sidecar stabile. Errori di lock/SQLite non autorizzano esecuzione.
  Cleanup NativeStore su inizializzazione fallita e close ripetuto; il
  coordinatore rilascia il descriptor anche se la chiusura del DB fallisce.
- Regressioni osservate prima della correzione: close ripetuto, lock trattenuto
  dopo connect/schema falliti e URI panic con # che apriva un file diverso.
  URI assoluto escaped e connessione panic esplicitamente chiusa dopo l'uso.
- Aggiunte dipendenze condivise alla base, eth-account esplicito tra gli SDK,
  requirements-dev.txt per la suite completa. Pin preesistenti conservati.
  Pytest resta nella base per compatibilità. Uvicorn loop auto nella console;
  uvloop conserva il marker non-Windows. TUI stdin Windows non certificata.
- Nessun limite finanziario, default operativo, intento, riconciliazione o
  controllo di isolamento indebolito. Nessun test eliminato o disabilitato.
- Mac/Python 3.12.14: baseline 432 passati (24,82 s); mirati finali 70 passati
  (1,40 s); checkout locale completo 444 passati (36,48 s), 0 falliti/skip.
  Guard rete 0/credenziali 0; un warning preesistente websockets.legacy.
- Anche la sola versione selezionata per il commit è stata esportata in una
  cartella temporanea, senza file privati né lavoro executor. Venv nuova senza
  system-site-packages, installazione requirements-dev.txt riuscita. Comandi:
  python -m compileall -q app.py config src tests: output vuoto, exit 0;
  test mirati: 70 passati in 1,72 s; python -m pytest -q: 398 passati in
  24,00 s, 0 falliti/skip, un warning; guard rete 0/credenziali 0;
  python -m pip check: No broken requirements found., exit 0.
  Aggiunto poi il pin esplicito eth-account==0.13.7 già presente nella venv.
- git diff --check e git diff --cached --check: output vuoto, exit 0.
  Riletto il diff selezionato, nessun file .env/database/log tracciato incluso.
  Guida PowerShell, decisioni tecniche e matrice aggiornate. I risultati
  storici e la documentazione executor già locale restano conservati.
- Windows/Python 3.11.9 NON ESEGUITO: richiede output della copia di prova
  dell'utente. Nessun server, ordine, automazione, credenziale o DB personale
  aperto. I test verdi non attestano sicurezza del trading automatico.
