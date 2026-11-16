# Audit e integrazione applicazione locale — 16 novembre 2026

Mandato master dell'utente: implementare e verificare React/TypeScript/Vite,
FastAPI/Pydantic, Tauri e integrazione dei servizi Python; Streamlit resta
legacy. Nuova autorizzazione supera il precedente perimetro solo documentale
P4. Vietati merge su main, ordini reali, deploy/release, costi e credenziali
personali. Commit/branch/PR autorizzati. Nessun valore .env letto.

## Ricognizione iniziale

Host reale macOS arm64, non il PC Windows del percorso storico. Main remoto
fe988394d6ecdcb56763a81c627943b4cbe684e1; checkout principale locale 2b2d35a
con lavoro non committato (incluso esecutore Paper), preservato. Nessun conflitto
unmerged rilevato. I branch di migrazione P1/P2/P3 indicati non esistevano.
PR aperte #5/#6: CI draft e dipendenti; PR storiche #1..#4 già merged.
La base QA 3df4f82 includeva documenti locali della precedente missione:
conservati nel commit 1542dce prima di iniziare implementazioni.

Suite baseline Python 3.11 su Mac: 747 passati, 1 skip Proactor atteso,
1 warning websockets.legacy, 34,62 s; guard rete/credenziali 0/0.
Node 22.23.3, npm 10.9.9. Rust inizialmente assente da PATH; installato da
fonte ufficiale con SHA256 verificato in directory temporanea isolata,
senza cambiare profili o installazioni globali.

## Coordinamento e componenti

Letti Team Hub, direttiva migrazione e aree P1/P2/P3/P4 in Brave. La ricerca
Notion non ha trovato Agent Operating Guide né ArbitraBot; sono riferimenti
non accessibili/non reperiti, non ne viene inventato contenuto. Nessun MCP
Notion disponibile: non si aggiungono parametri instructions_version a tool
che non li supportano. Notion usato via UI, senza cambiare condivisioni.

- P1: React e Tauri in worktree dedicato dalla base e1bd306, conservando il
  lavoro legacy già committato.
- P2: FastAPI, sessione locale, quattro contesti, provider, packaging, dalla base main.
- P3: riuso motore puro e contratto versionato. Riprodotto un cap BUY troppo
  alto quando equity scende sotto capitale configurato; corretto in modo
  restrittivo, senza alzare soglie. Servizio non invia ordini.
- Coordinatore: worktree integration/local-web-desktop-20261116 da 1542dce;
  launcher cross-platform, integrazione, audit e prove.

I worktree sono distinti; nessun agente lavora simultaneamente nello stesso
checkout. Nessun ramo altrui cancellato o riscritto. Le integrazioni sono sul
ramo dedicato, mai su main.

## Contratto deciso

API /api/v1, UI stessa origine (backend serve asset React compilati), cookie
HttpOnly effimero, Host/Origin restrittivi e X-Local-Request; nessun token
esposto a JS/URL/CLI. Desktop carica la stessa UI loopback dopo handshake del
sidecar. Identità processo e socket sono verificati prima di stop. Il backend
non riusa il lifespan della console Omega che avviava un worker.

GET non invia ordini o attiva bot. Apertura conto e operazioni locali sono
POST espliciti, solo Demo/Simulazione e ledger distinti. Alpaca solo letture
Paper dopo connessione esplicita env-only. MT5 opzionale e read-only Windows;
nessun ordine MT5/Paper dall'API. Fonte sintetica non autorizza una proposta
operativa. Dati mancanti restano null/N/D, non capitale o prezzi inventati.

## Verifiche in corso

I risultati finali sono registrati a fine integrazione. La baseline non prova
la nuova applicazione. Windows 11 e conti autentici richiedono prove separate;
nessun esito Mac è attribuito a Windows. Non sono promessi profitti o sicurezza
assoluta.
