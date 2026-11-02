# Decisioni tecniche

## D1 — Separare contesti e fonti

Stato: confermato da codice e test. Demo, ledger, backtest e Alpaca Paper non condividono capitale. I percorsi DB sono verificati anche per identità del file. L'alternativa di un unico saldo aggregato è rifiutata perché mescola contabilità diverse.

Conseguenza: i livelli stop/target del motore Hyperliquid non vengono presentati come regole della SMA Streamlit. Riesaminare solo con un contratto operativo separato e test dei flussi.

## D2 — Componenti di presentazione piccoli

Stato: implementato. `src/ui/presentation.py` contiene funzioni pure per numeri, provenienza, tempi e segnale; `src/ui/charts.py` riceve esplicitamente dati, storico locale e ordini. Non legge broker o ledger.

Alternativa: riscrivere tutte le pagine o importare `app.py` nei test unitari. Scartata: comporta molti effetti collaterali e un diff difficile da controllare. Sono stati conservati i controlli sui sei casi del grafico come test diretti e aggiunto un test UI dell'isolamento Demo/Paper.

Rischio: cambiare una firma senza aggiornare i tre chiamanti. Test e revisione dei chiamanti fanno parte della verifica finale.

## D3 — Una fonte autorevole per le metriche Paper

Stato: implementato. Rimossa la card duplicata dell'equity dalla panoramica; i numeri sono prodotti dallo snapshot verificato. La duplicazione lasciava un valore vecchio dopo un errore del monitor, riprodotto da una regressione rafforzata.

I valori mancanti o non finiti restano N/D; elenco posizioni assente e vuoto sono diversi. La variazione equity è `equity - last_equity`, non il P/L realizzato. Nessuna base di capitale mancante viene ricostruita dal ledger. Il valore di mercato non è chiamato capitale investito.

Riesaminare con uno storico broker completo, flussi di cassa e valuta espliciti prima di aggiungere rendimenti cumulativi o metriche multivaluta.

## D4 — Anteprima senza modificare l'invio preesistente

Stato: implementato e testato solo con mock. `dry_run=True` entra negli stessi controlli disponibili e, in presenza di proposta valida, termina prima di `submit_order`. Nessun ordine è costruito come fill o salvato nel broker fittizio. Anche i casi senza segnale o bloccati restano senza invio.

L'alternativa di cambiare il default della funzione esistente avrebbe alterato i suoi chiamanti. Per compatibilità il default della funzione rimane invariato; la UI aggiunge un pulsante di anteprima esplicito che non avvia il loop. L'automazione rimane arrestata all'avvio. Il comando legacy di avvio è separato e può inviare Paper: non è un DRY-RUN.

Non implementata una modalità DRY-RUN continua. Restano necessarie decisioni su coordinamento per conto, recupero di richieste incerte e calendario prima di estendere l'automazione.

## D5 — Non inventare il piano operativo

Stato: deciso. Il close del segnale e il bid/ask dell'anteprima hanno tipi e timestamp distinti. Quantità e controvalore dell'anteprima sono teorici. Stop, take-profit, rapporto rischio/rendimento e rischio fino allo stop restano N/D perché la SMA non li definisce.

Alternativa: applicare percentuali arbitrarie o copiare stop da altri motori. Rifiutata. Una futura regola richiede formula, dati, costi, test unitari e confronto fuori campione prima di qualunque ordine condizionato.

## D6 — Controlli offline permanenti

Stato: implementato. Il `conftest.py` alla radice installa un audit hook, ripulisce l'ambiente del processo pytest e vieta rete e file locali delle credenziali. Le fixture temporanee rimangono ammesse. La sessione fallisce anche se il codice intercetta un tentativo vietato.

Alternativa precedente: plugin temporaneo esterno. Era utile per l'audit, ma non riproducibile nel checkout di altri sviluppatori. Due test della policy usano eventi simulati; la suite intera verifica che i test esistenti non tentino accessi vietati.

Il guard previene errori accidentali, non isola codice ostile. Non usare pytest per prove autentiche e non inserire segreti per farlo passare.

## D7 — Freschezza visuale e barre chiuse non sono sinonimi

Stato: UI verificata con mock. La presentazione rifiuta timestamp futuri e quote non valide; lo storico resta consultabile. Un timestamp recente non certifica che una barra sia completata.

Nella prima sessione i limiti operativi erano rimasti invariati. La sessione P1 introduce il contratto calendario descritto in D11 e rifiuta quote future anche nel backend. Le soglie economiche restano invariate. La UI dichiara che il segnale tecnico può usare una barra in formazione, distinta da quella operativa.

## D8 — Nessuna ottimizzazione prestazionale senza misura

