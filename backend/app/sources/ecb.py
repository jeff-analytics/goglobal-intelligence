from __future__ import annotations

import csv
from io import StringIO
from typing import Any

import requests

from ..source_runtime import cache_key, cached_call

ECB_BASE = "https://data-api.ecb.europa.eu/service/data/EXR"


def fetch_eur_reference_rate(currency: str, start_period: str | None = None) -> dict[str, Any]:
    currency = currency.upper()
    if currency == "EUR":
        return {"currency": "EUR", "base": "EUR", "rate": 1.0, "date": None, "source": "ECB"}

    key = f"D.{currency}.EUR.SP00.A"
    params = {"format": "csvdata"}
    if start_period:
        params["startPeriod"] = start_period
    url = f"{ECB_BASE}/{key}"
    cache_id = cache_key(url, params)

    def network_fetch():
        response = requests.get(url, params=params, timeout=12)
        response.raise_for_status()
        return response.text

    text, _meta = cached_call(
        provider="ECB",
        key=cache_id,
        fetcher=network_fetch,
        ttl_seconds=6 * 60 * 60,
        stale_ttl_seconds=3 * 24 * 60 * 60,
    )
    rows = list(csv.DictReader(StringIO(str(text))))
    rows = [r for r in rows if r.get("TIME_PERIOD") and r.get("OBS_VALUE")]
    if not rows:
        raise ValueError(f"No ECB rate returned for {currency}")

    rows.sort(key=lambda r: r["TIME_PERIOD"])
    last = rows[-1]
    return {
        "currency": currency,
        "base": "EUR",
        "rate": float(last["OBS_VALUE"]),
        "date": str(last["TIME_PERIOD"]),
        "source": "ECB",
        "series": key,
    }


def convert(amount: float, from_currency: str, to_currency: str, start_period: str | None = None) -> dict[str, Any]:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    if from_currency == to_currency:
        return {"amount": amount, "converted": amount, "rate": 1.0, "from": from_currency, "to": to_currency}

    fr = fetch_eur_reference_rate(from_currency, start_period)
    to = fetch_eur_reference_rate(to_currency, start_period)
    eur_amount = amount / fr["rate"]
    converted = eur_amount * to["rate"]
    return {
        "amount": amount,
        "converted": round(converted, 6),
        "rate": round(converted / amount, 8) if amount else None,
        "from": from_currency,
        "to": to_currency,
        "as_of": to.get("date") or fr.get("date"),
        "source": "ECB",
    }
