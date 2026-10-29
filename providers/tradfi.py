from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
from websockets.asyncio.client import connect

from config.providers import ProviderSettings
from providers.common import HistorySink, ProviderUnavailable, Quote, QuoteSink, frame_from_rows, request, timestamp


class YahooData:
    name = "yfinance"

    def __init__(self, symbol: str, instrument: str) -> None:
        self.symbol, self.instrument = symbol, instrument

    async def history(self) -> pd.DataFrame:
        import yfinance as yf
        frame = await asyncio.to_thread(yf.Ticker(self.symbol).history, period="5d", interval="1m", auto_adjust=False, timeout=8)
        if frame.empty:
            raise ProviderUnavailable("Yahoo history unavailable")
        frame = frame.rename(columns=str.lower).reset_index()
        frame = frame.rename(columns={frame.columns[0]: "timestamp"})
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        frame = frame[frame.timestamp + pd.Timedelta(minutes=1) <= pd.Timestamp.now(tz="UTC")].tail(1500)
        frame["symbol"], frame["is_synthetic"] = self.symbol, False
        return frame

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        import yfinance as yf
        async def snapshot():
            frame = await self.history()
            await history(frame, self.name, self.symbol)
            bar = frame.iloc[-1]
            await sink(Quote(provider=self.name, symbol=self.symbol, price=float(bar.close), source_time=bar.timestamp.timestamp() + 60,
                             transport="rest", quality="unknown", instrument=self.instrument))

        async def handler(message):
            if message.get("price", 0) > 0 and message.get("id") == self.symbol:
                await sink(Quote(provider=self.name, symbol=self.symbol, price=message["price"],
                                 source_time=timestamp(message["time"]) if message.get("time") else None,
                                 transport="websocket", quality="unknown", instrument=self.instrument))

        async def refresh():
            while True:
                try:
                    await snapshot()
                except Exception:
                    # Missing history must not stop the independent WebSocket connection.
                    await asyncio.sleep(0)
                await asyncio.sleep(60)

        task = asyncio.create_task(refresh())
        try:
            delay = 1
            while True:
                try:
                    async with yf.AsyncWebSocket(verbose=False) as ws:
                        await ws.subscribe([self.symbol])
                        await ws.listen(handler)
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                except Exception:
                    await asyncio.sleep(delay)
                    delay = min(60, delay * 2)
        finally:
            task.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):
                await task


class AlpacaData:
    name = "alpaca"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient, symbol: str, option: bool = False) -> None:
        self.settings, self.client, self.symbol, self.option = settings, client, symbol, option

    def headers(self):
        if not self.settings.alpaca_api_key or not self.settings.alpaca_secret_key:
            raise ProviderUnavailable("Alpaca credentials not configured")
        return {"APCA-API-KEY-ID": self.settings.secret("alpaca_api_key"), "APCA-API-SECRET-KEY": self.settings.secret("alpaca_secret_key")}

    async def history(self):
        if self.option:
            raise ProviderUnavailable("Option history requires a separate entitled feed")
        start = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        data = await request(self.client, "GET", "https://data.alpaca.markets/v2/stocks/bars", headers=self.headers(),
                             params={"symbols": self.symbol, "timeframe": "1Min", "start": start, "limit": 1500, "feed": "iex", "sort": "desc"})
        bars = data.get("bars", {}).get(self.symbol) or []
        frame = pd.DataFrame([{ "timestamp": b["t"], "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"]} for b in bars])
        if frame.empty:
            raise ProviderUnavailable("Alpaca history unavailable")
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        frame["is_synthetic"], frame["symbol"] = False, self.symbol
        return frame.sort_values("timestamp").reset_index(drop=True)

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        headers = self.headers()
        if not self.option:
            await history(await self.history(), self.name, self.symbol)
        endpoint = "wss://stream.data.alpaca.markets/v1beta1/indicative" if self.option else "wss://stream.data.alpaca.markets/v2/iex"
        ws_headers = {"Content-Type": "application/msgpack"} if self.option else {}
        async with connect(endpoint, open_timeout=8, ping_interval=20, additional_headers=ws_headers) as ws:
            await ws.send(json.dumps({"action": "auth", "key": headers["APCA-API-KEY-ID"], "secret": headers["APCA-API-SECRET-KEY"]}))
            await ws.send(json.dumps({"action": "subscribe", "quotes": [self.symbol]}))
            last_history = time.monotonic()
            while True:
                raw = await asyncio.wait_for(ws.recv(), 60)
                if isinstance(raw, bytes):
                    import msgpack
                    messages = msgpack.unpackb(raw, raw=False, timestamp=3)
                else:
                    messages = json.loads(raw)
                for value in messages:
                    if value.get("T") == "error":
                        raise ProviderUnavailable("Alpaca authentication/subscription rejected")
                    if value.get("T") == "q" and value.get("bp", 0) > 0 and value.get("ap", 0) > 0:
                        await sink(Quote(provider=self.name, symbol=value["S"], price=(value["bp"] + value["ap"]) / 2,
                                         bid=value["bp"], ask=value["ap"], source_time=timestamp(value["t"]), transport="websocket",
                                         quality="indicative" if self.option else "realtime", instrument="option" if self.option else "equity"))
                if not self.option and time.monotonic() - last_history >= 60:
                    await history(await self.history(), self.name, self.symbol)
                    last_history = time.monotonic()


