import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config.providers import ProviderSettings
from core.live_runtime import LiveRuntime
from core.state import Market
from execution.providers import ExecutionProviders, OrderIntent
from providers.ai import AIProvider, StrategyPlan
from providers.common import ProviderUnavailable, Quote, request
from providers.crypto import CCXTData, HyperliquidData
from providers.hub import ProviderHub
from providers.solana import Jupiter, SolanaData
from ui.control_box import create_app


def run(coroutine):
    return asyncio.run(coroutine)


def quote(**kwargs):
    return Quote(provider="test", symbol="BTC", price=100, source_time=time.time(),
                 transport="websocket", instrument="perpetual", quality="realtime", **kwargs)


def test_provider_credentials_come_from_environment_with_public_file_config(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=private-key\nCRYPTO_DATA_NETWORK=testnet\nOMEGA_ENABLE_LIVE_ORDERS=false\n")
    monkeypatch.setenv("CRYPTO_DATA_NETWORK", "mainnet")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    settings = ProviderSettings.from_env(path)
    assert settings.crypto_data_network == "mainnet"
    assert settings.secret("openai_api_key") == "environment-key"
    assert "private-key" not in repr(settings)
    assert not settings.omega_enable_live_orders


def test_env_example_covers_every_provider_setting():
    lines = (Path(__file__).resolve().parents[1] / ".env.example").read_text().splitlines()
    names = {line.split("=", 1)[0] for line in lines if line and not line.startswith("#")}
    assert {name.upper() for name in ProviderSettings.model_fields} <= names


def test_public_defaults_and_ai_fallback():
    settings = ProviderSettings()
    assert settings.rpc_endpoints()[-1][0] == "solana_public"
    assert settings.ai_backend() == "none"
    assert settings.crypto_data_network == "mainnet" and settings.crypto_execution_network == "testnet"
    assert not settings.omega_enable_native_orders and settings.alpaca_paper


def test_quote_validation_and_freshness():
    assert quote().fresh(60)
    assert not quote().model_copy(update={"source_time": time.time() - 120}).fresh(60)
    assert not quote().model_copy(update={"source_time": None}).fresh(60)
    with pytest.raises(ValidationError):
        quote(bid=101, ask=99)
    with pytest.raises(ValidationError):
        quote(bids=[(-1, 2)])


def test_hyperliquid_l2_parser():
    result = HyperliquidData.parse_book({"coin": "BTC", "time": int(time.time() * 1000),
        "levels": [[{"px": "99", "sz": "3"}], [{"px": "101", "sz": "1"}]]})
    assert result.price == 100 and result.imbalance == .5 and result.fresh(60)
    assert result.bids == [(99, 3)]


@pytest.mark.parametrize("venue", ["binance", "bybit"])
def test_ccxt_sandbox_is_set_before_network_access(monkeypatch, venue):
    import ccxt.pro as pro
    calls = []

    class Fake:
        def __init__(self, options):
            calls.append(("init", options))
        def set_sandbox_mode(self, enabled):
            calls.append(("sandbox", enabled))

    monkeypatch.setattr(pro, venue, Fake)
    settings = ProviderSettings(crypto_data_network="testnet")
    CCXTData(venue, settings).client()
    assert calls[0][0] == "init" and "apiKey" not in calls[0][1]
    assert calls[1] == ("sandbox", True)


def test_http_backoff_and_auth_failures_do_not_expose_keys(monkeypatch):
    async def check():
        count = 0
        def handler(req):
            nonlocal count
            count += 1
            return httpx.Response(503 if count < 3 else 200, json={"ok": True})
        monkeypatch.setattr("providers.common.asyncio.sleep", AsyncMock())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await request(client, "GET", "https://test.invalid?api-key=private-key") == {"ok": True}
        assert count == 3
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(401))) as client:
            with pytest.raises(ProviderUnavailable) as error:
                await request(client, "GET", "https://test.invalid?api-key=private-key")
            assert "private-key" not in str(error.value) and "401" in str(error.value)
    run(check())


