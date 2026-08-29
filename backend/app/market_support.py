from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .markets import MARKETS

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "market_sources.json"
SOURCES: dict[str, dict[str, Any]] = json.loads(_CONFIG.read_text(encoding="utf-8"))


def source_meta(market: str) -> dict[str, Any]:
    code = str(market or "").upper()
    return {**SOURCES.get(code, {}), "market": code}


def support_registry() -> list[dict[str, Any]]:
    rows=[]
    for code,cfg in MARKETS.items():
        src=SOURCES.get(code,{})
        rows.append({
            "market":code,"label":cfg.get("label"),"currency":cfg.get("currency"),
            "trade_provider":"UN Comtrade","supplier_provider":"UN Comtrade",
            "tariff_provider":src.get("tariff_source") or "Not configured","tariff_mode":src.get("tariff_mode","not_configured"),
            "tax_provider":src.get("tax_source") or "Not configured","local_code_digits":src.get("local_code_digits"),
            "tariff_url":src.get("tariff_url"),"tax_url":src.get("tax_url"),
            "marketplace_provider":"eBay" if cfg.get("ebay") else None,
            "marketplace_environment":"sandbox" if cfg.get("ebay") else None,
        })
    return rows


def contract_from_snapshot(snapshot: dict[str, Any] | None, market: str) -> dict[str, Any]:
    cfg=MARKETS.get(market,{})
    src=SOURCES.get(market,{})
    snap=snapshot or {}
    trade=snap.get("trade") or {}
    suppliers=snap.get("suppliers") or {}
    tariff=snap.get("tariff") or {}
    official=snap.get("tariff_official_lookup") or {}
    fx=snap.get("fx") or {}
    tax=snap.get("tax") or {}
    quality=snap.get("quality") or {}
    synced=snap.get("synced_at")
    freshness_days=None
    if synced:
        try:
            dt=datetime.fromisoformat(str(synced).replace("Z","+00:00"))
            freshness_days=max(0,(datetime.now(timezone.utc)-dt).days)
        except Exception:
            pass
    blocks={
        "trade": trade.get("latest_total_imports") is not None,
        "origin_trade": trade.get("latest_origin_share") is not None,
        "suppliers": bool(suppliers.get("suppliers") or suppliers.get("supplier_count")),
        "tariff_rate": tariff.get("rate") is not None,
        "tariff_local_code": bool(official.get("local_code") or tariff.get("nomenclature")),
        "tax_rate": tax.get("rate") is not None,
        "fx": fx.get("rate") is not None,
    }
    ratio=sum(bool(v) for v in blocks.values())/len(blocks)
    if ratio>=0.85 and blocks["trade"] and blocks["tariff_rate"] and blocks["tax_rate"]:
        tier="decision_ready_core"
    elif blocks["trade"] and ratio>=0.5:
        tier="research_ready"
    else:
        tier="limited"
    return {
        "market":market,"label":cfg.get("label",market),"currency":cfg.get("currency"),
        "trade":{"latest_year":trade.get("latest_year"),"imports":trade.get("latest_total_imports"),"origin_imports":trade.get("latest_imports_from_origin"),"origin_share":trade.get("latest_origin_share"),"yoy":(trade.get("world_metrics") or {}).get("yoy"),"cagr":(trade.get("world_metrics") or {}).get("cagr"),"history":trade.get("history") or []},
        "supply":{"supplier_count":suppliers.get("supplier_count"),"cr3":suppliers.get("cr3"),"cr5":suppliers.get("cr5"),"hhi":suppliers.get("hhi"),"top_suppliers":suppliers.get("suppliers") or []},
        "tariff":{"rate":tariff.get("rate"),"source":tariff.get("source"),"reference_year":tariff.get("year"),"official_source":official.get("source") or src.get("tariff_source"),"official_status":official.get("status"),"official_url":official.get("lookup_url") or src.get("tariff_url"),"local_code":official.get("local_code") or tariff.get("nomenclature")},
        "tax":{"rate":tax.get("rate"),"source":tax.get("source") or src.get("tax_source"),"official_url":tax.get("source_url") or src.get("tax_url"),"status":"available" if tax.get("rate") is not None else "verify_current_rate","retrieval_method":tax.get("retrieval_method"),"confidence":tax.get("confidence")},
        "fx":fx,
        "quality":{"blocks":blocks,"completeness_ratio":round(ratio,4),"support_tier":tier,"trade_coverage":(quality.get("world") or {}).get("coverage_ratio"),"origin_coverage":(quality.get("origin") or {}).get("coverage_ratio"),"freshness_days":freshness_days,"synced_at":synced},
        "provenance":{"trade":"AI evidence recovery" if trade.get("ai_recovered_latest") else "UN Comtrade","suppliers":suppliers.get("source") or "UN Comtrade","tariff_reference":tariff.get("source"),"tariff_official":official.get("source") or src.get("tariff_source"),"tax_official":tax.get("source") or src.get("tax_source"),"fx":fx.get("source") if isinstance(fx,dict) else None},
    }
