# OMEGA: provider configuration and paper research console

Source repository: https://github.com/foffo09/AITradingBot.

The default console uses **real market data and an isolated local paper account**. A separate native Hyperliquid TESTNET runner now implements broker reconciliation, fills, protection and panic: see [HYPERLIQUID_TESTNET.md](HYPERLIQUID_TESTNET.md). It does not change the dashboard ledger. Missing credentials do not select synthetic data and do not terminate other markets. The original synthetic replay remains explicitly selectable with `OMEGA_DATA_MODE=synthetic`.

## Start

Python 3.11+ on macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-omega.txt
cp .env.example .env  # only when .env does not already exist
chmod 600 .env
.venv/bin/python main.py
```

Open http://127.0.0.1:8765. The server binds loopback only and starts with new entries paused. `--tui` adds Rich terminal controls and live telemetry; `1`–`5` select profiles, `m` toggles split, `s` arms paper entries, `p` pauses new entries, `!` requests panic flatten, and `q` leaves the TUI. Ctrl+C stops the server. Edit `.env` locally and restart to apply provider changes. Existing `.env` files are preserved; process environment variables take precedence.

The generated `.env.example` documents every provider setting. Secret-bearing values must be injected through the process environment, not saved in `.env`. The provider loader now ignores secret fields from files; the new native testnet runner never loads dotenv. Credentials, wallet keys and RPC URLs containing keys use `SecretStr`; they are not sent to the UI, included in AI prompts, or written to the order journal. HTTP debug logging is suppressed. Yahoo caches live in the project's ignored `config/feed_cache/` directory.

## Providers and fallback

| Profile | Configured routes | Credential-free behaviour |
| --- | --- | --- |
| Crypto perpetuals | Native Hyperliquid REST/candles/L2 WebSocket; CCXT Pro Binance and Bybit | Public Hyperliquid first by default, then the other venues on failure. Mainnet/testnet data is selected independently from execution. |
| Solana token monitoring | Custom RPC, Helius, QuickNode, public Solana RPC; DexScreener prices; Jupiter quote/unsigned swap builder | Public RPC account subscription and DexScreener REST snapshots. No timestamp is invented when DexScreener omits one; such prices cannot authorize automatic entries. |
| Options 0DTE | Alpaca indicative quote stream (MsgPack), IB/TWS contract resolution, Polygon aggregates, Yahoo | With no exact option contract, SPY is shown as an underlying **proxy**, never treated as an option premium. Exact OCC symbol goes in `OPTIONS_SYMBOL`. |
| Commodities futures | IB dated futures contract; Yahoo continuous futures fallback | `CL=F` by default, marked as a continuous-series **proxy** and ineligible for contract execution. IB requires symbol, expiry and exchange. |
| Biotech equity | Alpaca IEX, IB, Polygon, Finnhub, Yahoo | Yahoo history and public WebSocket, with REST history polling retained when WebSocket delivery is unavailable. Default watch symbol is MRNA; change it in `.env`. |
| News | Finnhub company news when keyed; Yahoo headlines otherwise | Headlines are displayed as provider news, not verified FDA approvals, SEC filings or automatic trade catalysts. |
| AI | OpenAI SDK, Anthropic SDK, Ollama local HTTP | `auto` selects an available configured provider; absent/failed providers fall back to deterministic bounded MA parameter generation. |

One worker per market owns its provider chain, reconnects with bounded exponential backoff and catches provider failures independently. History and quote schemas reject invalid prices, timestamps and crossed books. Older messages cannot overwrite newer quotes. Yahoo protobuf numeric-string timestamps and Alpaca option MsgPack frames are handled explicitly.

The UI displays provider, transport, symbol, quality and timestamp freshness. HTTP snapshots, delayed data and missing entitlements are not advertised as guaranteed real-time WebSockets. Public services can throttle, reject access, delay prices or be closed; a free real-time feed for every listed contract does not exist under these providers' documented access models.

## Paper execution and research gates

`core/live_runtime.py` connects providers to the existing router, ingestor, coder, sandbox, risk module and control box. `core/runtime.py` retains the offline synthetic replay. Live paper state is stored in `config/paper_live_state.json`; synthetic state remains in `config/live_state.json`. No migration or reset of the older paper/demo ledger is performed.

The dashboard executes against its **local paper ledger**. It does not automatically route fills to Alpaca, IB or an exchange, even if credentials are present. Restored positions are monitored only against their original provider and symbol. A fallback onto a different instrument cannot reprice or close an existing position. Stale/missing quotes block entries. Panic immediately disables entries and persists the lock; exits lacking fresh original quotes remain pending and complete after those quotes return, rather than claiming fabricated fills.

Three switch policies, a shared bankroll, equal split budgets, fractional Kelly (default Half-Kelly), per-profile allocation caps, sampled stops, partial meme take profit, options time stop and persistent daily-loss lock remain active. Stop prices use simulated entry fills. The fill ledger records quantities, reference/fill prices, commissions, reasons, position IDs and net PnL; partial exits reconcile to account equity. Positions and fills also retain provider/instrument identity.

Training ranks bounded MA parameter candidates on the first 60% of available history; training statistics determine Kelly inputs. The selected candidate is tested on the chronological remaining 40% through the same Vanguard stop/cost/partial-exit policy. Promotion requires Sharpe >=2, unrounded drawdown <=8%, profit factor >=1.6, a positive payoff estimate and at least ten closed trades. Missing/undefined metrics reject. Changing Kelly pauses entries and revalidates available history. Live histories use source timestamps for holding periods and daily reference changes; synthetic playback advances one simulated second per candle.

Minute-bar annualization is 365*1440 for crypto and 252*390 for TradFi; it assumes regular sampling. Costs remain explicit estimates of 5 bps commission plus 5 bps half spread plus 5 bps slippage per side. This model has **no leveraged derivatives collateral, funding payments, option expiry settlement, contract multipliers or realistic intrabar stop fills**. Sandbox acceptance is a local research screen and cannot validate production execution economics. Proxy feeds remain monitoring-only even if the numerical MA screen passes.

## Native execution transports

`execution/providers.py` provides prepared limit-order transports for Hyperliquid, CCXT Binance/Bybit, Alpaca Paper/Live, and IB/TWS. They are separate from the automatic local-paper runtime. `OMEGA_ENABLE_NATIVE_ORDERS=false` and `OMEGA_ENABLE_LIVE_ORDERS=false` are the defaults. Missing venue credentials leave the dashboard in local paper. Funded/mainnet native submissions are now prohibited even when a legacy live flag is true. The old one-shot Hyperliquid writer is disabled in favour of the reconciled testnet engine. IB verifies the configured managed account; paper detection conservatively requires a DU account. Paper/testnet accounts, balances, exchange access and TWS login must already exist.

The native API accepts validated `OrderIntent` objects: a fresh quote timestamp, venue, market, symbol, direction, quantity, limit price and stable client order ID. Futures/options quantities must be integral. Unsupported venue/asset combinations are rejected before submission. A persistent SQLite reservation is committed before any order write. Ambiguous write failures are not retried automatically, and reusing an ID is blocked until reconciled at the venue. An acknowledgement is never labelled a fill. The legacy transports remain separate from the local ledger. The new dedicated Hyperliquid TESTNET engine under `src/trading/native_engine.py` adds native risk sizing, fill de-duplication, pending-order reconciliation, native stops, partial exit targets and panic. It uses a separate journal and does not support mainnet.

Jupiter builds unsigned swap transactions and does not sign or broadcast them. The configurable base defaults to the documented `https://api.jup.ag/swap/v1` schema; compatible legacy v6 gateways can be supplied explicitly. The current public host requires `JUPITER_API_KEY`. DexScreener remains available without that key. Mint/freeze authority and token-account concentration checks are separate from LP-lock, beneficial-holder concentration and honeypot verification; the latter are not inferred and automatic swaps remain ineligible.