def test_solana_public_fallback_and_unverified_safety():
    async def check():
        methods = []
        def handler(req):
            if req.url.host == "private.invalid":
                return httpx.Response(401)
            method = json.loads(req.content)["method"]
            methods.append(method)
            values = {
                "getAccountInfo": {"value": {"data": {"parsed": {"type": "mint", "info": {"mintAuthority": None, "freezeAuthority": None}}}}},
                "getTokenLargestAccounts": {"value": [{"amount": "10"}]},
                "getTokenSupply": {"value": {"amount": "100"}},
            }
            return httpx.Response(200, json={"result": values[method]})
        settings = ProviderSettings(solana_rpc_url="https://private.invalid/?api-key=secret")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            solana = SolanaData(settings, client)
            result = await solana.mint_checks("mint")
            assert solana.rpc_status == "solana_public"
            assert result["mint_authority_disabled"] and result["top10_token_accounts_fraction"] == .1
            assert not result["eligible_for_automatic_swap"] and not result["holders_verified"]
    run(check())


def test_jupiter_builds_unsigned_swap_without_broadcast():
    async def check():
        paths = []
        def handler(req):
            paths.append(req.url.path)
            assert req.headers["x-api-key"] == "test-key"
            return httpx.Response(200, json={"routePlan": [{}]} if req.method == "GET" else {"swapTransaction": "unsigned"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            jupiter = Jupiter(ProviderSettings(jupiter_api_key="test-key"), client)
            route = await jupiter.quote("mint-a", "mint-b", 100)
            assert (await jupiter.unsigned_swap(route, "public-key"))["swapTransaction"] == "unsigned"
            assert paths == ["/swap/v1/quote", "/swap/v1/swap"]
        async with httpx.AsyncClient() as client:
            with pytest.raises(ProviderUnavailable):
                await Jupiter(ProviderSettings(), client).quote("a", "b", 1)
    run(check())


def test_market_worker_survives_one_provider_failure():
    async def check():
        received = asyncio.Event()
        async def sink(market, value):
            received.set()
        hub = ProviderHub(ProviderSettings(), sink, AsyncMock())
        class Broken:
            name = "broken"
            async def stream(self, sink, history):
                raise RuntimeError("private-key-in-error")
        class Healthy:
            name = "healthy"
            async def stream(self, sink, history):
                await sink(quote())
                await asyncio.Event().wait()
        hub.providers = lambda market: [Broken(), Healthy()]
        task = asyncio.create_task(hub.worker(Market.CRYPTO_PERPS))
        await asyncio.wait_for(received.wait(), 2)
        assert hub.status[Market.CRYPTO_PERPS]["state"] == "receiving"
        assert hub.status[Market.CRYPTO_PERPS]["provider"] == "healthy"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await hub.close()
    run(check())


def test_zero_credentials_live_runtime_starts_without_synthetic_data(tmp_path, monkeypatch):
    runtime = LiveRuntime(tmp_path / "paper.json", ProviderSettings())
    monkeypatch.setattr(runtime.hub, "start", AsyncMock())
    with TestClient(create_app(runtime)) as client:
        state = client.get("/api/state").json()
        assert state["source"] == "LIVE_DATA_PAPER"
        assert state["quotes"] == {} and state["reports"] == {} and runtime.ingestor.frames == {}
        assert not any(state["execution_providers"]["credentials_present"].values())
        token = re.search("const token='([^']+)'", client.get("/").text).group(1)
        response = client.post("/api/command", headers={"X-Control-Token": token}, json={"action": "start"})
        assert response.status_code == 200 and response.json()["running"]
        assert response.json()["fills"] == []


def test_live_panic_waits_for_fresh_quote_and_preserves_lock(tmp_path):
    async def check():
        runtime = LiveRuntime(tmp_path / "paper.json", ProviderSettings())
        market = Market.CRYPTO_PERPS
        current = quote()
        await runtime.on_quote(market, current)
        runtime.state.running = True
        runtime.risk.open(market, 100, .8, 2, 2, 1, instrument_id=current.instrument_id)
        runtime.quotes[market] = current.model_copy(update={"source_time": time.time() - 120})
        await runtime.command("panic")
        assert runtime.state.pending_flatten and len(runtime.state.positions) == 1
        locked = runtime.state.locked_until
        await runtime.on_quote(market, quote())
        await runtime.tick()
        assert not runtime.state.pending_flatten and not runtime.state.positions
        assert runtime.state.locked_until == locked and locked > time.time()
        await runtime.close()
    run(check())


def test_fallback_cannot_mark_an_existing_position_with_different_instrument(tmp_path):
    async def check():
        runtime = LiveRuntime(tmp_path / "paper.json", ProviderSettings())
        original = quote()
        market = Market.CRYPTO_PERPS
        await runtime.on_quote(market, original)
        runtime.state.running = True
        runtime.risk.open(market, 100, .8, 2, 2, 1, instrument_id=original.instrument_id)
        alternate = original.model_copy(update={"provider": "other", "price": 200})
        await runtime.on_quote(market, alternate)
        await runtime.tick()
        assert runtime.state.last_prices[market] == 100 and len(runtime.state.fills) == 1
        assert "original feed" in runtime.blocked[market]
        await runtime.close()
    run(check())


def intent():
    return OrderIntent(client_order_id="omega-test-0001", venue="alpaca", market=Market.BIOTECH_CATALYST,
                       symbol="SAVA", side="buy", quantity=1, limit_price=10, quote_timestamp=time.time())


def test_native_orders_default_off_and_mainnet_requires_explicit_live_flag(tmp_path):
    gateway = ExecutionProviders(ProviderSettings(), tmp_path / "orders.db")
    with pytest.raises(ProviderUnavailable, match="disabled"):
        run(gateway.submit(intent()))
    assert not gateway.journal.exists()
    settings = ProviderSettings(omega_enable_native_orders=True, alpaca_api_key="test", alpaca_secret_key="test", alpaca_paper=False)
    with pytest.raises(ProviderUnavailable, match="Live native"):
        ExecutionProviders(settings, tmp_path / "orders.db").check(intent())


def test_ambiguous_native_timeout_is_not_automatically_retried(tmp_path, monkeypatch):
    async def check():
        settings = ProviderSettings(omega_enable_native_orders=True, alpaca_api_key="test", alpaca_secret_key="test")
        gateway = ExecutionProviders(settings, tmp_path / "orders.db")
        calls = []
        def submit(value):
            calls.append(value)
            raise TimeoutError("secret-value")
        monkeypatch.setattr(gateway, "alpaca_order", submit)
        with pytest.raises(ProviderUnavailable, match="reconciliation") as error:
            await gateway.submit(intent())
        assert "secret-value" not in str(error.value)
        with pytest.raises(ProviderUnavailable, match="journaled"):
            await gateway.submit(intent())
        assert len(calls) == 1
    run(check())


def test_openai_sdk_plan_is_validated(monkeypatch):
    import openai
    async def check():
        create = AsyncMock(return_value=SimpleNamespace(output_text='{"candidates":[{"short_window":5,"long_window":20}]}'))
        class Fake:
            def __init__(self, **kwargs):
                assert kwargs["api_key"] == "test-key"
                self.responses = SimpleNamespace(create=create)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        monkeypatch.setattr(openai, "AsyncOpenAI", Fake)
        provider = AIProvider(ProviderSettings(ai_provider="openai", openai_api_key="test-key"))
        assert await provider.propose(Market.CRYPTO_PERPS, .02) == ((5, 20),)
        assert "test-key" not in create.call_args.kwargs["input"]
    run(check())


@pytest.mark.parametrize("body", [
    '{"candidates":[{"short_window":true,"long_window":20}]}',
    '{"candidates":[{"short_window":20,"long_window":5}]}',
    '{"candidates":[{"short_window":5,"long_window":20,"code":"import os"}]}',
])
def test_ai_rejects_unbounded_or_invalid_plans(body):
    with pytest.raises(ValidationError):
        StrategyPlan.model_validate_json(body)


def test_protobuf_numeric_string_timestamp():
    from providers.common import timestamp
    now = time.time()
    assert timestamp(str(int(now * 1000))) == pytest.approx(now, abs=.002)


def test_out_of_order_quote_cannot_replace_newer_quote(tmp_path):
    async def check():
        runtime = LiveRuntime(tmp_path / "paper.json", ProviderSettings())
        latest = quote()
        await runtime.on_quote(Market.CRYPTO_PERPS, latest)
        await runtime.on_quote(Market.CRYPTO_PERPS, latest.model_copy(update={"source_time": latest.source_time - 60, "price": 50}))
        assert runtime.quotes[Market.CRYPTO_PERPS].price == 100
        await runtime.close()
    run(check())


def test_anthropic_sdk_uses_same_bounded_plan(monkeypatch):
    import anthropic
    async def check():
        create = AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text='{"candidates":[{"short_window":3,"long_window":12}]}')]))
        class Fake:
            def __init__(self, **kwargs):
                self.messages = SimpleNamespace(create=create)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        monkeypatch.setattr(anthropic, "AsyncAnthropic", Fake)
        provider = AIProvider(ProviderSettings(ai_provider="anthropic", anthropic_api_key="test", anthropic_model="test-model"))
        assert await provider.propose(Market.BIOTECH_CATALYST, .03) == ((3, 12),)
    run(check())


