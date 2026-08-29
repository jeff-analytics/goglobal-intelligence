from __future__ import annotations

import base64
import json
import time
from time import perf_counter
from pathlib import Path
from typing import Any

import requests

from ..config import settings, refresh_settings
from ..storage import source_health_record, source_usage_increment

_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0, "credential_key": None}
_TAXONOMY_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "ebay_taxonomy"
_TAXONOMY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_TAXONOMY_META_CACHE: dict[str, dict[str, Any]] = {}
_TAXONOMY_TREE_MEMORY: dict[str, dict[str, Any]] = {}
_TAXONOMY_INDEX_MEMORY: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
_ASPECT_MEMORY: dict[tuple[str, str, str], dict[str, Any]] = {}
_SUGGESTION_MEMORY: dict[tuple[str, str], dict[str, Any]] = {}


def _roots() -> tuple[str, str, str]:
    refresh_settings()
    if settings.ebay_env == "production":
        root = "https://api.ebay.com"
    else:
        root = "https://api.sandbox.ebay.com"
    return (
        f"{root}/identity/v1/oauth2/token",
        f"{root}/buy/browse/v1",
        f"{root}/commerce/taxonomy/v1",
    )


def reset_token_cache() -> None:
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires_at"] = 0.0
    _TOKEN_CACHE["credential_key"] = None


