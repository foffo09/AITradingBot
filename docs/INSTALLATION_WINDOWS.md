# Installazione su Windows 10/11 (v1.0 candidata)

Sostituisce `INSTALLAZIONE_WINDOWS.md` (era Streamlit). Nessuna credenziale va scritta su file: Alpaca usa
variabili d'ambiente, MT5 usa il terminale già aperto e connesso.

## Requisiti
- Windows 10/11 64 bit (x64; MetaTrader5 per Python non esiste per ARM)
- Python 3.11 da python.org (`py -3.11`), Git, Node ≥ 22.12
- Per MT5: terminale MetaTrader 5 installato, aperto e collegato a un conto **Demo**
- Per l'app desktop: WebView2 (presente su Windows 11), strumenti C++ MSVC e Rust stable ≥ 1.90 (solo per compilarla)

## Modo A — servizio locale nel browser (consigliato per il collaudo)

```powershell
git clone https://github.com/foffo09/AITradingBot.git
Set-Location AITradingBot
git switch agents/claude-v1-review-20261124
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm ci
.\avvia_web.ps1 -Build
```

`requirements-dev.txt` installa anche `MetaTrader5` (solo Windows x64). Si apre il browser su
`http://127.0.0.1:<porta>`. Chiusura: Ctrl+C nella finestra PowerShell. Se un avvio precedente è rimasto
appeso: `.\avvia_web.ps1 -RecoverStale`.

Dati: `%LOCALAPPDATA%\AITradingBot\local-service` (altro percorso con `-DataDirectory`).

## Modo B — app desktop (build locale non firmata)

```powershell
.\.venv\Scripts\python.exe -m pip install -r packaging/backend/requirements.txt
npm run build
.\.venv\Scripts\python.exe scripts/build_backend.py
# copiare dist\backend\aitradingbot-service-<triple>.exe in src-tauri\binaries\
npm run desktop:build -- --bundles nsis
```

Installer: `src-tauri\target\release\bundle\nsis\*.exe`. Senza firma Authenticode SmartScreen mostra un
avviso: normale per una build di collaudo. Dati: `%APPDATA%\it.aitradingbot.desktop\local-service`.
Dettagli e verifica pacchetto: `DESKTOP_RELEASE_GUIDE.md`.

## Verifica MT5 (terminale aperto, conto Demo)

```powershell
.\.venv\Scripts\python.exe -m scripts.check_mt5_api --symbol EURUSD
```

Atteso: `MT5 API CHECK: PASS` e `MT5 MARKET READ: OK`. Il report non contiene numero di conto né
credenziali e mostra il profilo utente come `~`: si può incollare nell'issue #9. Se `MT5 MARKET READ`
riporta "… s ahead of UTC" o "… s vs UTC", il broker usa l'ora del server: incollare il report, serve per
la correzione (vedi `MT5_CONNECTION_FIX_REPORT.md`). `--symbol` deve essere un simbolo visibile in
Market Watch.

## Aggiornamento
Chiudere l'app, fare il backup (sotto), poi `git pull` (o installare il nuovo installer) e ripetere
`pip install -r requirements-dev.txt` e `npm ci`. Le tabelle SQLite si aggiornano solo aggiungendo colonne;
non c'è ancora una versione di schema né un backup automatico.

## Backup e ripristino
Con l'app **chiusa**, copiare l'intera cartella dati:

```powershell
Copy-Item -Recurse "$env:LOCALAPPDATA\AITradingBot\local-service" "$HOME\Documents\AITradingBot-backup-$(Get-Date -Format yyyyMMdd)"
```

Ripristino: app chiusa, rimettere la cartella copiata al suo posto. Desktop: stessa cosa con
`%APPDATA%\it.aitradingbot.desktop\local-service`. La disinstallazione potrebbe non rimuovere i dati
(non verificato): fare comunque il backup prima.
