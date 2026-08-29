from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

# Conditions are marketplace state labels. They are generic filter rules, not product data.
NON_NEW_CONDITIONS = {"used", "pre-owned", "for parts or not working", "parts only", "refurbished"}


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    w = pos - lo
    return values[lo] * (1 - w) + values[hi] * w


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(t) >= 2}


def _brand_guess(title: str) -> str | None:
    token = re.sub(r"[^A-Za-z0-9-]", "", title.strip().split(" ")[0]) if title.strip() else ""
    return token[:40] or None


def _attribute_tokens(attributes: dict[str, Any] | None) -> set[str]:
    tokens: set[str] = set()
    for key, value in (attributes or {}).items():
        if value in (None, "", False):
            continue
        tokens |= _tokens(str(key))
        tokens |= _tokens(str(value))
    return tokens


def _normalize_item(row: dict[str, Any], query_tokens: set[str], attribute_tokens: set[str]) -> dict[str, Any]:
    title = str(row.get("title") or "").strip()
    title_tokens = _tokens(title)
    query_overlap = len(title_tokens & query_tokens) / len(query_tokens) if query_tokens else None
    attribute_overlap = len(title_tokens & attribute_tokens) / len(attribute_tokens) if attribute_tokens else None
    return {
        **row,
        "title": title,
        "price": _num(row.get("price")),
        "shipping_cost": _num(row.get("shipping_cost")),
        "brand": row.get("brand") or _brand_guess(title),
        "query_overlap": query_overlap,
        "attribute_overlap": attribute_overlap,
    }


def _iqr_bounds(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 8:
        return None, None
    q1 = _percentile(values, .25)
    q3 = _percentile(values, .75)
    if q1 is None or q3 is None:
        return None, None
    iqr = q3 - q1
    if iqr <= 0:
        return None, None
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def build_comparable_set(
    rows: list[dict[str, Any]],
    *,
    query: str = "",
    target_price: float | None = None,
    excluded_terms: list[str] | None = None,
    minimum_query_overlap: float = 0.0,
    expected_category_id: str | None = None,
    expected_attributes: dict[str, Any] | None = None,
    minimum_attribute_overlap: float = 0.0,
    remove_price_outliers: bool = True,
    **_: Any,
) -> dict[str, Any]:
    query_tokens = _tokens(query)
    attr_tokens = _attribute_tokens(expected_attributes)
    exclusions = [term.lower().strip() for term in (excluded_terms or []) if term.strip()]
    accepted_stage1: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    reasons: Counter[str] = Counter()

    for raw in rows:
        item = _normalize_item(raw, query_tokens, attr_tokens)
        key = str(item.get("item_id") or item.get("listing_id") or item.get("title") or "")
        title_lower = item["title"].lower()
        reason = None

        if not item["title"]:
            reason = "missing title"
        elif item["price"] is None or item["price"] <= 0:
            reason = "missing price"
        elif key and key in seen:
            reason = "duplicate"
        elif str(item.get("condition") or "").lower() in NON_NEW_CONDITIONS:
            reason = "non-new condition"
        elif expected_category_id and item.get("category_id") and str(item.get("category_id")) != str(expected_category_id):
            reason = "category mismatch"
        elif exclusions and any(term in title_lower for term in exclusions):
            reason = "user-excluded term"
        elif query_tokens and minimum_query_overlap > 0 and (item.get("query_overlap") or 0) < minimum_query_overlap:
            reason = "low query overlap"
        elif attr_tokens and minimum_attribute_overlap > 0 and (item.get("attribute_overlap") or 0) < minimum_attribute_overlap:
            reason = "low attribute overlap"

        if reason:
            reasons[reason] += 1
            rejected.append({**item, "rejection_reason": reason})
            continue
        if key:
            seen.add(key)
        accepted_stage1.append(item)

    prices_stage1 = [float(r["price"]) for r in accepted_stage1 if r.get("price") is not None]
    low_bound, high_bound = _iqr_bounds(prices_stage1) if remove_price_outliers else (None, None)
    accepted: list[dict[str, Any]] = []
    for item in accepted_stage1:
        price = float(item["price"])
        if low_bound is not None and high_bound is not None and not (low_bound <= price <= high_bound):
            reasons["price outlier"] += 1
            rejected.append({**item, "rejection_reason": "price outlier"})
        else:
            accepted.append(item)

    prices = sorted([float(r["price"]) for r in accepted if r.get("price") is not None])
    p10 = _percentile(prices, .10)
    p25 = _percentile(prices, .25)
    median = _percentile(prices, .50)
    p75 = _percentile(prices, .75)
    p90 = _percentile(prices, .90)

    percentile = None
    if target_price is not None and prices:
        percentile = sum(1 for v in prices if v <= target_price) / len(prices)

    histogram: list[dict[str, Any]] = []
    if prices:
        lo, hi = min(prices), max(prices)
        if math.isclose(lo, hi):
            histogram = [{"bucket": f"{lo:.0f}", "count": len(prices), "low": lo, "high": hi}]
        else:
            bins = min(9, max(5, round(math.sqrt(len(prices)))))
            width = (hi - lo) / bins
            counts = [0] * bins
            for price in prices:
                idx = min(int((price - lo) / width), bins - 1)
                counts[idx] += 1
            for i, count in enumerate(counts):
                low = lo + i * width
                high = lo + (i + 1) * width
                histogram.append({"bucket": f"{low:.0f}–{high:.0f}", "count": count, "low": round(low, 2), "high": round(high, 2)})

    quality_ratio = len(accepted) / len(rows) if rows else 0
    return {
        "query": query,
        "input_count": len(rows),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "retention_ratio": round(quality_ratio, 4),
        "rejection_reasons": dict(reasons),
        "summary": {
            "p10": None if p10 is None else round(p10, 2),
            "p25": None if p25 is None else round(p25, 2),
            "median": None if median is None else round(median, 2),
            "p75": None if p75 is None else round(p75, 2),
            "p90": None if p90 is None else round(p90, 2),
            "target_price_percentile": None if percentile is None else round(percentile, 4),
        },
        "histogram": histogram,
        "accepted": accepted,
        "rejected_sample": rejected[:30],
        "filters": {
            "expected_category_id": expected_category_id,
            "minimum_query_overlap": minimum_query_overlap,
            "minimum_attribute_overlap": minimum_attribute_overlap,
            "excluded_terms": exclusions,
            "price_outlier_method": "IQR 1.5x" if remove_price_outliers and low_bound is not None else "disabled/not enough observations",
            "price_bounds": {"low": low_bound, "high": high_bound},
        },
        "filter_method": "category + condition + query/attribute overlap + optional user exclusions + statistical price outlier filter",
    }
