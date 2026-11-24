# AI Trading Bot

Applicazione desktop locale per analisi di mercato, backtest, walk-forward, simulazione
con capitale fittizio e monitoraggio **in sola lettura** di Alpaca Paper.
Nessun live trading; nessun ordine broker viene inviato dall'applicazione; l'automazione
è un dry-run locale e parte sempre arrestata.

Architettura unica (vedi [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)):
React + TypeScript (Vite) per l'interfaccia, FastAPI per il servizio locale su `127.0.0.1`,
motori Python esistenti (strategie, rischio, backtest, ledger SQLite), Tauri 2 per la shell desktop.
Streamlit è stato dismesso: il motivo di ogni rimozione è in
[docs/STREAMLIT_RETIREMENT_REPORT.md](docs/STREAMLIT_RETIREMENT_REPORT.md).

## Sezioni dell'applicazione

Panoramica, Mercati (grafico candlestick con volume, indicatori, intervalli), Watchlist,
Segnali (proposta analitica, mai un ordine), Portafoglio (ledger virtuale Demo/Simulazione),
Storico, Backtesting (backtest e walk-forward fuori campione), Automazione (solo dry-run),
Connessioni (Alpaca Paper / MT5 in sola lettura), Stato sistema, Impostazioni.

Il selettore **Contesto** separa: **Demo** (prezzi sintetici dichiarati, ledger proprio),
**Simulazione** (secondo ledger con capitale separato), **Alpaca Paper** (sola lettura,
credenziali dall'ambiente del processo), **MT5** (sola lettura, solo Windows).
Un dato mancante è mostrato come `N/D`, mai come zero o come valore sintetico.

## Avvio

**Utente finale:** installare il pacchetto desktop (Windows: installer NSIS; macOS: `.app`/DMG),
vedi [docs/DESKTOP_RELEASE_GUIDE.md](docs/DESKTOP_RELEASE_GUIDE.md). Non serve Python.

**Sviluppo, Windows (PowerShell):**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\avvia_web.ps1 -Build
```

Arresto con Ctrl+C oppure `.\arresta_web.ps1` da un'altra finestra.

**Sviluppo, macOS/Linux:**

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci && npm run build
.venv/bin/python -m scripts.start_local          # stampa l'URL 127.0.0.1:<porta>
.venv/bin/python -m scripts.start_local --stop   # da un'altra finestra
```

**Desktop dal sorgente:** vedi la sezione build in [docs/DESKTOP_RELEASE_GUIDE.md](docs/DESKTOP_RELEASE_GUIDE.md).

Credenziali Alpaca Paper: solo variabili `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` nell'ambiente
del processo; mai nel repository, in campi dell'interfaccia o in URL.
Contratti API, sicurezza e dati: [docs/LOCAL_APPLICATION.md](docs/LOCAL_APPLICATION.md).

## Test

```sh
python -m compileall -q config src scripts tests
python -m pytest -q
npm run lint && npm run typecheck && npm test && npm run build
cargo test --locked --manifest-path src-tauri/Cargo.toml
python -m scripts.check_local_service
```

La suite Python è offline (guard rete/credenziali in `conftest.py`). Stato e limiti per
piattaforma: [docs/CROSS_PLATFORM_QA.md](docs/CROSS_PLATFORM_QA.md);
audit macOS: [docs/MACOS_QA_AUDIT.md](docs/MACOS_QA_AUDIT.md).

## Protezioni dei motori esistenti

Il client Alpaca Paper del servizio desktop usa un trasporto in sola lettura (solo GET/HEAD,
solo host atteso, niente redirect, timeout (3.05, 10) s). I moduli di esecuzione Paper
legacy (`src/trading/paper_*`) restano protetti da coordinatore esclusivo, lease, intent
durevole e retry di scrittura disabilitati, ma **non sono raggiungibili dalla nuova applicazione**.
Le barre operative usano il calendario NYSE e il contratto del feed: timestamp futuri,
duplicati, fuori ordine o senza fuso bloccano la valutazione.

Per architettura, formule e limiti: [Guida completa](docs/GUIDA_COMPLETA_PROGETTO.md),
[decisioni tecniche](docs/DECISIONI_TECNICHE.md), [matrice test](docs/MATRICE_TEST.md),
[registro del lavoro](docs/WORKLOG.md).
