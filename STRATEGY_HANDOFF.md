# Persona 3 — Strategy engine e integrazione

## Base e ambito

Worktree `AITradingBot-strategy`, branch `feature/strategy-engine`.
Branch remoto iniziale 67f6a47 aggiornato fast-forward a dashboard
432ecdd7d9e997dcd4efdef3b55880caee51d493, contenente backend
1a68d5bbc25f3e1b6eceb0235f9ea2fdfa033240. Nessun merge su main.
Contratti letti: BACKEND_HANDOFF.md e DASHBOARD_HANDOFF.md.

Il nuovo motore genera proposte pure. Non importa broker, non apre file, non
registra log, non invia ordini e non abilita automazioni. Non modifica dashboard,
backend o runner Paper. L'integrazione automatica resta esplicita e separata.

## Architettura e strategie

- `src/strategy/trend.py`: EMACrossoverStrategy, EMA9/21 con filtro EMA50;
  generate_signals conserva frame/metadati e il contratto SMA esistente.
- `src/strategy/moving_average.py`: SMA preesistente riutilizzata, invariata.
- `src/strategy/levels.py`: LevelConfig e plan_levels, livelli causali da un
  prefisso storico fornito, nessun ordine protettivo.
- `src/risk/trade_plan.py`: RiskSnapshot/RiskPolicy e dimensionamento che usa
  il RiskManager esistente e aggiunge budget monetario, esposizione globale,
  drawdown e conteggio delle operazioni.
- `src/strategy/engine.py`: StrategyConfig, SignalProposal e StrategyEngine.
- `src/backtesting/engine.py`: simulatore esistente, con strategy e protection
  opzionali. Default SMA e costi restano compatibili.
- `src/backtesting/walk_forward.py`: walk-forward SMA invariato; nuova
  evaluate_strategy_partitions per strategia fissa su tre tranche indipendenti.

BUY: incrocio EMA breve sopra la lunga e close sopra EMA di trend. SELL: incrocio
opposto e close sotto il trend. WAIT durante warm-up, assenza di un nuovo
incrocio o fallimento di qualsiasi controllo. I valori SMA/EMA sono causali,
mai centrati o calcolati usando barre future. Niente segnali continui mentre
le medie restano sullo stesso lato.

RSI14 e volume relativo sono diagnostici, non ulteriori filtri combinati.
RSI usa ewm(alpha=1/14, adjust=False), inizializzazione dalla prima variazione
osservata e warm-up di 14 variazioni; non la seed SMA del Wilder classico.
Volume relativo = volume/media trailing20; media zero produce N/D. MACD non
aggiunto: ridondante rispetto alla scelta di trend/crossover, non validato.

## Gate, quote e contesto Paper

`evaluate(data, quote, *, symbol, interval, now, account, prior_signal_ids=())`
richiede impostazioni Paper esplicite. Non legge .env. Il simbolo deve essere
nel catalogo esistente; XAU/USD non viene inventato o assimilato a GLD.

La prima selezione è `select_completed_bars` con controllo operativo predefinito
require_market_open=True. Non viene replicato calendario, chiusura, cutoff o
freschezza delle barre. Metadati originali restano nella proposta. Fonti e
colonna data_quality devono coincidere con il contratto backend per quel mercato.
Barre sintetiche, provenienza mancante/contraddittoria, contratti o sessioni
non verificati, weekly/daily non supportati restano NO_TRADE secondo il gate.

Le quote ricevute sono rilette secondo il contratto backend: bid/ask finiti,
positivi e ordinati, midpoint coerente, fonte IEX o Crypto corretta, timestamp
UTC aware ed età 0..120 secondi. Flag sintetici o quality esplicitamente non reale nella quote sono rifiutati
anche se la stringa source dichiara Alpaca. Nessuna sostituzione col close storico.
Il caller deve associare risposta, simbolo e intervallo della stessa richiesta,
anche nelle cache: il payload Alpaca quote non contiene il simbolo.

## Entry, livelli, scadenza e duplicati

Entry BUY = ask, SELL = bid, **prezzi di riferimento**, non fill garantiti.
Reference_price = close dell'ultima barra selezionata, distinto dall'entry.
ATR14 è la media semplice trailing14 dei true range, richiede almeno 15 barre.
Supporto/resistenza = min low/max high delle ultime 10 barre completate.

