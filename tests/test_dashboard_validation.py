from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient, BrokerConnectionError
import src.broker.alpaca_client as alpaca_module
from src.simulation.ledger import SimulationLedger
from src.trading.paper_automation import PaperAutomationLog


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def widget(elements, label):
    return next(element for element in elements if element.label.startswith(label))


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    settings = AppSettings(
        trading_mode="demo",
        auto_trade_enabled=False,
        alpaca_api_key=None,
        alpaca_secret_key=None,
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setenv("AUTO_TRADE", "false")
    ledger_path = tmp_path / "dashboard-test.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_DEMO_DB_PATH", str(ledger_path))
    test_ledger = SimulationLedger(ledger_path)
    test_ledger.initialize_account(
        initial_eur=100,
        eur_usd_rate=1,
        fx_source="isolated test fixture",
        fx_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    original_ledger_init = SimulationLedger.__init__

    def isolated_ledger_init(self, database_path):
        original_ledger_init(self, ledger_path)

    monkeypatch.setattr(SimulationLedger, "__init__", isolated_ledger_init)
    submitted_orders = []
    monkeypatch.setattr(
        AlpacaClient,
        "submit_order",
        lambda *args, **kwargs: submitted_orders.append((args, kwargs)),
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert not app.exception
    return app, submitted_orders, ledger_path


def test_demo_dashboard_requires_isolated_database_before_ledger_initialization(
    monkeypatch,
):
    settings = AppSettings(trading_mode="demo", auto_trade_enabled=False)
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setenv("TRADING_MODE", "demo")
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    ledger_initializations = []
    monkeypatch.setattr(
        SimulationLedger,
        "__init__",
        lambda self, path: ledger_initializations.append(path),
    )

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert len(app.exception) == 1
    assert "requires an isolated database path" in app.exception[0].message
    assert ledger_initializations == []


def test_paper_dashboard_uses_dedicated_database_and_starts_with_bot_stopped(
    monkeypatch, tmp_path,
):
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="test-paper-key",
        alpaca_secret_key="test-paper-secret",
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    paper_path = tmp_path / "paper" / "paper.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(paper_path))
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    requested_paths = []
    original_ledger_init = SimulationLedger.__init__

    def isolated_ledger_init(self, database_path):
        requested_paths.append(Path(database_path))
        original_ledger_init(self, tmp_path / "paper-test.sqlite3")

    monkeypatch.setattr(SimulationLedger, "__init__", isolated_ledger_init)

    class FakeBroker:
        paper_client_configured = False

        def __init__(self, runtime_settings):
            self.settings = runtime_settings

        def get_instrument_availability(self, symbol):
            return {
                "visible": True,
                "data_available": "unverified",
                "paper_tradable": "unverified",
                "message": "mock unavailable",
            }

        def verify_connection(self):
            return {"connected": False, "message": "mock"}

        def get_paper_snapshot(self):
            raise BrokerConnectionError("mock unavailable")

    monkeypatch.setattr(alpaca_module, "AlpacaClient", FakeBroker)
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert not app.exception
    assert requested_paths == [paper_path]
    assert app.session_state["paper_automation_active"] is False


def test_paper_dashboard_displays_only_broker_snapshot_values_and_n_d_reasons(
    monkeypatch, tmp_path,
):
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="test-paper-key",
        alpaca_secret_key="test-paper-secret",
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    paper_path = tmp_path / "paper" / "paper.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(paper_path))
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    class SnapshotBroker:
        paper_client_configured = True

        def __init__(self, runtime_settings):
            self.settings = runtime_settings

        def get_instrument_availability(self, symbol):
            return {
                "visible": True,
                "data_available": "not tested",
                "paper_tradable": True,
                "fractionable": False,
                "min_order_size": "1",
                "min_trade_increment": "1",
                "message": "Mock asset metadata.",
            }

        def get_paper_snapshot(self):
            return {
                "account": {
                    "status": "ACTIVE",
                    "cash": "125.00",
                    "equity": "150.00",
                    "buying_power": "125.00",
                    "last_equity": "149.00",
                },
                "positions": [{
                    "symbol": "AAPL",
                    "qty": "1",
                    "qty_available": "1",
                    "avg_entry_price": "20",
                    "current_price": "25",
                    "market_value": "25",
                    "unrealized_pl": "5",
                    "unrealized_plpc": "0.25",
                }],
                "orders": [{
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": "1",
                    "filled_qty": "0.5",
                    "status": "partially_filled",
                    "submitted_at": "2026-10-11T10:00:00+00:00",
                }],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    monkeypatch.setattr(alpaca_module, "AlpacaClient", SnapshotBroker)
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert not app.exception
    assert app.session_state["paper_automation_active"] is False
    widget(app.button, "Verifica e aggiorna conto Alpaca Paper").click().run()

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Saldo in contanti (Paper)"] == "$125.00"
    assert metrics["Equity Alpaca Paper"] == "$150.00"
    assert metrics["Liquidità utilizzabile (buying power)"] == "$125.00"
    assert metrics["Capitale investito (valore posizioni)"] == "$25.00"
    assert metrics["P/L non realizzato Paper"] == "$5.00"
    assert metrics["P/L realizzato Paper"] == "N/D"
    assert metrics["P/L totale Paper"] == "N/D"
    assert any("P/L realizzato complessivo" in metric.help for metric in app.metric)
    assert any("capitale iniziale affidabile" in metric.help for metric in app.metric)
    assert any("pending: 1" in item.value for item in app.caption)
    assert app.session_state["paper_verified"] is True
    assert app.session_state["paper_automation_active"] is False


def test_paper_automation_requires_explicit_start_and_stop_is_persisted(
    monkeypatch, tmp_path,
):
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="test-paper-key",
        alpaca_secret_key="test-paper-secret",
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    paper_path = tmp_path / "paper" / "paper.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(paper_path))
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    submitted_orders = []

    class AutomationBroker:
        paper_client_configured = True

        def __init__(self, runtime_settings):
            self.settings = runtime_settings

        def get_instrument_availability(self, symbol):
            return {
                "visible": True,
                "data_available": "not tested",
                "paper_tradable": True,
                "fractionable": True,
                "min_order_size": "0.000001",
                "min_trade_increment": "0.000001",
                "message": "Mock paper asset.",
            }

        def get_paper_snapshot(self):
            return {
                "account": {
                    "status": "ACTIVE",
                    "cash": "10000",
                    "equity": "10000",
                    "buying_power": "10000",
                    "last_equity": "10000",
                    "trading_blocked": False,
                    "account_blocked": False,
                },
                "positions": [],
                "orders": [],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        def verify_connection(self):
            return {"connected": True}

        def is_connected(self):
            return True

        def get_account(self):
            return {
                "status": "ACTIVE",
                "cash": "10000",
                "equity": "10000",
                "buying_power": "10000",
                "last_equity": "10000",
                "trading_blocked": False,
                "account_blocked": False,
            }

        def get_positions(self):
            return []

        def get_orders(self):
            return []

        def submit_order(self, **kwargs):
            submitted_orders.append(kwargs)

        def get_market_data(
            self, symbol, timeframe="1Day", period="3M", limit=1000, start_time=None,
        ):
            if start_time is not None:
                return pd.DataFrame(columns=[
                    "timestamp", "open", "high", "low", "close", "volume",
                ])
            end = pd.Timestamp.now(tz="UTC").floor("s")
            return pd.DataFrame({
                "timestamp": pd.date_range(end=end, periods=40, freq="D"),
                "open": [100.0] * 40,
                "high": [101.0] * 40,
                "low": [99.0] * 40,
                "close": [100.0] * 40,
                "volume": [1000] * 40,
            })

        def get_latest_quote(self, symbol):
            return {
                "bid": 99.99,
                "ask": 100.01,
                "price": 100,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "mock paper feed",
            }

    monkeypatch.setattr(alpaca_module, "AlpacaClient", AutomationBroker)
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["paper_automation_active"] is False
    widget(app.button, "Verifica e aggiorna conto Alpaca Paper").click().run()
    widget(app.checkbox, "Usa serie sintetica demo").set_value(False).run()
    widget(app.button, "Carica dati / applica selezione").click().run()

    assert not app.exception
    assert widget(app.button, "Avvia automazione Paper").disabled is False
    widget(app.button, "Avvia automazione Paper").click().run()

    assert not app.exception
    assert app.session_state["paper_automation_active"] is True
    assert not submitted_orders
    app.run()
    assert not app.exception
    widget(app.button, "Arresto immediato").click().run()

    assert not app.exception
    assert app.session_state["paper_automation_active"] is False
    assert not submitted_orders
    decisions = [
        event["decision"]
        for event in PaperAutomationLog(paper_path).recent()
    ]
    assert decisions[0] == "stopped"
    assert "no_signal" in decisions


def test_paper_path_cannot_alias_the_demo_database(monkeypatch, tmp_path):
    settings = AppSettings(
        trading_mode="paper",
        alpaca_api_key="test-paper-key",
        alpaca_secret_key="test-paper-secret",
        paper_trading_enabled=True,
    )
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    shared_path = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(shared_path))
    monkeypatch.setenv("AI_TRADINGBOT_DEMO_DB_PATH", str(shared_path))
    ledger_initializations = []
    monkeypatch.setattr(
        SimulationLedger,
        "__init__",
        lambda self, path: ledger_initializations.append(path),
    )

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert len(app.exception) == 1
    assert "Paper and demo modes must use separate database files" in app.exception[0].message
    assert ledger_initializations == []


def test_paper_configuration_fallback_does_not_open_paper_or_personal_ledger(
    monkeypatch, tmp_path,
):
    settings = AppSettings(trading_mode="demo", auto_trade_enabled=False)
    monkeypatch.setattr(
        AppSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setenv("AI_TRADINGBOT_PAPER_DB_PATH", str(tmp_path / "paper.sqlite3"))
    monkeypatch.delenv("AI_TRADINGBOT_DEMO_DB_PATH", raising=False)
    ledger_initializations = []
    monkeypatch.setattr(
        SimulationLedger,
        "__init__",
        lambda self, path: ledger_initializations.append(path),
    )

    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()

    assert len(app.exception) == 1
    assert "Paper configuration was not available" in app.exception[0].message
    assert ledger_initializations == []


def test_dashboard_starts_and_reports_unavailable_real_market_data(dashboard, monkeypatch):
    app, _, _ = dashboard
    quote_requests = []
    monkeypatch.setattr(
        AlpacaClient,
        "get_latest_quote",
        lambda self, symbol: quote_requests.append(symbol),
    )
    assert app.session_state["paper_automation_active"] is False
    automation_button = widget(app.button, "Avvia automazione Paper")
    assert automation_button.disabled is True
    widget(app.button, "Carica dati / applica selezione").click().run()
    assert not app.exception
    assert any(
        "Dati non disponibili per la selezione corrente" in item.value
        for item in app.warning
    )
    assert "Choose the explicitly labeled demo data option" in app.session_state[
        "market_load_error"
    ]
    assert any(
        "Walk-forward non disponibile" in item.value
        for item in app.info
    )
    assert not any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert not any("paper order" in str(item) for item in app.exception)
    assert quote_requests == []


def test_live_quote_fragment_uses_current_selection_and_strategy_with_short_history(
    dashboard, monkeypatch,
):
    app, submitted_orders, _ = dashboard
    now = pd.Timestamp.now(tz="UTC").floor("s")
    market_bars = pd.DataFrame({
        "timestamp": pd.date_range(end=now, periods=3, freq="D"),
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": [100.5, 101.5, 102.5],
        "volume": [1000, 1100, 1200],
    })
    market_requests = []
    quote_requests = []

    def get_market_data(
        self, symbol, timeframe="1Day", period="3M", limit=1000, start_time=None,
    ):
        market_requests.append((symbol, timeframe, period, limit, start_time))
        return market_bars.iloc[0:0].copy() if start_time is not None else market_bars.copy()

    def get_latest_quote(self, symbol):
        quote_requests.append(symbol)
        return {
            "price": 102.6,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "source": "mock Alpaca feed",
        }

    monkeypatch.setattr(AlpacaClient, "get_market_data", get_market_data)
    monkeypatch.setattr(AlpacaClient, "get_latest_quote", get_latest_quote)
    widget(app.number_input, "Media mobile breve").set_value(2).run()
    widget(app.number_input, "Media mobile lunga").set_value(5).run()
    widget(app.checkbox, "Mostra RSI (14)").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()

    assert not app.exception
    assert len(market_requests) == 2
    assert market_requests[0][:4] == ("SPY", "1Day", "3M", None)
    assert market_requests[0][4] is None
    assert market_requests[1][:4] == ("SPY", "1Day", "1M", 100)
    assert market_requests[1][4] is not None
    assert quote_requests == ["SPY"]
    assert app.session_state["market_quote"]["source"] == "mock Alpaca feed"
    assert any(
        "Dati insufficienti per calcolare le due medie mobili" in item.value
        for item in app.warning
    )
    assert submitted_orders == []


def test_dashboard_marks_explicit_demo_prices_as_synthetic(dashboard):
    app, _, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    assert not app.exception
    assert any("SINTETICI — SOLO DEMO" in item.value for item in app.info)
    assert any("Serie sintetica generata localmente" in item.value for item in app.warning)
    assert app.session_state["market_quality"] == "synthetic"
    assert app.session_state["data_availability"]["data_available"] == "unverified"
    assert "availability is not verified" in app.session_state["data_availability"]["message"]
    assert app.session_state["market_frame"]["is_synthetic"].all()


def test_dashboard_rejects_invalid_strategy_windows_without_traceback(dashboard):
    app, _, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.number_input, "Media mobile breve").set_value(30).run()
    assert not app.exception
    assert any(
        "Strategia non disponibile" in item.value
        for item in app.error
    )


def test_dashboard_reports_insufficient_demo_bars_without_traceback(dashboard):
    app, _, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.selectbox, "Periodo grafico").set_value("1M").run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.number_input, "Media mobile lunga").set_value(31).run()

    assert not app.exception
    assert any(
        "Dati insufficienti per calcolare le due medie mobili" in item.value
        for item in app.warning
    )


def test_changing_market_selection_hides_prior_backtest_result(dashboard):
    app, _, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui backtest").click().run()
    assert not app.exception
    assert app.session_state["backtest_result"]
    assert any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert any(metric.label == "Commissioni" for metric in app.metric)
    assert any(metric.label == "Spread stimato" for metric in app.metric)
    assert any(metric.label == "Slippage stimato" for metric in app.metric)
    assert any(metric.label == "Buy & hold finale" for metric in app.metric)
    assert any(metric.label == "Sharpe (rf 0%)" for metric in app.metric)
    assert any(metric.label == "Sharpe buy & hold" for metric in app.metric)
    assert any(metric.label == "Delta rendimento vs buy & hold" for metric in app.metric)
    assert any(
        metric.label == "Costi totali buy & hold (incl. liquidazione stimata)"
        for metric in app.metric
    )

    widget(app.selectbox, "Strumento da analizzare").set_value("QQQ").run()
    assert not app.exception
    assert any(
        "La selezione dei dati è cambiata" in item.value
        for item in app.info
    )
    assert not any(metric.label == "P/L lordo realizzato" for metric in app.metric)


def test_dashboard_backtest_invalidates_on_interval_period_and_strategy_changes(dashboard):
    app, _, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui backtest").click().run()
    assert not app.exception
    assert app.session_state["backtest_result"]

    widget(app.selectbox, "Periodo grafico").set_value("6M").run()
    assert not any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert any("La selezione dei dati è cambiata" in item.value for item in app.info)

    widget(app.selectbox, "Periodo grafico").set_value("3M").run()
    widget(app.number_input, "Media mobile breve").set_value(9).run()
    assert not any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert any("riesegui il backtest" in item.value for item in app.info)

    widget(app.number_input, "Media mobile breve").set_value(10).run()
    assert any(metric.label == "P/L lordo realizzato" for metric in app.metric)

    widget(app.selectbox, "Intervallo dati").set_value("1Week").run()
    assert not any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert any("La selezione dei dati è cambiata" in item.value for item in app.info)


def test_walk_forward_dashboard_uses_selected_synthetic_data_without_broker_or_ledger_writes(
    dashboard, monkeypatch,
):
    app, submitted_orders, ledger_path = dashboard
    broker_reads = []
    monkeypatch.setattr(
        AlpacaClient,
        "get_market_data",
        lambda *args, **kwargs: broker_reads.append(("market_data", args, kwargs)),
    )
    monkeypatch.setattr(
        AlpacaClient,
        "get_latest_quote",
        lambda *args, **kwargs: broker_reads.append(("latest_quote", args, kwargs)),
    )
    ledger = SimulationLedger(ledger_path)
    account_before = ledger.account()
    history_before = ledger.history()

    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()

    assert not app.exception
    result = app.session_state["walk_forward_result"]
    assert result.data_source.startswith("synthetic:")
    assert len(result.folds) > 0
    assert any("SINTETICI — SOLO DEMO" in item.value for item in app.info)
    assert any(
        "Dati OOS: synthetic · SPY · 1Day · 3M · fonte:" in item.value
        for item in app.info
    )
    assert any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert any(metric.label == "Fold esclusi" for metric in app.metric)
    metric_labels = [metric.label for metric in app.metric]
    assert "MA scelte (training)" in metric_labels
    assert "Rendimento strategia OOS" in metric_labels
    assert "Rendimento buy & hold OOS" in metric_labels
    assert "Delta vs benchmark" in metric_labels
    fold_periods = [
        item.value
        for item in app.markdown
        if item.value.startswith("**Fold ")
    ]
    assert len(fold_periods) == len(result.folds)
    assert "Training:" in fold_periods[0] and "Test OOS:" in fold_periods[0]
    assert any("Aggregato OOS non calcolato" in item.value for item in app.warning)
    assert submitted_orders == []
    assert broker_reads == []
    assert ledger.account() == account_before
    assert ledger.history() == history_before


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("Periodo grafico", "6M"),
        ("Intervallo dati", "1Week"),
        ("Strumento da analizzare", "QQQ"),
    ],
)
def test_walk_forward_results_are_hidden_after_market_selection_changes(
    dashboard, label, value,
):
    app, submitted_orders, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()
    assert not app.exception
    assert app.session_state["walk_forward_result"].folds

    widget(app.selectbox, label).set_value(value).run()
    assert not app.exception
    assert any(
        "Walk-forward non disponibile" in item.value
        for item in app.info
    )
    assert not any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert submitted_orders == []


