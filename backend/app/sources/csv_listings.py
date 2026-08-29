from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _coerce(value: str | None) -> Any:
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_demo_listings() -> list[dict[str, Any]]:
    path = DATA_DIR / "listings_demo.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: _coerce(v) for k, v in row.items()} for row in csv.DictReader(f)]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    weight = pos - lo
    return values[lo] * (1 - weight) + values[hi] * weight


def summarize_prices(rows: list[dict[str, Any]], market: str | None = None) -> dict[str, Any]:
    filtered = [r for r in rows if not market or r.get("market") == market]
    prices: list[float] = []
    for row in filtered:
        try:
            value = float(row.get("price"))
            if math.isfinite(value):
                prices.append(value)
        except (TypeError, ValueError):
            continue

    if not prices:
        return {"count": 0, "p10": None, "p25": None, "median": None, "p75": None, "p90": None}

    return {
        "count": len(prices),
        "p10": round(_percentile(prices, 0.10), 2),
        "p25": round(_percentile(prices, 0.25), 2),
        "median": round(_percentile(prices, 0.50), 2),
        "p75": round(_percentile(prices, 0.75), 2),
        "p90": round(_percentile(prices, 0.90), 2),
    }
