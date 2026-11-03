# Revisione qualità e roadmap — AITradingBot

Data: 29 ottobre 2026. Revisione locale, senza commit, push o operazioni sui conti.

## Identità, perimetro e stato iniziale

Repository: `foffo09/AITradingBot`, checkout macOS confermato dall'utente nella cartella `outputs/codex_omega_bot`; percorso assoluto personale omesso. Branch verificato: `main`, base `f74a961`. Il checkout Windows `prova-ai-locale` non è accessibile e non è stato aggiornato o verificato.

All'inizio erano già modificati `app.py` e `tests/test_dashboard_validation.py`: 61 inserimenti e 9 rimozioni. Contenevano la correzione del grafico e sei regressioni della precedente attività. Queste modifiche sono state preservate e rilette, non sostituite con un'altra versione del file. Nessun file non tracciato era presente all'inizio.

Carico di riferimento: applicazione locale con un operatore. Più sessioni Paper simultanee non sono un caso supportato con garanzie di rischio globali. Le tre superfici applicative sono distinte:

- `app.py`: Streamlit, ledger locale, analisi SMA, backtest, walk-forward e Alpaca Paper.
- `main.py`, `core/`, `providers/`, `execution/`, `ui/`: console con dati pubblici e contabilità Paper locale.
- `src/hyperliquid_testnet_cli.py`: motore nativo Hyperliquid esclusivamente testnet, journal e protezioni propri.

Lettura approfondita dei flussi Streamlit, impostazioni, adattatore Alpaca, catalogo, dati Demo, cambio, strategia, rischio, backtest, walk-forward, automazione e schema/persistenza del ledger. Esaminati anche gli entry point e le protezioni dei runtime aggiuntivi; i loro test fanno parte della suite completa. Non è una nuova verifica end-to-end di ogni protocollo dei provider esterni.

Alla prima revisione `src/data/bar_timing.py` e `src/strategy/auto_selector.py` non esistevano. La terza sessione introduce `bar_timing.py`; `auto_selector.py` resta assente. La selezione delle tre coppie SMA avviene nel walk-forward; non è presente un selettore autonomo con decisione economica NO_TRADE. Documentazione e interfaccia non devono prometterlo.

## Riscontri corretti e relative prove

P0: nessun nuovo difetto critico dimostrato nei percorsi esaminati. Questo non è una certificazione di sicurezza per capitale reale o pubblicazione multiutente.