def test_walk_forward_results_are_hidden_when_fold_parameters_change(dashboard):
    app, submitted_orders, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()
    assert not app.exception
    assert any(metric.label == "Fold OOS validi" for metric in app.metric)

    widget(app.number_input, "Barre per training").set_value(40).run()
    assert not app.exception
    assert not any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert any(
        "risultati walk-forward precedenti nascosti" in item.value
        for item in app.info
    )
    assert submitted_orders == []


def test_traditional_and_walk_forward_results_remain_separate_and_invalidate_independently(
    dashboard,
):
    app, submitted_orders, _ = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui backtest").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()

    assert not app.exception
    assert app.session_state["backtest_result"]
    assert app.session_state["walk_forward_result"].folds
    assert any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert any(
        "Backtest in-sample ≠ performance fuori campione ≠ risultati futuri"
        in item.value
        for item in app.warning
    )

    widget(app.number_input, "Barre per training").set_value(40).run()
    assert not app.exception
    assert any(metric.label == "P/L lordo realizzato" for metric in app.metric)
    assert not any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert any(
        "risultati walk-forward precedenti nascosti" in item.value
        for item in app.info
    )
    assert submitted_orders == []


def test_walk_forward_dashboard_blocks_insufficient_market_history(
    dashboard, monkeypatch,
):
    from src.data.market_data import generate_synthetic_market_data

    app, submitted_orders, _ = dashboard
    original_generate = generate_synthetic_market_data

    def short_synthetic_series(*, symbol, periods):
        return original_generate(symbol=symbol, periods=min(periods, 23))

    monkeypatch.setattr(
        "src.data.market_data.generate_synthetic_market_data",
        short_synthetic_series,
    )
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()

    assert not app.exception
    assert any("Campione insufficiente" in item.value for item in app.warning)
    assert not any(
        button.label == "Esegui valutazione walk-forward"
        for button in app.button
    )
    assert submitted_orders == []


