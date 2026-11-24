# Guida build e distribuzione desktop

Stato al 24 novembre 2026: **nessuna release pubblicata**. I pacchetti sotto sono build locali/CI
non firmate, per collaudo. Non distribuirle a utenti finali prima dei gate in §4.

## 1. Prerequisiti (sviluppatore)

Python 3.11, Node ≥ 22.12 con npm ≥ 10, Rust stable ≥ 1.90.
macOS: Command Line Tools di Xcode. Windows: strumenti C++ MSVC e WebView2.
Build sul sistema di destinazione: PyInstaller non fa cross-compilazione.

## 2. Build

```sh
python -m pip install -r requirements-dev.txt -r packaging/backend/requirements.txt
npm ci
npm run build
python scripts/build_backend.py          # dist/backend/aitradingbot-service-<target-triple>
```

Copiare il sidecar in `src-tauri/binaries/` con lo stesso nome, poi:

```sh
# macOS (CI=true evita lo script Finder del DMG in sessioni senza GUI)
CI=true npm run desktop:build -- --bundles app,dmg
# Windows
npm run desktop:build -- --bundles nsis
```

`npm run desktop:build` (`scripts/desktop_build.mjs`) aggiunge `--remap-path-prefix=<home>=~` tramite
`cargo --config build.rustflags=[...]`, che si somma ai `rustflags` dei file `.cargo/config.toml`
(se `RUSTFLAGS` è già impostata viene estesa quella, perché Cargo ignora allora i file di config):
il binario release non contiene la home di chi compila (verifica: `strings <binario> | grep -c "$HOME"` = 0).

Output: `src-tauri/target/release/bundle/macos/AITradingBot.app`,
`src-tauri/target/release/bundle/dmg/AITradingBot_<versione>_<arch>.dmg`,
`src-tauri/target/release/bundle/nsis/*.exe`.

## 3. Verifica di un pacchetto prima di consegnarlo

1. Annotare commit esatto e `shasum -a 256` di DMG/installer, desktop e sidecar.
2. macOS: `hdiutil verify <dmg>`; montarlo in sola lettura, copiare l'app in una cartella di prova.
   Windows: `scripts/check_windows_installer.ps1` (installazione in percorso temporaneo, smoke, disinstallazione).
3. Avviare con dati isolati (macOS: `HOME` temporanea), verificare sezioni, `Stato sistema`
   (`Invio ordini: disabilitato`), recupero dopo sospensione del worker, chiusura con ⌘Q:
   nessun processo `aitradingbot-*` residuo, porta liberata.
4. `python scripts/qa_sidecar_lifecycle.py <sidecar>` e `python -m scripts.check_local_service --binary <sidecar>`.

## 4. Gate di distribuzione (servono il proprietario e le sue credenziali)

| Gate | Stato | Cosa serve |
|---|---|---|
| Firma macOS Developer ID + Hardened Runtime | **Aperto**: firma ad-hoc, `spctl` rifiuta l'app | Account Apple Developer, certificato "Developer ID Application" nel portachiavi; `APPLE_SIGNING_IDENTITY` per Tauri; entitlements per il sidecar PyInstaller (eseguibile figlio firmato con hardened runtime) |
| Notarizzazione + stapling | **Aperto** | `APPLE_ID`, `APPLE_PASSWORD` (app-specific) e `APPLE_TEAM_ID`, oppure chiave API App Store Connect; poi `xcrun stapler staple` sul DMG |
| macOS Intel | **Build verificata in CI** (`macos-15-intel`: binario x86_64, smoke sidecar, DMG x64) | Prova manuale su un Mac Intel reale; un pacchetto universal richiederebbe due sidecar |
| Firma Windows (Authenticode) | **Aperto** | Certificato di firma codice; senza, SmartScreen avvisa l'utente |
| Windows 11 GUI reale | Avvio/chiusura/crash dell'app installata **verificati su Windows Server in CI**; Windows 11 non provato | Prova manuale su PC Windows 11 |
| Licenza e NOTICE del progetto | **Licenza del progetto aperta**; inventario terze parti pronto (`THIRD_PARTY_NOTICES.md`, 287 componenti, nessun GPL, alcuni MPL-2.0) | Scelta della licenza da parte del proprietario; verifica legale degli obblighi (MPL-2.0, Apache NOTICE) |
| Aggiornamenti automatici | Non configurati | Decidere se usare il plugin updater di Tauri (richiede chiave di firma degli aggiornamenti) |

Nessuna firma è simulata: senza questi elementi i pacchetti restano per collaudo interno.

## 5. Installazione per l'utente (quando i gate saranno chiusi)

- **macOS:** aprire il DMG, trascinare AITradingBot in Applicazioni, avviare. Con una build non
  notarizzata macOS blocca l'apertura: non aggirare Gatekeeper sul computer di altri.
- **Windows:** eseguire l'installer NSIS; collegamento nel menu Start; disinstallazione da
  Impostazioni → App. Che i dati in app-data restino dopo la disinstallazione **non è ancora verificato**:
  fare un backup prima.
- Alpaca Paper: impostare `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` nell'ambiente prima di avviare;
  l'app non chiede né salva credenziali.