Distanza minima stop = max(1,5 ATR, 3 spread). BUY SL è il min fra entry meno
questa distanza e supporto meno 0,1 ATR. SELL SL è il max simmetrico sopra
entry/resistenza. Target iniziale 2R, limitato dalla struttura se esiste un
ostacolo fra entry e target. Se il rapporto scende sotto 1,5R, NO_TRADE.
Tutti i prezzi/distanze devono essere positivi e finiti:
BUY SL < entry < TP; SELL TP < entry < SL. Nessun livello se ATR/dati mancano.

**SELL riduce soltanto un long posseduto.** TP sotto entry e SL sopra entry
sono livelli dello scenario ribassista/invalidation dell'analisi, non una
posizione short né un bracket applicato al long residuo. Non attaccarli come
protezione long. Le vere uscite TP/SL del long nel backtest usano i suoi livelli
BUY originari. Questo branch non installa ordini TP/SL nativi presso Alpaca.

Scadenza = min(chiusura barra + TTL configurata, timestamp quote + 120s).
Una nuova quote non rinnova l'evento oltre la sua TTL. is_expired(now) vale
True al raggiungimento della scadenza. Invalidation_conditions elenca le
condizioni che il consumer deve rivalidare; non è un monitor broker attivo.

Signal_id SHA256 lega conto, simbolo, intervallo, lato e chiusura barra. Cambiare parametri/rischio
non rinnova lo stesso evento già consumato. Il caller deve persistere gli ID consumati e ripassarli dopo
un riavvio. Il motore è stateless: da solo non crea un archivio di deduplica.
Questo meccanismo non sostituisce client_order_id, journal e coordinatore.

## Rischio e configurazione

RiskSnapshot richiede account_id, observed_at, equity, cash, esposizione globale,
P/L giornaliero, peak_equity verificata, orders_today (comprende tentativi già
prenotati/ordini pendenti), positions_count e position_quantity associata a
**position_symbol**. verified deve essere True e scope paper; timestamp entro
45 secondi. Nessun dato mancante diventa zero. Simboli backend senza slash
vanno normalizzati mediante il catalogo dal consumer, senza inventare alias.

Il backend REST non fornisce una peak_equity storica verificata né garantisce
snapshot atomici: il consumer deve ottenere questi dati da contabilità Paper
verificata. Se mancano, non costruire valori fittizi: il motore resta NO_TRADE.

RiskPolicy default: rischio massimo stop/costi 0,5%, drawdown massimo 10%,
5 operazioni/giorno. Valgono anche i limiti esistenti AppSettings (trade,
esposizione, perdita giornaliera, posizioni e ordini/giorno). I cap usano il
minimo fra equity e capitale configurato, senza aumentarli dopo guadagni o perdite.
Budget = capitale prudenziale * risk_fraction. Il rischio unitario aggiunge a
stop_distance costi roundtrip prudenziali e spread; size viene ulteriormente
limitata da cash, cap notional, esposizione globale e quantità long posseduta.
Rapporto netto dopo costi deve restare almeno min_reward_risk. Quantità proposta
troncata a 8 decimali: incrementi/minimi asset restano da validare all'esecuzione.
Nessuna martingala. Se un controllo fallisce, WAIT/NO_TRADE con motivazione.

StrategyConfig espone strategia ema/sma, short_window=9, long_window=21,
trend_window=50, signal_ttl_seconds=180, LevelConfig e RiskPolicy.
LevelConfig espone atr_period=14, atr_multiple=1.5, reward_risk=2,
min_reward_risk=1.5, structure_window=10, min_spread_multiple=3.
Impostazioni non valide vengono rifiutate, non corrette automaticamente.

## Contratto per Persona 2 / dashboard

```python
from src.strategy.engine import StrategyEngine, StrategyConfig
from src.risk.trade_plan import RiskSnapshot
# settings, bars, quote e snapshot sono forniti dal contesto Paper verificato.
proposal = StrategyEngine(settings, StrategyConfig()).evaluate(
    bars, quote, symbol=symbol, interval=interval, now=decision_time,
    account=verified_risk_snapshot, prior_signal_ids=consumed_signal_ids)
view = proposal.to_dict()
```

