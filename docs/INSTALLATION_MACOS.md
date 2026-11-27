# Installazione su macOS (Apple Silicon e Intel, v1.0 candidata)

MT5 non è supportato su macOS: il contesto MT5 risponde "unsupported" senza avviare processi. Demo,
Simulazione e Alpaca Paper (sola lettura) funzionano.

## Requisiti
Python 3.11, Node ≥ 22.12, Git. Per l'app desktop anche Command Line Tools di Xcode e Rust stable ≥ 1.90.

## Servizio locale nel browser

```bash
git clone https://github.com/foffo09/AITradingBot.git && cd AITradingBot
git switch agents/claude-v1-review-20261124
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci && npm run build
.venv/bin/python scripts/start_local.py
```

Si apre il browser su `http://127.0.0.1:<porta>`; chiusura con Ctrl+C.
Dati: `~/Library/Application Support/AITradingBot/local-service` (altro percorso con `--data-dir`).

## App desktop (build locale non firmata)

```bash
.venv/bin/python -m pip install -r packaging/backend/requirements.txt
.venv/bin/python scripts/build_backend.py
cp dist/backend/aitradingbot-service-* src-tauri/binaries/
CI=true npm run desktop:build -- --bundles app,dmg
```

Output in `src-tauri/target/release/bundle/`. L'app non è firmata né notarizzata: Gatekeeper la blocca
su altri Mac e non va aggirato lì. Dati: `~/Library/Application Support/it.aitradingbot.desktop/local-service`.
Dettagli: `DESKTOP_RELEASE_GUIDE.md`.

## Alpaca Paper (facoltativo)
Esportare `ALPACA_API_KEY` e `ALPACA_SECRET_KEY` nella shell prima dell'avvio. L'app non le salva e non
invia ordini.

## Aggiornamento, backup, ripristino
App chiusa: `cp -R ~/Library/Application\ Support/AITradingBot/local-service ~/AITradingBot-backup-$(date +%Y%m%d)`,
poi `git pull`, `pip install -r requirements-dev.txt`, `npm ci && npm run build`. Ripristino: app chiusa,
rimettere la cartella copiata. Prima di aggiornare il ledger SQLite l'app ne controlla l'integrità e salva
una copia `*.v<versione>-<data>.bak`; un ledger di una versione più recente non viene aperto.
