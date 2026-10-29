from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from core.state import Controls, Market


class BaseMarketAdapter(ABC):
    """Demo adapters expose risk profiles, not venue execution connectivity."""

    market: Market

    @property
    @abstractmethod
    def unavailable(self) -> str:
        raise NotImplementedError

    def atr(self, data: pd.DataFrame) -> float:
        previous = data.close.shift()
        ranges = pd.concat([data.high - data.low, (data.high - previous).abs(), (data.low - previous).abs()], axis=1)
        return float(ranges.max(axis=1).tail(14).mean())


class MemeSniperAdapter(BaseMarketAdapter):
    market = Market.MEME_SNIPER
    unavailable = "RPC, LP locks, holder analysis, honeypot simulation and private execution unavailable"


class CryptoPerpsAdapter(BaseMarketAdapter):
    market = Market.CRYPTO_PERPS
    unavailable = "No derivatives venue, funding, L2, CVD or leverage; synthetic long-only candles"


class Options0DTEAdapter(BaseMarketAdapter):
    market = Market.OPTIONS_0DTE
    unavailable = "No option chain, greeks, expiry or underlying hedge; synthetic premium proxy"


class CommoditiesAdapter(BaseMarketAdapter):
    market = Market.COMMODITIES_FUT
    unavailable = "No futures contracts, multipliers, rolls, NYMEX calendar or EIA feed"


class BiotechAdapter(BaseMarketAdapter):
    market = Market.BIOTECH_CATALYST
    unavailable = "No SEC/FDA feed, float data, dilution detection or LULD status"


class MarketRouter:
    def __init__(self) -> None:
        self.adapters = {adapter.market: adapter for adapter in (
            MemeSniperAdapter(), CryptoPerpsAdapter(), Options0DTEAdapter(), CommoditiesAdapter(), BiotechAdapter()
        )}

    def active(self, controls: Controls) -> list[Market]:
        return list(Market) if controls.multi_split_kelly else [controls.market]
