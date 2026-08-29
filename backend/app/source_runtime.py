from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from .storage import (
    source_cache_get,
    source_cache_put,
    source_health_record,
    source_usage_increment,
)


def cache_key(*parts: Any) -> str:
    normalized = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def cached_call(
    *,
    provider: str,
    key: str,
    fetcher: Callable[[], Any],
    ttl_seconds: int,
    stale_ttl_seconds: int,
    force_refresh: bool = False,
) -> tuple[Any, dict[str, Any]]:
    cached = source_cache_get(provider, key)
    age = _age_seconds((cached or {}).get("fetched_at"))
    if not force_refresh and cached is not None and age is not None and age <= max(0, int(ttl_seconds)):
        source_usage_increment(provider, "cache_hits")
        source_health_record(provider, ok=True, latency_ms=0, status="cached")
        return cached["payload"], {"mode": "cache", "age_seconds": age, "fetched_at": cached.get("fetched_at")}

    started = perf_counter()
    source_usage_increment(provider, "network_requests")
    try:
        payload = fetcher()
        latency = int((perf_counter() - started) * 1000)
        source_cache_put(provider, key, payload)
        source_health_record(provider, ok=True, latency_ms=latency, status="live")
        return payload, {"mode": "live", "age_seconds": 0.0, "latency_ms": latency}
    except Exception as exc:
        latency = int((perf_counter() - started) * 1000)
        source_usage_increment(provider, "failures")
        source_health_record(provider, ok=False, latency_ms=latency, error=str(exc), status="error")
        if cached is not None and age is not None and age <= max(0, int(stale_ttl_seconds)):
            source_usage_increment(provider, "stale_hits")
            source_health_record(provider, ok=True, latency_ms=latency, status="stale-cache")
            return cached["payload"], {"mode": "stale-cache", "age_seconds": age, "fetched_at": cached.get("fetched_at"), "network_error": str(exc)}
        raise