## AI boundary

OpenAI uses `AsyncOpenAI.responses.create`, Anthropic uses `AsyncAnthropic.messages.create`, and Ollama uses `/api/chat` with a JSON schema and non-streaming response. Only the profile name and observed return volatility are sent. Model names are configurable; no model is downloaded automatically. Cloud keys and Ollama models are not provisioned by this project.

Providers propose one to three integer MA window pairs. Pydantic validates the response, then the existing coder writes its bounded `BaseStrategy` source and validates its AST. Generated Python is parsed into trusted parameters rather than imported or executed. This is a bounded strategy-parameter agent, not arbitrary autonomous Python self-modification or a complete set of specialized market strategies.

## Verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Generated verification reports remain local and are excluded from Git. Run the commands above to obtain current results. Tests cover dashboard behaviour plus credential absence, per-market failover, timeout/backoff, secret redaction, public Solana fallback, unsigned Jupiter swaps, CCXT sandbox ordering, OpenAI/Anthropic/Ollama interfaces, native-order guards and persistent duplicate prevention, stale-position panic handling and out-of-order quote rejection. Authenticated/native writes are tested with mocks; no funded or testnet order is sent as part of verification.

## Primary documentation

- Hyperliquid WebSocket: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
- CCXT Pro and sandbox configuration: https://docs.ccxt.com/docs/pro-manual
- Solana RPC: https://solana.com/docs/rpc
- DexScreener REST reference: https://docs.dexscreener.com/api/reference
- Jupiter quote and unsigned swap: https://developers.jup.ag/docs/api-reference/swap/v1/quote
- Alpaca feed access: https://docs.alpaca.markets/us/docs/about-market-data-api
- Alpaca option MsgPack stream: https://docs.alpaca.markets/us/docs/real-time-option-data
- IB API: https://ib-insync.readthedocs.io/api.html
- yfinance public WebSockets: https://ranaroussi.github.io/yfinance/reference/yfinance.websocket.html
- OpenAI SDK: https://developers.openai.com/api/reference/python
- Anthropic SDK: https://github.com/anthropics/anthropic-sdk-python
- Ollama chat API: https://docs.ollama.com/api/chat
