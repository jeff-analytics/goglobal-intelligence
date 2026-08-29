from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests

from ..market_support import source_meta
from ..source_runtime import cache_key, cached_call

USITC_SEARCH = "https://hts.usitc.gov/reststop/search"
UK_TARIFF_BASE = "https://www.trade-tariff.service.gov.uk/uk/api"

EU_CODES = {"DE", "FR", "IT", "ES", "NL"}


def _official_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    safe_params = params or {}
    key = cache_key(url, safe_params, "json")
    def fetcher():
        response = requests.get(url, params=safe_params or None, timeout=15, headers={"Accept": "application/json", "User-Agent": "BorderMargin/5.3.8"})
        response.raise_for_status()
        return response.json()
    payload, _meta = cached_call(provider="Official Tariff", key=key, fetcher=fetcher, ttl_seconds=6*60*60, stale_ttl_seconds=7*24*60*60)
    return payload


def _official_text(url: str, *, params: dict[str, Any] | None = None) -> tuple[str, str]:
    safe_params = params or {}
    key = cache_key(url, safe_params, "text")
    resolved_url = [url]
    def fetcher():
        response = requests.get(url, params=safe_params or None, timeout=15, headers={"User-Agent": "BorderMargin/5.3.8"})
        response.raise_for_status()
        resolved_url[0] = response.url
        return {"text": response.text, "url": response.url}
    payload, _meta = cached_call(provider="Official Tariff", key=key, fetcher=fetcher, ttl_seconds=6*60*60, stale_ttl_seconds=7*24*60*60)
    if isinstance(payload, dict):
        return str(payload.get("text") or ""), str(payload.get("url") or url)
    return str(payload or ""), resolved_url[0]


def _clean_code(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _numeric_rate(value: Any) -> float | None:
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value)).strip()
    if not text:
        return None
    if text.lower() == "free":
        return 0.0
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*", text)
    return float(m.group(1)) if m else None


def _flatten_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "data", "items", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    # Some JSON:API payloads return one data object and an included array.
    rows: list[dict[str, Any]] = []
    if isinstance(payload.get("data"), dict):
        rows.append(payload["data"])
    if isinstance(payload.get("included"), list):
        rows.extend(x for x in payload["included"] if isinstance(x, dict))
    return rows


def lookup_us_hts(code: str) -> dict[str, Any]:
    clean = _clean_code(code)
    if len(clean) < 6:
        return {"status": "needs_local_code", "rate": None, "candidates": [], "source": "USITC HTS", "note": "Confirm at least HS6 first."}
    last_error: Exception | None = None
    payload = None
    # The public HTS site has used both query and keyword names across clients.
    for params in ({"query": clean}, {"keyword": clean}):
        try:
            payload = _official_json(USITC_SEARCH, params=params)
            break
        except Exception as exc:
            last_error = exc
    if payload is None:
        return {"status": "error", "rate": None, "candidates": [], "source": "USITC HTS", "error": str(last_error)}

    candidates = []
    for row in _flatten_rows(payload):
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else row
        hts = attrs.get("htsno") or attrs.get("htsNumber") or attrs.get("hts_number") or attrs.get("number")
        hts_clean = _clean_code(str(hts or ""))
        if not hts_clean or not hts_clean.startswith(clean[:6]):
            continue
        general = attrs.get("general") or attrs.get("generalRate") or attrs.get("general_rate") or attrs.get("generalRateOfDuty")
        desc = attrs.get("description") or attrs.get("descriptionText") or attrs.get("articleDescription") or ""
        candidates.append({
            "code": str(hts or ""),
            "description": re.sub(r"<[^>]+>", " ", str(desc)).strip(),
            "general_rate_text": general,
            "rate": _numeric_rate(general),
            "special_rate_text": attrs.get("special") or attrs.get("specialRate"),
            "other_rate_text": attrs.get("other") or attrs.get("otherRate"),
        })
    numeric = [c for c in candidates if c.get("rate") is not None]
    exact = [c for c in numeric if _clean_code(c.get("code")) == clean]
    chosen = exact[0] if len(exact) == 1 else numeric[0] if len(numeric) == 1 else None
    return {
        "status": "resolved" if chosen else "candidates",
        "rate": chosen.get("rate") if chosen else None,
        "rate_text": chosen.get("general_rate_text") if chosen else None,
        "local_code": chosen.get("code") if chosen else None,
        "candidates": candidates[:30],
        "source": "USITC HTS",
        "source_type": "official-current",
        "lookup_url": f"https://hts.usitc.gov/search?query={quote(clean)}",
        "note": "General duty rate only. Chapter 99 and origin-specific additional duties require separate review.",
    }


def _uk_measure_rows(payload: Any) -> list[dict[str, Any]]:
    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("included"), list):
        for item in payload["included"]:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").lower()
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            if "measure" in typ or "duty" in typ:
                rows.append({**attrs, "_type": typ})
    return rows


