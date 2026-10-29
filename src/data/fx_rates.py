from __future__ import annotations

import json
import math
from datetime import date
from urllib.request import urlopen


def fetch_eur_usd_rate(timeout: float = 4.0) -> dict[str, str | float]:
    """Fetch the latest published EUR/USD reference rate from Frankfurter."""
    url = "https://api.frankfurter.app/latest?from=EUR&to=USD"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Cambio EUR/USD non disponibile dalla fonte Frankfurter.") from exc
    try:
        rate = float(payload["rates"]["USD"])
        rate_date = date.fromisoformat(str(payload["date"])).isoformat()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("Risposta EUR/USD non valida dalla fonte Frankfurter.") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise RuntimeError("La fonte EUR/USD ha restituito un tasso non valido.")
    return {"rate": rate, "timestamp": rate_date, "source": "Frankfurter API (ECB reference rate)"}
