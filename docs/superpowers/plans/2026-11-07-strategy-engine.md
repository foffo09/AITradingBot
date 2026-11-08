# Strategy Engine Implementation Plan

Goal: segnali puri Paper, BUY/SELL/WAIT con livelli e rischio verificabili,
senza inviare ordini e senza modificare dashboard/backend.
Architecture: strategie causali compatibili con generate_signals; gate unico
select_completed_bars; livelli ATR/struttura condivisi; rischio delegato al
RiskManager esistente e limiti globali aggiuntivi prudenziali. Backtest esteso
in modo opzionale, default SMA invariato. Nessuna nuova dipendenza.
Tech stack: Python/pandas, dataclass, pytest, engine/walk-forward esistenti.

Base: branch remoto strategy 67f6a47 aggiornato fast-forward a 432ecdd,
contenente backend 1a68d5b e dashboard. Worktree AITradingBot-strategy.
Esecuzione autonoma richiesta: nessuna approvazione intermedia.

- [x] EMA9/21, trend50; RSI14 e volume diagnostici, ATR14 per livelli.
  MACD escluso per ridondanza; SMA esistente riutilizzabile. Test causali.
- [x] src/strategy/levels.py: LevelConfig + plan_levels(data, side, entry,
  spread=0, config=LevelConfig()) -> dict entry/stop_loss/take_profit/
  stop_distance/target_distance/reward_risk/atr. ATR semplice true range
  trailing14, supporto/resistenza trailing10, min stop 3 spread. Errori ValueError.
- [x] src/strategy/engine.py: StrategyEngine(settings, config), evaluate
  con snapshot rischio Paper esplicito, quote/fonte/time/expiry/dedup.
  SignalProposal serializzabile per dashboard, qualità non probabilistica.
  SELL riduce soltanto un long; livelli bearish analitici, nessuno short.
- [x] Riusare RiskManager per cap/size/daily loss; controllare esposizione
  globale, drawdown, conteggio giornaliero, costi e capitale mancante.
- [x] BacktestEngine.run: strategia opzionale e protezione ATR opzionale,
  default invariato. Next open, stop conservativo se TP/SL nella stessa
  barra, gap e costi distinti. Nessuna lettura di barre future nei livelli.
- [x] Test red/green su gate reale, quote, origine, livelli, rischio, dedup,
  scadenza e prefissi causali. Test OOS separati da training/validation.
- [x] Suite completa, gruppi strategia/rischio/backtest/backend/sicurezza,
  compileall, pip check, diff-check, review. Documentare esempi sintetici,
  nessuna pretesa di validazione statistica o profitto su mercati autentici.
- [x] STRATEGY_HANDOFF, guide, matrice e worklog. Commit/push solo strategy.

Limiti espliciti: nessun hook automatico nel runner o UI senza accordo; contratto
pronto per integrazione, non nuovi invii. Nessuna credenziale/DB personale,
server, ordine o automazione. Windows e broker autentici non verificati.
