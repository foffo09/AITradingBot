import asyncio
import json
import re
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.coder_brain import CoderBrain
from core.ingestor import Ingestor
from core.runtime import Runtime
from core.state import Controls, LiveState, Market, save_state
from engine.sandbox import Sandbox
from execution.vanguard import COMMISSION, IMPACT, LIMITS, Vanguard
from ui.control_box import create_app


@pytest.mark.parametrize("source", [
    "import os\nos.system('id')", "while True: x = 1", "class GeneratedStrategy(BaseStrategy):\n short_window=2\n long_window=__import__('os')",
    "@exploit\nclass GeneratedStrategy(BaseStrategy):\n short_window=2\n long_window=10",
    "class GeneratedStrategy(BaseStrategy):\n short_window=True\n long_window=10",
    "class GeneratedStrategy(BaseStrategy):\n short_window=10\n long_window=2",
    "class GeneratedStrategy(BaseStrategy):\n short_window=2\n short_window=3",
    "class GeneratedStrategy(BaseStrategy):\n short_window=2\n long_window=10\n def evil(self): return 1",
])
def test_bounded_ast_rejects_executable_payloads(source):
    with pytest.raises((ValueError, SyntaxError)):
        CoderBrain.validate(source)


def test_generation_uses_repo_strategy_and_original_backtest(tmp_path):
    brain = CoderBrain(tmp_path)
    source, strategy = brain.generate(Market.CRYPTO_PERPS, 5, 20)
    assert CoderBrain.validate(source) == (5, 20)
    data = Ingestor().frames[Market.CRYPTO_PERPS]
    report = Sandbox().evaluate(data.iloc[:500], strategy, 0.04)
    assert report.synthetic and report.costs > 0 and report.trades > 0
    assert report.approved == (report.trades >= 10 and report.sharpe is not None and report.sharpe >= 2
                               and report.max_drawdown <= 0.08 and report.profit_factor is not None
                               and report.profit_factor >= 1.6 and report.payoff is not None and report.payoff > 0)


@pytest.mark.parametrize("p,b,k", [(np.nan, 2, .5), (.5, 0, .5), (1.1, 2, .5), (.5, 2, 5)])
def test_invalid_kelly_rejected(p, b, k):
    with pytest.raises(ValueError):
        Vanguard.kelly(p, b, k)


def test_half_kelly_and_negative_edge():
    assert Vanguard.kelly(.6, 2) == pytest.approx(.2)
    assert Vanguard.kelly(.1, 1) == 0


@pytest.mark.parametrize("market", list(Market))
def test_position_caps_costs_and_stops(market):
    state = LiveState(running=True)
    risk = Vanguard(state)
    assert risk.open(market, 100, .8, 2, 3, 1)
    assert 10000 - state.cash <= 10000 * LIMITS[market][0] + 1e-8
    assert not risk.open(market, 100, .8, 2, 3, 1)
    position = state.positions[0]
    assert position.stop == pytest.approx(position.entry - 4.5 if market == Market.COMMODITIES_FUT
                                         else position.entry * (1 - LIMITS[market][1]))
    risk.flatten({market: 100})
    assert not state.positions and state.equity < 10000
    assert state.cash == pytest.approx(10000 - 10000 * LIMITS[market][0] +
        position.quantity * 100 * (1 - IMPACT) * (1 - COMMISSION))


def test_kill_switch_flattens_and_persists_24h_lock(tmp_path):
    state = LiveState(running=True)
    risk = Vanguard(state)
    now = time.time()
    assert risk.open(Market.COMMODITIES_FUT, 100, .8, 2, 2, 1)
    state.cash -= 600
    assert not risk.guard({Market.COMMODITIES_FUT: 90}, now)
    assert not state.positions and not state.running
    assert state.locked_until == pytest.approx(now + 86400)
    path = tmp_path / "state.json"
    save_state(path, state)
    restored = LiveState.model_validate_json(path.read_text())
    assert restored.locked_until == state.locked_until
    assert not Vanguard(restored).guard({}, now + 3600)
    assert Vanguard(restored).guard({}, now + 86401)


def test_meme_partial_and_options_time_stop():
    state = LiveState(running=True)
    risk = Vanguard(state)
    risk.open(Market.MEME_SNIPER, 100, .8, 2, 2, 1)
    position = state.positions[0]
    original = position.quantity
    risk.monitor({Market.MEME_SNIPER: 210})
    assert position.partial_taken and position.quantity == original / 2
    risk.monitor({Market.MEME_SNIPER: 220})
    assert position.quantity == original / 2
    risk.open(Market.OPTIONS_0DTE, 100, .8, 2, 2, 1)
    risk.monitor({Market.MEME_SNIPER: 220, Market.OPTIONS_0DTE: 100}, time.time() + 901)
    assert [p.market for p in state.positions] == [Market.MEME_SNIPER]


