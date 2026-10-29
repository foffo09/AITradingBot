"""Manual runner. Never used by pytest to place authenticated orders."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

from config.hyperliquid_testnet import TestnetSettings
from src.broker.hyperliquid_testnet import HyperliquidTestnetBroker
from src.broker.native import BrokerUnavailable
from src.strategy.moving_average import MovingAverageStrategy
from src.trading.native_engine import NativeEngine
from src.trading.native_store import NativeStore


def closed_candles(rows: list[dict], now_ms: int) -> list[dict]:
    normalized = {}
    for row in rows:
        start, end, price = int(row["t"]), int(row["T"]), float(row["c"])
        if start < 0 or end < start or not math.isfinite(price) or price <= 0:
            raise BrokerUnavailable("Invalid testnet candle data")
        if end < now_ms:
            normalized[start] = {**row, "t": start, "T": end, "c": price}
    return [normalized[key] for key in sorted(normalized)]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Hyperliquid TESTNET ONLY; credentials only from process environment")
    result.add_argument("--action", choices=["status", "run", "signal", "panic", "partial", "cancel", "resume"], default="status")
    result.add_argument("--trade-testnet", action="store_true", help="Explicitly enable signed TESTNET actions")
    result.add_argument("--journal", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "hyperliquid_testnet.sqlite3")
    result.add_argument("--fraction", type=Decimal, default=Decimal("0.5"))
    result.add_argument("--intent-id", help="Stable ID for a partial exit; reuse on retry")
    result.add_argument("--cloid", help="Client order ID for cancellation")
    result.add_argument("--signal", choices=["buy", "sell"], help="Explicit manual signal for a TESTNET smoke check")
    return result


async def execute(args) -> None:
    if args.action != "status" and not args.trade_testnet:
        raise ValueError("Signed actions require --trade-testnet")
    if args.action == "partial" and not args.intent_id:
        raise ValueError("Partial exits require --intent-id for restart idempotency")
    if args.action == "signal" and (not args.intent_id or not args.signal):
        raise ValueError("Manual signals require --intent-id and --signal")
    if args.action == "cancel" and not args.cloid:
        raise ValueError("Cancellation requires --cloid")
    broker = HyperliquidTestnetBroker(TestnetSettings.from_env())
    try:
        controller = NativeEngine(broker, broker.settings, args.journal)
    except RuntimeError:
        if args.action != "panic":
            raise
        NativeStore.queue_panic(args.journal, broker.scope)
        await broker.close()
        print(json.dumps({"network": "testnet", "state": "panic_queued_for_running_engine", "panic_complete": False}))
        return
    try:
        if args.action == "status":
            print(json.dumps(await controller.reconcile(), indent=2))
        elif args.action == "panic":
            print(json.dumps(await controller.panic(), indent=2))
        elif args.action == "partial":
            await controller.partial_exit(args.intent_id, args.fraction)
            print(json.dumps(controller.status(), indent=2))
        elif args.action == "cancel":
            await controller.cancel(args.cloid)
            print(json.dumps(controller.status(), indent=2))
        elif args.action == "resume":
            await controller.resume()
            print(json.dumps(controller.status(), indent=2))
        elif args.action == "signal":
            await controller.on_signal("manual:" + args.intent_id, 1 if args.signal == "buy" else -1, time.time())
            print(json.dumps(controller.status(), indent=2))
        else:
            strategy, last_minute = MovingAverageStrategy(), None
            while True:
                try:
                    await controller.tick()
                    minute = int(time.time() // 60)
                    if minute != last_minute and not controller.store.get("panic"):
                        bars = await broker.candles(broker.settings.symbol)
                        closed = closed_candles(bars, int(time.time() * 1000))
                        if closed:
                            frame = pd.DataFrame({"close": [float(bar["c"]) for bar in closed]})
                            signal = strategy.current_signal(frame)["signal"]
                            await controller.on_signal(f"ma:{broker.settings.symbol}:{closed[-1]['t']}", signal, closed[-1]["T"] / 1000)
                        last_minute = minute
                    print(json.dumps(controller.status()))
                except BrokerUnavailable:
                    print(json.dumps({"network": "testnet", "state": "blocked_pending_broker_reconciliation"}))
                await asyncio.sleep(5)
    finally:
        await controller.close()


def main() -> int:
    args = parser().parse_args()
    if args.action != "status" and not args.trade_testnet:
        parser().error("Signed actions require --trade-testnet; mainnet is never supported")
    if args.action == "partial" and not args.intent_id:
        parser().error("--intent-id is required")
    if args.action == "cancel" and not args.cloid:
        parser().error("--cloid is required")
    if args.action == "signal" and (not args.intent_id or not args.signal):
        parser().error("--intent-id and --signal are required")
    for name in ("hyperliquid", "urllib3", "httpx", "httpcore"):
        logging.getLogger(name).disabled = True
    try:
        asyncio.run(execute(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # SDK exception messages can include signed payloads; print only their type.
        print(json.dumps({"network": "testnet", "error": type(exc).__name__,
                          "state": "blocked; inspect TESTNET account and run read-only status"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
