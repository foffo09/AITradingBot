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


def test_default_environment_settings_are_valid(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("TRADING_MODE", "paper")
    settings = AppSettings.from_env()
    assert settings.short_window < settings.long_window
    assert settings.initial_capital_usd > 0


def test_auto_trading_environment_flag_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AUTO_TRADE", "true")
    settings = AppSettings.from_env(tmp_path / "no-env-file")
    assert settings.auto_trade_enabled is False
