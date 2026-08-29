from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if value.endswith("%"):
                value = value[:-1].strip()
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from dict-like data or a Pydantic/domain model.

    Pricing calculations return ``PricingResult`` (a Pydantic model), while
    persisted evidence is usually a plain mapping.  Decision read paths accept
    both so a model object can never cause a page-level ``.get`` AttributeError.
    """
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(name, default)
    try:
        return getattr(value, name)
    except (AttributeError, TypeError):
        pass
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                return dumped.get(name, default)
        except Exception:
            pass
    return default


def trade_volatility(history: list[dict[str, Any]]) -> float | None:
    values = [_num(x.get("total_imports") or x.get("trade_value")) for x in history]
    values = [v for v in values if v is not None and v > 0]
    if len(values) < 3:
        return None
    growth = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    if len(growth) < 2:
        return None
    return statistics.pstdev(growth)


def evidence_quality(snapshot: dict[str, Any] | None, *, benchmark_available: bool = False, cost_ready: bool = False) -> dict[str, Any]:
    if not snapshot:
        return {
            "available_blocks": 0,
            "total_blocks": 6,
            "completeness_ratio": 0.0,
            "status": "insufficient",
            "missing": ["trade", "origin_trade", "supplier_structure", "tariff", "fx", "pricing_or_cost"],
        }
    quality = snapshot.get("quality") or {}
    trade = snapshot.get("trade") or {}
    suppliers = snapshot.get("suppliers") or {}
    checks = {
        "trade": bool((trade.get("world_metrics") or {}).get("latest_value") is not None or trade.get("latest_total_imports") is not None),
        "origin_trade": bool(trade.get("latest_imports_from_origin") is not None),
        "supplier_structure": bool(suppliers.get("supplier_count")),
        "tariff": bool((snapshot.get("tariff") or {}).get("rate") is not None),
        "fx": bool((snapshot.get("fx") or {}).get("rate") is not None),
        "pricing_or_cost": bool(benchmark_available or cost_ready),
    }
    available = sum(1 for v in checks.values() if v)
    ratio = available / len(checks)
    if available == len(checks):
        status = "complete"
    elif checks["trade"] and available >= 3:
        status = "partial"
    else:
        status = "insufficient"
    return {
        "available_blocks": available,
        "total_blocks": len(checks),
        "completeness_ratio": round(ratio, 4),
        "status": status,
        "missing": [k for k, v in checks.items() if not v],
        "trade_coverage": (quality.get("world") or {}).get("coverage_ratio"),
        "origin_coverage": (quality.get("origin") or {}).get("coverage_ratio"),
        "latest_year": trade.get("latest_year") or (trade.get("world_metrics") or {}).get("latest_year"),
    }


def reverse_cost(
    *,
    target_selling_price: float,
    packaging_cost: float = 0,
    freight_cost: float = 0,
    fulfillment_cost: float = 0,
    duty_rate: float = 0,
    tax_rate: float = 0,
    platform_fee_rate: float = 0,
    target_margin_rate: float = 0,
    current_factory_cost: float | None = None,
) -> dict[str, Any]:
    if target_selling_price < 0:
        raise ValueError("Target selling price must be non-negative.")
    if not (0 <= platform_fee_rate < 1 and 0 <= target_margin_rate < 1):
        raise ValueError("Platform fee and target margin must be rates between 0 and 1.")
    if platform_fee_rate + target_margin_rate >= 1:
        raise ValueError("Platform fee plus target margin must be below 100%.")
    if duty_rate < 0 or tax_rate < 0:
        raise ValueError("Duty and tax rates must be non-negative.")
    max_landed = target_selling_price * (1 - platform_fee_rate - target_margin_rate)
    multiplier = (1 + duty_rate) * (1 + tax_rate)
    max_pre_duty_base = max_landed / multiplier if multiplier > 0 else None
    other = packaging_cost + freight_cost + fulfillment_cost
    max_factory = None if max_pre_duty_base is None else max_pre_duty_base - other
    gap = None if current_factory_cost is None or max_factory is None else max_factory - current_factory_cost
    return {
        "target_selling_price": target_selling_price,
        "max_landed_cost_before_platform": max_landed,
        "max_pre_duty_operating_cost": max_pre_duty_base,
        "other_operating_costs": other,
        "max_factory_cost": max_factory,
        "current_factory_cost": current_factory_cost,
        "factory_cost_headroom": gap,
        "economically_within_target": None if gap is None else gap >= 0,
        "method": "reverse solution of the deterministic BorderMargin pricing formula",
    }


def decision_case(
    *,
    market: str,
    snapshot: dict[str, Any] | None,
    pricing: Any = None,
    reverse: dict[str, Any] | None = None,
    benchmark: dict[str, Any] | None = None,
    cost_ready: bool = False,
) -> dict[str, Any]:
    evidence = evidence_quality(snapshot, benchmark_available=bool(benchmark), cost_ready=cost_ready)
    blockers: list[str] = []
    next_actions: list[str] = []
    if snapshot is None or evidence["status"] == "insufficient":
        blockers.append("Market evidence is incomplete")
        next_actions.append("Sync trade data for this market")
    if snapshot and (snapshot.get("tariff") or {}).get("rate") is None:
        blockers.append("Tariff reference is unavailable")
        next_actions.append("Confirm a defensible tariff rate or official local tariff code")
    if not cost_ready:
        blockers.append("Private cost inputs are incomplete")
        next_actions.append("Complete factory cost, platform fee and target margin")
    if benchmark is None:
        blockers.append("Market price benchmark is unavailable")
        next_actions.append("Add source-backed marketplace observations or a target market price")

    economics = None
    if pricing and benchmark and benchmark.get("median") is not None:
        required = _num(_field(pricing, "target_price"))
        median = _num(benchmark.get("median"))
        if required is not None and median is not None and median > 0:
            economics = {
                "required_price": required,
                "benchmark_median": median,
                "premium_to_median": required / median - 1,
                "within_median": required <= median,
            }
    if reverse:
        economics = {**(economics or {}), "reverse": reverse}

    if evidence["status"] == "insufficient":
        status = "INSUFFICIENT_EVIDENCE"
    elif blockers:
        status = "CONDITIONAL"
    else:
        status = "READY_FOR_DECISION"

    trade = (snapshot or {}).get("trade") or {}
    suppliers = (snapshot or {}).get("suppliers") or {}
    return {
        "market": market,
        "status": status,
        "evidence_quality": evidence,
        "evidence": {
            "latest_year": trade.get("latest_year"),
            "imports": trade.get("latest_total_imports"),
            "origin_imports": trade.get("latest_imports_from_origin"),
            "origin_share": trade.get("latest_origin_share"),
            "trade_yoy": (trade.get("world_metrics") or {}).get("yoy"),
            "trade_cagr": (trade.get("world_metrics") or {}).get("cagr"),
            "trade_volatility": trade.get("volatility"),
            "supplier_cr3": suppliers.get("cr3"),
            "supplier_cr5": suppliers.get("cr5"),
            "supplier_hhi": suppliers.get("hhi"),
            "tariff_rate": ((snapshot or {}).get("tariff") or {}).get("rate"),
        },
        "economics": economics,
        "blockers": blockers,
        "next_actions": list(dict.fromkeys(next_actions)),
        "method": "deterministic evidence completeness and economics checks; no synthetic market attractiveness score",
    }


def pareto_frontier(
    rows: list[dict[str, Any]],
    *,
    maximize: tuple[str, ...] = ("imports", "cagr", "coverage"),
    minimize: tuple[str, ...] = (),
    min_metrics: int = 2,
) -> set[str]:
    """Return market codes on a non-weighted Pareto frontier.

    Only metrics present for both markets are compared. A market can dominate another
    only when at least ``min_metrics`` shared metrics are available.
    """
    frontier: set[str] = set()
    for row in rows:
        market = str(row.get("market") or "")
        if not market:
            continue
        dominated = False
        for other in rows:
            if other is row:
                continue
            shared = []
            weakly_better = True
            strictly_better = False
            for key in maximize:
                a, b = _num(row.get(key)), _num(other.get(key))
                if a is None or b is None:
                    continue
                shared.append(key)
                if b < a:
                    weakly_better = False
                    break
                if b > a:
                    strictly_better = True
            if weakly_better:
                for key in minimize:
                    a, b = _num(row.get(key)), _num(other.get(key))
                    if a is None or b is None:
                        continue
                    shared.append(key)
                    if b > a:
                        weakly_better = False
                        break
                    if b < a:
                        strictly_better = True
            if weakly_better and strictly_better and len(shared) >= min_metrics:
                dominated = True
                break
        if not dominated:
            frontier.add(market)
    return frontier


def market_quadrants(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Classify markets using sample medians of observed import size and CAGR."""
    valid = [r for r in rows if _num(r.get("imports")) is not None and _num(r.get("cagr")) is not None]
    if len(valid) < 2:
        return {}
    import_median = statistics.median(float(r["imports"]) for r in valid)
    growth_median = statistics.median(float(r["cagr"]) for r in valid)
    out: dict[str, str] = {}
    for r in valid:
        high_scale = float(r["imports"]) >= import_median
        high_growth = float(r["cagr"]) >= growth_median
        if high_scale and high_growth:
            label = "HIGH_SCALE_HIGH_GROWTH"
        elif high_scale:
            label = "HIGH_SCALE_LOWER_GROWTH"
        elif high_growth:
            label = "SMALLER_HIGH_GROWTH"
        else:
            label = "SMALLER_LOWER_GROWTH"
        out[str(r.get("market"))] = label
    return out


def standout_markets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("largest_import_market", "imports", max),
        ("fastest_3y_growth", "cagr", max),
        ("highest_origin_share", "origin_share", max),
        ("best_coverage", "coverage", max),
        ("most_diversified_supply", "hhi", min),
    ]
    out = []
    for key, field, fn in specs:
        candidates = [(float(r[field]), r) for r in rows if _num(r.get(field)) is not None]
        if not candidates:
            continue
        value, row = fn(candidates, key=lambda x: x[0])
        out.append({"type": key, "market": row.get("market"), "value": value, "field": field})
    return out