| ID | Priorità | File/funzione e problema concreto | Correzione e prova |
| --- | --- | --- | --- |
| Q1 | P1 | `app.py::_plot_market_chart`: nella versione base le uscite locali erano nel ciclo dei fill Paper e leggevano `item` di un altro ciclo. Ledger vuoto con fill poteva interrompere la UI; senza fill mancavano le uscite locali. | Correzione precedente preservata: blocchi separati. Sei casi esistenti verificano ledger vuoto/chiuso e ordine assente/pendente/eseguito, prezzi e numero di marker, medie, volume e RSI. |
| Q2 | P1 | Inizializzazione DB in `app.py`: il confronto era solo in modalità Paper e solo tra percorsi risolti. Demo poteva usare il percorso Paper; due hard link diversi potevano riferirsi allo stesso file. | Controllo comune a entrambe le modalità, uguaglianza del percorso e identità del file. Tre nuove regressioni provano il rifiuto prima di costruire il broker o modificare il file temporaneo. |
| Q3 | P1 | `AlpacaClient.get_orders`: richiesta ALL senza limite esplicito; l'SDK installato documenta un default server di 50 ordini. Il conteggio giornaliero e i controlli sui pendenti potevano usare una risposta incompleta. | Richiesta fino a 500 e rifiuto prudenziale se la risposta raggiunge il limite. Due test verificano limite e blocco della saturazione. Non viene dichiarata completa una lista potenzialmente troncata. |
| Q4 | P2 | `fetch_eur_usd_rate`: NaN/infinito positivi superavano il confronto con zero; date arbitrarie venivano convertite in stringa e accettate. | Controllo di finitezza e parsing della data ISO. Undici casi, tutti con risposta HTTP simulata, coprono valori/date invalidi e conservazione di valore, data e timeout validi. |
| Q5 | P2 | `SimulationLedger._find_duplicate`: LIKE interpretava `%` e `_` nelle chiavi; anche un semplice confronto di prefisso confondeva `exit` con `exit:detail`. Operazioni distinte risultavano duplicate senza essere registrate. | Confronto esatto con la chiave e con la forma persistita `chiave:ID_chiusura`. Quattro casi verificano chiavi distinte e ripetizioni effettive di acquisto e vendita. |
| Q6 | P2 | `app.py::_data_is_fresh`: mancava il limite inferiore dell'età. Barre datate molti giorni nel futuro rendevano disponibili i pulsanti locali, anche se il ledger avrebbe poi rifiutato l'ordine. | Applicato lo stesso margine futuro di 120 secondi già usato dal ledger, senza cambiare la sua regola. Test UI con barre future: nessun pulsante di acquisto, nessuna chiamata di invio. |
| Q7 | P2 | `_plot_market_chart`, RSI: sostituire una perdita media nulla con NaN cancellava l'indicatore su serie sempre crescenti o piatte. | RSI visuale 100 senza perdite, 0 senza guadagni, convenzione neutra 50 con entrambi nulli. Warm-up invariato. Tre casi verificano il grafico; la strategia resta esclusivamente SMA. |
| Q8 | P1 | `SimulationLedger.update_mark`: un'osservazione vecchia sovrascriveva prezzo/fonte recenti e aggiungeva uno snapshot regressivo. Riprodotto con database temporaneo. | Timestamp validato e confronto consapevole del fuso nella stessa transazione `BEGIN IMMEDIATE`. Le risposte vecchie non scrivono né producono snapshot; le rettifiche della stessa barra restano ammesse. Due casi coprono ordine temporale, offset, timestamp invalidi e recupero di un vecchio record malformato. |

I test di Q2/Q4/Q5 hanno prodotto 11 fallimenti prima dei fix; Q6/Q7 tre; Q3 due; Q8 due. Nell'autocontrollo è stato aggiunto il quarto caso Q5, che ha esposto e corretto anche la collisione sul separatore. Non sono stati introdotti skip o modificati i test per ignorare eccezioni dell'applicazione.

## Verifiche positive e limiti dell'evidenza

- La SMA calcola gli incroci con medie correnti e precedenti; le barre insufficienti producono nessun segnale. Nessun indicatore aggiunto alla decisione.
- Il backtest verifica prezzi e timestamp, esegue il segnale sulla barra successiva, separa operazioni chiuse e posizioni aperte e valuta queste ultime al netto dei costi stimati di liquidazione. Il benchmark usa capitale e ipotesi di costo coerenti.
- Il walk-forward seleziona sul training e valuta sul test successivo; test fold disgiunti, warm-up e capitale ripartono per ogni fold. Non viene inventato un rendimento composto di portafogli indipendenti.
- Il client Alpaca è Paper; richiede verifica dell'account e ricontrolla account attivo/non bloccato prima dell'invio. Fonte sintetica e quotazioni invalide non possono autorizzare l'automazione.
- Il log SQLite e il saldo nativo Alpaca rimangono concetti distinti. Stop dei cicli non significa cancellazione degli ordini già inviati: l'interfaccia lo dichiara.
- Gli invii Hyperliquid mainnet e i redirect HTTP sono vietati da codice e test simulati. Non è stata eseguita alcuna operazione autenticata testnet.
- Gli input/risultati di backtest sono identificati da dati, fonte e parametri; cambi di selezione invalidano i risultati nella UI.
- I test TUI eseguiti su macOS passano. Nessuna prova Windows e nessuno skip aggiunto. `main.py` e il journal nativo usano `fcntl`; la console sceglie `uvloop`. Questi percorsi richiedono lavoro di portabilità, non una semplice etichetta di test.

