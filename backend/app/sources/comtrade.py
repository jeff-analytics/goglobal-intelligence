from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable

import requests

from ..config import settings
from ..source_runtime import cache_key, cached_call

PREVIEW_BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
SUBSCRIPTION_BASE = "https://comtradeapi.un.org/data/v1/get/C/A/HS"


def _request_params(*, reporter_code: str, hs_code: str, period: str, partner_code: str | None, flow_code: str = "M") -> dict[str, Any]:
    params: dict[str, Any] = {
        "reportercode": str(reporter_code),
        "flowCode": str(flow_code).upper(),
        "period": str(period),
        "cmdCode": str(hs_code),
        "partnerCode": None if partner_code in (None, "", "all") else str(partner_code),
        "partner2Code": None,
        "motCode": None,
        "customsCode": None,
        "maxRecords": 100000 if settings.comtrade_subscription_key else 500,
        "format": "JSON",
        "aggregateBy": None,
        "breakdownMode": "classic",
        "countOnly": None,
        "includeDesc": "true",
    }
    return {k: v for k, v in params.items() if v is not None}


def fetch_trade(*, reporter_code: str, hs_code: str, period: str, partner_code: str | None = "0", flow_code: str = "M", force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch annual merchandise trade from UN Comtrade with persistent reuse.

    The cache is shared across projects so repeated research does not consume the
    free API allowance unnecessarily. A recent cached response is reused; if the
    live source is temporarily unavailable, a bounded stale response can be used
    instead of discarding previously verified evidence.
    """
    has_key = bool(settings.comtrade_subscription_key)
    base_url = SUBSCRIPTION_BASE if has_key else PREVIEW_BASE
    params = _request_params(
        reporter_code=reporter_code,
        hs_code=hs_code,
        period=period,
        partner_code=partner_code,
        flow_code=flow_code,
    )
    if has_key:
        params["subscription-key"] = settings.comtrade_subscription_key

    safe_params = {k: v for k, v in params.items() if k != "subscription-key"}
    key = cache_key("annual", "key" if has_key else "preview", base_url, safe_params)

    def network_fetch() -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        delays = (0.0, 0.6, 1.4)
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            try:
                response = requests.get(base_url, params=params, timeout=20)
                status_code = getattr(response, "status_code", 200)
                if status_code in {429, 500, 502, 503, 504} and attempt < len(delays) - 1:
                    last_exc = requests.HTTPError(f"UN Comtrade HTTP {status_code}")
                    continue
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                return rows if isinstance(rows, list) else []
            except Exception as exc:
                last_exc = exc
                if attempt >= len(delays) - 1:
                    break
        assert last_exc is not None
        raise last_exc

    payload, _meta = cached_call(
        provider="UN Comtrade",
        key=key,
        fetcher=network_fetch,
        ttl_seconds=6 * 60 * 60,
        stale_ttl_seconds=30 * 24 * 60 * 60,
        force_refresh=force_refresh,
    )
    return payload if isinstance(payload, list) else []



def validate_subscription_key(api_key: str) -> dict[str, Any]:
    """Validate a user-supplied UN Comtrade subscription key without persisting it.

    This probe deliberately bypasses the global settings object so the web UI can
    test the value currently typed into the form before saving it to .env.
    """
    key = str(api_key or "").strip()
    if not key:
        raise ValueError("UN Comtrade API key is required")

    year = time.gmtime().tm_year - 1
    params = {
        "reportercode": "842",
        "flowCode": "M",
        "period": str(year),
        "cmdCode": "850440",
        "partnerCode": "0",
        "maxRecords": 10,
        "format": "JSON",
        "breakdownMode": "classic",
        "includeDesc": "true",
        "subscription-key": key,
    }
    response = requests.get(SUBSCRIPTION_BASE, params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    return {"ok": True, "provider": "UN Comtrade", "mode": "free-key", "records": len(rows), "year": year}

def fetch_imports(*, reporter_code: str, hs_code: str, period: str, partner_code: str | None = "0") -> list[dict[str, Any]]:
    return fetch_trade(reporter_code=reporter_code, hs_code=hs_code, period=period, partner_code=partner_code, flow_code="M")


def fetch_exports(*, reporter_code: str, hs_code: str, period: str, partner_code: str | None = "0") -> list[dict[str, Any]]:
    return fetch_trade(reporter_code=reporter_code, hs_code=hs_code, period=period, partner_code=partner_code, flow_code="X")


def _numeric(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_numeric(rows: Iterable[dict[str, Any]], keys: list[str]) -> float | None:
    values: list[float] = []
    for row in rows:
        for key in keys:
            if key in row:
                val = _numeric(row.get(key))
                if val is not None:
                    values.append(val)
                    break
    return float(sum(values)) if values else None


def summarize_trade(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"trade_value": None, "net_weight": None, "qty": None, "records": 0}
    return {
        "trade_value": _sum_numeric(rows, ["primaryValue", "TradeValue", "tradeValue", "primary_value"]),
        "net_weight": _sum_numeric(rows, ["netWgt", "NetWeight", "netWeight"]),
        "qty": _sum_numeric(rows, ["qty", "Qty", "quantity"]),
        "records": len(rows),
    }


def summarize_imports(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_trade(rows)


def fetch_trade_history(*, reporter_code: str, hs_code: str, years: list[int], partner_code: str | None = "0", flow_code: str = "M") -> list[dict[str, Any]]:
    def one_year(year: int) -> dict[str, Any]:
        try:
            rows = fetch_trade(reporter_code=reporter_code, hs_code=hs_code, period=str(year), partner_code=partner_code, flow_code=flow_code)
            summary = summarize_trade(rows)
            return {"year": year, "trade_value": summary.get("trade_value"), "net_weight": summary.get("net_weight"), "qty": summary.get("qty"), "records": summary.get("records", 0), "ok": summary.get("trade_value") is not None, "error": None}
        except Exception as exc:
            return {"year": year, "trade_value": None, "net_weight": None, "qty": None, "records": 0, "ok": False, "error": str(exc)}

    workers = max(1, min(3, len(years)))
    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one_year, year): year for year in years}
        for future in as_completed(futures):
            row = future.result()
            results[int(row["year"])] = row
    return [results[year] for year in years]


def fetch_import_history(*, reporter_code: str, hs_code: str, years: list[int], partner_code: str | None = "0") -> list[dict[str, Any]]:
    return fetch_trade_history(reporter_code=reporter_code, hs_code=hs_code, years=years, partner_code=partner_code, flow_code="M")


def compute_growth_metrics(history: list[dict[str, Any]]) -> dict[str, Any]:
    points = [(int(r["year"]), _numeric(r.get("trade_value"))) for r in history]
    points = [(y, v) for y, v in points if v is not None and v > 0]
    points.sort()
    if not points:
        return {"latest_year": None, "latest_value": None, "yoy": None, "cagr": None, "first_year": None, "observation_count": 0, "span_years": 0, "contiguous": False}
    latest_year, latest_value = points[-1]
    yoy = None
    if len(points) >= 2 and points[-2][1] > 0 and points[-2][0] == latest_year - 1:
        yoy = latest_value / points[-2][1] - 1
    cagr = None
    first_year, first_value = points[0]
    years = latest_year - first_year
    if years > 0 and first_value > 0:
        cagr = (latest_value / first_value) ** (1 / years) - 1
    observed_years = [y for y, _ in points]
    return {"latest_year": latest_year, "latest_value": latest_value, "yoy": yoy, "cagr": cagr, "first_year": first_year, "observation_count": len(points), "span_years": years, "contiguous": observed_years == list(range(first_year, latest_year + 1))}


def _partner_structure(rows: list[dict[str, Any]], *, limit: int, total_key: str, item_key: str, method: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("partnerCode") or row.get("ptCode") or "").strip()
        if not code or code == "0":
            continue
        value = _numeric(row.get("primaryValue") if "primaryValue" in row else row.get("TradeValue"))
        if value is None or value < 0:
            continue
        name = row.get("partnerDesc") or row.get("partner2Desc") or row.get("ptTitle") or code
        iso3 = row.get("partnerISO") or row.get("pt3ISO")
        bucket = grouped.setdefault(code, {"partner_code": code, "partner_name": name, "partner_iso3": iso3, "trade_value": 0.0})
        bucket["trade_value"] += float(value)
    partners = sorted(grouped.values(), key=lambda x: x["trade_value"], reverse=True)
    total = sum(x["trade_value"] for x in partners)
    for rank, row in enumerate(partners, 1):
        row["share"] = row["trade_value"] / total if total > 0 else None
        row["rank"] = rank
        row["trade_value"] = round(row["trade_value"], 2)
    shares = [x["share"] for x in partners if x.get("share") is not None]
    return {
        total_key: total if total > 0 else None,
        "partner_count": len(partners),
        "cr3": sum(shares[:3]) if shares else None,
        "cr5": sum(shares[:5]) if shares else None,
        "hhi": sum(s * s for s in shares) if shares else None,
        item_key: partners[: max(1, min(limit, 50))],
        "source": "UN Comtrade",
        "method": method,
    }


def fetch_supplier_structure(*, reporter_code: str, hs_code: str, period: str, limit: int = 10) -> dict[str, Any]:
    rows = fetch_imports(reporter_code=reporter_code, hs_code=hs_code, period=period, partner_code=None)
    result = _partner_structure(rows, limit=limit, total_key="total_partner_imports", item_key="suppliers", method="partner-level import shares calculated from returned HS trade records")
    result["year"] = int(str(period)[:4])
    result["supplier_count"] = result.pop("partner_count")
    return result


def fetch_export_destination_structure(*, reporter_code: str, hs_code: str, period: str, limit: int = 15) -> dict[str, Any]:
    rows = fetch_exports(reporter_code=reporter_code, hs_code=hs_code, period=period, partner_code=None)
    result = _partner_structure(rows, limit=limit, total_key="total_partner_exports", item_key="destinations", method="partner-level export destination shares calculated from returned HS trade records")
    result["year"] = int(str(period)[:4])
    result["destination_count"] = result.pop("partner_count")
    return result


def fetch_trade_history_compact(*, reporter_code: str, hs_code: str, years: list[int], partner_code: str | None = "0", flow_code: str = "M") -> list[dict[str, Any]]:
    if not years:
        return []
    try:
        rows = fetch_trade(reporter_code=reporter_code, hs_code=hs_code, period=",".join(str(y) for y in years), partner_code=partner_code, flow_code=flow_code)
        grouped: dict[int, list[dict[str, Any]]] = {int(y): [] for y in years}
        for row in rows:
            raw_year = row.get("period") or row.get("refYear") or row.get("yr") or row.get("year")
            try:
                yr = int(str(raw_year)[:4])
            except (TypeError, ValueError):
                continue
            if yr in grouped:
                grouped[yr].append(row)
        result = []
        for year in years:
            summary = summarize_trade(grouped.get(year, []))
            result.append({"year": year, "trade_value": summary.get("trade_value"), "net_weight": summary.get("net_weight"), "qty": summary.get("qty"), "records": summary.get("records", 0), "ok": summary.get("trade_value") is not None, "error": None})
        if any(x.get("trade_value") is not None for x in result):
            missing = [x["year"] for x in result if x.get("trade_value") is None]
            if missing:
                fallback = {x["year"]: x for x in fetch_trade_history(reporter_code=reporter_code, hs_code=hs_code, years=missing, partner_code=partner_code, flow_code=flow_code)}
                result = [fallback.get(x["year"], x) if x.get("trade_value") is None else x for x in result]
            return result
    except Exception:
        pass
    return fetch_trade_history(reporter_code=reporter_code, hs_code=hs_code, years=years, partner_code=partner_code, flow_code=flow_code)


def fetch_import_history_compact(*, reporter_code: str, hs_code: str, years: list[int], partner_code: str | None = "0") -> list[dict[str, Any]]:
    return fetch_trade_history_compact(reporter_code=reporter_code, hs_code=hs_code, years=years, partner_code=partner_code, flow_code="M")


def fetch_export_history_compact(*, reporter_code: str, hs_code: str, years: list[int], partner_code: str | None = "0") -> list[dict[str, Any]]:
    return fetch_trade_history_compact(reporter_code=reporter_code, hs_code=hs_code, years=years, partner_code=partner_code, flow_code="X")
