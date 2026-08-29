from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import RLock
from collections import Counter
from typing import Any

import requests

HS_REFERENCE_URLS = [
    "https://comtradeapi.un.org/files/v1/app/reference/classificationHS.json",
    "https://comtrade.un.org/data/cache/classificationHS.json",
]
_CACHE: dict[str, Any] = {"loaded_at": 0.0, "rows": []}
_CACHE_LOCK = RLock()
_DISK_CACHE = Path(__file__).resolve().parents[2] / "data" / "hs_reference.json"


def _first(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _normalize_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalize_row(row: dict[str, Any]) -> dict[str, Any] | None:
    code = _normalize_code(_first(row, ["id", "cmdCode", "code", "commodityCode"]))
    desc = _first(row, ["text", "cmdDescE", "cmdDesc", "description", "name"])
    if not code or not desc:
        return None
    level_raw = _first(row, ["aggrLevel", "level", "aggregateLevel"])
    try:
        level = int(level_raw) if level_raw not in (None, "") else len(code)
    except (TypeError, ValueError):
        level = len(code)
    leaf_raw = _first(row, ["isLeaf", "leaf", "is_leaf"])
    leaf = str(leaf_raw).lower() in {"1", "true", "yes"} if leaf_raw not in (None, "") else len(code) == 6
    return {
        "code": code,
        "description": str(desc).strip(),
        "level": level,
        "leaf": leaf,
        "source": "UN Comtrade HS reference",
    }


def get_hs_reference(*, force: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE["rows"] and not force and now - float(_CACHE["loaded_at"]) < 24 * 3600:
            return list(_CACHE["rows"])

        disk_rows: list[dict[str, Any]] = []
        try:
            if _DISK_CACHE.exists():
                payload = json.loads(_DISK_CACHE.read_text(encoding="utf-8"))
                disk_rows = payload.get("rows", []) if isinstance(payload, dict) else []
                if disk_rows and not force:
                    _CACHE["rows"] = disk_rows
                    _CACHE["loaded_at"] = float(payload.get("loaded_at") or now)
                    return list(disk_rows)
        except Exception:
            disk_rows = []

        last_exc: Exception | None = None
        for url in HS_REFERENCE_URLS:
            try:
                response = requests.get(url, timeout=(4, 12))
                response.raise_for_status()
                payload = response.json()
                raw = payload.get("results", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
                rows = [n for r in raw if isinstance(r, dict) and (n := _normalize_row(r))]
                if rows:
                    _CACHE["rows"] = rows
                    _CACHE["loaded_at"] = now
                    try:
                        _DISK_CACHE.parent.mkdir(parents=True, exist_ok=True)
                        _DISK_CACHE.write_text(json.dumps({"loaded_at": now, "rows": rows}, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                    return list(rows)
            except Exception as exc:
                last_exc = exc
        if disk_rows:
            _CACHE["rows"] = disk_rows
            _CACHE["loaded_at"] = now
            return list(disk_rows)
        if last_exc:
            raise last_exc
        return []


_STOP = {
    "and", "or", "the", "a", "an", "of", "for", "with", "to", "in", "on", "by", "from",
    "item", "items", "product", "products", "other", "including", "whether", "not", "elsewhere",
}


def _tokens(text: str) -> list[str]:
    out = []
    for token in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        if len(token) >= 2 and token not in _STOP:
            out.append(token)
    return out


def _score(query_tokens: list[str], desc: str) -> tuple[float, dict[str, float]]:
    if not query_tokens:
        return 0.0, {}
    desc_l = desc.lower()
    desc_tokens = _tokens(desc)
    counts = Counter(desc_tokens)
    unique_q = list(dict.fromkeys(query_tokens))
    matched = [t for t in unique_q if t in counts]
    phrase = " ".join(unique_q)
    phrase_bonus = 2.0 if phrase and phrase in desc_l else 0.0
    coverage = len(matched) / max(1, len(unique_q))
    frequency = sum(min(counts[t], 2) for t in matched) / max(1, len(unique_q))
    starts_bonus = 0.5 if matched and desc_l.startswith(matched[0]) else 0.0
    score = coverage * 5 + frequency * 1.5 + phrase_bonus + starts_bonus
    return score, {"token_coverage": round(coverage, 4), "matched_tokens": matched}


def suggest_hs_candidates(
    *,
    query: str,
    category_path: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    rows = get_hs_reference()
    parts = [query]
    if category_path:
        parts.extend(str(x) for x in category_path if x)
    if attributes:
        for key, value in attributes.items():
            if value not in (None, "", False):
                parts.append(str(key))
                parts.append(str(value))
    query_text = " ".join(parts)
    q_tokens = _tokens(query_text)
    candidates = []
    for row in rows:
        code = row["code"]
        # UN Comtrade analysis is built on HS6. Prefer actual six-digit leaves.
        if len(code) != 6:
            continue
        score, explain = _score(q_tokens, row["description"])
        if score <= 0:
            continue
        candidates.append({**row, "score": round(score, 4), **explain})
    candidates.sort(key=lambda x: (x["score"], x["token_coverage"]), reverse=True)
    top = candidates[: max(1, min(limit, 20))]
    if top:
        max_score = top[0]["score"] or 1
        for item in top:
            item["relative_confidence"] = round(item["score"] / max_score, 4)
    return {
        "query": query,
        "query_context": query_text,
        "candidates": top,
        "count": len(top),
        "source": "UN Comtrade HS reference",
        "method": "deterministic token matching over the official HS reference; user confirmation required",
    }


def search_hs_reference(*, query: str, limit: int = 12) -> dict[str, Any]:
    """Search official HS6 rows by typed code prefix or description text.

    Numeric input behaves like an autocomplete: every keystroke narrows HS6 rows
    whose code starts with the current prefix. Text input uses the same deterministic
    token scoring as the existing suggestion endpoint. No AI is involved.
    """
    q = str(query or "").strip()
    if not q:
        return {"query": q, "items": [], "count": 0, "source": "UN Comtrade HS reference"}
    rows = get_hs_reference()
    cap = max(1, min(int(limit or 12), 50))
    digits = _normalize_code(q)
    numeric_only = bool(digits) and all(ch.isdigit() or ch in " .-_/" for ch in q)
    if numeric_only:
        # Only offer selectable HS6 leaves. A partial prefix such as 60, 603 or
        # 60345 progressively narrows the list until the user clicks one row.
        items = [r for r in rows if len(r.get("code", "")) == 6 and r["code"].startswith(digits[:6])]
        items.sort(key=lambda r: r["code"])
        return {"query": q, "items": items[:cap], "count": min(len(items), cap), "source": "UN Comtrade HS reference", "mode": "code_prefix"}

    q_tokens = _tokens(q)
    scored = []
    for row in rows:
        if len(row.get("code", "")) != 6:
            continue
        score, explain = _score(q_tokens, row["description"])
        if score <= 0:
            continue
        scored.append({**row, "score": round(score, 4), **explain})
    scored.sort(key=lambda x: (x["score"], x.get("token_coverage", 0), x["code"]), reverse=True)
    return {"query": q, "items": scored[:cap], "count": min(len(scored), cap), "source": "UN Comtrade HS reference", "mode": "text"}