## Problemi aperti da affrontare prima di estendere l'uso

### R1 — P1: rischio globale tra sessioni Paper

Nella base mancava un coordinatore condiviso fra sessioni. La terza sessione introduce lock OS per conto e journal degli intenti: tre processi/sessioni con stato vuoto concorrente ottengono un solo intento/invio simulato. Account cambiato, lease rilasciato/scaduto, thread diverso, journal corrotto e piattaforma senza flock bloccano l'esecuzione. Il submit pubblico richiede un lease associato alla directory configurata e al conto verificato. Default operativo disabilitato.

**Stato: mitigazione locale verificata, P1 globale ancora aperto.** Tutti i processi cooperanti devono usare stesso host e directory; niente garanzie fra macchine, SDK esterni o directory divergenti. Dopo un fill resta il blocco finché non esiste una riconciliazione affidabile di saldo/posizioni. Solo terminali con zero fill esplicito possono essere recuperati automaticamente; assenza, parziali e timeout non sono uno stato sicuro.

Soluzione residua: singolo servizio esecutore per conto con credenziali esclusivamente nel servizio, richieste client senza accesso all'SDK, journal centrale e riconciliazione verificata dei fill. Accettazione: worker su due host, crash tra intento/API/conferma, snapshot broker ritardati e nessun overshoot o reinvio ambiguo. Non aggirare il blocco cancellando file.

### R2 — P1: completamento delle barre senza calendario

La terza sessione sostituisce l'esclusione basata sulla sola durata con `select_completed_bars`: calendario NYSE, DST, festività, sedute ridotte, contratto di inizio barra, acquisizione e margine prudenziale di pubblicazione. Quote future non ammesse; barre duplicate/fuori ordine/senza fuso/stale rifiutate. Un ulteriore ricontrollo temporale viene eseguito dopo la riverifica del broker, subito prima dell'invio: un test riproduce la chiusura durante la valutazione e impedisce il submit.

**Stato: calendario implementato/testato per i contratti supportati; integrazione autentica e aggregati ambigui non verificati.** Intraday equity solo RTH, crypto intraday continuo. Daily RTH espliciti sono testati ma non attribuiti al feed grezzo; daily equity grezzi, daily crypto e weekly restano solo analisi e sono bloccati operativamente. Il flag storico degli orari non autorizza extended hours. Mancanza calendario o contratto non genera fallback permissivi.

Residuo: verificare il contratto/aggregazione RTH del feed con fixture autentiche ripulite, certificare i daily/weekly prima di abilitarli e mantenere aggiornate le chiusure straordinarie. La chiusura temporale non garantisce immutabilità del feed; il ricontrollo locale non può garantire l'istante di ricezione in rete del broker.

### R3 — P2: DRY-RUN continuo e tracciabilità completa

Alla prima revisione mancava un percorso di valutazione senza submit. La sessione successiva ha introdotto `execute_paper_signal(dry_run=True)` e il pulsante di anteprima manuale: tutti i controlli esistenti restano applicati e il risultato valido viene restituito prima dell'invio. Test BUY/SELL fanno fallire qualunque chiamata al submit e confermano quantità/prezzo; AppTest verifica che il pulsante non attivi l'automazione. Un avvio operativo rimane distinto e può inviare ordini Paper.

Residuo: progettare un DRY-RUN continuo predefinito con log strutturato di versione/parametri/fonte, senza cambiare implicitamente il contratto degli attuali chiamanti. La nuova anteprima registra la decisione nel log esistente, ma non migra né ricostruisce i campi assenti degli eventi storici. Accettazione: un broker simulato che fallisce su qualunque submit deve completare un'intera sessione continua DRY-RUN.

### R4 — P2: disponibilità con storico ordini saturo

Q3 è una protezione, non una paginazione completa. Con almeno 500 ordini restituiti, monitor e automazione si bloccano prudentemente. Anche 500 ordini esattamente completi vengono trattati come ambigui.