Campi JSON: direction BUY/SELL/WAIT, symbol, validation_state PAPER_PROPOSAL o
NO_TRADE, reason, signal_id, timestamp, expires_at, reference_price, entry,
entry_type, stop_loss, take_profit, stop_distance, target_distance, reward_risk,
net_reward_risk, quantity, risk_amount, provenance (bars attrs + quote intera),
indicators (EMA/SMA, RSI, volume relativo, ATR), invalidation_conditions.
quality=uncalibrated_rules: **non è una probabilità di successo**.
Campi indisponibili e numeri non finiti di input rifiutati sono None/N/D nella
serializzazione JSON; i metadati validi restano invariati. Una proposta validata non concede permessi.

app.py non viene modificato: mostra ancora il proprio riepilogo SMA. Il runner
preesistente e il selettore walk-forward restano invariati; SELECTED è proposta
analitica, non una validazione di questa nuova strategia. Prima di collegare
view alla UI o al trading concordare il consumer; mai chiamare submit_order
come conseguenza automatica del rendering. Non convertire un SELL analitico
in short o applicare i suoi livelli a una posizione long.

## Backtest e separazione temporale

BacktestEngine.run(data, strategy=EMACrossoverStrategy(), protection=LevelConfig())
riusa l'engine long-only. Segnale barra i-1, fill open barra i; livelli dal
prefisso precedente, intorno al **market open**, mentre il motore proposte usa
ask/bid corrente. Non sono lo stesso prezzo garantito. Costi commissioni,
spread e slippage distinti; entry e uscita li addebitano una volta per lato.

Stop/target fissi per il trade. Stop colpito in gap: open peggiore; target
superato in gap: prezzo target senza miglioramento garantito. Nella stessa
barra stop e target, stop vince. Un SELL discrezionale all'open precede i
successivi eventi intrabar; le protezioni vengono controllate anche nella
barra d'ingresso. OHLC non ricostruisce la sequenza reale degli scambi.
Dati OHLC o livelli non validi fanno fallire il replay esplicitamente; la
protezione non viene mai disattivata silenziosamente per proseguire.

Win rate, profit factor (None senza perdite), expectancy netta, drawdown,
numero operazioni, ritorno netto e R medio realizzato sono calcolati. R medio
usa P/L netto diviso rischio iniziale a mercato per le sole operazioni chiuse.
Equity include posizioni aperte e costi stimati di liquidazione; net_pnl dei
trade chiusi non deve essere confuso con il rendimento totale dell'equity.
Dimensionamento backtest preesistente per cap notional: non replica integralmente
il nuovo RiskSnapshot multi-asset/budget stop. Nessuna equivalenza di performance
con l'esecuzione della nuova proposta viene dichiarata.

`evaluate_strategy_partitions` richiede timestamp e closed_at UTC-aware per
barra, con intervalli non sovrapposti. Esclude closed_at > as_of e divide tre
tranche contigue disgiunte: training_bars, validation_bars, resto OOS. Ogni
tranche riparte con capitale/indicatori propri e deve avere warm-up sufficiente.
Il feed deve attestare closed_at: non viene inventata la chiusura dal timestamp.
Nessuna ottimizzazione in questo helper; parametri fissati prima del replay.
L'ottimizzazione SMA esistente usa training e fold OOS separati. Per scegliere
parametri EMA futuri usare training/validation e non ritoccarli sull'OOS.

## Prove e limiti

Tutti i test usano dati controllati, broker fittizi e database temporanei;
nessun server, ordine, automazione, credenziale o DB personale aperti.
Test: test_trend_strategy, test_trade_levels, test_strategy_risk,
test_strategy_engine, test_strategy_backtest, test_strategy_partitions più
suite esistenti. Casi BUY/SELL/WAIT, gate reale, simboli, source, prezzi, quote
vecchie, livelli invalidi, snapshot non verificati, replay/expiry, prefissi
causali, stop/target/gap/costi, separazione OOS e nessun submit.
Risultati delle esecuzioni nel WORKLOG e nell'esempio sintetico sottostante.

Windows, broker autentico, slippage reale, redditività e robustezza statistica
non verificati. Nessun corto, leva, trailing broker o protezione nativa aggiunta.
Le condizioni di invalidazione vanno rivalidate dal consumer continuamente.
Serve il successivo lavoro di integrazione UI/runner e contabilità Paper
verificata; non attivare l'automazione da questo handoff.

