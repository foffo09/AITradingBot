from __future__ import annotations

INSTRUMENTS = {
    "SPY": {"name": "SPDR S&P 500 ETF", "description": "ETF che segue l'indice S&P 500.", "kind": "equity"},
    "QQQ": {"name": "Invesco QQQ Trust", "description": "ETF collegato al Nasdaq-100.", "kind": "equity"},
    "GLD": {"name": "SPDR Gold Shares", "description": "ETF collegato al prezzo dell'oro.", "kind": "equity"},
    "AAPL": {"name": "Apple Inc.", "description": "Azione individuale Apple.", "kind": "equity"},
    "MSFT": {"name": "Microsoft Corp.", "description": "Azione individuale Microsoft.", "kind": "equity"},
    "NVDA": {"name": "NVIDIA Corp.", "description": "Azione individuale NVIDIA.", "kind": "equity"},
    "BTC/USD": {"name": "Bitcoin / US Dollar", "description": "Criptovaluta; disponibilità e negoziabilità da verificare.", "kind": "crypto"},
    "ETH/USD": {"name": "Ethereum / US Dollar", "description": "Criptovaluta; disponibilità e negoziabilità da verificare.", "kind": "crypto"},
}

EQUITY_SYMBOLS = tuple(symbol for symbol, info in INSTRUMENTS.items() if info["kind"] == "equity")
CRYPTO_SYMBOLS = tuple(symbol for symbol, info in INSTRUMENTS.items() if info["kind"] == "crypto")