def lookup_uk_tariff(code: str) -> dict[str, Any]:
    clean = _clean_code(code)
    lookup_url = f"https://www.trade-tariff.service.gov.uk/commodities/{clean}" if clean else "https://www.trade-tariff.service.gov.uk/"
    if len(clean) < 10:
        return {
            "status": "needs_local_code", "rate": None, "candidates": [], "source": "GOV.UK Trade Tariff",
            "source_type": "official-current", "lookup_url": lookup_url,
            "note": "UK duty is applied to the declarable commodity code. Confirm the UK commodity code before using an official current rate.",
        }
    payload = None
    last_error: Exception | None = None
    for url in (f"{UK_TARIFF_BASE}/commodities/{clean}.json", f"{UK_TARIFF_BASE}/commodities/{clean}"):
        try:
            payload = _official_json(url)
            break
        except Exception as exc:
            last_error = exc
    if payload is None:
        return {"status": "error", "rate": None, "source": "GOV.UK Trade Tariff", "source_type": "official-current", "lookup_url": lookup_url, "error": str(last_error)}

    measures = _uk_measure_rows(payload)
    candidates = []
    for row in measures:
        duty = row.get("duty_expression") or row.get("dutyExpression") or row.get("duty") or row.get("formatted_duty_expression")
        if duty is None:
            continue
        candidates.append({
            "measure_type": row.get("measure_type_description") or row.get("measureTypeDescription") or row.get("_type"),
            "duty_text": str(duty),
            "rate": _numeric_rate(duty),
        })
    numeric = [x for x in candidates if x.get("rate") is not None]
    chosen = numeric[0] if len(numeric) == 1 else None
    return {
        "status": "resolved" if chosen else "candidates",
        "rate": chosen.get("rate") if chosen else None,
        "rate_text": chosen.get("duty_text") if chosen else None,
        "local_code": clean,
        "candidates": candidates[:30],
        "source": "GOV.UK Trade Tariff",
        "source_type": "official-current",
        "lookup_url": lookup_url,
        "note": "If multiple measures apply, review the official tariff page before using a single numeric duty rate.",
    }




def lookup_au_tariff(code: str) -> dict[str, Any]:
    clean = _clean_code(code)
    meta = source_meta("AU")
    lookup_url = meta.get("tariff_url")
    if len(clean) < 6:
        return {"status":"needs_local_code","rate":None,"source":meta.get("tariff_source"),"source_type":"official-current","lookup_url":lookup_url,"note":"Confirm at least HS6 before checking the Australian Working Tariff."}
    # ABF exposes the current Schedule 3 as public HTML. Querying the HS term
    # keeps this provider source-backed without bundling a stale tariff table.
    try:
        html_text, resolved_url = _official_text(f"{lookup_url}/schedule-3", params={"hs":clean})
        html=re.sub(r"\s+"," ",html_text)
        variants=[clean, f"{clean[:4]}.{clean[4:6]}"]
        pos=-1
        for v in variants:
            pos=html.find(v)
            if pos>=0: break
        if pos>=0:
            chunk=re.sub(r"<[^>]+>"," ",html[pos:pos+2200])
            free=re.search(r"\bFree\b",chunk,re.I)
            pctm=re.search(r"(?<![0-9])([0-9]+(?:\.[0-9]+)?)\s*%",chunk)
            if free and (not pctm or free.start()<pctm.start()): rate=0.0; text="Free"
            elif pctm: rate=float(pctm.group(1)); text=pctm.group(0)
            else: rate=None; text=None
            if rate is not None:
                return {"status":"resolved","rate":rate,"rate_text":text,"local_code":clean,"candidates":[],"source":meta.get("tariff_source"),"source_type":"official-current","lookup_url":resolved_url,"note":"Parsed from the current ABF Working Tariff page. Review origin-specific preferences separately."}
        return {"status":"official_source_available","rate":None,"candidates":[],"source":meta.get("tariff_source"),"source_type":"official-current","lookup_url":resolved_url,"note":"Official source reached, but a unique numeric tariff line could not be resolved from the supplied code."}
    except Exception as exc:
        return {"status":"error","rate":None,"candidates":[],"source":meta.get("tariff_source"),"source_type":"official-current","lookup_url":lookup_url,"error":str(exc)}

def lookup_official_tariff(*, market: str, code: str, origin: str = "") -> dict[str, Any]:
    market = str(market or "").upper()
    clean = _clean_code(code)
    meta = source_meta(market)
    if market == "US":
        return {"market": market, **lookup_us_hts(clean)}
    if market == "UK":
        return {"market": market, **lookup_uk_tariff(clean)}
    if market == "AU":
        return {"market": market, **lookup_au_tariff(clean)}
    if market in EU_CODES:
        return {
            "market": market, "status": "official_source_available", "rate": None,
            "source": meta.get("tariff_source") or "EU TARIC", "source_type": "official-current",
            "lookup_url": meta.get("tariff_url"), "local_code_requirement": meta.get("local_code_digits"),
            "note": "The official source is configured for every EU market. A verified local CN/TARIC code is required before a single current rate is treated as decision-grade."
        }
    if meta.get("tariff_source"):
        return {
            "market": market, "status": "official_source_available", "rate": None,
            "source": meta.get("tariff_source"), "source_type": "official-current",
            "lookup_url": meta.get("tariff_url"), "local_code_requirement": meta.get("local_code_digits"),
            "note": "Official source is registered in the V5 data backbone. Until an unambiguous local tariff line can be resolved automatically, use the connected WITS/TRAINS reference or save a verified manual rate."
        }
    return {"market":market,"status":"not_configured","rate":None,"source":"Official tariff source not configured","source_type":"not-configured","lookup_url":None}

