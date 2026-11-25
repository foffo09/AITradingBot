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

1. Apri MetaTrader 5, accedi al conto **Demo** e lascia il terminale aperto. In Market Watch deve essere visibile EURUSD (o un altro simbolo da passare con `--symbol`).
2. In PowerShell, nella cartella del progetto:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m scripts.check_mt5_api --symbol EURUSD
```

3. In fondo al report ci sono 9 righe `PASS`/`FAIL`: SDK, terminale, worker, connessione, conto, quotazione, candele, orari, chiusura. Atteso: tutte `PASS` e `MT5 API CHECK: PASS`.
4. Copia **tutto l'output** in un commento dell'issue #9. Non contiene password, numero di conto né saldi; il percorso del profilo appare come `~`. Il nome del server del broker è visibile: se preferisci, cancellalo prima di incollare.

Lo script è solo lettura: non invia ordini, non tocca posizioni e non attiva automazioni.

Come leggere i `FAIL` più probabili:
- `1 SDK` → manca il pacchetto: ripeti il `pip install`.
- `2 terminale` → MT5 non è aperto, o è un'installazione diversa da quella predefinita.
- `4 connessione` → leggi `connection.reason` (per esempio, il conto non è Demo o il login è scaduto).
- `6 quotazione` / `8 orari` con "… s vs UTC" o "… s ahead of UTC" → il broker usa l'ora del server. Il dato viene scartato e **non** corretto con un offset inventato. Serve il report per decidere la correzione.
- `7 candele` → simbolo non presente in Market Watch.

## Aggiornamento
Chiudere l'app, fare il backup (sotto), poi `git pull` (o installare il nuovo installer) e ripetere
`pip install -r requirements-dev.txt` e `npm ci`. Il ledger SQLite ha una versione di schema: prima di
aggiornarlo l'app ne controlla l'integrità e salva una copia accanto al file (`*.v<versione>-<data>.bak`).
Un ledger creato da una versione più recente dell'app non viene aperto, così i dati restano intatti.

## Backup e ripristino
Con l'app **chiusa**, copiare l'intera cartella dati:

```powershell
Copy-Item -Recurse "$env:LOCALAPPDATA\AITradingBot\local-service" "$HOME\Documents\AITradingBot-backup-$(Get-Date -Format yyyyMMdd)"
```

Ripristino: app chiusa, rimettere la cartella copiata al suo posto. Desktop: stessa cosa con
`%APPDATA%\it.aitradingbot.desktop\local-service`. La disinstallazione potrebbe non rimuovere i dati
(non verificato): fare comunque il backup prima.