Stato: criterio di lavoro. Rimosse duplicazioni di presentazione e isolato il renderer per correttezza e testabilità. Non viene dichiarata una riduzione di latenza, memoria o numero di richieste. Restano da misurare cache, polling, ricostruzione grafici e crescita degli snapshot.

## D9 — Continuità e prove

Stato: documentazione persistente. WORKLOG registra risultati senza sostituire quelli precedenti. La matrice distingue codice, mock, piattaforma e prove autentiche mancanti. Nessuna fase è chiusa soltanto per il conteggio dei test.

## D10 — Proprietà Paper locale e blocco dei casi non dimostrabili

Il lock di processo è riutilizzato come meccanismo POSIX già presente nel journal nativo, ma con scope per conto e ciclo completo: acquisizione → verifica conto/stato → rischio → intento durevole → submit → rilascio. Nessuna dipendenza aggiunta per il lock. Non c'è lease temporale rinnovabile: 30 s invalidano la decisione, non l'esclusione. Un processo morto perde automaticamente il lock OS; un intento durevole resta da riconciliare. Il vecchio proprietario non può usare un lease rilasciato o da altro thread/processo.

Il journal non conserva credenziali, saldi o ID account in chiaro. Il file del lock non viene cancellato né sostituito; identità del file controllata prima di autorizzare il submit. Una directory diversa non coordina i processi: tutta la distribuzione deve usare un solo filesystem locale e la medesima directory. NFS e multi-host non supportati.

Scartata una lease con TTL e takeover: il proprietario sospeso potrebbe riprendere mentre il secondo invia e Alpaca non offre fencing sul nostro token. Scartato anche il semplice mutex in memoria e il recupero basato su PID, ora o assenza dell'ordine.

La nuova configurazione predefinita è `paper_execution_scope=disabled`. La configurazione single_host deve dichiarare una directory assoluta condivisa; non è stata attivata durante il lavoro. Il percorso pubblico di submit richiede un lease associato alla directory e all'account verificati. Le chiamate SDK esterne al percorso non sono una superficie protetta da codice ostile.

Disponibilità volutamente ridotta: dopo un fill/ordine pendente, anche confermato, si blocca fino a riconciliazione affidabile del conto, non implementata qui. Solo un terminale con zero fill esplicito consente recupero automatico, mantenendo l'ID già consumato. Questo chiude la gara locale con snapshot obsoleti, non la gestione distribuita né il recupero pieno dei fill.

## D11 — Calendario e contratto del feed prima della decisione

Implementato in `src/data/bar_timing.py`, riusato dall'automazione e dalla UI per spiegare l'ultima barra temporalmente conclusa. Dipendenza diretta fissata `pandas-market-calendars==5.5.0`; installate nella venv anche le dipendenze exchange-calendars 4.13.2, pyluach 2.3.0 e korean-lunar-calendar 0.4.0. Nessun aggiornamento delle dipendenze preesistenti.

Scartati calendario scritto a mano, weekday generico, 24 ore per le daily e fallback permissivo se la libreria manca. La libreria serve per festività, DST ed early close; usa dati locali, non richieste broker. Non garantisce chiusure straordinarie future e va mantenuta aggiornata.

Il contratto richiede istanti con fuso, inizio intervallo verificato, ordine/unicità, acquisizione dopo il termine e margine 30 s. Le soglie massime di età sono mantenute; quote future non ammesse. Il margine è una scelta prudenziale esplicita, non una stima di slippage né una prova di immutabilità.

Raw daily equity e weekly non hanno un contratto RTH sufficientemente verificato; crypto daily timezone non validato qui. Invece di inventare una chiusura, restano solo per analisi e vengono rifiutati nell'automazione. Il supporto ai daily RTH espliciti è testato con fixture, non attribuito automaticamente alle risposte grezze Alpaca. Il paper equity è sempre RTH: il flag storico degli orari non abilita extended hours.

I test temporali usano orari fissi. Le fixture di automazione sono state rese deterministiche e conformi alla griglia reale; non sono cambiate le aspettative di rischio, quantità, doppio ordine o invio. Il test AppTest di avvio/arresto usa un daily RTH fittizio esplicitamente dichiarato, non un feed autentico.

Autocontrollo D11: il lease deve ricevere una validazione finale temporale, eseguita dall'adattatore dopo la riverifica dell'account e prima del request API. Un test riproduce il passaggio da mercato aperto a chiuso durante quel tratto e dimostra zero submit. Il lock da solo non prolunga la validità del segnale o della quotazione. Se fallisce dopo la prenotazione, l'intento rimane prudenzialmente irrisolto; non viene cancellato automaticamente.
