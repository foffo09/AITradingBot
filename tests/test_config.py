import os

import pytest

from config.settings import AppSettings


def test_missing_credentials_fallback_to_demo():
    settings = AppSettings(trading_mode="paper", alpaca_api_key=None, alpaca_secret_key=None, paper_trading_enabled=True)
    assert settings.trading_mode == "demo"
    assert settings.paper_trading_enabled is True
    assert settings.auto_trade_enabled is False


def test_live_mode_is_rejected_even_if_paper_flag_is_set():
    with pytest.raises(ValueError):
        AppSettings(
            trading_mode="live",
            alpaca_api_key="KEY",
            alpaca_secret_key="SECRET",
            paper_trading_enabled=True,
        )


def test_default_environment_settings_are_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("PAPER_MAX_DAILY_ORDERS", "7")
    settings = AppSettings.from_env(tmp_path / "nonexistent-test-env")
    assert settings.short_window < settings.long_window
    assert settings.initial_capital_usd > 0
    assert settings.paper_max_daily_orders == 7


def test_explicit_demo_mode_does_not_load_dotenv(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "demo")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    def unexpected_dotenv_load(*args, **kwargs):
        pytest.fail("Explicit demo mode must not load .env.")

    monkeypatch.setattr("config.settings.load_dotenv", unexpected_dotenv_load)
    settings = AppSettings.from_env()

    assert settings.trading_mode == "demo"
    assert settings.auto_trade_enabled is False
    assert settings.alpaca_api_key is None
    assert settings.alpaca_secret_key is None


def test_auto_trading_environment_flag_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AUTO_TRADE", "true")
    settings = AppSettings.from_env(tmp_path / "no-env-file")
    assert settings.auto_trade_enabled is False


def test_secret_values_are_redacted_in_repr_and_whitespace_is_trimmed():
    settings = AppSettings(
        trading_mode=" paper ",
        alpaca_api_key="  KEY123  ",
        alpaca_secret_key="  SECRET456  ",
        paper_trading_enabled=True,
    )
    assert settings.alpaca_api_key == "KEY123"
    assert settings.alpaca_secret_key == "SECRET456"
    rendered = repr(settings)
    assert "KEY123" not in rendered
    assert "SECRET456" not in rendered
    assert "<redacted>" in rendered


@pytest.mark.parametrize(
    "setting",
    [
        {"risk_max_trade_fraction": float("nan")},
        {"risk_max_exposure_fraction": float("inf")},
        {"daily_loss_limit_pct": float("nan")},
        {"risk_max_trade_fraction": None},
        {"risk_max_exposure_fraction": None},
        {"daily_loss_limit_pct": None},
        {"initial_capital_eur": None},
        {"eur_usd_rate": None},
        {"initial_capital_eur": 1e308, "eur_usd_rate": 2},
        {"paper_max_daily_orders": 0},
        {"paper_max_daily_orders": 101},
    ],
)
def test_non_finite_risk_configuration_is_rejected(setting):
    with pytest.raises(ValueError):
        AppSettings(**setting)
