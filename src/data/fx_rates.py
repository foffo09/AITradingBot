from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
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
        raw_rate = payload["rates"]["USD"]
        if isinstance(raw_rate, bool):
            raise ValueError("A reference rate must be numeric, not boolean.")
        rate = float(raw_rate)
        reference_date = date.fromisoformat(str(payload["date"]))
        if reference_date > datetime.now(timezone.utc).date():
            raise ValueError("A reference rate date cannot be in the future.")
        rate_date = reference_date.isoformat()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("Risposta EUR/USD non valida dalla fonte Frankfurter.") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise RuntimeError("La fonte EUR/USD ha restituito un tasso non valido.")
    return {"rate": rate, "timestamp": rate_date, "source": "Frankfurter API (ECB reference rate)"}