def test_multi_split_has_single_shared_cash_pool():
    state = LiveState(running=True)
    risk = Vanguard(state)
    for market in Market:
        assert risk.open(market, 100, .8, 2, 2, 5)
    assert 10000 - state.cash == pytest.approx(10000 * sum(v[0] for v in LIMITS.values()) / 5)


@pytest.mark.parametrize("policy", ["flatten", "tight_trailing", "background"])
def test_hot_swap_open_position_policies(tmp_path, policy):
    runtime = Runtime(tmp_path / "state.json")
    runtime.state.running = True
    market = Market.CRYPTO_PERPS
    runtime.risk.open(market, runtime.prices()[market], .8, 2, 2, 1)
    controls = Controls(market=Market.MEME_SNIPER, switch_policy=policy)
    asyncio.run(runtime.configure(controls))
    if policy == "flatten":
        assert runtime.state.positions == []
    else:
        assert runtime.state.positions[0].tight_trailing == (policy == "tight_trailing")
    assert runtime.state.controls.market == Market.MEME_SNIPER


def test_bankroll_cannot_erase_losses(tmp_path):
    runtime = Runtime(tmp_path / "state.json")
    runtime.state.cash -= 1
    with pytest.raises(ValueError, match="PnL"):
        asyncio.run(runtime.configure(Controls(bankroll=20000)))


def test_control_api_all_modes_live_rejection_panic_and_persistence(tmp_path):
    runtime = Runtime(tmp_path / "state.json")
    with TestClient(create_app(runtime)) as client:
        html = client.get("/").text
        token = re.search("const token='([^']+)'", html).group(1)
        headers = {"X-Control-Token": token}
        assert client.post("/api/command", json={"action": "start"}).status_code == 403
        for market in Market:
            response = client.post("/api/controls", json=Controls(market=market).model_dump(mode="json"), headers=headers)
            assert response.status_code == 200
            assert response.json()["controls"]["market"] == market
        assert client.post("/api/controls", json={"execution": "LIVE_EXECUTION"}, headers=headers).status_code == 422
        assert client.post("/api/command", json={"action": "start"}, headers=headers).json()["running"]
        assert client.post("/api/command", json={"action": "panic"}, headers=headers).status_code == 200
        assert client.post("/api/command", json={"action": "start"}, headers=headers).status_code == 409
        state = client.get("/api/state").json()
        assert state["source"] == "SYNTHETIC_REPLAY" and len(state["reports"]) == 5
        assert state["positions"] == []
    saved = json.loads((tmp_path / "state.json").read_text())
    assert not saved["running"] and saved["locked_until"] > time.time()


def test_normalizer_blocks_bad_values():
    data = Ingestor().frames[Market.MEME_SNIPER].iloc[:20].copy()
    data.loc[data.index[-1], "close"] = np.nan
    with pytest.raises(ValueError):
        Ingestor.normalize(data)


def test_live_mode_and_invalid_state_are_rejected():
    with pytest.raises(ValidationError):
        Controls(execution="LIVE_EXECUTION")
    with pytest.raises(ValidationError):
        LiveState(cursors={Market.CRYPTO_PERPS: -1})


def test_rejected_strategies_cannot_trade_and_replay_does_not_rewind(tmp_path):
    runtime = Runtime(tmp_path / "state.json")
    asyncio.run(runtime.initialize())
    runtime.strategies.clear()
    asyncio.run(runtime.command("start"))
    before = runtime.state.cash
    asyncio.run(runtime.tick())
    assert runtime.state.positions == [] and runtime.state.cash == before
    assert runtime.state.cursors[Market.CRYPTO_PERPS] == 1501
    runtime.state.cursors[Market.CRYPTO_PERPS] = 2000
    asyncio.run(runtime.tick())
    assert not runtime.state.running and runtime.state.cursors[Market.CRYPTO_PERPS] == 2000
    with pytest.raises(ValueError, match="exhausted"):
        asyncio.run(runtime.command("start"))


def test_tick_uses_previous_close_and_current_open_before_current_close(tmp_path):
    from dataclasses import replace

    runtime = Runtime(tmp_path / "state.json")
    market = Market.CRYPTO_PERPS
    asyncio.run(runtime.initialize())
    strategy = runtime.brain.generate(market, 5, 20)[1]
    observed = []
    strategy.current_signal = lambda data: observed.append(len(data)) or {"signal": 1}
    runtime.strategies[market] = strategy
    runtime.reports[market] = replace(runtime.reports[market], approved=True, policy_verified=True,
                                      win_rate=.8, payoff=2, sizing_win_rate=.8, sizing_payoff=2)
    frame = runtime.ingestor.frames[market]
    frame.loc[1500, "open"] = 100
    frame.loc[1500, "close"] = 100
    asyncio.run(runtime.command("start"))
    asyncio.run(runtime.tick())
    assert observed == [1500]
    assert runtime.state.positions[0].entry == pytest.approx(100 * (1 + IMPACT))
    assert runtime.state.positions[0].quantity * 100 * (1 + IMPACT) * (1 + COMMISSION) == pytest.approx(400)


