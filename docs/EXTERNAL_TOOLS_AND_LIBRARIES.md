# Strumenti e librerie esterne — stato al 24 novembre 2026

Regola applicata: si integra solo ciò che produce un miglioramento concreto e verificabile stasera. Nessun plugin
o MCP installato; nessuna configurazione globale modificata; nessuna credenziale richiesta o salvata.

## Strumenti disponibili nella sessione (verificati)

| Strumento | Stato | Uso |
|---|---|---|
| GitHub CLI (`gh`) autenticato | disponibile | branch, push, dispatch e log di GitHub Actions |
| GitHub Actions `windows-ci.yml` | disponibile | unico ambiente Windows reale accessibile all'agente |
| Browser integrato (Claude desktop) | disponibile | prova end-to-end della UI sul servizio locale reale (desktop e 375 px) |
| Notion | **non connesso** in questa sessione | Agent Operating Guide, task e report non letti: nessuna informazione inventata |
| Codex CLI | bloccato (intercettazione TLS e limite d'uso, sessioni precedenti) | non usato |
| MCP `packet-tracer` | connessione fallita | non pertinente |
| Terminale MetaTrader 5 | assente (macOS e runner CI) | connessione reale da verificare sul PC Windows |

## Librerie già integrate (mantenute, versioni bloccate)

| Componente | Licenza | Perché resta |
|---|---|---|
| `lightweight-charts` 5.3.0 (TradingView) | Apache-2.0 | grafici candlestick/volume/indicatori; già il riferimento richiesto, nessuna alternativa più leggera |
| React 19, Vite 8, TypeScript 6 | MIT / Apache-2.0 | UI unica dopo la dismissione di Streamlit |
| FastAPI, uvicorn, pydantic | MIT / BSD | servizio locale su loopback |
| Tauri 2 + PyInstaller | MIT-Apache / GPL con eccezione bootloader | app desktop con sidecar posseduto |
| `MetaTrader5` 5.0.6231 (MetaQuotes, ufficiale) | proprietaria, gratuita | unico SDK MT5 supportato; installato solo su Windows AMD64 |
| pytest, Vitest, Testing Library, ESLint, Ruff | MIT | test e lint già in CI |
| pip-audit, npm audit, cargo audit | Apache-2.0 / MIT | controllo dipendenze (0 vulnerabilità note) |

## Valutate e non aggiunte stasera

| Candidato | Motivo |
|---|---|
| Playwright | la CI già avvia la vera app desktop (NSIS + GUI) e la UI è stata provata nel browser reale; un secondo stack E2E aggiunge ~300 MB senza coprire il difetto MT5 |
| mypy | codice Python non annotato in modo uniforme: centinaia di errori non legati al prodotto; da introdurre per moduli |
| Bandit | Ruff (E9, F) + test di sicurezza mirati (Host/Origin, segreti, endpoint di scrittura) già presenti; utile più avanti come gate non bloccante |
| TanStack Query / Redux | lo strato `api.ts` valida già ogni risposta; una libreria di cache non risolve problemi aperti |
| Wrapper MT5 di terze parti (bridge ZeroMQ, REST EA) | richiedono un Expert Advisor nel terminale e permessi di trading: contrari al vincolo read-only |

## Cosa servirebbe per altre integrazioni

- Notion: connettere il server MCP di Notion alla sessione (autorizzazione dell'utente) per leggere guida e task.
- Codex: rete senza intercettazione TLS e quota disponibile.