def test_walk_forward_dashboard_displays_unavailable_risk_metrics_explicitly(
    dashboard, monkeypatch,
):
    from src.data.market_data import generate_synthetic_market_data

    app, _, _ = dashboard
    original_generate = generate_synthetic_market_data

    def constant_synthetic_series(*, symbol, periods):
        data = original_generate(symbol=symbol, periods=periods)
        data[["open", "high", "low", "close"]] = 100.0
        return data

    monkeypatch.setattr(
        "src.data.market_data.generate_synthetic_market_data",
        constant_synthetic_series,
    )
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()

    assert not app.exception
    volatility_metrics = [
        metric for metric in app.metric
        if metric.label == "Volatilità strategia ann."
    ]
    sharpe_metrics = [
        metric for metric in app.metric
        if metric.label == "Sharpe strategia (rf 0%)"
    ]
    assert len(volatility_metrics) == len(app.session_state["walk_forward_result"].folds)
    assert len(sharpe_metrics) == len(app.session_state["walk_forward_result"].folds)
    assert all(metric.value == "n/d" for metric in volatility_metrics)
    assert all(metric.value == "n/d" for metric in sharpe_metrics)


def test_walk_forward_dashboard_shows_excluded_fold_reason(dashboard, monkeypatch):
    from src.backtesting.engine import BacktestEngine

    app, _, _ = dashboard
    original_run = BacktestEngine.run

    def reject_test_slices(self, data, **kwargs):
        if len(data) == 15:
            raise ValueError("test fixture excludes this fold")
        return original_run(self, data, **kwargs)

    monkeypatch.setattr(BacktestEngine, "run", reject_test_slices)
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.button, "Esegui valutazione walk-forward").click().run()

    assert not app.exception
    result = app.session_state["walk_forward_result"]
    assert len(result.folds) == 0
    assert len(result.excluded_folds) == 4
    assert any(metric.label == "Fold OOS validi" for metric in app.metric)
    assert any(metric.label == "Fold esclusi" for metric in app.metric)
    assert any("test fixture excludes this fold" in item.value for item in app.error)


