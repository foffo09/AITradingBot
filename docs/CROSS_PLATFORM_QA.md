# QA multipiattaforma — stato al 24 novembre 2026

Branch `agents/claude-complete-modernization-20261124`. "Verificato" significa eseguito davvero;
CI GitHub usa Windows Server e macOS arm64 ospitati, non Windows 11 o Mac Intel.

## Matrice

| Verifica | macOS arm64 locale (M5, macOS 27.2.1) | CI macos-latest (arm64) | CI windows-latest (Server) | Windows 11 GUI | macOS Intel |
|---|---|---|---|---|---|
| Suite Python offline | 890 passed, 1 skipped (venv pulito senza Streamlit) | PASS | 888 passed, 3 skipped (run 45397140080) | non eseguito | non eseguito |
| Ruff (E9 + pyflakes) | PASS | PASS | PASS | — | — |
| Frontend lint/typecheck/test/build | PASS, 61 test | PASS | PASS | — | — |
| Rust `cargo test` | 4 passed (incluso kill del process group) | PASS | PASS (test Unix esclusi) | — | — |
| Smoke HTTP sorgente e sidecar frozen | PASS | PASS | PASS | — | — |
| Sidecar lifecycle (`qa_sidecar_lifecycle.py`) | 5/5 PASS | — | — | — | — |
| Lock broker sotto carico (60 richieste Paper bloccate) | Demo < 2 s (prima: timeout 30 s) | vedi run finale | vedi run finale (prima saltato: richiedeva la build React) | — | — |
| Launcher PowerShell reale (avvio, duplicato, stop, riavvio) | n/a | n/a | PASS su `4e656de`; su `4503e49` vedi nota | non eseguito | n/a |
| Bundle desktop | `.app` + DMG costruiti, DMG verificato, installato in cartella isolata | `--no-bundle` compilato | NSIS costruito, installato, smoke, disinstallato | non eseguito | non eseguito |
| App reale: sezioni, walk-forward, watchlist, stato sistema | PASS | — | — | non eseguito | non eseguito |
| Timeout backend (worker sospeso 32 s) e recupero stessa istanza | PASS | — | — | non eseguito | non eseguito |
| Chiusura (⌘Q / Apple Event quit), worker bloccato + quit | PASS: 0 processi, porta chiusa (≤ 21 s col worker bloccato) | — | — | non eseguito | — |
| Firma / notarizzazione | ad-hoc, `spctl` rifiuta | — | NSIS non firmato | — | — |

## Note

- **Launcher Windows su `4503e49`:** un tentativo è fallito con `Invalid HTTP request received` scritto da
  uvicorn su stderr durante l'arresto; nel job PowerShell lo stderr nativo diventa un errore. Nessun file del
  launcher/runtime è cambiato rispetto a `4e656de`, dove lo stesso passo era PASS; Codex aveva già corretto una
  corsa simile (`83382c0`). Il rerun dello stesso SHA è PASS: **intermittente**, 1 fallimento su 3 esecuzioni
Windows osservate. Causa non riprodotta su macOS; ipotesi: richiesta di polling dell'arresto che arriva mentre
uvicorn chiude il socket. Aperto, nessuna correzione speculativa.
- **Windows 11 GUI** e **macOS Intel** restano da provare su macchine reali; la CI non li sostituisce.
- I test Python saltati su Windows sono: guardia self-pipe Proactor (solo non-Windows), permessi `chmod` e alias
  symlink (non applicabili alle ACL di Windows senza privilegi).