def get_application_token() -> str:
    refresh_settings()
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        source = ", ".join(settings.config_sources) if settings.config_sources else "no .env file detected"
        raise RuntimeError(
            f"eBay credentials are not loaded ({source}). Configure them in Data Sources or project-root .env."
        )

    credential_key = (settings.ebay_env, settings.ebay_client_id, settings.ebay_client_secret)
    if _TOKEN_CACHE.get("credential_key") != credential_key:
        reset_token_cache()
        _TOKEN_CACHE["credential_key"] = credential_key

    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
        source_usage_increment("eBay", "cache_hits")
        return str(_TOKEN_CACHE["token"])

    token_url, _, _ = _roots()
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    basic = base64.b64encode(raw).decode()
    started = perf_counter()
    source_usage_increment("eBay", "network_requests")
    try:
        response = requests.post(
            token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        source_health_record("eBay", ok=True, latency_ms=int((perf_counter()-started)*1000), status="live")
    except Exception as exc:
        source_usage_increment("eBay", "failures")
        source_health_record("eBay", ok=False, latency_ms=int((perf_counter()-started)*1000), error=str(exc))
        raise
    _TOKEN_CACHE["token"] = data["access_token"]
    _TOKEN_CACHE["expires_at"] = now + float(data.get("expires_in", 7200))
    return str(data["access_token"])


def _auth_headers(*, marketplace_id: str | None = None, gzip: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {get_application_token()}"}
    if marketplace_id:
        headers["X-EBAY-C-MARKETPLACE-ID"] = marketplace_id
    if gzip:
        headers["Accept-Encoding"] = "gzip"
    return headers


def test_connection_with_config(*, environment: str, client_id: str, client_secret: str) -> dict[str, Any]:
    environment = "production" if str(environment).strip().lower() == "production" else "sandbox"
    client_id = str(client_id or "").strip()
    client_secret = str(client_secret or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Client ID and Client Secret are required")
    root = "https://api.ebay.com" if environment == "production" else "https://api.sandbox.ebay.com"
    token_url = f"{root}/identity/v1/oauth2/token"
    raw = f"{client_id}:{client_secret}".encode()
    basic = base64.b64encode(raw).decode()
    started = perf_counter()
    source_usage_increment("eBay", "network_requests")
    try:
        response = requests.post(
            token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        source_health_record("eBay", ok=True, latency_ms=int((perf_counter()-started)*1000), status="live")
    except Exception as exc:
        source_usage_increment("eBay", "failures")
        source_health_record("eBay", ok=False, latency_ms=int((perf_counter()-started)*1000), error=str(exc))
        raise
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("eBay OAuth response did not include an access token")
    return {
        "ok": True,
        "environment": environment,
        "credentials_present": True,
        "token_received": True,
    }


def test_connection() -> dict[str, Any]:
    refresh_settings()
    return test_connection_with_config(
        environment=settings.ebay_env,
        client_id=settings.ebay_client_id,
        client_secret=settings.ebay_client_secret,
    )


def _money_value(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    try:
        return float(row.get("value"))
    except (TypeError, ValueError):
        return None


def search_listings(*, query: str, marketplace_id: str, limit: int = 50, category_id: str | None = None, sort: str | None = None, offset: int = 0) -> dict[str, Any]:
    _, browse_base, _ = _roots()
    params: dict[str, Any] = {
        "q": query,
        "limit": min(max(limit, 1), 200),
        "offset": min(max(int(offset or 0), 0), 10000),
        "filter": "buyingOptions:{FIXED_PRICE}",
    }
    if sort in {"price", "-price", "newlyListed", "distance"}:
        params["sort"] = sort
    if category_id:
        params["category_ids"] = category_id
    started = perf_counter()
    source_usage_increment("eBay", "network_requests")
    try:
        response = requests.get(
            f"{browse_base}/item_summary/search",
            headers=_auth_headers(marketplace_id=marketplace_id),
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        source_health_record("eBay", ok=True, latency_ms=int((perf_counter()-started)*1000), status="live")
    except Exception as exc:
        source_usage_increment("eBay", "failures")
        source_health_record("eBay", ok=False, latency_ms=int((perf_counter()-started)*1000), error=str(exc))
        raise
    items = []
    for row in data.get("itemSummaries", []):
        price = row.get("price") or {}
        shipping_options = row.get("shippingOptions") or []
        shipping_cost = None
        if shipping_options:
            shipping_cost = _money_value((shipping_options[0] or {}).get("shippingCost"))
        seller = row.get("seller") or {}
        location = row.get("itemLocation") or {}
        categories = row.get("categories") or []
        items.append({
            "item_id": row.get("itemId"),
            "legacy_item_id": row.get("legacyItemId"),
            "title": row.get("title"),
            "price": _money_value(price),
            "currency": price.get("currency"),
            "shipping_cost": shipping_cost,
            "condition": row.get("condition"),
            "marketplace": row.get("listingMarketplaceId") or marketplace_id,
            "item_location": location,
            "seller_username": seller.get("username"),
            "seller_feedback_percentage": seller.get("feedbackPercentage"),
            "seller_feedback_score": seller.get("feedbackScore"),
            "image_url": (row.get("image") or {}).get("imageUrl"),
            "web_url": row.get("itemWebUrl"),
            "category_id": (categories[0] or {}).get("categoryId") if categories else category_id,
        })
    return {
        "query": query,
        "category_id": category_id,
        "marketplace": marketplace_id,
        "total": data.get("total"),
        "returned": len(items),
        "offset": params["offset"],
        "limit": params["limit"],
        "sort": sort or "bestMatch",
        "items": items,
        "environment": settings.ebay_env,
        "is_market_data": settings.ebay_env == "production",
        "provenance_note": (
            "eBay Sandbox data is synthetic/test data and is used only to validate integration."
            if settings.ebay_env == "sandbox"
            else "Production Browse API response."
        ),
    }


def _taxonomy_request(path: str, *, params: dict[str, Any] | None = None, timeout: int = 20, gzip: bool = False) -> dict[str, Any]:
    _, _, taxonomy_base = _roots()
    started = perf_counter()
    source_usage_increment("eBay", "network_requests")
    try:
        response = requests.get(
            f"{taxonomy_base}{path}",
            headers=_auth_headers(gzip=gzip),
            params=params or {},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        source_health_record("eBay", ok=True, latency_ms=int((perf_counter()-started)*1000), status="live")
        return payload
    except Exception as exc:
        source_usage_increment("eBay", "failures")
        source_health_record("eBay", ok=False, latency_ms=int((perf_counter()-started)*1000), error=str(exc))
        raise


def _safe_marketplace(marketplace_id: str) -> str:
    return marketplace_id.replace("/", "_").replace("\\", "_")


def _cached_tree_candidates(marketplace_id: str) -> list[Path]:
    safe = _safe_marketplace(marketplace_id)
    try:
        return sorted(
            _TAXONOMY_CACHE_DIR.glob(f"{safe}_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return []


def _read_latest_cached_tree(marketplace_id: str) -> dict[str, Any] | None:
    memory = _TAXONOMY_TREE_MEMORY.get(marketplace_id)
    if memory:
        return memory
    for path in _cached_tree_candidates(marketplace_id):
        # Aspect cache files use a different prefix, but keep this guard defensive.
        if path.name.startswith("aspects_"):
            continue
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("rootCategoryNode") and cached.get("categoryTreeId") is not None:
                _TAXONOMY_TREE_MEMORY[marketplace_id] = cached
                _TAXONOMY_META_CACHE[marketplace_id] = {
                    "marketplace": marketplace_id,
                    "category_tree_id": str(cached.get("categoryTreeId") or ""),
                    "category_tree_version": str(cached.get("categoryTreeVersion") or ""),
                    "environment": settings.ebay_env,
                    "source": "disk_cache",
                }
                return cached
        except Exception:
            continue
    return None


def get_default_category_tree_id(marketplace_id: str, *, force: bool = False) -> dict[str, Any]:
    if not force and marketplace_id in _TAXONOMY_META_CACHE:
        return dict(_TAXONOMY_META_CACHE[marketplace_id])

    # Fast path after the first successful load. Taxonomy changes rarely enough that an
    # explicit Refresh is a better UX than blocking every navigation on a metadata call.
    if not force:
        cached = _read_latest_cached_tree(marketplace_id)
        if cached:
            return dict(_TAXONOMY_META_CACHE[marketplace_id])

    data = _taxonomy_request(
        "/get_default_category_tree_id",
        params={"marketplace_id": marketplace_id},
    )
    result = {
        "marketplace": marketplace_id,
        "category_tree_id": str(data.get("categoryTreeId")),
        "category_tree_version": str(data.get("categoryTreeVersion")),
        "environment": settings.ebay_env,
        "source": "ebay_api",
    }
    _TAXONOMY_META_CACHE[marketplace_id] = result
    return dict(result)


def _cache_path(marketplace_id: str, tree_id: str) -> Path:
    safe = _safe_marketplace(marketplace_id)
    return _TAXONOMY_CACHE_DIR / f"{safe}_{tree_id}.json"


def _get_category_tree(marketplace_id: str, *, force: bool = False) -> dict[str, Any]:
    if not force:
        cached = _read_latest_cached_tree(marketplace_id)
        if cached:
            return cached

    meta = get_default_category_tree_id(marketplace_id, force=force)
    path = _cache_path(marketplace_id, meta["category_tree_id"])
    if path.exists() and not force:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            _TAXONOMY_TREE_MEMORY[marketplace_id] = cached
            return cached
        except Exception:
            pass

    data = _taxonomy_request(f"/category_tree/{meta['category_tree_id']}", timeout=30, gzip=True)
    _TAXONOMY_TREE_MEMORY[marketplace_id] = data
    _TAXONOMY_META_CACHE[marketplace_id] = {
        "marketplace": marketplace_id,
        "category_tree_id": str(data.get("categoryTreeId") or meta["category_tree_id"]),
        "category_tree_version": str(data.get("categoryTreeVersion") or meta["category_tree_version"]),
        "environment": settings.ebay_env,
        "source": "ebay_api",
    }
    # Invalidate old in-memory indexes for this marketplace after a forced refresh.
    for key in [k for k in _TAXONOMY_INDEX_MEMORY if k[0] == marketplace_id]:
        _TAXONOMY_INDEX_MEMORY.pop(key, None)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return data


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    category = node.get("category") or {}
    children = node.get("childCategoryTreeNodes") or []
    return {
        "category_id": str(category.get("categoryId") or ""),
        "name": category.get("categoryName") or "Unnamed category",
        "level": node.get("categoryTreeNodeLevel"),
        "leaf": bool(node.get("leafCategoryTreeNode", False) or not children),
        "child_count": len(children),
    }


def _category_index(marketplace_id: str, tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    version = str(tree.get("categoryTreeVersion") or tree.get("categoryTreeId") or "")
    key = (marketplace_id, version)
    cached = _TAXONOMY_INDEX_MEMORY.get(key)
    if cached is not None:
        return cached

    index: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any], parent_path: list[str]) -> None:
        category = node.get("category") or {}
        category_id = str(category.get("categoryId") or "")
        name = category.get("categoryName") or "Unnamed category"
        path = parent_path + ([name] if name else [])
        if category_id:
            index[category_id] = {"node": node, "path": path}
        for child in node.get("childCategoryTreeNodes") or []:
            walk(child, path)

    root = tree.get("rootCategoryNode") or {}
    root_name = (root.get("category") or {}).get("categoryName")
    # Do not expose the synthetic root name in user-facing paths.
    root_parent: list[str] = []
    if root_name and str(root_name).strip().lower() not in {"root", "root category"}:
        root_parent = []
    for child in root.get("childCategoryTreeNodes") or []:
        walk(child, root_parent)
    root_category_id = str((root.get("category") or {}).get("categoryId") or "")
    if root_category_id:
        index[root_category_id] = {"node": root, "path": []}

    _TAXONOMY_INDEX_MEMORY[key] = index
    return index


def get_top_categories_cached(marketplace_id: str) -> dict[str, Any]:
    """Return a taxonomy already stored on disk/memory without any eBay network call.

    This endpoint is used on page entry so taxonomy browsing never blocks the UI.
    Users can search lightweight suggestions or explicitly request the full tree when
    a marketplace has not been cached yet.
    """
    tree = _read_latest_cached_tree(marketplace_id)
    if not tree:
        return {
            "marketplace": marketplace_id,
            "categories": [],
            "count": 0,
            "environment": settings.ebay_env,
            "cached": False,
            "cache": "miss",
        }
    root = tree.get("rootCategoryNode") or {}
    children = [_compact_node(x) for x in root.get("childCategoryTreeNodes") or []]
    children.sort(key=lambda x: x["name"].lower())
    return {
        "marketplace": marketplace_id,
        "category_tree_id": str(tree.get("categoryTreeId") or ""),
        "category_tree_version": str(tree.get("categoryTreeVersion") or ""),
        "categories": children,
        "count": len(children),
        "environment": settings.ebay_env,
        "cached": True,
        "cache": "local",
    }


def get_top_categories(marketplace_id: str, *, force: bool = False) -> dict[str, Any]:
    tree = _get_category_tree(marketplace_id, force=force)
    root = tree.get("rootCategoryNode") or {}
    children = [_compact_node(x) for x in root.get("childCategoryTreeNodes") or []]
    children.sort(key=lambda x: x["name"].lower())
    return {
        "marketplace": marketplace_id,
        "category_tree_id": str(tree.get("categoryTreeId") or ""),
        "category_tree_version": str(tree.get("categoryTreeVersion") or ""),
        "categories": children,
        "count": len(children),
        "environment": settings.ebay_env,
        "cache": "local" if not force else "refreshed",
    }


def get_category_children(marketplace_id: str, category_id: str) -> dict[str, Any]:
    # The full category tree is cached after the first marketplace load. Walking the
    # local tree makes category navigation effectively instant and avoids one eBay API
    # request for every click.
    tree = _get_category_tree(marketplace_id, force=False)
    index = _category_index(marketplace_id, tree)
    entry = index.get(str(category_id))
    if entry:
        node = entry["node"]
        children = [_compact_node(x) for x in node.get("childCategoryTreeNodes") or []]
        children.sort(key=lambda x: x["name"].lower())
        current = _compact_node(node)
        current["path"] = entry.get("path") or [current.get("name")]
        return {
            "marketplace": marketplace_id,
            "category_tree_id": str(tree.get("categoryTreeId") or ""),
            "category_tree_version": str(tree.get("categoryTreeVersion") or ""),
            "category": current,
            "children": children,
            "count": len(children),
            "environment": settings.ebay_env,
            "cache": "local_tree",
        }

    # Defensive fallback in case eBay returns a category not present in the cached tree.
    meta = get_default_category_tree_id(marketplace_id)
    data = _taxonomy_request(
        f"/category_tree/{meta['category_tree_id']}/get_category_subtree",
        params={"category_id": category_id},
        timeout=20,
        gzip=True,
    )
    node = data.get("categorySubtreeNode") or {}
    children = [_compact_node(x) for x in node.get("childCategoryTreeNodes") or []]
    children.sort(key=lambda x: x["name"].lower())
    current = _compact_node(node) if node else {"category_id": category_id, "name": category_id, "leaf": False, "child_count": len(children)}
    return {
        "marketplace": marketplace_id,
        "category_tree_id": meta["category_tree_id"],
        "category_tree_version": data.get("categoryTreeVersion") or meta["category_tree_version"],
        "category": current,
        "children": children,
        "count": len(children),
        "environment": settings.ebay_env,
        "cache": "api_fallback",
    }


def get_category_suggestions(marketplace_id: str, query: str, *, limit: int = 12) -> dict[str, Any]:
    query_key = query.strip().lower()
    key = (marketplace_id, query_key)
    cached = _SUGGESTION_MEMORY.get(key)
    if cached is not None:
        result = dict(cached)
        result["suggestions"] = list(result.get("suggestions") or [])[: max(1, min(limit, 20))]
        result["count"] = len(result["suggestions"])
        result["cache"] = "memory"
        return result

    meta = get_default_category_tree_id(marketplace_id)
    data = _taxonomy_request(
        f"/category_tree/{meta['category_tree_id']}/get_category_suggestions",
        params={"q": query},
        timeout=20,
    )
    out: list[dict[str, Any]] = []
    for row in (data.get("categorySuggestions") or [])[:20]:
        cat = row.get("category") or {}
        ancestors = sorted(row.get("categoryTreeNodeAncestors") or [], key=lambda x: int(x.get("categoryTreeNodeLevel") or 0))
        path = [x.get("categoryName") for x in ancestors if x.get("categoryName")] + [cat.get("categoryName")]
        out.append({
            "category_id": str(cat.get("categoryId") or ""),
            "name": cat.get("categoryName") or "Unnamed category",
            "level": row.get("categoryTreeNodeLevel"),
            "leaf": True,
            "path": path,
        })
    base = {
        "marketplace": marketplace_id,
        "query": query,
        "category_tree_id": meta["category_tree_id"],
        "suggestions": out,
        "count": len(out),
        "environment": settings.ebay_env,
        "cache": "api",
    }
    _SUGGESTION_MEMORY[key] = dict(base)
    result = dict(base)
    result["suggestions"] = out[: max(1, min(limit, 20))]
    result["count"] = len(result["suggestions"])
    return result


def _aspect_cache_path(marketplace_id: str, tree_id: str, category_id: str) -> Path:
    safe_market = _safe_marketplace(marketplace_id)
    safe_category = str(category_id).replace("/", "_").replace("\\", "_")
    return _TAXONOMY_CACHE_DIR / f"aspects_{safe_market}_{tree_id}_{safe_category}.json"


def get_item_aspects(marketplace_id: str, category_id: str, *, force: bool = False) -> dict[str, Any]:
    meta = get_default_category_tree_id(marketplace_id, force=False)
    key = (marketplace_id, meta["category_tree_id"], str(category_id))
    if not force and key in _ASPECT_MEMORY:
        result = dict(_ASPECT_MEMORY[key])
        result["cache"] = "memory"
        return result

    cache_path = _aspect_cache_path(marketplace_id, meta["category_tree_id"], category_id)
    if cache_path.exists() and not force:
        try:
            result = json.loads(cache_path.read_text(encoding="utf-8"))
            _ASPECT_MEMORY[key] = result
            result = dict(result)
            result["cache"] = "disk"
            return result
        except Exception:
            pass

    data = _taxonomy_request(
        f"/category_tree/{meta['category_tree_id']}/get_item_aspects_for_category",
        params={"category_id": category_id},
        timeout=20,
    )
    aspects = []
    for row in data.get("aspects") or []:
        details = row.get("aspectConstraint") or {}
        values = [v.get("localizedValue") for v in row.get("aspectValues") or [] if v.get("localizedValue")]
        aspects.append({
            "name": row.get("localizedAspectName"),
            "required": bool(details.get("aspectRequired")),
            "mode": details.get("aspectMode"),
            "data_type": details.get("aspectDataType"),
            "usage": details.get("aspectUsage"),
            "values": values[:80],
        })
    aspects.sort(key=lambda x: (not x["required"], (x["name"] or "").lower()))
    result = {
        "marketplace": marketplace_id,
        "category_id": category_id,
        "category_tree_id": meta["category_tree_id"],
        "aspects": aspects,
        "count": len(aspects),
        "environment": settings.ebay_env,
        "cache": "api",
    }
    _ASPECT_MEMORY[key] = result
    try:
        cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return dict(result)