def test_simulated_trade_persists_without_broker_submission(dashboard):
    app, submitted_orders, ledger_path = dashboard
    widget(app.checkbox, "Usa serie sintetica demo").set_value(True).run()
    widget(app.button, "Carica dati / applica selezione").click().run()
    widget(app.number_input, "Quantità da acquistare").set_value(0.01)
    widget(app.button, "Conferma acquisto simulato").click().run()

    assert not app.exception
    assert any(
        "Acquisto registrato nella simulazione locale" in item.value
        for item in app.success
    )
    assert submitted_orders == []

    widget(app.button, "Conferma vendita simulata").click().run()
    assert not app.exception
    assert any(
        "Vendita registrata localmente" in item.value
        for item in app.success
    )
    assert submitted_orders == []

    restored_ledger = SimulationLedger(ledger_path)
    account = restored_ledger.account()
    history = restored_ledger.history()
    assert account is not None
    assert account["cash"] > 0
    assert len(history) == 1
    assert history[0]["status"] == "closed"
    assert history[0]["symbol"] == "SPY"
    assert history[0]["net_pnl"] is not None
    summary = restored_ledger.summary(commission_bps=5, slippage_bps=5, spread_bps=0)
    assert summary["open_positions"] == 0
    assert summary["closed_trades"] == 1
    assert summary["cash"] == pytest.approx(account["cash"])
    assert submitted_orders == []

    restarted_app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
    assert not restarted_app.exception
    restarted_ledger = SimulationLedger(ledger_path)
    assert restarted_ledger.account() == account
    assert restarted_ledger.history() == history
    restarted_summary = restarted_ledger.summary(
        commission_bps=5, slippage_bps=5, spread_bps=0
    )
    assert restarted_summary["realized_pnl"] == pytest.approx(summary["realized_pnl"])
    assert restarted_summary["cash"] == pytest.approx(summary["cash"])
    assert submitted_orders == []
