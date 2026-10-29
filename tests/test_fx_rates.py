import io
import json

import pytest

from src.data import fx_rates


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), float("-inf"), 0, -1, None, "invalid"])
def test_fx_rejects_invalid_reference_rate(monkeypatch, rate):
    payload = {"rates": {"USD": rate}, "date": "2026-01-01"}
    monkeypatch.setattr(fx_rates, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeError):
        fx_rates.fetch_eur_usd_rate()


@pytest.mark.parametrize("reference_date", [None, "invalid", "2026-99-99"])
def test_fx_rejects_invalid_reference_date(monkeypatch, reference_date):
    payload = {"rates": {"USD": 1.1}, "date": reference_date}
    monkeypatch.setattr(fx_rates, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeError):
        fx_rates.fetch_eur_usd_rate()


def test_fx_keeps_provider_value_date_and_timeout(monkeypatch):
    requests = []
    def response(url, timeout):
        requests.append((url, timeout))
        return io.BytesIO(b'{"rates":{"USD":1.1},"date":"2026-01-01"}')
    monkeypatch.setattr(fx_rates, "urlopen", response)
    result = fx_rates.fetch_eur_usd_rate(timeout=2)
    assert result["rate"] == 1.1 and result["timestamp"] == "2026-01-01"
    assert requests == [("https://api.frankfurter.app/latest?from=EUR&to=USD", 2)]
