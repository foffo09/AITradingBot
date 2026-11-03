# Installazione e verifica Windows

Questa correzione prepara la portabilità: i risultati macOS non certificano Windows.
La prova su Windows 11/Python 3.11.9 deve ancora essere eseguita dall'utente.
Usare una copia di prova, filesystem locale e nessuna credenziale.

## Ambiente pulito e suite completa

Da PowerShell, nella root della copia di prova aggiornata:

```powershell
git rev-parse --short HEAD
py -3.11 -m venv .venv-win-test
.\.venv-win-test\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-win-test\Scripts\python.exe -m compileall -q app.py config src tests
.\.venv-win-test\Scripts\python.exe -m pytest -q tests/test_native_store.py tests/test_paper_coordinator.py tests/test_hyperliquid_testnet.py
.\.venv-win-test\Scripts\python.exe -m pytest -q
.\.venv-win-test\Scripts\python.exe -m pip check
git diff --check
```

Non serve attivare l'ambiente PowerShell. Annotare hash, versione Python,
output completo, passati/falliti/saltati e contatori `TEST ISOLATION`.
Non avviare launcher, server, automazioni o ordini per questa verifica.
Non copiare `.env`, database o impostazioni personali nella copia di prova.

## Dipendenze

- `requirements.txt`: dashboard e runtime condiviso; FastAPI, HTTPX, Rich,
  Pydantic, Starlette, Requests, Msgpack, WebSockets e Portalocker sono
  dipendenze esplicite. Pytest è conservato qui per compatibilità con i comandi esistenti.
- `requirements-omega.txt`: include la base e aggiunge SDK opzionali dei provider
  e Uvicorn. Uvloop resta escluso su Windows mediante marker di piattaforma.
- `requirements-dev.txt`: include anche gli SDK opzionali usati con mock dai test.
  Per **l'intera suite** usare questo file: la sola base non installa gli SDK opzionali.

Una venv già esistente può nascondere dipendenze mancanti. Non riutilizzare la
venv macOS su Windows. Gli import sono stati inventariati dal codice e dai test;
le dipendenze transitive restano risolte da pip, non è un lockfile completo.

## Lock esclusivi e limiti

NativeStore, coordinatore Paper e console usano `portalocker==3.2.0`, che
seleziona i lock del sistema operativo. Su Windows questa versione richiede
`pywin32`, installato automaticamente dal suo metadata condizionale.
Il lock è esclusivo e non bloccante; un secondo proprietario non può procedere.
Il file laterale stabile non viene eliminato o sostituito al rilascio.
Il journal resta SQLite con le impostazioni di durabilità preesistenti.

NativeStore chiude connessione e lock anche dopo un errore di inizializzazione;
la chiusura ripetuta è innocua e un errore di unlock chiude comunque l'handle.
La richiesta panic usa un URI assoluto con escaping, senza creare un journal
mancante e con chiusura esplicita della connessione. Non si modificano intenti,
riconciliazione, idempotenza o soglie di rischio.

Tutti i processi cooperanti di uno stesso conto devono usare la stessa directory
locale. Non sono attestati NFS/SMB, sincronizzazione cloud, multi-host o directory
diverse. Non eliminare journal/lock per aggirare uno stato incerto. Nessun lock
protegge da un altro programma che ignora il protocollo o da scritture SDK esterne.
Demo, ledger locale, backtest, Alpaca Paper e Hyperliquid testnet restano separati.

La console sceglie il loop Uvicorn `auto`, senza imporre Uvloop a Windows.
La TUI interattiva e il supporto dei pipe stdin Windows richiedono una verifica
separata: non sono certificati dai risultati macOS. La dashboard non usa stdin.

## Evidenze richieste

La regressione dei lock usa processi `spawn` reali, percorsi temporanei, crash
con `os._exit`, contesa, rilascio, scope incompatibile e errori del backend/SQLite.
La suite conserva il guard offline: niente rete o credenziali, nessun test
eliminato o disabilitato. Passare questi test non autorizza trading automatico.

La verifica Windows è **NON ESEGUITA** finché non viene riportato l'output del PC.