class PolygonData:
    name = "polygon"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient, symbol: str, option: bool = False) -> None:
        self.settings, self.client, self.symbol, self.option = settings, client, symbol, option

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        key = self.settings.secret("polygon_api_key")
        if not key:
            raise ProviderUnavailable("Polygon key not configured")
        ticker = "O:" + self.symbol if self.option else self.symbol
        while True:
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=5)
            data = await request(self.client, "GET", f"{self.settings.polygon_base_url}/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}",
                                 headers={"Authorization": f"Bearer {key}"}, params={"sort": "desc", "limit": 1500, "adjusted": "true"})
            bars = sorted(data.get("results") or [], key=lambda b: b["t"])
            if not bars:
                raise ProviderUnavailable("Polygon history not entitled or unavailable")
            frame = frame_from_rows([[b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars], self.symbol)
            await history(frame, self.name, self.symbol)
            bar = bars[-1]
            await sink(Quote(provider=self.name, symbol=self.symbol, price=bar["c"], source_time=timestamp(bar["t"]),
                             transport="rest", quality="indicative", instrument="option" if self.option else "equity"))
            await asyncio.sleep(60)


class FinnhubData:
    name = "finnhub"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient, symbol: str) -> None:
        self.settings, self.client, self.symbol = settings, client, symbol

    async def news(self):
        key = self.settings.secret("finnhub_api_key")
        if not key:
            raise ProviderUnavailable("Finnhub key not configured")
        today = datetime.now(timezone.utc).date()
        return await request(self.client, "GET", "https://finnhub.io/api/v1/company-news", headers={"X-Finnhub-Token": key},
                             params={"symbol": self.symbol, "from": str(today - timedelta(days=1)), "to": str(today)})

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        key = self.settings.secret("finnhub_api_key")
        if not key:
            raise ProviderUnavailable("Finnhub key not configured")
        async with connect(f"wss://ws.finnhub.io?token={key}", open_timeout=8, ping_interval=20) as ws:
            await ws.send(json.dumps({"type": "subscribe", "symbol": self.symbol}))
            while True:
                payload = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if payload.get("type") == "error":
                    raise ProviderUnavailable("Finnhub subscription rejected")
                for trade in payload.get("data") or []:
                    await sink(Quote(provider=self.name, symbol=self.symbol, price=trade["p"], source_time=timestamp(trade["t"]),
                                     transport="websocket", quality="unknown", instrument="equity"))


class IBData:
    name = "interactive_brokers"

    def __init__(self, settings: ProviderSettings, symbol: str, kind: str) -> None:
        self.settings, self.symbol, self.kind = settings, symbol, kind

    def contract(self):
        import re
        from ib_insync import Contract, Future, Option, Stock
        if self.kind == "future":
            if not self.settings.ib_futures_expiry:
                raise ProviderUnavailable("A dated futures contract is required")
            return Future(self.symbol, self.settings.ib_futures_expiry, self.settings.ib_futures_exchange, currency="USD")
        if self.kind == "option":
            match = re.fullmatch(r"([A-Z]{1,6})(\d{6})([CP])(\d{8})", self.symbol)
            if match:
                root, expiry, right, strike = match.groups()
                return Option(root, "20" + expiry, int(strike) / 1000, right, "SMART", currency="USD")
            return Contract(secType="OPT", localSymbol=self.symbol, exchange="SMART", currency="USD")
        return Stock(self.symbol, "SMART", "USD")

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        from ib_insync import IB
        if not self.settings.ib_enabled:
            raise ProviderUnavailable("TWS/Gateway not enabled")
        ib = IB()
        try:
            offset = {"equity": 0, "option": 1, "future": 2}[self.kind]
            await ib.connectAsync(self.settings.ib_host, self.settings.ib_port, self.settings.ib_client_id + offset,
                                  timeout=self.settings.request_timeout_seconds, readonly=True)
            contract = self.contract()
            if not await ib.qualifyContractsAsync(contract):
                raise ProviderUnavailable("IB contract not qualified")
            ib.reqMarketDataType(3)
            bars = await ib.reqHistoricalDataAsync(contract, "", "2 D", "1 min", "TRADES", False, formatDate=2)
            if bars:
                frame = pd.DataFrame([{"timestamp": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in bars])
                frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
                frame["symbol"], frame["is_synthetic"] = self.symbol, False
                await history(frame, self.name, self.symbol)
            ticker = ib.reqMktData(contract)
            while ib.isConnected():
                await asyncio.sleep(1)
                price = ticker.marketPrice()
                if pd.notna(price) and price > 0:
                    await sink(Quote(provider=self.name, symbol=self.symbol, price=price,
                                     source_time=timestamp(ticker.time) if ticker.time else None,
                                     transport="tws", quality="indicative", instrument=self.kind))
            raise ProviderUnavailable("IB disconnected")
        finally:
            ib.disconnect()
