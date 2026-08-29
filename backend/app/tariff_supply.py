from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from .markets import MARKETS
from .sources.comtrade import (
    compute_growth_metrics,
    fetch_export_destination_structure,
    fetch_export_history_compact,
)
from .sources.wits import fetch_tariff
from .storage import save_tariff_matrix_row

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = Lock()
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bm-tariff-job")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_supply_profile(*, origin: dict[str, Any], hs6: str, years: list[int], target_markets: list[str]) -> dict[str, Any]:
    """Build observed origin-country export capacity and target-market corridors.

    This uses UN Comtrade export observations only. Missing observations remain
    missing so the profile can be audited and does not imply supply where the
    source has no record.
    """
    reporter = str(origin.get("code") or "")
    if not reporter:
        raise ValueError("Origin reporter code is required")
    years = sorted({int(y) for y in years})
    history = fetch_export_history_compact(reporter_code=reporter, hs_code=hs6, years=years, partner_code="0")
    metrics = compute_growth_metrics(history)
    latest_year = metrics.get("latest_year") or (years[-1] if years else None)
    structure = fetch_export_destination_structure(reporter_code=reporter, hs_code=hs6, period=str(latest_year), limit=25) if latest_year else {}
    destination_map = {str(x.get("partner_code")): x for x in (structure.get("destinations") or [])}
    corridors = []
    for market in target_markets:
        cfg = MARKETS.get(str(market).upper()) or {}
        partner = str(cfg.get("reporter") or "")
        observed = destination_map.get(partner)
        corridors.append({
            "market": str(market).upper(),
            "label": cfg.get("label") or market,
            "partner_code": partner or None,
            "trade_value": observed.get("trade_value") if observed else None,
            "share": observed.get("share") if observed else None,
            "rank": observed.get("rank") if observed else None,
            "observed": bool(observed),
        })
    return {
        "hs6": hs6,
        "origin": origin,
        "years": years,
        "history": history,
        "metrics": metrics,
        "destination_structure": structure,
        "target_corridors": corridors,
        "quality": {
            "requested_years": years,
            "available_years": [int(x["year"]) for x in history if x.get("trade_value") is not None],
            "coverage_ratio": (sum(1 for x in history if x.get("trade_value") is not None) / len(years)) if years else 0,
            "target_corridors_observed": sum(1 for x in corridors if x.get("observed")),
            "target_corridors_requested": len(corridors),
        },
        "source": "UN Comtrade",
        "method": "Origin reporter exports by HS6, plus observed partner destination shares.",
        "synced_at": _now(),
    }


def _tariff_row(*, market: str, hs6: str, origin_code: str, year: int) -> dict[str, Any]:
    cfg = MARKETS.get(market) or {}
    reporter = str(cfg.get("reporter") or "")
    base = {
        "market": market,
        "label": cfg.get("label") or market,
        "reporter_code": reporter or None,
        "currency": cfg.get("currency"),
        "hs_code": hs6,
        "origin_code": str(origin_code or ""),
        "requested_year": int(year),
        "source": "UNCTAD TRAINS / WITS",
        "reference_scope": "HS6 analytical tariff reference",
    }
    if not reporter:
        return {**base, "status": "unsupported", "rate": None, "note": "No reporter code is configured for this market."}
    try:
        result = fetch_tariff(reporter_code=reporter, partner_code=str(origin_code or "000"), hs_code=hs6, year=str(year))
        status = "available" if result.get("rate") is not None else "missing"
        return {**base, **result, "market": market, "label": base["label"], "status": status}
    except Exception as exc:
        return {**base, "status": "error", "rate": None, "error": str(exc), "note": "Tariff source request failed; no value was substituted."}


def scan_tariff_matrix(*, markets: list[str], hs6: str, origin_code: str, year: int, workers: int = 6, progress=None) -> list[dict[str, Any]]:
    market_codes = [str(x).upper() for x in markets if str(x).upper() in MARKETS]
    results: dict[str, dict[str, Any]] = {}
    total = len(market_codes)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {pool.submit(_tariff_row, market=m, hs6=hs6, origin_code=origin_code, year=year): m for m in market_codes}
        for future in as_completed(futures):
            market = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"market": market, "hs_code": hs6, "origin_code": origin_code, "requested_year": year, "status": "error", "rate": None, "error": str(exc), "source": "UNCTAD TRAINS / WITS"}
            row = save_tariff_matrix_row(row)
            results[market] = row
            done += 1
            if progress:
                progress(done, total, market, row)
    return [results[m] for m in market_codes if m in results]


def start_tariff_job(*, markets: list[str], hs6: str, origin_code: str, year: int) -> dict[str, Any]:
    job_id = uuid4().hex[:16]
    job = {"job_id": job_id, "status": "queued", "done": 0, "total": len(markets), "current_market": None, "started_at": _now(), "finished_at": None, "error": None, "hs6": hs6, "origin_code": origin_code, "year": int(year)}
    with _LOCK:
        _JOBS[job_id] = job

    def worker():
        with _LOCK:
            _JOBS[job_id]["status"] = "running"
        def report(done, total, market, row):
            with _LOCK:
                _JOBS[job_id].update({"done": done, "total": total, "current_market": market, "last_status": row.get("status")})
        try:
            rows = scan_tariff_matrix(markets=markets, hs6=hs6, origin_code=origin_code, year=year, progress=report)
            with _LOCK:
                _JOBS[job_id].update({"status": "completed", "done": len(rows), "finished_at": _now()})
        except Exception as exc:
            with _LOCK:
                _JOBS[job_id].update({"status": "failed", "error": str(exc), "finished_at": _now()})

    _JOB_EXECUTOR.submit(worker)
    return deepcopy(job)


def tariff_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        value = _JOBS.get(job_id)
        return deepcopy(value) if value else None
