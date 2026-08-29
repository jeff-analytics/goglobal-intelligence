from __future__ import annotations

import time
from typing import Any

import requests

PARTNER_REFERENCE_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
_CACHE: dict[str, Any] = {"loaded_at": 0.0, "rows": []}


def _first(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _normalize_row(row: dict[str, Any]) -> dict[str, str] | None:
    code = _first(row, ["id", "partnerCode", "PartnerCode", "M49", "m49", "code"])
    name = _first(row, ["text", "partnerDesc", "PartnerDesc", "name", "country", "areaDesc"])
    iso2 = _first(row, ["isoAlpha2", "ISOAlpha2", "iso2", "iso_2"])
    iso3 = _first(row, ["isoAlpha3", "ISOAlpha3", "iso3", "iso_3"])
    if code in (None, "") or name in (None, ""):
        return None
    return {
        "code": str(code).strip(),
        "name": str(name).strip(),
        "iso2": str(iso2 or "").strip().upper(),
        "iso3": str(iso3 or "").strip().upper(),
    }


def get_partner_reference(*, force: bool = False) -> list[dict[str, str]]:
    now = time.time()
    if _CACHE["rows"] and not force and now - float(_CACHE["loaded_at"]) < 24 * 3600:
        return list(_CACHE["rows"])
    response = requests.get(PARTNER_REFERENCE_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    raw_rows = payload.get("results", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    rows = [n for r in raw_rows if isinstance(r, dict) and (n := _normalize_row(r))]
    _CACHE["rows"] = rows
    _CACHE["loaded_at"] = now
    return list(rows)


def search_partners(query: str, *, limit: int = 12) -> list[dict[str, str]]:
    q = str(query or "").strip().casefold()
    if not q:
        return []
    rows = get_partner_reference()
    ranked: list[tuple[int, dict[str, str]]] = []
    for row in rows:
        name = row["name"].casefold()
        iso2 = row["iso2"].casefold()
        iso3 = row["iso3"].casefold()
        code = row["code"].casefold()
        score = None
        if q in {name, iso2, iso3, code}:
            score = 0
        elif name.startswith(q) or iso2.startswith(q) or iso3.startswith(q):
            score = 1
        elif q in name:
            score = 2
        if score is not None:
            ranked.append((score, row))
    ranked.sort(key=lambda x: (x[0], x[1]["name"].casefold()))
    return [row for _, row in ranked[: max(1, min(limit, 50))]]


def resolve_partner(query: str) -> dict[str, str] | None:
    q = str(query or "").strip().casefold()
    if not q:
        return None
    matches = search_partners(query, limit=20)
    exact = [r for r in matches if q in {r["name"].casefold(), r["iso2"].casefold(), r["iso3"].casefold(), r["code"].casefold()}]
    if len(exact) == 1:
        return exact[0]
    return matches[0] if len(matches) == 1 else None