def test_persistent_fill_ledger_reconciles_partial_exits(tmp_path):
    state = LiveState(running=True)
    risk = Vanguard(state)
    market = Market.MEME_SNIPER
    risk.open(market, 100, .8, 2, 2, 1)
    risk.monitor({market: 210})
    risk.flatten({market: 40})
    assert [fill.side for fill in state.fills] == ["buy", "sell", "sell"]
    assert len({fill.position_id for fill in state.fills}) == 1
    assert sum(fill.net_pnl for fill in state.fills if fill.side == "sell") == pytest.approx(state.equity - 10000)
    path = tmp_path / "state.json"
    save_state(path, state)
    restored = LiveState.model_validate_json(path.read_text())
    assert restored.fills == state.fills


def test_policy_backtest_counts_partial_exits_as_one_trade():
    import pandas as pd
    from agent.coder_brain import BaseStrategy

    opens = np.array([100, 100, 40, 100, 100, 100, 100, 100], dtype=float)
    closes = np.array([100, 210, 40, 100, 100, 50, 100, 100], dtype=float)
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=8, tz="UTC"), "open": opens, "close": closes,
        "high": np.maximum(opens, closes) * 1.01, "low": np.minimum(opens, closes) * .99, "volume": 100,
    })
    strategy = BaseStrategy(2, 3)
    strategy.generate_signals = lambda data: data.assign(signal=[1, 0, 0, 1, 0, 0, 0, 0])
    result = Sandbox()._paper_replay(frame, strategy, Market.MEME_SNIPER, (.8, 2), .5, 365)
    assert result.total_trades == 2
    assert result.winning_trades == result.losing_trades == 1
    assert result.total_transaction_costs > 0
    assert result.final_capital < result.initial_capital


def test_gate_uses_unrounded_drawdown(monkeypatch):
    import pandas as pd
    from agent.coder_brain import BaseStrategy
    from src.backtesting.engine import BacktestResult

    result = BacktestResult(
        initial_capital=10000, final_capital=10119.89, return_pct=1.1989, total_trades=20,
        winning_trades=12, losing_trades=8, win_rate=60, max_drawdown_pct=8.0, fees_paid=10,
        equity_curve=[10000, 11000, 10119.89], sharpe_ratio=3, profit_factor=2,
        average_profit_per_trade=20, average_loss_per_trade=-10,
    )
    sandbox = Sandbox()
    monkeypatch.setattr(sandbox.engine, "run", lambda *args, **kwargs: result)
    report = sandbox.evaluate(pd.DataFrame({"is_synthetic": [True]}), BaseStrategy(2, 3), .04)
    assert report.max_drawdown > .08
    assert not report.approved


def test_tui_commands_and_cancellation_do_not_wait_for_stdin(tmp_path, monkeypatch):
    import os
    import sys
    from ui.control_box import terminal

    async def check():
        runtime = Runtime(tmp_path / "state.json")
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd)
        monkeypatch.setattr(sys, "stdin", stream)
        os.write(write_fd, b"1\nm\ns\np\nq\n")
        os.close(write_fd)
        await asyncio.wait_for(terminal(runtime), 2)
        assert runtime.state.controls.market == Market.MEME_SNIPER
        assert runtime.state.controls.multi_split_kelly and not runtime.state.running
        read_fd, write_fd = os.pipe()
        monkeypatch.setattr(sys, "stdin", os.fdopen(read_fd))
        task = asyncio.create_task(terminal(runtime))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, .5)
        os.close(write_fd)

    asyncio.run(check())


def test_policy_gate_is_required_even_when_ma_metrics_pass(tmp_path):
    from dataclasses import replace

    runtime = Runtime(tmp_path / "state.json")
    market = Market.CRYPTO_PERPS
    asyncio.run(runtime.initialize())
    strategy = runtime.brain.generate(market, 5, 20)[1]
    strategy.current_signal = lambda data: {"signal": 1}
    runtime.strategies[market] = strategy
    runtime.reports[market] = replace(runtime.reports[market], approved=True, policy_verified=False)
    asyncio.run(runtime.command("start"))
    asyncio.run(runtime.tick())
    assert runtime.state.fills == []