Soluzione: richieste separate per pendenti e storico del giorno, paginazione verificata, deduplicazione e rilevazione di pagine sature al medesimo timestamp. Nessuna indicazione di cancellare dati o azzerare conti per aggirare il blocco.

### R5 — P2: portabilità, crescita dei dati e debito UI

- La compatibilità Windows di TUI, `fcntl` e loop eventi non è provata. Serve una verifica nativa del medesimo commit e delle dipendenze; un risultato macOS non la sostituisce.
- `app.py` combina ancora avvio, risorse e pagine. Nella seconda sessione renderer e funzioni pure sono stati estratti in `src/ui/`; la separazione completa delle pagine rimane futura. Il rischio è cambiare origini o stato di una pagina intervenendo su un'altra.
- I fragment aggiornano conto, quote e automazione indipendentemente; alcuni riepiloghi esterni al fragment si riallineano solo al rerun completo. Non promettere aggiornamento atomico di tutte le sezioni. Test di refresh coordinato e verifica visuale restano necessari.
- `update_mark()` registra snapshot a ogni aggiornamento accettato e la summary li carica integralmente. La memoria e il tempo crescono con la durata della sessione. Servono una politica di campionamento/retention e query aggregate prima di un uso continuativo di mesi.
- Il modello usa spread, commissioni e slippage configurati, non misurati da esecuzioni autentiche. Annualizzazione e Sharpe assumono campionamento regolare; non dimostrano redditività.

## Roadmap ordinata e criteri di accettazione

Costi relativi: basso = modifica circoscritta; medio = più moduli/contratti; alto = nuovo flusso o validazione prolungata. Nessuna stima di rendimento economico.

| Ordine | Area/problema e beneficio | Costo / rischio | Prerequisito e accettazione verificabile |
| --- | --- | --- | --- |
| 1 | Estendere l'anteprima DRY-RUN manuale a un ciclo continuo tracciabile. | Medio; rischio confondere simulazione e invio. | R3; submit-spy sempre vuoto per più cicli, log con versione, origine, controlli, prezzo e timestamp. |
| 2 | Coordinamento rischio per conto: impedire overshoot e richieste concorrenti. | Alto; blocchi e recupero dopo crash. | R1; tre worker concorrenti non superano esposizione/ordini massimi, riavvio senza reinvio ambiguo. |
| 3 | Sessioni e barre completate: rendere coerenti segnale UI e automazione. | Medio; rischio usare barre in formazione. | R2; test NYSE con DST, festività, seduta ridotta; test crypto continui e timestamp futuri. |
| 4 | Storico ordini, timeout e retry: disponibilità senza perdere i controlli. | Medio; retry di scritture può duplicare ordini. | R4; oltre 500 ordini, pagine sovrapposte, timeout e fill ritardati; nessun retry cieco di submit. |
| 5 | Sicurezza dei test e riproducibilità Windows/macOS. | Medio; dipendenze/loop diversi. | Guard offline versionato e CI con ambiente senza segreti, socket vietati e file temporanei; stessa suite, skip motivati singolarmente. |
| 6 | Dati: schema unico, freschezza e simboli normalizzati per feed/broker. | Medio; normalizzazione errata cambia lo strumento. | Fixture contrattuali salvate e ripulite; duplicati, NaT, offset, barre mancanti e risposte fuori ordine rifiutati o gestiti esplicitamente. |
| 7 | Snapshot e ledger: rendere sostenibili mesi di uso. | Medio; retention può cancellare evidenze. | Backup/ripristino su DB temporaneo, aggregati coerenti e benchmark con milioni di snapshot; nessuna migrazione distruttiva. |
| 8 | UI ed errori uniformi: separare le pagine dalle decisioni. | Medio; cache/session state e contesti possono mescolarsi. | Componenti di presentazione con provenienza obbligatoria; tutti i test di isolamento e grafico invariati; n/d per dati assenti. |
| 9 | Backtest e versionamento strategie: riprodurre un risultato. | Medio; modifiche di calendario o aggiustamenti cambiano confronti. | Manifest con hash dati, versione codice/strategia, parametri, calendario e costi; medesimo input produce stessi trade e metriche. |
| 10 | Costi realistici e slippage: quantificare l'errore del modello. | Medio; campione piccolo e feed parziale. | Solo dopo DRY-RUN stabile e prova Paper autorizzata; confronto spread/quote/fill, distribuzioni dei costi e sensibilità, senza inferire profitto. |
| 11 | Log strutturati e diagnosi: ricostruire blocchi senza dati sensibili. | Basso/medio; rischio esposizione di segreti o crescita dei log. | Correlation ID per segnale/ordine, redazione verificata, rotazione e report di errore riproducibile. |
| 12 | Walk-forward: misurare stabilità dei parametri e incertezza. | Medio; rischio selezione ripetuta sull'OOS. | Stessa serie e costi, test finale intatto, numerosità e intervalli di incertezza; aggregazione solo con portafoglio continuo esplicito. |
| 13 | Rischio di portafoglio/correlazioni: distinguere quantità da rischio economico. | Alto; stime instabili. | Coordinatore R1 e quotazioni coerenti; stress test con gap e liquidità scarsa, metriche calcolate su dati disponibili al momento. |
| 14 | Indicatori: RSI/MACD, ATR, breakout o liquidità solo come esperimenti isolati. | Medio/alto; overfitting e aumento del turnover. | Baseline SMA congelata, stessi periodi/costi e walk-forward; mantenere una tecnica solo con beneficio OOS robusto e campione dichiarato. |
| 15 | Mean reversion separata dalla SMA: evitare mescolare semantiche. | Alto; scelta ex post del regime. | Strategia/versione indipendente, decisioni registrate, confronto OOS con costi e turnover omogenei. |
| 16 | Statistica/ML solo dopo dati e obiettivo adeguati. | Alto; leakage, instabilità e complessità operativa. | Dataset versionato, feature disponibili al tempo, split temporali rigorosi e benchmark semplice; nessuna promessa previsionale o etichetta confidence inventata. |