def test_ollama_uses_local_json_schema(monkeypatch):
    async def check():
        original = httpx.AsyncClient
        def handler(req):
            body = json.loads(req.content)
            assert req.url.host == "127.0.0.1" and body["stream"] is False
            assert "properties" in body["format"]
            return httpx.Response(200, json={"message": {"content": '{"candidates":[{"short_window":5,"long_window":30}]}'}})
        monkeypatch.setattr("providers.ai.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
        provider = AIProvider(ProviderSettings(ai_provider="ollama", ollama_model="local-test"))
        assert await provider.propose(Market.CRYPTO_PERPS, .01) == ((5, 30),)
    run(check())


def test_native_alpaca_paper_keeps_ack_separate_from_fill(tmp_path, monkeypatch):
    from alpaca.trading import client as alpaca_client
    class Fake:
        def __init__(self, key, secret, paper):
            assert paper is True
        def get_account(self):
            return SimpleNamespace(status="ACTIVE", trading_blocked=False)
        def get_asset(self, symbol):
            return SimpleNamespace(tradable=True)
        def submit_order(self, order):
            assert order.client_order_id == "omega-test-0001"
            return {"id": "paper-id", "status": "accepted"}
    monkeypatch.setattr(alpaca_client, "TradingClient", Fake)
    settings = ProviderSettings(omega_enable_native_orders=True, alpaca_api_key="test", alpaca_secret_key="test")
    response = run(ExecutionProviders(settings, tmp_path / "journal.db").submit(intent()))
    assert response["status"] == "accepted"


def test_ib_occ_symbol_is_resolved_to_contract():
    from providers.tradfi import IBData
    async def check():
        contract = IBData(ProviderSettings(), "SPY261028C00600000", "option").contract()
        assert contract.symbol == "SPY" and contract.lastTradeDateOrContractMonth == "20261028"
        assert contract.right == "C" and contract.strike == 600
        with pytest.raises(ProviderUnavailable):
            IBData(ProviderSettings(), "CL", "future").contract()
    run(check())


def test_yahoo_shutdown_propagates_swallowed_library_cancellation(monkeypatch):
    import yfinance
    from providers.tradfi import YahooData
    async def check():
        entered = asyncio.Event()
        class FakeWS:
            def __init__(self, **kwargs):
                self.received = False
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def subscribe(self, symbols):
                return None
            async def listen(self, handler):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return None
        monkeypatch.setattr(yfinance, "AsyncWebSocket", FakeWS)
        provider = YahooData("SPY", "proxy")
        monkeypatch.setattr(provider, "history", AsyncMock(side_effect=ProviderUnavailable("no history")))
        task = asyncio.create_task(provider.stream(AsyncMock(), AsyncMock()))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    run(check())
