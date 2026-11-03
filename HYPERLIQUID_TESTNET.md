# Hyperliquid: prova manuale esclusivamente TESTNET

Il motore condiviso usa il protocollo `NativeBroker` (`src/broker/native.py`) e una configurazione `TestnetRisk` senza credenziali. L’adapter Hyperliquid contiene autenticazione e normalizzazione; un futuro adapter può implementare lo stesso contratto senza cambiare il journal o le regole di uscita.

Il runner dedicato è `python -m src.hyperliquid_testnet_cli`. La dashboard Omega esistente continua a usare il proprio ledger locale: i suoi pulsanti non controllano questo conto nativo. Nessun altro mercato è collegato al nuovo motore.

## Prerequisiti e limiti

- Usare un **conto testnet dedicato a questo bot**, senza ordini manuali o altre istanze. Il panic opera su tutti gli ordini e tutte le posizioni del conto testnet configurato, inclusi eventuali ordini non creati dal bot.
- Avere fondi esclusivamente testnet e un API wallet testnet configurato. L'indirizzo del conto deve essere quello del conto master, non quello del wallet agente.
- Iniettare `HYPERLIQUID_PRIVATE_KEY` e `HYPERLIQUID_ACCOUNT_ADDRESS` nell'ambiente del processo usando il proprio secret manager. **Non salvarli in `.env`, script, notebook, file di log o cronologia della shell.** Il runner non carica `.env` e non stampa questi valori. Anche i redirect HTTP vengono rifiutati dal trasporto testnet.
- Impostare nell'ambiente `CRYPTO_EXECUTION_NETWORK=testnet`, `HL_TESTNET_NETWORK=testnet` e, facoltativamente, `HYPERLIQUID_COIN=BTC`, `HL_TESTNET_MAX_ORDER_USD=25`. L'endpoint dell'adapter è fisso: `https://api.hyperliquid-testnet.xyz`. Non c'è un parametro per sostituirlo; mainnet è rifiutata anche dai vecchi trasporti nativi, indipendentemente dai flag legacy.
- Richiesti Python 3.11+ su macOS/Linux e `requirements-omega.txt`. I test di questa consegna usano il Python della `.venv`; la prova autentica sul broker non è inclusa nei test unitari.
- Usare sempre lo **stesso journal** per quel conto: `data/hyperliquid_testnet.sqlite3`. Non cancellarlo per superare un blocco. Il journal memorizza richieste, client ID, fill e snapshot di saldo/posizioni, ma non chiavi o indirizzi del conto in chiaro. L'associazione al conto usa un fingerprint.
- Un file lock consente una sola istanza per journal. Non avviare lo stesso conto da percorsi/journal diversi o da più macchine: non esiste fencing distribuito.

## 1. Controllo locale, senza ordini

Attivare `.venv` e dalla radice del repository eseguire:

```sh
python -m compileall -q app.py config src tests
python -m pytest -q
python -m src.hyperliquid_testnet_cli --help
```

L’output completo dei controlli locali eseguiti è conservato in [HYPERLIQUID_TESTNET_VERIFICATION.txt](HYPERLIQUID_TESTNET_VERIFICATION.txt).

Il comando seguente legge lo stato del broker, ma non invia ordini o cancellazioni e non installa stop:

```sh
python -m src.hyperliquid_testnet_cli --action status
```

Controllare `network: testnet`, `cash`, `equity`, `available`, `positions` e `open_orders` contro l'interfaccia testnet. Non proseguire se il conto non è quello atteso o ci sono ordini/esposizioni di altri sistemi. Il runner non effettua trasferimenti o depositi.

## 2. Un segnale manuale e un ordine testnet

Il flag `--trade-testnet` abilita azioni firmate esclusivamente verso testnet. Questo comando può creare una posizione testnet:

```sh
python -m src.hyperliquid_testnet_cli --action signal --signal buy --intent-id smoke-entry-001 --trade-testnet
```

Controllare sul broker e nell'output:

- Ordine IOC con un `cloid` stabile. La quantità rispetta precisione, minimo di negoziazione, disponibilità e il minore fra 25 USD e 4% dell'equity, con riserva per i costi. L'adapter imposta margine isolato con leva 1× prima di ogni ingresso.
- `filled_quantity` e `fill_count` crescono solo dopo la lettura dei fill del broker. Un acknowledgement non deve apparire come fill.
- Se esiste una posizione long, deve essere presente uno stop broker `reduce_only`, normalmente al 98,5% del prezzo medio di ingresso, arrotondato verso una protezione più stretta.
- Un IOC senza liquidità può essere rifiutato o cancellato senza fill: è un risultato distinto da un ingresso completato. Non alterare i limiti per forzare il successo.

Ripetere **lo stesso comando con lo stesso intent ID**. Il bot deve riconciliare il cloid esistente, senza creare un secondo ingresso. Registrare gli ID e gli esiti, senza chiavi o payload firmati.

## 3. Uscita parziale e riavvio

Solo se il passo precedente ha una posizione e uno stop confermato:

```sh
python -m src.hyperliquid_testnet_cli --action partial --fraction 0.5 --intent-id smoke-partial-001 --trade-testnet
python -m src.hyperliquid_testnet_cli --action status
```

Il target residuo viene persistito una sola volta. Un nuovo processo con lo stesso journal deve leggere la posizione effettiva; ripetere `smoke-partial-001` non deve vendere nuovamente metà della posizione rimasta. Le uscite sono sempre `reduce-only` e non possono aprire uno short.

Se un'uscita è parziale o resta pending, `pending_exits` non deve essere vuoto. Per continuare la riconciliazione/protezione avviare il runner, sempre con lo stesso journal:

```sh
python -m src.hyperliquid_testnet_cli --action run --trade-testnet
```

`run` usa la strategia MA esistente su candele chiuse testnet, senza introdurre nuove strategie. Può inviare nuovi ingressi se i controlli lo consentono: non usarlo come monitor privo di scritture. `status` rimane la lettura senza ordini. Il runner controlla periodicamente lo stato; gli stop già confermati risiedono sul broker e non vengono rimossi alla chiusura del processo.

## 4. Cancellazione e panic

Un segnale `sell` annulla anche un ingresso ancora pendente prima di chiudere l'esposizione effettiva. Se l'ingresso ha esito ambiguo, l'obiettivo di uscita resta persistente anche con saldo posizioni temporaneamente zero: dopo un riavvio, un eventuale fill tardivo viene riconciliato e chiuso senza duplicare l'ingresso. Finché il broker non risolve l'ambiguità, i nuovi ingressi restano bloccati.

Per cancellare un ordine del journal:

```sh
python -m src.hyperliquid_testnet_cli --action cancel --cloid CLIENT_ORDER_ID --trade-testnet
```

Sostituire `CLIENT_ORDER_ID` con il cloid dell'output. Se si cancella una protezione mentre esiste esposizione, il motore non lascia intenzionalmente il conto senza difesa: può chiedere una chiusura di emergenza. Non usare questo comando per togliere uno stop e continuare a operare scoperti.

Per bloccare gli ingressi, cancellare ordini pendenti e chiudere le posizioni native:

```sh
python -m src.hyperliquid_testnet_cli --action panic --trade-testnet
python -m src.hyperliquid_testnet_cli --action status
```

Se `run` è attivo, una seconda invocazione di `panic` sullo stesso journal controlla il fingerprint del conto e accoda un latch persistente. Stampa `panic_queued_for_running_engine`, mai una falsa conferma di conto flat: il processo già attivo continua cancellazioni e uscite. Le richieste già in volo possono ancora produrre fill, che verranno rilevati e chiusi nei cicli successivi. Per gli altri comandi il file lock impedisce un secondo motore concorrente; usare l’output del runner o fermarlo prima di invocare `status`.

Il panic è persistito **prima** delle richieste di rete. Mantiene gli stop del bot finché esiste la posizione, mentre cancella gli ingressi pendenti; le chiusure IOC sono `reduce-only`. Alla posizione zero elimina gli ordini residui. `panic_complete: true` richiede conferma di zero posizioni, zero ordini aperti e nessuna richiesta locale irrisolta. Se non c'è liquidità, la rete non risponde o un'uscita viene rifiutata, il panic resta incompleto: controllare il conto testnet e non dichiararlo liquidato. Una nuova invocazione di `panic` o `run` continua la riconciliazione senza reinviare richieste ambigue.

Il panic e la perdita giornaliera almeno pari al 5% bloccano gli ingressi per 24 ore. Anche dopo la scadenza occorre una ripresa esplicita, possibile soltanto con conto riconciliato e flat:

```sh
python -m src.hyperliquid_testnet_cli --action resume --trade-testnet
```

## Esiti da annotare nella prova autentica

| Caso | Evidenza richiesta dal vero testnet |
| --- | --- |
| Ingresso | cloid, broker order ID, stato, quantità e fill effettivi; saldo/posizione concordi |
| Idempotenza | stessa intent ID prima/dopo riavvio; nessun secondo ingresso |
| Parziale | quantità residua e stop effettivo; stessa exit ID non ripete la frazione |
| Cancellazione | conferma del broker; gestione di eventuali fill in gara con il cancel |
| Stop | presenza nativa reduce-only e successivo fill/cancel effettivo |
| Panic | richieste pendenti gestite; conto flat e zero ordini prima di dichiarare completamento |
| Rete indisponibile | nessun saldo/fill inventato, nuovi ingressi bloccati; ripartenza sullo stesso journal |

## Rischi noti e scelte conservative

- Ingresso e stop sono due richieste, non un bracket atomico. Esiste una finestra senza protezione tra il fill e la conferma dello stop, più lunga se il processo o la rete si fermano in quel punto. Il codice chiede un flatten di emergenza quando la protezione non è confermata, ma non può garantire esecuzione senza connettività o liquidità. Non è adatto a capitale reale, che è comunque bloccato.
- Un invio con esito ambiguo e `unknownOid` non viene ritentato automaticamente: l'assenza temporanea nel broker non prova che la richiesta non arriverà. Questo blocco può richiedere controllo manuale sul broker. Il journal non va azzerato per aggirarlo.
- I fill vengono de-duplicati e recuperati con paginazione e sovrapposizione temporale. La documentazione del broker limita lo storico disponibile agli ultimi 10.000 fill. Una paginazione saturata o un fill mancante blocca gli ingressi; non è promesso recupero illimitato dopo lunghi periodi offline.
- Uno stop reduce-only già aperto può coprire una quantità superiore alla posizione rimasta dopo una parziale: il vincolo reduce-only impedisce il ribaltamento. Se il broker cancella tale stop, il successivo controllo deve installare una nuova protezione o chiedere l'uscita.
- Il saldo è quello del conto broker, non una somma locale delle operazioni. Depositi, prelievi o operazioni di altri sistemi alterano la baseline giornaliera: usare un conto dedicato senza movimenti esterni.
- Verificare clock, permessi dell'API wallet, precisione e liquidità effettivi. I test simulati non dimostrano il comportamento autentico dell'exchange né redditività.

Riferimenti: [orderStatus e fill](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [cloid, IOC e ordini trigger](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint).