## Autocontrollo e riproduzione dei controlli

Rilette integralmente le funzioni modificate e i test aggiunti, più i relativi chiamanti. Verificati il diff, l'assenza di import inutilizzati nei file toccati mediante analisi AST e la permanenza di tutti i controlli di rischio. Nessuna soglia economica, strategia, ordine operativo o schema personale modificato. RSI corretto solo come visualizzazione.

Nessun server Streamlit avviato: le prove UI usano `AppTest`, broker simulati e SQLite temporanei. Il test TUI usa pipe locali. Niente richieste operative al broker, ordini o credenziali reali. L'automazione sui conti non è stata attivata da questa attività.

Nella prima revisione la suite è stata eseguita con ambiente ripulito e un guard temporaneo esterno. Nella seconda sessione il guard è stato inserito nel `conftest.py` radice: dotenv disabilitato, ambiente test ripulito, rete e file locali delle credenziali bloccati e tentativi contati anche se intercettati dal test. Sono ammesse fixture temporanee fittizie. Questa è una protezione dagli accessi accidentali del codice Python nel processo pytest, non una sandbox contro codice ostile o processi esterni. La riproduzione in CI e negli altri checkout rimane da eseguire.

Comandi di verifica nella `.venv` Python 3.12:

```sh
python -m compileall -q app.py config src tests
python -m pytest -q tests/test_dashboard_validation.py tests/test_paper_automation.py tests/test_fx_rates.py tests/test_simulation_ledger.py tests/test_broker.py tests/test_strategy.py tests/test_backtest_execution.py tests/test_walk_forward.py tests/test_omega.py::test_tui_commands_and_cancellation_do_not_wait_for_stdin
python -m pytest -q
git diff --check
git status --short --branch
git diff --stat
```

Esiti storici della prima revisione, conservati come osservati:

| Controllo | Esito |
| --- | --- |
| `compileall` | Exit 0, nessun output. |
| Test mirati elencati sopra | 134 passati, 1 warning, 14,92 secondi. |
| Intera suite | 313 passati, 0 falliti, 0 saltati; 1 warning, 23,63 secondi. |
| Guard offline della suite finale | Tentativi di rete: 0; accessi ai file locali delle credenziali: 0. |
| `git diff --check` | Exit 0, nessun output. |
| Import nei file Python toccati | Nessun candidato inutilizzato rilevato dall'analisi AST. |

Il warning è la deprecazione `websockets.legacy`. I 287 casi già presenti sono preservati; sono stati aggiunti 26 casi, senza skip. La prima esecuzione completa intermedia aveva 310 casi verdi; l'autocontrollo ha poi aggiunto e corretto due casi sui mark e un ulteriore caso sulle chiavi con separatore, prima dell'esecuzione finale.

## Limiti della revisione

Non aperti file delle credenziali o database personali. Non effettuati audit storico dei segreti, nuove prove dei feed pubblici, prove autentiche Alpaca/Hyperliquid, avvio manuale nel browser, misure di carico prolungato o esecuzione Windows. Le integrazioni esterne sono verificate con simulazioni e mock, non con servizi autentici. La suite verde prova i casi eseguiti, non sicurezza assoluta, correttezza di ogni contratto esterno o redditività.

Giudizio: migliorata la stabilità locale con difetti riprodotti e regressioni mirate. L'anteprima manuale senza submit è ora presente; prima di estendere l'automazione occorrono DRY-RUN continuo, coordinamento per conto e calendario. Non è una dichiarazione di completamento economico o di idoneità al capitale reale.

## Seconda sessione — Dashboard, documentazione e test riproducibili

Base della seconda sessione: 8 file tracciati già modificati, review e test FX non tracciati, 313 test della prima revisione. Modifiche preservate. I seguenti interventi si aggiungono ai Q1–Q8:

| Area | Modifica circoscritta | Evidenza / limite |
| --- | --- | --- |
| Conto | Eliminato il riepilogo duplicato che poteva mostrare vecchia equity dopo un errore snapshot. | Regressione AppTest sul valore precedente; metriche ufficiali solo nello snapshot disponibile. |
| Denominazioni e N/D | Valore di mercato Paper distinto dal costo storico; calcoli puri per equity/variazione/P/L noto e denominatori invalidi. | Test numerici con zero, dati assenti, NaN, infinito e overflow. Nessuna conversione EUR inventata. |
| Dati futuri | Q6 è stato ulteriormente ristretto nella sola UI: nessun margine futuro. Quote con timestamp invalido mostrano indisponibilità senza crash. | Due regressioni AppTest inizialmente fallite e poi passate. Le tolleranze e le regole temporali del backend restano invariate; calendario R2 ancora aperto. |
| Grafico | Renderer con input espliciti, senza accesso implicito al ledger; Demo senza marker Paper; ordini deduplicati e fill con quantità/prezzo/tempo validi. | Sei casi originali mantenuti come test del renderer, più test Demo e fill incompleti. Il primo gruppo intermedio aveva 4 fallimenti dovuti al vecchio presupposto di sovrapporre Paper alla Demo; aggiornato il setup conservando le asserzioni sui marker. |
| Segnale | Stato SMA con motivazione, fonte, medie, parametri e timestamp; storico e quotazione separati. | Test puri e AppTest; la barra tecnica può essere in formazione e non autorizza ordini. Stop/target/rischio: N/D. |
| Attività | Filtro ordini, esecuzioni confermate, filtro decisioni ed export dei 25 eventi mostrati. | Copertura AppTest esistente più helper puri; non è un export completo dello storico. |
| DRY-RUN | Anteprima manuale dopo i controlli e prima del submit; nessuna modifica alle soglie economiche o al percorso operativo predefinito. | BUY/SELL con submit proibito; vincoli sintetico/stale mantenuti e test UI su automazione arrestata. R3 resta parzialmente aperto. |
| Continuità | Istruzioni permanenti, guida, uso dashboard, decisioni, matrice test e worklog. | Documenti aderenti ai moduli presenti; nuove strategie, ML, livelli ATR e ottimizzazioni non misurate rimangono proposte. |

