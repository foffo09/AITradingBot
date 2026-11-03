from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from websockets.asyncio.client import connect

from config.providers import ProviderSettings
from providers.common import HistorySink, ProviderUnavailable, Quote, QuoteSink, request


class SolanaData:
    name = "dexscreener"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self.settings, self.client = settings, client
        self.rpc_status = "not connected"

    async def rpc(self, method: str, params: list[Any]) -> Any:
        for name, url, _ in self.settings.rpc_endpoints():
            try:
                result = await request(self.client, "POST", url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if "error" in result:
                    continue
                self.rpc_status = name
                return result["result"]
            except ProviderUnavailable:
                continue
        raise ProviderUnavailable("Solana RPC providers unavailable")

    async def mint_checks(self, mint: str) -> dict[str, Any]:
        account, largest, supply = await asyncio.gather(
            self.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}]),
            self.rpc("getTokenLargestAccounts", [mint]), self.rpc("getTokenSupply", [mint]),
        )
        data = (account.get("value") or {}).get("data", {}).get("parsed", {})
        info = data.get("info", {}) if data.get("type") == "mint" else {}
        total = int(supply["value"]["amount"])
        return {
            "mint_authority_disabled": info.get("mintAuthority") is None if info else None,
            "freeze_authority_disabled": info.get("freezeAuthority") is None if info else None,
            "top10_token_accounts_fraction": sum(int(row["amount"]) for row in largest["value"][:10]) / total if total else None,
            "holders_verified": False, "lp_lock_verified": False, "honeypot_verified": False,
            "eligible_for_automatic_swap": False,
        }

    async def quote(self) -> Quote:
        mint = self.settings.solana_token_mint
        values = await request(self.client, "GET", f"https://api.dexscreener.com/token-pairs/v1/solana/{mint}")
        pairs = [p for p in values if p.get("priceUsd") and p.get("baseToken", {}).get("address") == mint]
        if not pairs:
            raise ProviderUnavailable("No priced Solana pair")
        pair = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        # The REST API does not provide a quote timestamp: freshness cannot be certified.
        return Quote(provider=self.name, symbol=mint, price=float(pair["priceUsd"]), source_time=None,
                     transport="rest", quality="indicative", instrument="token")

    async def watch_rpc(self) -> None:
        while True:
            for name, _, ws_url in self.settings.rpc_endpoints():
                try:
                    async with connect(ws_url, open_timeout=8, ping_interval=20) as ws:
                        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "accountSubscribe",
                                                  "params": [self.settings.solana_token_mint, {"encoding": "jsonParsed", "commitment": "confirmed"}]}))
                        while True:
                            result = json.loads(await asyncio.wait_for(ws.recv(), 60))
                            if "error" in result:
                                raise ProviderUnavailable("RPC subscription rejected")
                            self.rpc_status = f"{name}: subscription active"
                except Exception:
                    self.rpc_status = f"{name}: unavailable"
            await asyncio.sleep(30)

    async def stream(self, sink: QuoteSink, history: HistorySink) -> None:
        watcher = asyncio.create_task(self.watch_rpc())
        try:
            while True:
                await sink(await self.quote())
                await asyncio.sleep(15)
        finally:
            watcher.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):
                await watcher


class Jupiter:
    """Quote and unsigned swap builder; never signs or broadcasts a transaction."""

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self.settings, self.client = settings, client

    def headers(self) -> dict[str, str]:
        key = self.settings.secret("jupiter_api_key")
        if not key and self.settings.jupiter_base_url.startswith("https://api.jup.ag/"):
            raise ProviderUnavailable("Jupiter API key not configured; DexScreener remains available")
        return {"x-api-key": key} if key else {}

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50) -> dict[str, Any]:
        if type(amount) is not int or amount <= 0 or not 0 <= slippage_bps <= 500:
            raise ValueError("Invalid quote amount or slippage")
        return await request(self.client, "GET", self.settings.jupiter_base_url + "/quote", headers=self.headers(),
                             params={"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount), "slippageBps": slippage_bps})

    async def unsigned_swap(self, quote: dict[str, Any], public_key: str) -> dict[str, Any]:
        if not public_key or not quote.get("routePlan"):
            raise ValueError("A route and wallet public key are required")
        return await request(self.client, "POST", self.settings.jupiter_base_url + "/swap", headers=self.headers(),
                             json={"quoteResponse": quote, "userPublicKey": public_key, "dynamicComputeUnitLimit": True})
