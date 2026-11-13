# Gate di integrazione e release

Procedura per il responsabile di `foffo09/AITradingBot`. Sprint 05, Persona 4.
Questo documento descrive azioni future: **non le autorizza né le esegue**.
Non abilita broker, feed, server, ordini, automazione, deploy o capitale reale.
Demo, Simulazione locale e Alpaca Paper conservano capitali, ledger e stato separati.

## 1. Come usare la checklist

- **PASS**: evidenza osservata, limitata a fonte, piattaforma e commit indicati.
- **FAIL**: una verifica eseguita ha prodotto un risultato incompatibile col gate.
- **BLOCKED**: manca un prerequisito o una decisione necessaria per proseguire.
- **NON VERIFICATO**: prova non eseguita o fonte non accessibile; non equivale a PASS.

Le caselle vuote sono passi da eseguire dal responsabile con autorizzazione
specifica. Non sono attestazioni di controlli già passati. Le raccomandazioni di
policy vanno approvate dal proprietario; non sono impostazioni già configurate.
Un check verde non è una review, una release o un permesso di trading.

## 2. Stato osservato e fonti

Ricontrollo: **13 novembre 2026, 13:47:45 UTC / 14:47:45 Europe/Rome**,
Codex su macOS 27.2.1, build 26B131, arm64. Fonte: fetch origin senza prune,
GitHub CLI/REST/GraphQL in sola lettura; workflow e matrice dalla base reale.
Le letture CI sono state completate nella stessa sessione. Nessuna nuova suite
applicativa o pipeline avviata nello Sprint 05.

| Riferimento | SHA osservato | Stato |
| --- | --- | --- |
| `origin/main` | `fe988394d6ecdcb56763a81c627943b4cbe684e1` | Base attuale della PR #5 |
| PR #5, head `agents/p4-windows-ci-20261110` | `5e759404ef574c1dacc22a79a417f29362a8a2ef` | OPEN/DRAFT, base `main` allo SHA sopra |
| PR #6, head `agents/p4-cross-platform-ci-20261112` | `97ff2966b9d8d82d6c6f10d30e9da125656e5259` | OPEN/DRAFT, base branch PR #5 a `5e75940` |