Le verifiche finali aggiornate sono registrate nel WORKLOG della seconda sessione. La suite intermedia prima degli ultimi casi ha prodotto 333 passati in 21,46 s, un warning e zero tentativi rete/credenziali. La suite finale ha prodotto **336 passati, 0 falliti, 0 saltati, 1 warning, 22,57 s**; gruppo mirato **90 passati in 14,37 s**. Compilazione e `git diff --check`: exit 0, output vuoto. Guard finale: rete 0, credenziali 0.

### Fasi e condizioni per chiuderle

| Fase | Stato locale | Accettazione residua osservabile |
| --- | --- | --- |
| A — Stabilità | Fix circoscritti verificati con test | Mantenere regressioni verdi; prove autentiche e sicurezza multiutente sono separate. |
| B — Dati | Provenienza e tempi UI migliorati | Calendario NYSE/DST/festività/crypto e contratto unico per barre completate. |
| C — Dashboard | Metriche, segnale, filtri e N/D implementati | Verifica visuale responsive e refresh coerente fra fragment su quote/errori. |
| D — Validazione quantitativa | Motore e walk-forward coperti da test esistenti | Manifest riproducibile, sensibilità ai costi e OOS con campione dichiarato; nessuna promessa di profitto. |
| E — Paper | Anteprima manuale senza submit verificata | DRY-RUN continuo, coordinatore di conto e riavvio con richieste incerte simulati. |
| F — Manutenzione | Componenti puri, guard e documenti presenti | CI/macOS/Windows, paginazione e benchmark snapshot con retention non distruttiva. |
| G — Strategie future | Non implementate | Regola deterministica, test, benchmark/costi e OOS prima di qualsiasi abilitazione. |

## Terza sessione — Risoluzione P1 incrementale

R1 è mitigato per processi cooperanti sullo stesso host: lock per conto, intento durevole prima del submit, proprietà esplicita e nessun takeover per scadenza. Configurazione operativa disabilitata per default; senza coordinatore il submit pubblico è bloccato e il pulsante di avvio disabilitato.

R1 NON è chiuso come requisito distribuito: manca un servizio unico fra macchine e la riconciliazione piena dopo fill. Il recupero di un terminale con zero fill è implementato; per gli altri stati si conserva il blocco prudenziale. Non eliminare journal/lock per ripartire. Vedere D10 e la matrice test per confini e prove locali.

R2 ora è implementato nel perimetro descritto sopra. Aggiunti 29 test calendario e integrazioni operative; i test temporali usano clock controllato. L'autocontrollo ha riprodotto un ultimo submit dopo la chiusura avvenuta durante la verifica account: aggiunto ricontrollo finale sul lease, con test fallito prima del fix. Nessuna soglia economica indebolita e nessuna strategia cambiata.

La prima suite di fase 1 ha avuto 2 fallimenti di bootstrap multiprocessing dopo AppTest (348 passati): corretto il main usato da spawn, senza rieseguire app.py e mantenendo il guard nei worker. Suite di fase 1 successiva: 350 passati, un warning, 21,96 s. La suite intermedia di fase 2 aveva 384 passati in 23,81 s; i risultati dopo l'ultimo ricontrollo sono nel WORKLOG.

### Esito finale terza sessione

Compilazione exit 0, output vuoto; test mirati **124 passati in 15,65 s**; suite **386 passati, nessun fallimento o skip, un warning, 24,01 s**. Guard: rete 0, credenziali 0. Diff-check exit 0. Aggiunti 50 casi rispetto ai 336 iniziali. Il warning resta `websockets.legacy`. Nessuno staging, commit o push. Inventario e output Git integrali nel WORKLOG.

R1 globale resta P1 aperto, con mitigazione locale e default disabilitato; R2 ha implementazione e test per il perimetro supportato, con blocchi espliciti per aggregati non verificati. Non dichiarati completati deployment distribuito, recupero dei fill o contratti autentici dei feed.