## Replay sintetico eseguito, non validazione di mercato

720 barre da 1 minuto; close=100+4*sin(i/8)+0.002*i, open=close precedente,
high=max(open,close)+0.4, low=min(open,close)-0.4, volume=1000. Timestamp dal
2026-10-01 UTC, closed_at=start+1 minuto. Tre tranche da 240 barre, EMA9/21/50
fissate prima della prova, 10.000 USD iniziali per tranche, notional massimo
20%, commissione 5bps, spread 2bps e slippage 5bps. Nessun feed interrogato.

Risultati osservati **senza protezione ATR e senza RiskSnapshot multi-asset**:

| Tranche | Trade chiusi | P/L chiuso USD | Ritorno equity % | Max DD % | Expectancy USD/trade |
| --- | ---: | ---: | ---: | ---: | ---: |
| Training | 3 | 51.4486 | 0.5145 | 0.72 | 17.1495 |
| Validation | 4 | 80.3066 | 0.8031 | 0.72 | 20.0766 |
| OOS | 3 | 54.1834 | 1.3197 | 0.72 | 18.0611 |

Win rate del toy replay 100% in tutte le tranche; profit factor N/D perché
nessuna perdita chiusa, R N/D senza stop. Il ritorno equity OOS include una
posizione ancora aperta, quindi non equivale al solo P/L chiuso.
Questa sinusoide non è evidenza di redditività né calibrazione statistica.
Ripetendo **con LevelConfig predefinita**, il replay è bloccato da
`Insufficient reward/risk before market structure.`: nessun risultato protetto
viene dichiarato. I test separati verificano il funzionamento TP/SL con fixture
in cui livelli e rapporto sono validi. Non ottimizzare livelli per rendere
positivo o far completare questo toy replay.

Per riprodurre il dataset, usare numpy.arange(720), la formula sopra e
EMACrossoverStrategy() in evaluate_strategy_partitions con training_bars=240,
validation_bars=240, as_of=ultimo closed_at e data_source esplicitamente
sintetica. Provare protection=None e poi protection=LevelConfig().

## Integrazione generale successiva

1. Integrare feature/strategy-engine in un branch di prova del coordinatore;
   backend e dashboard indicati sono già antenati. Nessun merge diretto su main.
2. Eseguire i comandi sotto su Windows prima di attivare qualsiasi consumer.
3. Procurare snapshot Paper verificati e contabilità necessaria, con simboli e
   contatori espliciti. N/D implica NO_TRADE, non valori iniziali inventati.
4. Collegare la sola serializzazione del contratto alla dashboard; mantenerla
   distinta dalla decisione di invio. Persistenza degli ID consumati a carico
   del consumer, con account/scopo separati.
5. L'eventuale futuro adattamento al runner deve mantenere gate, quote, rischio,
   incrementi asset, client order ID e coordinatore, con rivalidazione finale.
   Nessun collegamento automatico o protezione broker autentica verificati qui.

```text
python -m compileall -q app.py config src tests
python -m pytest -q tests/test_strategy_engine.py tests/test_trend_strategy.py tests/test_trade_levels.py tests/test_strategy_risk.py tests/test_strategy_backtest.py tests/test_strategy_partitions.py tests/test_strategy.py tests/test_risk_manager.py tests/test_backtesting.py tests/test_backtest_execution.py tests/test_walk_forward.py
python -m pytest -q tests/test_backend_contract.py tests/test_backend_integration.py tests/test_broker.py tests/test_config.py tests/test_fx_rates.py tests/test_bar_timing.py
python -m pytest -q tests/test_paper_safety.py tests/test_paper_coordinator.py tests/test_native_store.py tests/test_test_isolation.py
python -m pytest -q
python -m pip check
git diff --check
```

Comandi equivalenti in PowerShell o shell Mac usando python dell'ambiente
virtuale attivo; nessun comando richiede credenziali o accesso al broker.

Esito finale osservato su macOS/Python3.12.14: **747 passati, 1 saltato,
0 falliti**; gruppo strategia/rischio/backtest232, backend172, sicurezza39
con1 skip. Compilazione, pip check e diff-check riusciti. Guard rete/credenziali
zero;146 casi nuovi senza modificare test preesistenti. Skip Windows Proactor,
warning preesistente websockets.legacy. Windows e broker autentico non provati.
