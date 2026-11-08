from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from config.settings import AppSettings
from src.broker.alpaca_client import AlpacaClient
from src.simulation.ledger import SimulationLedger

APP = Path(__file__).resolve().parents[1] / 'app.py'


def state_value(app, key, default=None):
    try:
        return app.session_state[key]
    except KeyError:
        return default


def widget(elements, prefix):
    return next(element for element in elements if element.label.startswith(prefix))


@pytest.fixture
def contexts(monkeypatch, tmp_path):
    paths = {scope: tmp_path / f'{scope}.sqlite3' for scope in ('demo', 'simulation', 'paper')}
    for scope, amount in [('demo', 1000), ('simulation', 2000)]:
        SimulationLedger(paths[scope]).initialize_account(initial_eur=amount, eur_usd_rate=1,
            fx_source='synthetic test fixture', fx_timestamp=datetime.now(timezone.utc).isoformat())
    settings = AppSettings(trading_mode='paper', alpaca_api_key='synthetic-key', alpaca_secret_key='synthetic-secret')
    monkeypatch.setattr(AppSettings, 'from_env', classmethod(lambda cls: settings))
    for scope in paths:
        monkeypatch.setenv(f'AI_TRADINGBOT_{scope.upper()}_DB_PATH', str(paths[scope]))
    calls = []
    account = dict(id='synthetic-account', status='ACTIVE', cash='54321', equity='55000', buying_power='55000',
                   last_equity='54000', trading_blocked=False, account_blocked=False)
    class Trading:
        def __init__(self, *args, **kwargs):
            assert kwargs['paper'] is True
            calls.append('construct-paper')
        def get_account(self):
            calls.append('account')
            return account
        def get_all_positions(self): return []
        def get_orders(self, **kwargs): return []
        def submit_order(self, *args, **kwargs):
            pytest.fail('Dashboard tests never submit orders')
    monkeypatch.setattr('src.broker.alpaca_client.TradingClient', Trading)
    def create(scope):
        app = AppTest.from_file(str(APP), default_timeout=30)
        app.session_state['ui_workspace'] = scope
        return app
    return create, calls, paths


def test_offline_workspaces_have_independent_balances_and_never_construct_sdk(contexts):
    create, calls, paths = contexts
    app = create('Demo').run()
    assert not app.exception
    assert widget(app.metric, 'Saldo disponibile Demo').value == '$1,000.00'
    widget(app.selectbox, 'Contesto').select('Simulazione').run()
    assert not app.exception
    assert widget(app.metric, 'Saldo disponibile Simulazione').value == '$2,000.00'
    widget(app.selectbox, 'Contesto').select('Demo').run()
    assert widget(app.metric, 'Saldo disponibile Demo').value == '$1,000.00'
    assert calls == []
    assert SimulationLedger(paths['demo']).account()['cash'] == 1000
    assert SimulationLedger(paths['simulation']).account()['cash'] == 2000


def test_switch_clears_paper_snapshot_automation_and_market_state(contexts):
    create, calls, paths = contexts
    app = create('Alpaca Paper').run()
    widget(app.button, 'Verifica e aggiorna conto Alpaca Paper').click().run()
    assert app.session_state['paper_verified'] is True
    app.session_state['paper_automation_active'] = True
    app.session_state['market_symbol'] = 'MSFT'
    app.session_state['market_quote'] = {'price': 987654.32}
    widget(app.selectbox, 'Contesto').select('Demo').run()
    assert not app.exception
    assert app.session_state['paper_automation_active'] is False
    assert not state_value(app, 'paper_verified', False)
    assert state_value(app, 'paper_snapshot') is None
    assert state_value(app, 'market_quote') is None
    assert all('54,321' not in metric.value for metric in app.metric)
    before = len(calls)
    widget(app.selectbox, 'Contesto').select('Simulazione').run()
    assert len(calls) == before


def test_paper_hides_local_ledger_operations_and_does_not_create_local_capital(contexts):
    create, calls, paths = contexts
    app = create('Alpaca Paper').run()
    assert not app.exception
    assert widget(app.checkbox, 'Usa serie sintetica demo').disabled is True
    assert not any(expander.label == 'Simulazione locale' for expander in app.expander)
    widget(app.button, 'Verifica e aggiorna conto Alpaca Paper').click().run()
    assert not app.exception
    assert widget(app.metric, 'Capitale iniziale Paper').value == 'N/D'
    assert widget(app.metric, 'P/L cumulativo Paper').value == 'N/D'
    assert widget(app.metric, 'Drawdown massimo Paper').value == 'N/D'
    assert widget(app.metric, 'Saldo disponibile Paper').value == '$54,321.00'
    assert SimulationLedger(paths['paper']).account() is None


@pytest.mark.parametrize('age', [timedelta(minutes=2), timedelta(seconds=-1)])
def test_old_or_future_snapshot_does_not_render_current_account_values(contexts, monkeypatch, age):
    create, calls, paths = contexts
    def snapshot(self):
        return {'account': {'status': 'ACTIVE', 'cash': '987654.32', 'equity': '987654.32'},
                'positions': [], 'orders': [], 'updated_at': (datetime.now(timezone.utc) - age).isoformat()}
    monkeypatch.setattr(AlpacaClient, 'get_paper_snapshot', snapshot)
    app = create('Alpaca Paper').run()
    widget(app.button, 'Verifica e aggiorna conto Alpaca Paper').click().run()
    assert not app.exception
    assert app.session_state['paper_verified'] is False
    assert all('987,654.32' not in metric.value for metric in app.metric)
    assert any('timestamp' in alert.value for alert in app.warning)


def test_unknown_paper_configuration_does_not_fall_back_to_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(AppSettings, 'from_env', classmethod(lambda cls: AppSettings(trading_mode='demo')))
    constructed = []
    monkeypatch.setattr(AlpacaClient, '__init__', lambda *args: constructed.append(1))
    app = AppTest.from_file(str(APP), default_timeout=30)
    app.session_state['ui_workspace'] = 'Alpaca Paper'
    app.run()
    assert not app.exception
    assert any('non configurato' in alert.value for alert in app.warning)
    assert constructed == []


def test_trade_history_is_not_shared_between_offline_workspaces(contexts):
    create, calls, paths = contexts
    ledger = SimulationLedger(paths['simulation'])
    ledger.buy(symbol='SPY', quantity=1, market_price=10, commission_bps=0, slippage_bps=0,
               max_trade_fraction=.1, max_exposure_fraction=.5, daily_loss_limit_fraction=.05,
               data_timestamp=datetime.now(timezone.utc).isoformat(), data_source='synthetic fixture',
               reason='isolated test')
    app = create('Simulazione').run()
    assert not app.exception
    assert SimulationLedger(paths['simulation']).history()
    widget(app.selectbox, 'Contesto').select('Demo').run()
    assert not app.exception
    assert SimulationLedger(paths['demo']).history() == []
    assert widget(app.metric, 'Saldo disponibile Demo').value == '$1,000.00'
    assert calls == []
