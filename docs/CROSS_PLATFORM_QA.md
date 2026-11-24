# QA multipiattaforma — stato al 24 novembre 2026

Branch `agents/claude-complete-modernization-20261124`, commit verificato `0f8dac4`, CI run 45417229635
(5 job su 5 verdi). "Verificato" significa eseguito davvero. La CI usa runner GitHub (Windows Server, macOS
arm64, macOS Intel), non Windows 11 di un utente.

## Matrice

| Verifica | macOS arm64 locale (M5) | CI macos-latest (arm64) | CI macos-15-intel (x86_64) | CI windows-latest (Server) | Windows 11 reale |
|---|---|---|---|---|---|
| Suite Python offline | 893 passed, 1 skipped (venv pulito senza Streamlit) | 893 passed, 1 skipped | — | 892 passed, 2 skipped | non eseguito |
| Ruff, frontend lint/typecheck/test/build | PASS, 65 test | PASS | PASS | PASS | — |
| Rust `cargo test` | 4 passed | PASS | 4 passed | 4 passed, incluso Job Object (nipote terminato) | — |
| Carico broker (60 letture Paper bloccate) | Demo < 2 s | PASS | — | PASS | — |
| Smoke HTTP sorgente e sidecar frozen | PASS | PASS | PASS | PASS (anche sidecar installato) | — |
| Launcher PowerShell (avvio, duplicato, stop, riavvio) | n/a | n/a | n/a | PASS | — |
| App desktop reale avviata | `.app` da DMG, cartella isolata | — | — | **PASS**: app installata con WebView2, sidecar sano | non eseguito |
| Chiusura finestra / crash della shell | PASS (⌘Q, Apple Event, worker bloccato) | — | — | **PASS**: nessun sidecar e porta chiusa in entrambi i casi | non eseguito |
| Timeout backend (worker sospeso 32 s) e recupero | PASS | — | — | — | non eseguito |
| Pacchetto | `.app` + DMG arm64, `hdiutil verify` | DMG arm64, verify, 0 percorsi home | `Mach-O x86_64`, DMG x64, verify, 0 percorsi home | NSIS: installazione, avvio, disinstallazione | — |
| `cargo audit` | 0 vulnerabilità, 3 avvisi senza correzione | 0 vulnerabilità | — | — | — |
| Firma / notarizzazione | ad-hoc, `spctl` rifiuta | — | — | NSIS non firmato | — |

## Note

- **Intermittenze risolte:** il test Rust di shutdown su Windows usava `powershell.exe` (avvio a freddo oltre
  20 s); ora usa `cmd.exe`. Il launcher falliva una volta su tre per un warning benigno di uvicorn su stderr
  durante la chiusura; il servizio ora registra solo errori. In tutte le esecuzioni successive: PASS.
- Un job `macos-tests` è stato annullato una volta da GitHub per mancanza di runner ("not acquired … capacity
  constraints"): infrastruttura, non codice; verde nelle altre esecuzioni.
- Test saltati su Windows: alias symlink e permessi `chmod` (non applicabili alle ACL di Windows); su macOS:
  guardia self-pipe Proactor (solo Windows).
- **Windows 11 con utente reale** resta da provare a mano; la CI Windows Server non lo sostituisce.
