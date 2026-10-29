from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pandas as pd
from websockets.asyncio.client import connect

from config.providers import ProviderSettings
from providers.common import HistorySink, Quote, QuoteSink, frame_from_rows, request


class HyperliquidData:
    name = "hyperliquid"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self.settings, self.client = settings, client
        suffix = "-testnet" if settings.crypto_data_network == "testnet" else ""
        self.base = f"https://api.hyperliquid{suffix}.xyz"
        self.ws = self.base.replace("https://", "wss://") + "/ws"

    @staticmethod
    def parse_book(data: dict[str, Any]) -> Quote:
        bids, asks = [[(float(level["px"]), float(level["sz"])) for level in side] for side in data["levels"]]
        if not bids or not asks:
            raise ValueError("Empty order book")
        bid_size, ask_size = sum(q for _, q in bids), sum(q for _, q in asks)
        return Quote(provider="hyperliquid", symbol=data["coin"], price=(bids[0][0] + asks[0][0]) / 2,
                     bid=bids[0][0], ask=asks[0][0], source_time=timestamp_ms(data["time"]),
                     transport="websocket", quality="realtime", instrument="perpetual", bids=bids, asks=asks,
                     imbalance=(bid_size - ask_size) / (bid_size + ask_size) if bid_size + ask_size else 0)

    async def history(self) -> pd.DataFrame:
        now = int(time.time() * 1000)
        values = await request(self.client, "POST", self.base + "/info", json={
            "type": "candleSnapshot", "req": {"coin": self.settings.hyperliquid_coin, "interval": "1m",
                                              "startTime": now - 1500 * 60000, "endTime": now}})
        rows = [[bar["t"], bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]] for bar in values if bar["T"] < now]
        return frame_from_rows(rows, self.settings.hyperliquid_coin)

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        coin = self.settings.hyperliquid_coin
        await history(await self.history(), self.name, coin)
        async with connect(self.ws, open_timeout=8, ping_interval=20, max_size=2**20) as ws:
            for subscription in ({"type": "l2Book", "coin": coin}, {"type": "candle", "coin": coin, "interval": "1m"}):
                await ws.send(json.dumps({"method": "subscribe", "subscription": subscription}))
            last_history = time.monotonic()
            while True:
                payload = json.loads(await asyncio.wait_for(ws.recv(), 35))
                if payload.get("channel") == "l2Book":
                    await sink(self.parse_book(payload["data"]))
                if time.monotonic() - last_history >= 60:
                    await history(await self.history(), self.name, coin)
                    last_history = time.monotonic()


def timestamp_ms(value: Any) -> float:
    return float(value) / 1000


class CCXTData:
    def __init__(self, venue: str, settings: ProviderSettings) -> None:
        self.name, self.settings = venue, settings

    def client(self, *, execution: bool = False):
        if execution and self.settings.crypto_execution_network != "testnet":
            raise ValueError("Mainnet execution is prohibited")
        import ccxt.pro as ccxtpro
        options: dict[str, Any] = {"enableRateLimit": True, "timeout": int(self.settings.request_timeout_seconds * 1000),
                                   "options": {"defaultType": "swap"}, "newUpdates": True}
        if execution:
            options.update(apiKey=self.settings.secret(f"{self.name}_api_key"), secret=self.settings.secret(f"{self.name}_secret_key"))
        exchange = getattr(ccxtpro, self.name)(options)
        network = self.settings.crypto_execution_network if execution else self.settings.crypto_data_network
        if network == "testnet":
            exchange.set_sandbox_mode(True)
        return exchange

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        exchange, symbol = self.client(), self.settings.ccxt_symbol
        try:
            await exchange.load_markets()
            last_history = 0.0
            while True:
                if time.monotonic() - last_history > 60:
                    rows = await exchange.fetch_ohlcv(symbol, "1m", limit=1000)
                    closed = [row for row in rows if row[0] + 60000 <= time.time() * 1000]
                    await history(frame_from_rows(closed, symbol), self.name, symbol)
                    last_history = time.monotonic()
                book = await asyncio.wait_for(exchange.watch_order_book(symbol), 35)
                bids, asks = book["bids"], book["asks"]
                if bids and asks:
                    await sink(Quote(provider=self.name, symbol=symbol, price=(bids[0][0] + asks[0][0]) / 2,
                                     bid=bids[0][0], ask=asks[0][0], source_time=timestamp_ms(book["timestamp"]) if book.get("timestamp") else None,
                                     transport="websocket", quality="realtime", instrument="perpetual",
                                     bids=[tuple(level[:2]) for level in bids[:20]], asks=[tuple(level[:2]) for level in asks[:20]]))
        finally:
            await exchange.close()
