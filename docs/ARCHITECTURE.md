# Architettura AITradingBot (unica, dal 24 novembre 2026)

Storico delle decisioni: [ARCHITETTURA_APP.md](ARCHITETTURA_APP.md), [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md) (D16, D17).
Contratti API dettagliati: [LOCAL_APPLICATION.md](LOCAL_APPLICATION.md).

```
┌──────────────────────── Tauri 2 shell (Rust, src-tauri/) ────────────────────────┐
│ finestra WebView → http://127.0.0.1:<porta dinamica> (navigazione solo stessa origine) │
│ possiede il sidecar: stdin/stdout, handshake {port,pid,supervisor_pid,instance_id}   │
│ avvio: handshake entro 30 s; chiusura: "shutdown" su stdin → max 20 s → SIGKILL al    │
│ process group (Unix)                                                                │
└──────────────┬──────────────────────────────────────────────────────────────────────┘
               │ spawn, pipe
┌──────────────▼────────── sidecar PyInstaller (src/runtime/local_service.py) ─────────┐
│ uvicorn su 127.0.0.1, socket legato una sola volta; esce su "shutdown" o EOF stdin   │
│ FastAPI src/api/local_app.py: asset React + API v1 stessa origine                    │
│   middleware: Host/Origin esatti, cookie HttpOnly SameSite=Strict, X-Local-Request   │
│   lock per contesto: demo · simulation · paper · mt5 (+ preferenze/watchlist);       │
│   paper/mt5 attendono max 2 s poi 503 "occupato" (il pool di 40 thread non si satura) │
└──────┬───────────────┬──────────────────┬──────────────────┬───────────────────────┘
       │               │                  │                  │
  ledger SQLite    ledger SQLite     AlpacaClient          MT5Process
  local-v1-demo    local-v1-simulation (trasporto GET-only) (processo figlio, solo Windows)
  + controller dry-run per contesto (local-v1-<ctx>-control.sqlite3)
  motori esistenti: src/strategy, src/risk, src/backtesting, src/data, src/simulation
```

## Confini

| Livello | Fa | Non fa |
|---|---|---|
| React (`frontend/src`) | UI, navigazione, grafici Lightweight Charts, validazione delle risposte (`api.ts`), N/D per dati mancanti, timeout 12 s per richiesta | Accesso a DB o file, credenziali, formule finanziarie (indicatori arrivano dal backend) |
| FastAPI (`src/api`) | Validazione input Pydantic (extra vietati, numeri finiti), DTO di output verificati, errori sanificati, idempotenza trade, trade incerto registrato nel servizio (`/pending-trade`, sopravvive al riavvio), ledger per contesto | Invio ordini broker, scrittura su Paper, fallback sintetico quando un feed fallisce |
| Motori Python (`src/*`) | Strategie, rischio, backtest, walk-forward, ledger, calendario barre | Conoscere la UI |
| Tauri (`src-tauri`) | Avvio/arresto del sidecar, porta dinamica, finestra, packaging | Terminare PID ricevuti via rete; capability IPC (nessuna: `capabilities: []`) |

## Modalità

| Contesto | Capitale | Dati | Ordini |
|---|---|---|---|
| Demo | ledger `local-v1-demo.sqlite3`, creato solo con POST esplicito | sintetici dichiarati (`synthetic-demo`) | solo virtuali nel ledger |
| Simulazione | ledger `local-v1-simulation.sqlite3`, separato | sintetici dichiarati | solo virtuali nel ledger |
| Alpaca Paper | conto del broker, solo lettura | Alpaca, con fonte e timestamp | nessuno (trasporto GET/HEAD) |
| MT5 | terminale dell'utente, solo lettura, solo Windows | MT5 | nessuno |

Automazione: dry-run locale per Demo/Simulazione, parte `STOPPED`, ogni ciclo è una richiesta esplicita.

## Percorsi dati

Browser (sviluppo): `~/Library/Application Support/AITradingBot/local-service` (macOS),
`%LOCALAPPDATA%\AITradingBot\local-service` (Windows). Desktop: app-data Tauri
`it.aitradingbot.desktop/local-service`. I due non condividono capitale. Nessuno script cancella database.
