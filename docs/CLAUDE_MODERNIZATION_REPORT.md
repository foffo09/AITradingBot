# Report di modernizzazione — Claude Code, 24 novembre 2026

## 1. Contesto e limiti di coordinamento

- Branch: `agents/claude-complete-modernization-20261124`, base `agents/master-consolidation-20261117` (`8a4d740`,
  ultimo consolidamento Codex, contenente PR #7 e #8). Tutti i branch remoti sono contenuti in questo HEAD,
  tranne il commit di merge `1afd8fb` su `mie-modifiche` (successivo al merge della PR #3, senza contenuto nuovo).
- Codex Mac non raggiungibile: da questa rete il TLS verso `chatgpt.com`/`api.openai.com` è intercettato da un
  firewall Fortinet. Su richiesta dell'utente il lavoro (anche quello assegnato a Codex nell'issue #9) è stato
  eseguito da Claude. **Correzioni e verifiche sono dello stesso agente: serve una revisione indipendente prima del merge.**
- Notion: nessun connettore in questa sessione, non letto né aggiornato.

## 2. Commit (15, sopra `8a4d740`)

| Commit | Contenuto |
|---|---|
| `3c65242`, `644ab56` | Audit macOS indipendente, handoff |
| `513a45f` | M1: lock per contesto |
| `fc4b2ea` | L1 timeout WebKit, L4 form conto senza stato |
| `94472de` | L2 busy timeout SQLite, L3 kill del process group, L5 home fuori dal binario |
| `77ce174`, `b0d84bc`, `3884104` | Report fasi 3–5 |
| `c5ecb7f`, `f663536` | API e UI: walk-forward, watchlist, stato sistema, tema chiaro |
| `439b3c7` | Dismissione Streamlit |
| `4e656de` | Gate ruff in CI (L6), correzioni UI dal collaudo dell'app installata |
| `f65be2d`, `4503e49`, `fece56b` | Correzioni dalla revisione completa (§4) |

## 3. Cosa è stato realizzato

- **Unica architettura** React/TypeScript + FastAPI + Tauri 2 (`docs/ARCHITECTURE.md`). Streamlit, `app.py`,
  tre launcher e `src/ui` rimossi; streamlit/plotly/pillow fuori dai manifest (`docs/STREAMLIT_RETIREMENT_REPORT.md`).
- **Sezioni**: Panoramica, Mercati, Watchlist (nuova), Segnali, Portafoglio, Storico, Backtesting + Walk-forward
  (nuovo), Automazione (dry-run), Connessioni, Stato sistema (nuova), Impostazioni. Tema chiaro predefinito.
- **Audit**: M1 e L1–L6 corretti con test RED→GREEN.
- **Packaging**: `.app` e DMG macOS arm64 costruiti da ambiente pulito, installati in cartella isolata e collaudati;
  NSIS Windows costruito, installato e disinstallato in CI.

## 4. Revisione completa e correzioni successive

| Falla | Gravità | Correzione | Prova |
|---|---|---|---|
| Lock Paper: richieste in coda saturano il pool di 40 thread, Demo in timeout | MEDIUM | attesa ≤ 2 s su lock paper/mt5, poi 503 | probe su uvicorn reale: prima timeout 30 s, dopo Demo < 2 s (CI Windows e macOS) |
| `os.geteuid` bloccava la raccolta dei test su Windows | MEDIUM | skip su Windows | CI Windows 889 passed |
| Trade virtuale incerto perso al cambio di porta (doppia registrazione) | LOW | record nel servizio (`/pending-trade`), trade diversi rifiutati finché in sospeso | test riavvio + risposta persa; app reale |
| Walk-forward: test sotto il minimo → 409 generico | LOW | 422 esplicito | test parametrizzato |
| Stato MT5 fisso "disconnected" su Windows | LOW | `MT5Process.state` senza IPC | test |
| Serie demo identica per tutti i simboli | LOW | seed deterministico per simbolo | test + Watchlist reale |
| Watchlist svuota la scelta anche se il salvataggio fallisce | LOW | svuota solo su successo | — |
| Ack ordine Paper senza `client_order_id` accettato | LOW | rifiutato | test contrattuale RED→GREEN |
| Build: `CARGO_ENCODED_RUSTFLAGS` sostituiva i rustflags di config | LOW | `cargo --config` (si somma, verificato) | build verbose |
| Primo avvio vicino al limite di 15 s | LOW | limite 30 s, sempre fail-closed | — |

## 5. Risultati finali

| Suite | Esito |
|---|---|
| Python, macOS locale (venv pulito senza Streamlit) | 890 passed, 1 skipped, coverage 88% |
| Python, CI macOS / Windows (run 45401539011) | 890 passed, 1 skipped / 889 passed, 2 skipped |
| Frontend lint, typecheck, test, build | PASS, 61 test |
| Rust | 4 passed (macOS); Windows PASS al rerun, 1 fallimento intermittente (§6) |
| ruff, pip check, pip-audit, npm audit | PASS, coerente, 0, 0 |
| Smoke HTTP sorgente e frozen, lifecycle sidecar | PASS, 5/5 |
| App installata dal DMG: sezioni, walk-forward, watchlist, trade virtuale, timeout e recupero, quit | PASS, 0 processi residui, porta chiusa |

Artefatti (build locale arm64, firma ad-hoc, codice di `4503e49`; `fece56b` cambia solo test/docs):
DMG `11a8e5d0174c215a4289e22ffcfd3af6cddfb2b77b384691e5bf048c17578898` (44.7 MB),
desktop `68da5fd166529067c7aeefa5bc163e24330a991a0837653c801db794f83031b7`,
sidecar `590ff9c4161dfc561de7d4019289282583f5c1b88411d78c575dfd362153b6ca`. Nessun artefatto pubblicato.

## 6. Problemi aperti

- **Intermittenti Windows CI** (codice non modificato da questo lavoro): launcher PowerShell, `Invalid HTTP request`
  su stderr durante l'arresto (1 su 3 esecuzioni); test Rust `shutdown_allows_bounded_native_cleanup…` con
  `powershell.exe` oltre i 20 s (1 su 3). Entrambi PASS al rerun. Cause non riprodotte: nessuna correzione speculativa.
- **Gate di distribuzione**: firma Developer ID e notarizzazione, firma Authenticode, licenza/NOTICE, macOS Intel,
  Windows 11 GUI reale (`docs/DESKTOP_RELEASE_GUIDE.md` §4).
- `cargo audit` non eseguito (strumento non installato).
- Revisione indipendente delle correzioni di Claude.

## 7. Classificazione

**CONDITIONALLY READY** — nessun problema funzionale o di sicurezza aperto nelle verifiche eseguite; non
**READY FOR RELEASE CANDIDATE** perché mancano revisione indipendente, firma/notarizzazione, prove Windows 11 e Intel,
e due test CI Windows sono intermittenti.
