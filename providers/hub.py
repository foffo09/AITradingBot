from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from config.providers import ProviderSettings
from core.state import Market
from providers.common import HistorySink, QuoteSink, error_code
from providers.crypto import CCXTData, HyperliquidData
from providers.solana import SolanaData
from providers.tradfi import AlpacaData, FinnhubData, IBData, PolygonData, YahooData


class ProviderHub:
    """Each market has an isolated retry/failover loop; missing keys are ordinary state."""

    def __init__(self, settings: ProviderSettings, quote_sink, history_sink) -> None:
        self.settings, self.quote_sink, self.history_sink = settings, quote_sink, history_sink
        self.client = httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=False)
        self.status = {market: {"state": "starting", "provider": None, "error": None} for market in Market}
        self.news: list[dict] = []
        self.tasks: list[asyncio.Task] = []
        self.solana = SolanaData(settings, self.client)

    def providers(self, market: Market):
        s = self.settings
        if market == Market.CRYPTO_PERPS:
            names = list(dict.fromkeys([s.crypto_provider, "hyperliquid", "binance", "bybit"]))
            return [HyperliquidData(s, self.client) if name == "hyperliquid" else CCXTData(name, s) for name in names]
        if market == Market.MEME_SNIPER:
            return [self.solana]
        if market == Market.COMMODITIES_FUT:
            return ([IBData(s, s.ib_futures_symbol, "future")] if s.ib_enabled else []) + [YahooData(s.futures_yahoo_symbol, "proxy")]
        option = market == Market.OPTIONS_0DTE
        symbol = s.options_symbol if option else s.biotech_symbol
        providers = []
        if symbol:
            if s.alpaca_api_key and s.alpaca_secret_key:
                providers.append(AlpacaData(s, self.client, symbol, option))
            if s.ib_enabled:
                providers.append(IBData(s, symbol, "option" if option else "equity"))
            if s.polygon_api_key:
                providers.append(PolygonData(s, self.client, symbol, option))
            if not option and s.finnhub_api_key:
                providers.append(FinnhubData(s, self.client, symbol))
        providers.append(YahooData(symbol or s.options_underlying, "option" if option and symbol else "proxy" if option else "equity"))
        return providers

    async def worker(self, market: Market) -> None:
        delay = 1
        while True:
            for provider in self.providers(market):
                self.status[market] = {"state": "connecting", "provider": provider.name, "error": None}

                async def quote_sink(quote):
                    await self.quote_sink(market, quote)
                    self.status[market] = {"state": "receiving", "provider": provider.name, "error": None,
                                           "last_received": time.time()}

                async def history_sink(frame, name, symbol):
                    await self.history_sink(market, frame, name, symbol)

                try:
                    await provider.stream(quote_sink, history_sink)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.status[market] = {"state": "unavailable", "provider": provider.name, "error": error_code(exc)}
            await asyncio.sleep(delay)
            delay = min(60, delay * 2)

    async def news_worker(self) -> None:
        while True:
            try:
                if self.settings.finnhub_api_key:
                    items = await FinnhubData(self.settings, self.client, self.settings.biotech_symbol).news()
                    self.news = [{"title": str(item.get("headline", ""))[:500], "url": item.get("url"),
                                  "timestamp": item.get("datetime"), "provider": "finnhub"} for item in items[:30]]
                else:
                    import yfinance as yf
                    items = await asyncio.to_thread(yf.Ticker(self.settings.biotech_symbol).get_news, count=10)
                    self.news = [{"title": str(item.get("content", {}).get("title", item.get("title", "")))[:500],
                                  "provider": "yfinance", "verified_fda_sec_event": False} for item in items]
            except Exception:
                # News failure never tears down price feeds; no event is inferred from missing news.
                self.news = []
            await asyncio.sleep(300)

    async def start(self) -> None:
        self.tasks = [asyncio.create_task(self.worker(market)) for market in Market]
        self.tasks.append(asyncio.create_task(self.news_worker()))

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.aclose()