Fonti correnti: [PR #5](https://github.com/foffo09/AITradingBot/pull/5),
[PR #6](https://github.com/foffo09/AITradingBot/pull/6). Entrambe risultano
MERGEABLE/CLEAN, senza approvazioni: `reviews=[]`, `reviewRequests=[]`,
`reviewDecision` vuoto. Zero thread per ciascuna, paginazione GraphQL conclusa.
Questi stati non sostituiscono l'autorizzazione del responsabile.

Ancestry verificata con `git merge-base --is-ancestor` (exit 0):
`main -> 065859d -> 5e75940 -> 1e43466 -> 97ff296`.
`rev-list --left-right --count` restituisce 0/2 per main/PR #5 e 0/2 per
PR #5/PR #6. Nessuna divergenza o merge inatteso nei quattro commit aggiuntivi.
La PR #6 **dipende** dalla #5: non va trattata come indipendente.

PR #5 aggiunge solo il workflow Windows e aggiorna la matrice: commit
`065859dced4db1253172ea1f8c01081ad20cd496` e
`5e759404ef574c1dacc22a79a417f29362a8a2ef`.
Il delta proprio #6 aggiunge il job macOS, il trigger per il branch base
impilato e documentazione: commit `1e4346672a0508d5fb6a54187dbd49bd9112bc50`
e `97ff2966b9d8d82d6c6f10d30e9da125656e5259`.
Entrambi i delta interessano soltanto `.github/workflows/windows-ci.yml` e
`docs/MATRICE_TEST.md`. Il job Windows e codice/test/guard sono invariati.

### Protezioni: osservazione attuale e limite di accesso storico

Il prompt Notion del 13 novembre riporta una lettura precedente HTTP 403:
**NON VERIFICATO per quella lettura**, non prova di presenza o assenza di regole.
Nel ricontrollo di questa consegna:

| Fonte REST, metodo GET | Risposta osservata |
| --- | --- |
| `/repos/foffo09/AITradingBot/branches/main` | HTTP 200, `protected=false`, SHA main sopra |
| `/repos/foffo09/AITradingBot/rules/branches/main` | HTTP 200, `[]` |
| `/repos/foffo09/AITradingBot/rulesets?includes_parents=true` | HTTP 200, `[]` |
| `/repos/foffo09/AITradingBot/branches/main/protection` | HTTP 404 |

Non risultano protezioni applicate o required checks nelle letture riuscite;
la conclusione non deriva dal solo 404. Nessuna impostazione modificata.
Se una lettura futura è negata, incompleta o contraddittoria, scrivere
**NON VERIFICATO**, registrare endpoint/HTTP/data e chiedere al proprietario
evidenza della configurazione effettiva. Non ampliare permessi per dedurla.

## 3. Mappa dei check effettivi

Fonte: [workflow](../.github/workflows/windows-ci.yml), nome `Windows CI`,
e [matrice delle prove](MATRICE_TEST.md), allo SHA `97ff296` completo sopra.

| Job e check context esatto | Disponibilità | Runner richiesto | Shell | Python |
| --- | --- | --- | --- | --- |
| `windows-tests` | PR #5 e PR #6 | `windows-latest` | PowerShell `pwsh` | 3.11 |
| `macos-tests` | Solo PR #6 | `macos-latest` | Bash | 3.11 |

La PR #5 ha `pull_request` verso `main` e `workflow_dispatch`.
La PR #6 conserva entrambi e permette anche PR verso
`agents/p4-windows-ci-20261110`, per provare la PR impilata.
Non esiste trigger `push` né `merge_group`: non presumere un nuovo run dopo
ogni push su main o una copertura merge queue già implementata.

Entrambi i job hanno timeout 20 minuti, permesso `contents: read`, checkout
senza persistenza delle credenziali e con storia disponibile (`fetch-depth: 0`).
Azioni ufficiali fissate a SHA: checkout `3d3c42e5aac5ba805825da76410c181273ba90b1`
e setup-python `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`.
Ambiente conservativo: `PYTHON_DOTENV_DISABLED=1`, `TRADING_MODE=demo`,
`AUTO_TRADE=false`, `PAPER_EXECUTION_SCOPE=disabled`. Nessun secret broker.

Checklist di controllo del run, per ciascun job atteso:

- [ ] Checkout PR, sistema nativo e Python 3.11 confermati dai metadati.
- [ ] Installazione `requirements-dev.txt` e compilazione app/config/src/tests riuscite.
- [ ] Mirati: `test_backend_contract.py`, `test_broker.py`, `test_paper_safety.py`,
  `test_config.py`, `test_fx_rates.py`, `test_bar_timing.py`, tutti in `tests/`.
- [ ] Suite completa `python -m pytest -q -rs` riuscita, con report JUnit.
- [ ] Ogni gruppo mirato/completo riporta `TEST ISOLATION: {'network': 0, 'credentials': 0}`.
- [ ] Su Windows il test Proactor è presente e superato senza skip; su macOS lo
  skip ha la condizione originale di piattaforma, non una deroga aggiunta.
- [ ] Altri skip o variazioni dei conteggi analizzati, non nascosti correggendo aspettative.
- [ ] `pip check` e `git diff --check` riusciti; quest'ultimo include base/head PR,
  non soltanto il checkout pulito. Il dispatch controlla l'ultimo commit.
- [ ] Tutti gli step conclusi con successo; nessun errore nascosto da `tee` o pipeline.

I conteggi seguenti sono baseline osservate, non numeri da imporre ai test futuri.
Un job interamente skipped/neutral non basta per il gate operativo qui proposto,
anche se GitHub può accettarlo secondo la propria configurazione.

## 4. Evidenze storiche ricontrollate, separate per ambito

I run esistenti sono stati riletti il 13 novembre; **non sono nuove esecuzioni**.
Lo SHA head e il checkout sintetico della PR sono distinti dal commit main.

| Prova | Head | Checkout realmente testato | Fonte |
| --- | --- | --- | --- |
| PR #5, run corrente | `5e759404ef574c1dacc22a79a417f29362a8a2ef` | `356f38c743ffd2145535e060ac494f01ffcab899` | [42921890791](https://github.com/foffo09/AITradingBot/actions/runs/42921890791) |
| PR #6, run corrente | `97ff2966b9d8d82d6c6f10d30e9da125656e5259` | `d85faa84008bc85f391aba8322c8e8cce94313b2` | [43121098415](https://github.com/foffo09/AITradingBot/actions/runs/43121098415) |
| PR #6, run precedente | `1e4346672a0508d5fb6a54187dbd49bd9112bc50` | `e3ac5e53717b57614b49308428ca636d226ee3d9` | [43120507994](https://github.com/foffo09/AITradingBot/actions/runs/43120507994), SUCCESS, storico Sprint 03 |

I checkout PR sopra sono riferimenti temporanei GitHub, non merge effettuati
sui branch. Il run precedente non certifica l'head corrente.

| Ambito | Stato dell'evidenza | Piattaforma, commit e limiti |
| --- | --- | --- |
| Windows CI PR #5 | PASS | Head `5e75940`, job [130198536464](https://github.com/foffo09/AITradingBot/actions/runs/42921890791/job/130198536464): Server 2025 x64, Python 3.11.9, 152 mirati (6,44 s) e 748 completi (137,63 s), 0 fail/skip, 1 warning per gruppo. |
| Windows CI PR #6 | PASS | Head `97ff296`, job [130861448483](https://github.com/foffo09/AITradingBot/actions/runs/43121098415/job/130861448483): Server 2025 x64, Python 3.11.9, 152 mirati (6,98 s), 748 completi (160,92 s), 0 fail/skip, 1 warning per gruppo. |
| macOS CI PR #6 | PASS | Head `97ff296`, job [130861449009](https://github.com/foffo09/AITradingBot/actions/runs/43121098415/job/130861449009): macOS 26.7.2 arm64, Python 3.11.9, 152 mirati (3,10 s, 0 skip), 747 completi (62,72 s, 1 skip Proactor), 0 fail, 1 warning per gruppo. |
| macOS locale | PASS storico | Base `fe988394d6ecdcb56763a81c627943b4cbe684e1`, macOS 27.2.1 arm64/Python 3.11.18, baseline Sprint 01: 747 passati, 1 skip Proactor. Fonte: [matrice Sprint 02](MATRICE_TEST.md). Non rieseguito sul documento Sprint 05. |
| Windows 11 desktop/UI | NON VERIFICATO | Per head `97ff296`, nessuna prova desktop in questi run; Server 2025 CI non la sostituisce. |
| UI manuale su macOS | NON VERIFICATO | Per `97ff296`, nessuna sessione manuale della dashboard certificata da questa catena. AppTest offline non equivale a browser manuale. |
| Alpaca autenticato | NON VERIFICATO | Per `97ff296`, nessun account o ordine autentico provato; [BACKEND_HANDOFF](../BACKEND_HANDOFF.md). |
| Feed reali | NON VERIFICATO | Per `97ff296`, test con mock, nessuna attestazione di disponibilità/provenienza live. |
| Multi-host e recupero contabile autentico | NON VERIFICATO | Per `97ff296`, esclusione locale e test offline non provano coordinamento distribuito o riconciliazione reale. |
| Strategy Engine integrato UI/runner | BLOCKED | Per `97ff296`, integrazione applicativa attende specifica/contratti/report verificati; [STRATEGY_HANDOFF](../STRATEGY_HANDOFF.md). Test del motore puro non attestano il consumer completo. |
| Demo / Simulazione locale | PASS solo test offline | Per `97ff296`, suite con guard 0/0 e test di isolamento; [matrice](MATRICE_TEST.md). Non prova UX manuale, migrazione o persistenza prolungata in produzione. |
| Alpaca Paper operativo | NON VERIFICATO | Per `97ff296`, mock e default disabilitati non provano il ciclo operativo autenticato né autorizzano avvio. |
| Dispatch manuale | NON VERIFICATO | Workflow assente da main `fe98839`, confermato Git/API contents 404. Nessun dispatch eseguito. |

Per tutti i job correnti: compileall/pip check/diff-check PASS; guard 0/0 in
entrambi i gruppi, Proactor Windows PASS e solo skip atteso su macOS.
Warning noto `websockets.legacy`. Immagini effettive: `windows-2025-vs2026`
e `macos-26-arm64`. Non trasferire questi PASS a broker, feed o trading.

## 5. Gate comune: congelare la revisione esatta

Da una copia di ispezione pulita, con Git e GitHub CLI già autorizzati, i
seguenti comandi POSIX sono diagnostici. Il fetch aggiorna solo riferimenti;
non cambia i file. Non avviare test applicativi o leggere credenziali.

```sh
git status --short --branch
git fetch origin --no-tags
git rev-parse origin/main origin/agents/p4-windows-ci-20261110 origin/agents/p4-cross-platform-ci-20261112
gh pr view 5 --repo foffo09/AITradingBot --json state,isDraft,baseRefName,baseRefOid,headRefName,headRefOid,commits,reviews,reviewRequests,statusCheckRollup
gh pr view 6 --repo foffo09/AITradingBot --json state,isDraft,baseRefName,baseRefOid,headRefName,headRefOid,commits,reviews,reviewRequests,statusCheckRollup
git diff --name-status origin/main...origin/agents/p4-windows-ci-20261110
git diff --check origin/main...origin/agents/p4-windows-ci-20261110
git diff --name-status origin/agents/p4-windows-ci-20261110...origin/agents/p4-cross-platform-ci-20261112
git diff --check origin/agents/p4-windows-ci-20261110...origin/agents/p4-cross-platform-ci-20261112
```

Dopo l'eventuale integrazione della #5, adeguare il confronto #6 soltanto
alla base nuova autorizzata e registrata, non riusare ciecamente il comando
con il branch impilato. Non continuare su output falliti o fonti discordanti.

- [ ] Registrare data UTC/fuso, operatore, PR, base SHA, head SHA, checkout SHA
  del run, URL/attempt dei job e risultato. Associare ogni approvazione al diff esaminato.
- [ ] Confrontare i riferimenti Git con GitHub; fermarsi se differiscono dallo
  snapshot approvato. Non imporre per sempre i vecchi SHA dopo una modifica autorizzata.
- [ ] Esaminare diff completo e commit, separando delta proprio e lavoro ereditato;
  confermare scope e assenza di segreti, database, artefatti o modifiche inattese.
- [ ] Verificare ancestry, assenza di conflitti e stato Git pulito.
- [ ] Leggere review e thread con paginazione completa: nessuna richiesta di
  modifica pendente, tutti i thread pertinenti risolti con evidenza verificabile.
- [ ] Ottenere review approvata da persona autorizzata sul diff corrente, nel
  numero previsto dalla policy approvata; essere MERGEABLE non sostituisce la review.
- [ ] Draft/ready cambiato solo dal responsabile autorizzato, mai implicitamente.
- [ ] Controllare ogni job atteso, concluso SUCCESS sul head/base esatto:
  un run vecchio, check assente o solo status aggregato verde non basta.
- [ ] Ricontrollare regole applicate e required contexts. `gh pr checks --required`
  senza check configurati non dimostra che tutti i gate di questa procedura siano PASS.
- [ ] Registrare decisione esplicita del responsabile per la specifica azione e
  gli SHA. In caso di nuovi commit/base, riaprire gate CI e review prima di agire.

## 6. Ordine di integrazione proposto: #5, poi #6

**Nessun merge, retarget, conversione draft/ready o approvazione viene eseguito
da questo documento.** Non contiene comandi che effettuano tali scritture.

### A. Prima di una futura integrazione #5 in main

- [ ] Completare il gate comune su main/head #5 correnti e autorizzati.
- [ ] Richiedere `windows-tests`, con tutti i controlli della sezione 3.
  `macos-tests` non esiste nella #5: non imporlo a questa PR.
- [ ] Responsabile/proprietario decide review, policy e modalità d'integrazione.
  Preferire una storia che preservi ancestry per semplificare la catena; se
  viene scelto squash/rebase, registrare gli SHA nuovi e verificare contenuto,
  senza assumere che `5e75940` rimanga antenato.
- [ ] Subito prima dell'azione autorizzata, ricontrollare SHA, review/thread,
  job e diff; se mutati, fermarsi e aggiornare lo snapshot.

### B. Dopo l'eventuale integrazione #5

- [ ] Registrare nuovo main e commit d'integrazione; verificare che workflow
  Windows e matrice attesi siano presenti e il resto del delta sia quello rivisto.
- [ ] Verificare ancestry oppure equivalenza di contenuto se la modalità scelta
  ha cambiato gli SHA. Non dichiarare main certificata da un run su base diversa.
- [ ] Non cancellare il branch base della #6 prima di averne chiarito la dipendenza.
- [ ] Rileggere base/head effettivi della #6: non assumere retarget automatici.
  Il responsabile decide esplicitamente se/quando spostare la base su main.
  Lo scopo è integrare il solo incremento macOS nel ramo predefinito.

### C. Prima della futura integrazione #6 su main

- [ ] Dopo il cambio base autorizzato, rileggere tutti i commit e il delta:
  nessuna duplicazione della #5, nessuna perdita Windows o modifica applicativa inattesa.
- [ ] Se ancestry non coincide per squash/rebase della #5, analizzare il
  contenuto residuo; nessun riallineamento o riscrittura automatica.
- [ ] Ottenere nuovi `windows-tests` **e** `macos-tests` SUCCESS sulla combinazione
  head/base nuova. Un retarget non garantisce da solo un nuovo run: se manca,
  STOP e richiesta di un percorso CI autorizzato, senza riusare il vecchio verde.
- [ ] Ripetere gate comune e controlli della sezione 3, inclusi review e thread.
- [ ] Responsabile decide integrazione; dopo l'eventuale azione verificare nuovo
  main, contenuto finale, policy e corrispondenza con le prove raccolte.

La catena è chiusa solo con evidenze finali coerenti, decisioni registrate e
policy verificata. Una release applicativa è un gate separato: non deriva
automaticamente dall'integrazione delle due PR CI o di questo documento.

## 7. Protezioni consigliate, da approvare dal proprietario

Questa è una proposta, non una configurazione già applicata. Valutare su main:

- [ ] Required status checks con nomi reali: `windows-tests` per la fase #5;
  aggiungere `macos-tests` quando la fase #6 lo rende disponibile per le PR pertinenti.
- [ ] Verificare origine del check (GitHub Actions), unicità dei nomi e assenza
  di regole che richiedano job inesistenti o non attivati dai trigger.
- [ ] Review obbligatoria da persona autorizzata, risoluzione conversazioni e
  rivalutazione delle approvazioni dopo nuovi commit o variazioni sostanziali di base.
- [ ] Blocco force-push e cancellazione main; definire e limitare eventuali bypass.
- [ ] Definire come mantenere le PR aggiornate rispetto alla base e ricontrollare
  CI dopo aggiornamenti. Valutare costi e modalità senza imporre riscritture automatiche.
- [ ] Se si propone una merge queue, prima verificare supporto `merge_group`:
  il workflow attuale non lo dichiara. Non attivarla presumendo questa copertura.
- [ ] Rileggere la policy effettiva dopo ogni modifica autorizzata; una policy
  proposta, un salvataggio UI o un elenco di check verdi non attestano enforcement.

Fonte di riferimento: [GitHub, protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
Configurazione e decisione su review/bypass/required checks restano al proprietario.

## 8. Workflow manuale

`workflow_dispatch` richiede che il workflow sia presente nel branch predefinito
e sia configurato per quell'evento. Main osservata non contiene ancora il file;
il suo elenco come workflow active dopo run PR non basta. Fonte:
[GitHub, manual run](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

- [ ] Solo dopo disponibilità sul default branch e autorizzazione specifica,
  valutare un run manuale con ref/SHA fissati e registrati.
- [ ] Non considerarlo sostitutivo di una prova PR head/base diversa: il controllo
  whitespace manuale attuale riguarda l'ultimo commit, non l'intero delta PR.
- [ ] Se non autorizzato o non disponibile: NON VERIFICATO/BLOCKED, non avviare run.

## 9. Dipendenze applicative e release successive

Secondo i report Notion assegnati, Persona 2 ha ancora il task paginazione
ordini Alpaca e Persona 3 la specifica d'integrazione Strategy Engine; non
risultano dichiarati completati nei report letti. Persona 1 è gestita dal
responsabile. Questo documento non assegna o duplica il lavoro di nessuno.

- [ ] Per future integrazioni applicative, attendere contratti, commit, report e
  limiti verificati delle parti interessate; leggere [backend](../BACKEND_HANDOFF.md),
  [dashboard](../DASHBOARD_HANDOFF.md) e [strategia](../STRATEGY_HANDOFF.md).
- [ ] Rivedere la matrice per la release candidata allo SHA esatto, con prove
  separate di OS/UX/contabilità e perimetro. Non promuovere mock a dati operativi.
- [ ] Confermare isolamento capitali e ledger Demo/Simulazione/Paper, default
  disabilitato, rischio/coordinatore/gate e assenza di retry ambiguo o invii duplicati.
- [ ] Nessuna prova di questa procedura legge credenziali, connette broker/feed,
  invia ordini o attiva automazione. Integrazioni autentiche richiedono incarico separato.
- [ ] Il responsabile decide quali evidenze mancano per la release richiesta;
  un ambito indispensabile NON VERIFICATO/BLOCKED impedisce quella release.

## 10. STOP e registrazione della decisione

Fermarsi, registrare causa/fonte/SHA e non correggere automaticamente se:

- base/head o SHA diversi dallo snapshot autorizzato, fonte Git/GitHub discordante;
- check mancante, fallito, annullato, in corso, obsoleto o su combinazione diversa;
- review approvata assente/non aggiornata, richiesta di modifica o thread da risolvere;
- diff/commit fuori scope, conflitti o lavoro altrui non riconciliato;
- guard rete/credenziali non zero o mancante, skip immotivato o incompatibilità OS;
- segreto esposto, lettura credenziale o test che contatta broker/feed o invia ordini;
- impossibilità di verificare policy o prerequisiti indispensabili alla decisione.

Non usare reset, clean, rebase, force-push, deroghe ai test o abbassamento dei
limiti per sbloccare un gate. Un segreto non va riportato nel report: indicare
solo fonte e contesto redatti e coinvolgere il responsabile.

Scheda da compilare, senza dati personali o log integrali:

| Campo | Valore da registrare al momento della decisione |
| --- | --- |
| Operatore autorizzato, data UTC/fuso | Da compilare |
| Scopo e azione autorizzata | Da compilare, distinta da trading/release/deploy |
| PR, base SHA, head SHA, checkout testato | Da compilare |
| Run/attempt e job Windows/macOS | URL, conclusioni, guard, pass/fail/skip/warning |
| Review, thread, policy effettiva | Fonte ed evidenza, oppure NON VERIFICATO |
| Gate tecnico / disponibilità / release | PASS, FAIL, BLOCKED o NON VERIFICATO con motivo |
| Decisione e prossimo passo | Responsabile, ambito e condizioni; nessuna approvazione implicita |

Alla verifica iniziale: CI #5/#6 PASS agli SHA osservati; integrazione/release
BLOCKED per draft/review e decisioni del responsabile pendenti. Il controllo
delle fonti non costituisce review approvata o autorizzazione a cambiare policy.
