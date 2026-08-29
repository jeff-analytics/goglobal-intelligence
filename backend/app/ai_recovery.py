from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, quote

import requests

from .ai_layer import (
    _config, _headers, _ensure_success, _parse_json_loose, _post_prompt,
    _extract_responses_text, _usage_from_payload, _is_deepseek, _structured_responses_call,
    _responses_text_call, _sum_usage,
)
from .config import refresh_settings
from .comparables import build_comparable_set
from .market_support import source_meta
from .markets import MARKETS
from .sources.comtrade import compute_growth_metrics
from .storage import (
    get_tariff_override,
    get_tax_override,
    save_ai_evidence,
    save_listing_snapshot,
    save_snapshot,
    start_ai_recovery_run,
    finish_ai_recovery_run,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _is_public_url(url: str) -> bool:
    try:
        parsed=urlparse(url)
        if parsed.scheme not in {"http","https"} or not parsed.hostname:
            return False
        host=parsed.hostname.lower()
        if host in {"localhost","127.0.0.1","::1"}:
            return False
        for info in socket.getaddrinfo(host, None):
            addr=info[4][0]
            ip=ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _strip_html(text: str) -> str:
    text=re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>"," ",text)
    text=re.sub(r"(?s)<[^>]+>"," ",text)
    text=(text.replace("&nbsp;"," ").replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
              .replace("&#39;","'").replace("&quot;",'"'))
    return re.sub(r"\s+"," ",text).strip()


def fetch_public_source(url: str, *, max_chars: int = 42000) -> dict[str, Any]:
    if not _is_public_url(url):
        raise RuntimeError("Source URL is not a public HTTP(S) address")
    r=requests.get(url,timeout=18,allow_redirects=True,headers={"User-Agent":"BorderMargin/5.3.8","Accept":"text/html,text/plain,application/json;q=0.8,*/*;q=0.2"},stream=True)
    r.raise_for_status()
    ctype=(r.headers.get("content-type") or "").lower()
    if "pdf" in ctype:
        raise RuntimeError("PDF source requires provider web search or a text/HTML official source")
    raw=b""
    for chunk in r.iter_content(65536):
        raw += chunk
        if len(raw)>2_000_000:
            break
    enc=r.encoding or "utf-8"
    text=raw.decode(enc,errors="replace")
    if "html" in ctype or "<html" in text[:1000].lower():
        text=_strip_html(text)
    else:
        text=re.sub(r"\s+"," ",text).strip()
    text=text[:max_chars]
    return {"url":r.url,"text":text,"content_type":ctype,"sha256":hashlib.sha256(raw).hexdigest()}


def _source_level(url: str, source_type: str = "") -> str:
    host=(urlparse(url).hostname or "").lower()
    if source_type.startswith("official") or any(x in host for x in (".gov","gov.","europa.eu","customs.go.jp","customs.gov.sg","wto.org","worldbank.org","un.org","ecb.europa.eu")):
        return "B"
    return "C"


def _registered_sources(market: str) -> list[dict[str,str]]:
    meta=source_meta(market)
    rows=[]
    for kind,name_key,url_key in (("tariff","tariff_source","tariff_url"),("tax","tax_source","tax_url")):
        url=_clean(meta.get(url_key)); name=_clean(meta.get(name_key))
        if url:
            rows.append({"kind":kind,"name":name or urlparse(url).hostname or kind,"url":url,"source_type":"official-registered"})
    return rows


def _base_research_schema() -> dict[str, Any]:
    # Keep the schema deliberately simple. Evidence values are returned as JSON
    # strings and decoded locally by field type. This is more portable across
    # structured-output providers than an untyped/union `value` property.
    evidence_fields = [
        "tariff.rate", "tariff.local_code", "tax.rate", "fx.rate",
        "trade.latest_total_imports", "trade.latest_imports_from_origin",
        "trade.latest_origin_share", "trade.history",
        "supply.supplier_count", "supply.cr3", "supply.cr5",
        "supply.hhi", "supply.top_suppliers",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string", "enum": evidence_fields},
                        "value": {"type": "string"},
                        "unit": {"type": "string"},
                        "source_name": {"type": "string"},
                        "source_url": {"type": "string"},
                        "source_type": {"type": "string"},
                        "observed_at": {"type": "string"},
                        "confidence": {"type": "string"},
                        "excerpt": {"type": "string"},
                    },
                    "required": ["field", "value", "unit", "source_name", "source_url", "source_type", "observed_at", "confidence", "excerpt"],
                },
            },
            "market_access": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requirement": {"type": "string"},
                        "status": {"type": "string"},
                        "source_name": {"type": "string"},
                        "source_url": {"type": "string"},
                        "confidence": {"type": "string"},
                        "excerpt": {"type": "string"},
                    },
                    "required": ["requirement", "status", "source_name", "source_url", "confidence", "excerpt"],
                },
            },
            "marketplace_observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "brand": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "source_url": {"type": "string"},
                        "source_name": {"type": "string"},
                        "observed_at": {"type": "string"},
                    },
                    "required": ["title", "brand", "price", "currency", "source_url", "source_name", "observed_at"],
                },
            },
            "gaps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["evidence", "market_access", "marketplace_observations", "gaps"],
    }



def _parse_or_repair_json(cfg: dict[str, Any], text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Parse provider output locally. Never issue a second paid model call."""
    del cfg, schema
    return _parse_json_loose(text)


def _supports_native_web(cfg: dict[str, Any]) -> bool:
    protocol = _clean(cfg.get("protocol")).lower()
    if protocol in {"anthropic", "gemini", "openai_responses"}:
        return True
    # Do not probe arbitrary OpenAI-compatible gateways with a paid /responses
    # request. DeepSeek V4 Flash is explicitly documented to support Responses
    # + server-side web_search, so it can be selected deterministically.
    model = _clean(cfg.get("model")).lower()
    return protocol == "openai_compatible" and _is_deepseek(cfg) and model.startswith("deepseek-v4-")


def _web_search_mode(cfg: dict[str, Any]) -> str:
    if not _supports_native_web(cfg):
        return "none"
    protocol = _clean(cfg.get("protocol")).lower()
    if protocol == "anthropic":
        return "anthropic"
    if protocol == "gemini":
        return "gemini"
    return "responses"

def _research_prompt(project: dict[str,Any], market: str, snapshot: dict[str,Any] | None, requested: list[str]) -> str:
    payload={
        "product":{"title":project.get("title"),"description":project.get("description"),"origin":project.get("origin"),"hs_code":project.get("hs_code"),"attributes":project.get("attributes") or {}},
        "market":{"code":market,"name":(MARKETS.get(market) or {}).get("label") or market},"requested":requested,
        "existing":{
            "trade":(snapshot or {}).get("trade") or {},"tariff":(snapshot or {}).get("tariff") or {},"tax":(snapshot or {}).get("tax") or {},"fx":(snapshot or {}).get("fx") or {},
            "supplier_structure":(snapshot or {}).get("suppliers") or {}
        }
    }
    return json.dumps(payload,ensure_ascii=False)


def _collect_urls(value: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "source_url", "link"} and isinstance(item, str) and _valid_url(item):
                urls.add(item)
            else:
                urls.update(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.update(_collect_urls(item))
    return urls


def _research_json_example() -> str:
    return json.dumps({
        "evidence": [
            {
                "field": "tariff.rate",
                "value": "5.0",
                "unit": "percent",
                "source_name": "Official customs authority",
                "source_url": "https://example.gov/tariff",
                "source_type": "official",
                "observed_at": "2026",
                "confidence": "high",
                "excerpt": "Short supporting excerpt"
            }
        ],
        "market_access": [],
        "marketplace_observations": [],
        "gaps": []
    }, ensure_ascii=False)


def _responses_web_research(
    cfg: dict[str,Any], *, system: str, user: str, max_tokens: int = 7000, schema: dict[str,Any] | None = None
) -> dict[str,Any]:
    """Reliable source-backed research for Responses providers.

    DeepSeek is intentionally two-stage: first let the server-side web-search
    agent research in plain text, then structure only that returned research into
    the BorderMargin schema. This avoids coupling web tool execution to JSON
    formatting, which was the source of the previous `MODEL_INVALID_JSON` user
    failures. The second stage has no web tool and is forbidden from adding facts.
    """
    schema = schema or _base_research_schema()
    if _is_deepseek(cfg):
        search_system = (
            system + "\nFor this research stage, do NOT return JSON. Write concise research notes. "
            "For every fact, include the exact full https:// source URL on the same line. "
            "Use the web_search tool. If a requested fact cannot be verified, say MISSING."
        )
        search_data, search_text, url = _responses_text_call(
            cfg, system=search_system, user=user, max_tokens=max_tokens,
            web_search=True, reasoning_effort="low", json_format=None,
        )
        discovered_urls = sorted(_collect_urls(search_data))
        structure_system = (
            "Convert ONLY the supplied web-research notes into the requested BorderMargin JSON schema. "
            "Do not browse, do not use model memory, and do not add facts that are absent from the notes. "
            "Every numeric evidence row must have a directly supporting full source_url from the notes or discovered URL list. "
            "If a field is not directly supported, put its category/field in gaps. "
            "Return exactly one JSON object."
        )
        structure_user = json.dumps({
            "original_request": json.loads(user) if user.strip().startswith("{") else user,
            "research_notes": search_text,
            "discovered_urls": discovered_urls,
        }, ensure_ascii=False)
        structure_data, result, _ = _structured_responses_call(
            cfg, system=structure_system, user=structure_user, schema=schema,
            schema_name="bordermargin_evidence", max_tokens=5200, web_search=False,
        )
        result["_model_calls"] = 2
        result["_model_usage"] = _sum_usage(search_data, structure_data)
        result["_web_urls"] = discovered_urls
        result["_endpoint"] = url
        return result

    data, result, url = _structured_responses_call(
        cfg, system=system, user=user, schema=schema,
        schema_name="bordermargin_evidence", max_tokens=max_tokens, web_search=True,
    )
    result["_model_calls"] = 1
    result["_model_usage"] = _usage_from_payload(data)
    result["_web_urls"] = sorted(_collect_urls(data))
    result["_endpoint"] = url
    return result


def _native_web_research(project: dict[str,Any], market: str, snapshot: dict[str,Any] | None, requested: list[str]) -> dict[str,Any] | None:
    cfg=_config()
    mode=_web_search_mode(cfg)
    if mode=="none":
        return None
    system=(
        "You are BorderMargin's evidence recovery engine. Search the live web for ONLY the requested missing fields. "
        "Prefer official government, customs, tax, central-bank, UN/WTO/World Bank sources. For market prices, use exact public retailer or marketplace product pages. "
        "Never fill a numeric field from model memory. Every returned numeric value must have a directly supporting source_url. "
        "Do not alter user-entered costs, margins, uploaded observations, manual tariff/tax overrides, or confirmed HS/local tariff codes. "
        "Return exactly one valid JSON object and no markdown. The word JSON is intentional. "
        "For trade monetary values, only return values explicitly denominated in USD; otherwise leave the field in gaps. "
        "For tariffs, distinguish MFN/base duty from origin-specific preferential duty and return the rate applicable to the supplied origin only when the source supports it. "
        "Allowed evidence field names: tariff.rate, tariff.local_code, tax.rate, fx.rate, trade.latest_total_imports, trade.latest_imports_from_origin, "
        "trade.latest_origin_share, trade.history, supply.supplier_count, supply.cr3, supply.cr5, supply.hhi, supply.top_suppliers. "
        "trade.history is an array of objects with year, total_imports and imports_from_origin. "
        "marketplace_observations must contain exact observed price, currency and a public product/listing URL. "
        "Every evidence.value must be a JSON-encoded STRING: use \"20.0\" for a number and a compact JSON string for arrays/objects. "
        "If a value is not directly supported, do not return it; add the missing field to gaps. "
        "JSON shape: "+json.dumps(_base_research_schema(),ensure_ascii=False)+"\nJSON example: "+_research_json_example()
    )
    user=_research_prompt(project,market,snapshot,requested)
    if mode=="responses":
        return _responses_web_research(cfg,system=system,user=user,max_tokens=7000,schema=_base_research_schema())
    if mode=="anthropic":
        base=_clean(cfg.get("base_url")).rstrip("/")
        url=f"{base}/messages"
        body={
            "model":cfg["model"],"max_tokens":2600,"temperature":0,"system":system,
            "messages":[{"role":"user","content":user}],
            "tools":[{"type":"web_search_20250305","name":"web_search","max_uses":4}],
        }
        r=requests.post(url,headers=_headers(cfg),json=body,timeout=90);_ensure_success(r);data=r.json()
        texts=[]
        for part in data.get("content") or []:
            if isinstance(part,dict) and part.get("type")=="text" and part.get("text"):
                texts.append(str(part["text"]))
        result=_parse_json_loose("\n".join(texts))
        result["_model_calls"]=1;result["_model_usage"]=_usage_from_payload(data);result["_web_urls"]=sorted(_collect_urls(data));result["_endpoint"]=url
        return result
    base=_clean(cfg.get("base_url")).rstrip("/")
    model=cfg["model"] if str(cfg["model"]).startswith("models/") else f"models/{cfg['model']}"
    url=f"{base}/{quote(model,safe='/')}:generateContent"
    params={"key":cfg["api_key"]} if cfg.get("api_key") else {}
    body={
        "systemInstruction":{"parts":[{"text":system}]},
        "contents":[{"role":"user","parts":[{"text":user}]}],
        "tools":[{"google_search":{}}],
        "generationConfig":{"temperature":0,"maxOutputTokens":2600,"responseMimeType":"application/json"},
    }
    r=requests.post(url,params=params,headers={"Content-Type":"application/json"},json=body,timeout=90);_ensure_success(r);data=r.json()
    texts=[]
    for c in data.get("candidates") or []:
        for part in ((c.get("content") or {}).get("parts") or []):
            if isinstance(part,dict) and part.get("text"):
                texts.append(str(part["text"]))
    result=_parse_json_loose("\n".join(texts))
    result["_model_calls"]=1;result["_model_usage"]=_usage_from_payload(data);result["_web_urls"]=sorted(_collect_urls(data));result["_endpoint"]=url
    return result

def _extract_from_registered_source(project: dict[str,Any], market: str, src: dict[str,str], requested: list[str]) -> dict[str,Any] | None:
    if src["kind"] not in requested and "all" not in requested:
        return None
    fetched=fetch_public_source(src["url"])
    cfg=_config()
    schema=_base_research_schema()
    system=(
        "Extract only facts explicitly supported by the supplied source text. Do not use model memory. Never modify user-entered fields. "
        "Use field names tariff.rate, tariff.local_code, tax.rate, fx.rate, trade.latest_total_imports, trade.latest_imports_from_origin, "
        "trade.latest_origin_share, supply.supplier_count, supply.cr3, supply.cr5, supply.hhi or supply.top_suppliers when applicable. "
        "Return JSON only. If a unique value cannot be established, put the missing field in gaps. Schema: "+json.dumps(schema,ensure_ascii=False)
    )
    user=json.dumps({"project":{"title":project.get("title"),"origin":project.get("origin"),"hs_code":project.get("hs_code")},"market":market,
                     "requested":requested,"source":{"name":src["name"],"url":fetched["url"],"text":fetched["text"]}},ensure_ascii=False)
    _,text,_=_post_prompt(cfg,system=system,user=user,max_tokens=1800,json_mode=True)
    result=_parse_or_repair_json(cfg,text,schema)
    result["_source_hash"]=fetched["sha256"]
    return result



def _extract_registered_sources_once(project: dict[str,Any], market: str, requested: list[str]) -> dict[str,Any] | None:
    """Fetch registered public sources locally, then use at most one model call."""
    docs=[];hashes=[];fetch_errors=[]
    for src in _registered_sources(market):
        if src["kind"] not in requested and "all" not in requested:
            continue
        try:
            fetched=fetch_public_source(src["url"],max_chars=22000)
            if len(_clean(fetched.get("text"))) < 80:
                continue
            docs.append({"kind":src["kind"],"name":src["name"],"url":fetched["url"],"text":fetched["text"]})
            hashes.append(fetched.get("sha256") or "")
        except Exception as exc:
            fetch_errors.append(f"{src['kind']}: {exc}")
    if not docs:
        return None
    cfg=_config();schema=_base_research_schema()
    system=(
        "Extract only facts explicitly supported by the supplied official-source documents. Do not use model memory or outside facts. "
        "Return exactly one valid JSON object and no markdown. The word JSON is intentional. Never modify user-entered fields. "
        "Only answer the requested missing categories. If a unique value cannot be established from the supplied source text, add it to gaps. "
        "Allowed field names: tariff.rate, tariff.local_code, tax.rate. Every evidence row must reuse the exact source URL supplied in the documents. "
        "JSON shape: "+json.dumps(schema,ensure_ascii=False)+"\nJSON example: "+_research_json_example()
    )
    user=json.dumps({
        "project":{"title":project.get("title"),"origin":project.get("origin"),"hs_code":project.get("hs_code")},
        "market":market,"requested":requested,"sources":docs,
    },ensure_ascii=False)
    if _is_deepseek(cfg) and _clean(cfg.get("model")).lower()=="deepseek-v4-flash":
        data,result,endpoint=_structured_responses_call(
            cfg,system=system,user=user,schema=schema,schema_name="bordermargin_official_extract",max_tokens=2200,web_search=False
        )
    else:
        data,text,endpoint=_post_prompt(cfg,system=system,user=user,max_tokens=2200,json_mode=True)
        result=_parse_json_loose(text)
    result["_source_hash"]=hashlib.sha256("|".join(hashes).encode()).hexdigest() if hashes else ""
    result["_model_calls"]=1;result["_model_usage"]=_usage_from_payload(data);result["_endpoint"]=endpoint
    result["_source_fetch_errors"]=fetch_errors
    return result

def _valid_url(value: Any) -> bool:
    try:
        p=urlparse(str(value or ""));return p.scheme in {"http","https"} and bool(p.netloc)
    except Exception:return False


def _field_allowed(field: str, requested: list[str] | None) -> bool:
    if not requested or "all" in requested:
        return True
    field=str(field or "")
    if field.startswith("tariff."):
        family="tariff"
    elif field.startswith("tax."):
        family="tax"
    elif field.startswith("fx."):
        family="fx"
    elif field.startswith("trade.") or field.startswith("supply."):
        family="trade"
    else:
        return False
    return family in requested


def _decode_evidence_value(field: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text=value.strip()
    if field in {"trade.history", "supply.top_suppliers"}:
        try:
            parsed=json.loads(text)
            return parsed if isinstance(parsed, list) else value
        except Exception:
            return value
    if field in {"tariff.rate", "tax.rate", "fx.rate", "trade.latest_total_imports", "trade.latest_imports_from_origin", "trade.latest_origin_share", "supply.supplier_count", "supply.cr3", "supply.cr5", "supply.hhi"}:
        cleaned=text.replace(",", "").replace("%", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except Exception:
            return value
    return value


def _save_result(project_id: int, market: str, result: dict[str,Any], *, retrieval_method: str, source_hash: str = "", requested: list[str] | None = None) -> list[dict[str,Any]]:
    saved=[]
    for row in result.get("evidence") or []:
        if not isinstance(row,dict) or not row.get("field") or not _valid_url(row.get("source_url")):
            continue
        field=str(row.get("field") or "")
        if not _field_allowed(field,requested):
            continue
        rec=save_ai_evidence({"project_id":project_id,"market":market,"evidence_type":"field","field_name":field,
            "source_name":row.get("source_name") or urlparse(str(row.get("source_url"))).hostname,"source_url":row.get("source_url"),
            "source_type":row.get("source_type") or "web","evidence_level":_source_level(str(row.get("source_url")),str(row.get("source_type") or "")),
            "retrieval_method":retrieval_method,"confidence":row.get("confidence") or "medium","observed_at":row.get("observed_at") or None,
            "excerpt":row.get("excerpt") or "","source_hash":source_hash,"metadata":{"unit":row.get("unit")},
            "value": _decode_evidence_value(field, row.get("value"))});saved.append(rec)
    if not requested or "market_access" in requested or "all" in requested:
        for row in result.get("market_access") or []:
            if not isinstance(row,dict) or not row.get("requirement") or not _valid_url(row.get("source_url")):
                continue
            rec=save_ai_evidence({"project_id":project_id,"market":market,"evidence_type":"market_access","field_name":str(row.get("requirement")),
                "value":{"status":row.get("status")},"source_name":row.get("source_name") or urlparse(str(row.get("source_url"))).hostname,
                "source_url":row.get("source_url"),"source_type":"web","evidence_level":_source_level(str(row.get("source_url"))),
                "retrieval_method":retrieval_method,"confidence":row.get("confidence") or "medium","excerpt":row.get("excerpt") or "","source_hash":source_hash});saved.append(rec)
    return saved

def _seed_snapshot(project: dict[str, Any], market: str) -> dict[str, Any]:
    """Create a minimal source-neutral snapshot so verified AI evidence can fill gaps.

    The seed contains no inferred values. It exists only to give the evidence layer a
    deterministic place to store recovered fields when primary providers returned no
    snapshot at all.
    """
    code=str(market or "").upper()
    cfg=MARKETS.get(code) or {}
    attrs=project.get("attributes") or {}
    year=datetime.now(timezone.utc).year
    hs="".join(ch for ch in str(project.get("hs_code") or "") if ch.isalnum())[:6]
    return {
        "market":code,
        "reporter_code":str(cfg.get("reporter") or ""),
        "currency":str(cfg.get("currency") or "USD"),
        "hs_code":hs,
        "origin":{"code":str(attrs.get("origin_partner_code") or ""),"name":str(project.get("origin") or "")},
        "start_year":year-5,
        "end_year":year-1,
        "trade":{"history":[],"latest_total_imports":None,"latest_imports_from_origin":None,"latest_origin_share":None},
        "suppliers":{},
        "tariff":{"rate":None},
        "tariff_official_lookup":{},
        "fx":{},
        "quality":{},
        "seeded_for_ai_recovery":True,
    }


def _numeric(value: Any) -> float | None:
    try:
        out=float(value)
        return out if out == out and out not in (float("inf"), float("-inf")) else None
    except Exception:
        return None


def _trade_unit_is_usable(rec: dict[str, Any]) -> bool:
    unit=str((rec.get("metadata") or {}).get("unit") or "").strip().upper()
    # Existing providers and older evidence records may omit a unit. Keep them
    # readable, but explicit non-USD monetary units must never be written into USD
    # trade fields.
    if not unit:
        return True
    return unit in {"USD","US$","US DOLLAR","US DOLLARS","CURRENT USD"} or "USD" in unit


def _apply_evidence(project: dict[str,Any], snapshot: dict[str,Any] | None, saved: list[dict[str,Any]]) -> dict[str,Any] | None:
    if not saved:return snapshot
    snapshot=snapshot or _seed_snapshot(project, str((saved[0] if saved else {}).get("market") or ""))
    out=json.loads(json.dumps(snapshot))
    applied=[]
    market=str(out.get("market") or "").upper()
    user_tariff=bool(get_tariff_override(market, str(project.get("hs_code") or "")[:6]))
    # A saved cost fallback is not a verified tax record. AI may populate source-
    # backed tax evidence without changing the user assumption itself.
    user_tax=bool(get_tax_override(market))
    for rec in saved:
        field=rec.get("field_name"); value=rec.get("value")
        if field=="tariff.rate" and not user_tariff and (out.get("tariff") or {}).get("rate") is None:
            try: rate=float(value)
            except Exception: continue
            out["tariff"]={"rate":rate,"year":rec.get("observed_at"),"tariff_type":"AI-recovered evidence","source":rec.get("source_name"),"source_type":"official-ai-recovered" if rec.get("evidence_level")=="B" else "ai-recovered","lookup_url":rec.get("source_url"),"retrieval_method":rec.get("retrieval_method"),"confidence":rec.get("confidence")};applied.append(field)
        elif field=="tax.rate" and not user_tax and (out.get("tax") or {}).get("rate") is None:
            try: rate=float(value)
            except Exception: continue
            observed=rec.get("observed_at")
            out["tax"]={
                "rate":rate,"source":rec.get("source_name"),"source_url":rec.get("source_url"),
                "source_type":"ai-recovered","retrieval_method":rec.get("retrieval_method"),
                "confidence":rec.get("confidence"),"observed_at":observed,"reference_year":observed,
            };applied.append(field)
        elif field=="trade.history" and not (out.get("trade") or {}).get("history") and isinstance(value,list) and _trade_unit_is_usable(rec):
            hist=[]
            for row in value[:20]:
                if not isinstance(row,dict): continue
                try: y=int(str(row.get("year"))[:4])
                except Exception: continue
                total=_numeric(row.get("total_imports")); origin=_numeric(row.get("imports_from_origin"))
                if total is None and origin is None: continue
                hist.append({"year":y,"total_imports":total,"imports_from_origin":origin})
            hist=sorted({int(x["year"]):x for x in hist}.values(),key=lambda x:x["year"])
            if hist:
                trade=out.setdefault("trade",{});trade["history"]=hist
                world_hist=[{"year":x["year"],"trade_value":x.get("total_imports")} for x in hist]
                metrics=compute_growth_metrics(world_hist);trade["world_metrics"]=metrics
                latest=next((x for x in reversed(hist) if x.get("total_imports") is not None),None)
                if latest:
                    trade["latest_year"]=latest["year"];trade["latest_total_imports"]=latest.get("total_imports")
                    trade["latest_imports_from_origin"]=latest.get("imports_from_origin")
                    if latest.get("total_imports") not in (None,0) and latest.get("imports_from_origin") is not None:
                        trade["latest_origin_share"]=float(latest["imports_from_origin"])/float(latest["total_imports"])
                trade["ai_recovered_history"]=True;applied.append(field)
        elif field=="trade.latest_total_imports" and (out.get("trade") or {}).get("latest_total_imports") is None and _trade_unit_is_usable(rec):
            val=_numeric(value)
            if val is None: continue
            out.setdefault("trade",{})["latest_total_imports"]=val;out["trade"]["ai_recovered_latest"]=True;applied.append(field)
            if rec.get("observed_at"):out["trade"]["latest_year"]=rec.get("observed_at")
        elif field=="trade.latest_imports_from_origin" and (out.get("trade") or {}).get("latest_imports_from_origin") is None and _trade_unit_is_usable(rec):
            val=_numeric(value)
            if val is None: continue
            out.setdefault("trade",{})["latest_imports_from_origin"]=val;out["trade"]["ai_recovered_origin_latest"]=True;applied.append(field)
        elif field=="trade.latest_origin_share" and (out.get("trade") or {}).get("latest_origin_share") is None:
            try: val=float(value)
            except Exception: continue
            if val > 1: val = val / 100
            out.setdefault("trade",{})["latest_origin_share"]=val;out["trade"]["ai_recovered_origin_share"]=True;applied.append(field)
        elif field=="tariff.local_code":
            confirmed=str(project.get("hs_code") or "").strip()
            current=(out.get("tariff_official_lookup") or {}).get("local_code")
            if len(''.join(ch for ch in confirmed if ch.isalnum())) <= 6 and not current and value:
                out.setdefault("tariff_official_lookup",{})["local_code"]=str(value)
                out["tariff_official_lookup"]["source"]=rec.get("source_name")
                out["tariff_official_lookup"]["lookup_url"]=rec.get("source_url")
                out["tariff_official_lookup"]["retrieval_method"]=rec.get("retrieval_method")
                out["tariff_official_lookup"]["confidence"]=rec.get("confidence");applied.append(field)
        elif field.startswith("supply."):
            suppliers=out.setdefault("suppliers",{})
            key=field.split(".",1)[1]
            if key=="top_suppliers" and not suppliers.get("suppliers") and isinstance(value,list):
                rows=[]
                for i,row in enumerate(value[:50],1):
                    if not isinstance(row,dict): continue
                    try: tv=float(row.get("trade_value")) if row.get("trade_value") not in (None,"") else None
                    except Exception: tv=None
                    try: sh=float(row.get("share")) if row.get("share") not in (None,"") else None
                    except Exception: sh=None
                    if sh is not None and sh>1: sh=sh/100
                    rows.append({"partner_code":str(row.get("partner_code") or row.get("iso3") or i),"partner_name":row.get("partner_name") or row.get("name") or row.get("country") or str(row.get("iso3") or i),"partner_iso3":row.get("iso3"),"trade_value":tv,"share":sh,"rank":int(row.get("rank") or i)})
                if rows:
                    suppliers["suppliers"]=rows;suppliers["supplier_count"]=suppliers.get("supplier_count") or len(rows);suppliers["source"]=rec.get("source_name");suppliers["retrieval_method"]=rec.get("retrieval_method");applied.append(field)
            elif key in {"supplier_count","cr3","cr5","hhi"} and suppliers.get(key) is None:
                try: val=float(value)
                except Exception: continue
                if key in {"cr3","cr5"} and val>1: val=val/100
                suppliers[key]=int(val) if key=="supplier_count" else val
                suppliers["source"]=rec.get("source_name");suppliers["retrieval_method"]=rec.get("retrieval_method");applied.append(field)
        elif field=="fx.rate" and (out.get("fx") or {}).get("rate") is None:
            try: val=float(value)
            except Exception: continue
            out["fx"]={"rate":val,"source":rec.get("source_name"),"source_url":rec.get("source_url"),"source_type":"ai-recovered","retrieval_method":rec.get("retrieval_method"),"confidence":rec.get("confidence")};applied.append(field)
    trade=out.get("trade") or {}
    if trade.get("latest_origin_share") is None and trade.get("latest_total_imports") not in (None,0) and trade.get("latest_imports_from_origin") is not None:
        try: trade["latest_origin_share"]=float(trade["latest_imports_from_origin"])/float(trade["latest_total_imports"])
        except Exception: pass
    if not applied:
        return snapshot
    out["ai_recovery"]={"updated_at":_now(),"evidence_count":len(saved),"applied_fields":list(dict.fromkeys(applied))}
    # Preserve the original source sync timestamp separately while making the
    # AI-updated snapshot the newest project state.
    out["source_synced_at"]=out.get("source_synced_at") or out.get("synced_at")
    out["synced_at"]=_now()
    return save_snapshot(out)


def _result_fields(result: dict[str, Any] | None) -> set[str]:
    return {str(row.get("field")) for row in ((result or {}).get("evidence") or []) if isinstance(row, dict) and row.get("field")}


def _remaining_after_result(project: dict[str, Any], snapshot: dict[str, Any] | None, requested: list[str], result: dict[str, Any] | None) -> list[str]:
    """Remove categories that a research result fully resolves."""
    fields = _result_fields(result)
    out: list[str] = []
    market = str((snapshot or {}).get("market") or "").upper()
    tariff = (snapshot or {}).get("tariff") or {}
    official = (snapshot or {}).get("tariff_official_lookup") or {}
    tax = (snapshot or {}).get("tax") or {}
    fx = (snapshot or {}).get("fx") or {}
    trade = (snapshot or {}).get("trade") or {}
    suppliers = (snapshot or {}).get("suppliers") or {}
    user_tariff = bool(get_tariff_override(market, str(project.get("hs_code") or "")[:6])) if market else False
    user_tax = bool(get_tax_override(market)) if market else False
    for item in requested:
        if item == "tax":
            if user_tax or tax.get("rate") is not None or "tax.rate" in fields:
                continue
        elif item == "fx":
            if fx.get("rate") is not None or "fx.rate" in fields:
                continue
        elif item == "tariff":
            has_rate = user_tariff or tariff.get("rate") is not None or "tariff.rate" in fields
            has_local = bool(official.get("local_code") or tariff.get("nomenclature") or "tariff.local_code" in fields)
            if has_rate and has_local:
                continue
        elif item == "trade":
            has_total = trade.get("latest_total_imports") is not None or "trade.latest_total_imports" in fields or "trade.history" in fields
            has_share = trade.get("latest_origin_share") is not None or "trade.latest_origin_share" in fields
            has_supply = bool(suppliers.get("suppliers")) or "supply.top_suppliers" in fields
            if has_total and has_share and has_supply:
                continue
        elif item == "market_access":
            if (result or {}).get("market_access"):
                continue
        elif item == "marketplace":
            if (result or {}).get("marketplace_observations"):
                continue
        out.append(item)
    return out


def recover_market(project: dict[str,Any], snapshot: dict[str,Any] | None, market: str, *, requested: list[str] | None = None) -> dict[str,Any]:
    """Recover missing evidence through official sources and provider web search.

    The flow is deliberately outcome-oriented: registered customs/tax pages are
    tried first, then native web research handles anything still missing.  DeepSeek
    web research uses a search stage plus a separate structured-extraction stage,
    so a valid search can no longer be discarded just because the first answer was
    not JSON.
    """
    refresh_settings()
    requested=list(dict.fromkeys(requested or ["tariff","tax","trade","fx","market_access","marketplace"]))
    project_id=int(project.get("id") or 0);market=str(market or "").upper()
    run_id=start_ai_recovery_run(project_id,market,{"requested":requested})
    saved: list[dict[str, Any]]=[];errors=[];methods=[];model_calls=0
    usage={"input_tokens":0,"output_tokens":0,"total_tokens":0}
    all_observations: list[dict[str, Any]]=[]
    gaps: list[str]=[]
    try:
        cfg=_config()
        remaining=list(requested)

        # 1) When the configured provider has native web search, use it first.
        # This is the most reliable path for DeepSeek Responses: the provider can
        # search/open current official pages itself instead of depending on our
        # local HTML fetcher being able to render every government site.
        if remaining and _supports_native_web(cfg):
            try:
                web_result=_native_web_research(project,market,snapshot,remaining)
                if web_result:
                    methods.append("provider-native-web-search")
                    model_calls += int(web_result.get("_model_calls") or 1)
                    u=web_result.get("_model_usage") or {}
                    for k in usage: usage[k]+=int(u.get(k) or 0)
                    requested_now=list(remaining)
                    saved.extend(_save_result(project_id,market,web_result,retrieval_method="provider-native-web-search",requested=requested_now))
                    gaps.extend(web_result.get("gaps") or [])
                    all_observations.extend(web_result.get("marketplace_observations") or [])
                    remaining=_remaining_after_result(project,snapshot,remaining,web_result)
            except Exception as exc:
                errors.append(f"web: {exc}")

        # 2) For tariff/tax still unresolved after web search (or for providers
        # without a web tool), try registered official pages as a deterministic
        # fallback.  This path can recover HMRC/CBSA/EU tax/tariff values even if
        # the broader web research did not surface a structured value.
        official_requested=[x for x in remaining if x in {"tariff","tax"}]
        if official_requested and _registered_sources(market):
            try:
                official_result=_extract_registered_sources_once(project,market,official_requested)
                if official_result:
                    methods.append("official-source-extraction")
                    model_calls += int(official_result.get("_model_calls") or 1)
                    u=official_result.get("_model_usage") or {}
                    for k in usage: usage[k]+=int(u.get(k) or 0)
                    errors.extend(official_result.get("_source_fetch_errors") or [])
                    saved.extend(_save_result(project_id,market,official_result,retrieval_method="official-source-extraction",source_hash=str(official_result.get("_source_hash") or ""),requested=official_requested))
                    gaps.extend(official_result.get("gaps") or [])
                    remaining=_remaining_after_result(project,snapshot,remaining,official_result)
            except Exception as exc:
                errors.append(f"official: {exc}")

        # 3) A provider without native web search cannot safely invent external
        # facts.  Anything not resolved from registered official pages remains a
        # visible gap.
        if remaining and not _supports_native_web(cfg):
            unsupported=[x for x in remaining if x not in {"tariff","tax"}]
            if unsupported:
                errors.append("NO_WEB_SEARCH_CAPABILITY: "+", ".join(unsupported))
            elif not methods:
                errors.append("NO_READABLE_OFFICIAL_SOURCE")

        valid_obs=[]
        if "marketplace" in requested:
            for row in all_observations:
                if not isinstance(row,dict) or not _valid_url(row.get("source_url")):
                    continue
                try: price=float(row.get("price"))
                except Exception: continue
                if price<=0: continue
                currency=_clean(row.get("currency")).upper()
                if len(currency)!=3: continue
                valid_obs.append({
                    "listing_id":hashlib.sha1(str(row.get("source_url")).encode()).hexdigest()[:20],
                    "title":_clean(row.get("title")),"brand":_clean(row.get("brand")),"price":price,"currency":currency,
                    "url":row.get("source_url"),"source":row.get("source_name") or urlparse(str(row.get("source_url"))).hostname,
                    "observed_at":row.get("observed_at")
                })
        if valid_obs:
            attrs=project.get("attributes") or {}
            comparable=build_comparable_set(
                valid_obs,query=project.get("title") or "",excluded_terms=[],expected_category_id=None,
                expected_attributes=attrs.get("ebay_aspects") if isinstance(attrs.get("ebay_aspects"),dict) else {},
                minimum_query_overlap=0.0,minimum_attribute_overlap=0.0,remove_price_outliers=True
            )
            save_listing_snapshot({
                "environment":"ai-web-research","source":"AI evidence recovery","project_id":project_id,"market_code":market,
                "marketplace":"WEB_RESEARCH","query":project.get("title") or "","verified_market_data":False,"source_backed_market_data":True,
                "is_market_data":True,"currency":valid_obs[0].get("currency"),"total":len(valid_obs),"returned":len(valid_obs),"items":valid_obs,
                "comparable_set":comparable,"retrieval_method":"provider-native-web-search","evidence_level":"B/C"
            })

        before_recovery=(snapshot or {}).get("ai_recovery") or {}
        updated=_apply_evidence(project,snapshot,saved)
        after_recovery=(updated or {}).get("ai_recovery") or {}
        applied_fields=list(after_recovery.get("applied_fields") or []) if after_recovery.get("updated_at") != before_recovery.get("updated_at") else []
        recovered_count=len(saved)+len(valid_obs)
        status="recovered" if recovered_count>0 and not remaining else "partial" if recovered_count>0 else "no_evidence"
        result={
            "project_id":project_id,"market":market,"status":status,"saved":len(saved),"applied":len(applied_fields),
            "applied_fields":applied_fields,"methods":methods,"errors":errors,"snapshot_updated":bool(applied_fields),
            "marketplace_observations":len(valid_obs),"gaps":list(dict.fromkeys(gaps+remaining)),
            "web_search_attempted":_supports_native_web(cfg),"model_calls":model_calls,"usage":usage,
        }
        finish_ai_recovery_run(run_id,status="completed" if recovered_count>0 else "partial",result=result,error="\n".join(errors))
        return result
    except Exception as exc:
        finish_ai_recovery_run(run_id,status="failed",result={"saved":len(saved),"model_calls":model_calls,"usage":usage},error=str(exc))
        raise



def recover_hs_candidates(project: dict[str, Any], *, query: str = "", limit: int = 8) -> dict[str, Any]:
    """Return source-backed HS6 candidates without changing the project.

    This fallback is available only when the configured protocol exposes native web
    research. Every candidate must carry a public source URL.
    """
    cfg=_config(); protocol=cfg.get("protocol")
    if not _supports_native_web(cfg):
        return {"candidates":[],"count":0,"source":"AI Evidence Recovery","method":"native web research unavailable"}
    text=_clean(query or project.get("title"))
    if len(text)<2:
        return {"candidates":[],"count":0,"source":"AI Evidence Recovery","method":"no product query"}
    schema={"type":"object","properties":{"candidates":{"type":"array","items":{"type":"object","properties":{"code":{"type":"string"},"description":{"type":"string"},"source_name":{"type":"string"},"source_url":{"type":"string"},"confidence":{"type":"number"}},"required":["code","description","source_url"]}}},"required":["candidates"]}
    system=(
        "Research HS classification candidates for the supplied product using live official customs, tariff or statistical classification sources. "
        "Do not use model memory as evidence. Return only six-digit HS candidates that are supported by a source URL. "
        "Do not change the user's product or any confirmed code. Return exactly one JSON object and no markdown. "
        "The word JSON is intentional. Schema: "+json.dumps(schema,ensure_ascii=False)+
        "\nJSON example: "+json.dumps({"candidates":[{"code":"850811","description":"Example classification description","source_name":"Official customs source","source_url":"https://example.gov/hs","confidence":0.8}]},ensure_ascii=False)
    )
    user=json.dumps({"product":text,"description":project.get("description"),"origin":project.get("origin"),"attributes":project.get("attributes") or {},"limit":max(1,min(int(limit),20))},ensure_ascii=False)
    data=None
    if protocol=="anthropic":
        base=_clean(cfg.get("base_url")).rstrip("/"); url=f"{base}/messages"
        body={"model":cfg["model"],"max_tokens":1200,"temperature":0,"system":system,"messages":[{"role":"user","content":user}],"tools":[{"type":"web_search_20250305","name":"web_search","max_uses":4}]}
        r=requests.post(url,headers=_headers(cfg),json=body,timeout=90);_ensure_success(r);payload=r.json(); chunks=[]
        for part in payload.get("content") or []:
            if isinstance(part,dict) and part.get("type")=="text" and part.get("text"): chunks.append(str(part["text"]))
        data=_parse_or_repair_json(cfg,"\n".join(chunks),schema)
    elif protocol=="gemini":
        base=_clean(cfg.get("base_url")).rstrip("/"); model=cfg["model"] if str(cfg["model"]).startswith("models/") else f"models/{cfg['model']}"; url=f"{base}/{quote(model,safe='/')}:generateContent"
        params={"key":cfg["api_key"]} if cfg.get("api_key") else {}; body={"systemInstruction":{"parts":[{"text":system}]},"contents":[{"role":"user","parts":[{"text":user}]}],"tools":[{"google_search":{}}],"generationConfig":{"temperature":0,"maxOutputTokens":1200,"responseMimeType":"application/json"}}
        r=requests.post(url,params=params,headers={"Content-Type":"application/json"},json=body,timeout=90);_ensure_success(r);payload=r.json();chunks=[]
        for c in payload.get("candidates") or []:
            for part in ((c.get("content") or {}).get("parts") or []):
                if isinstance(part,dict) and part.get("text"): chunks.append(str(part["text"]))
        data=_parse_or_repair_json(cfg,"\n".join(chunks),schema)
    else:
        data=_responses_web_research(cfg,system=system,user=user,max_tokens=1200,schema=schema)
    rows=[]
    for row in (data or {}).get("candidates") or []:
        if not isinstance(row,dict) or not _valid_url(row.get("source_url")): continue
        code=''.join(ch for ch in str(row.get("code") or "") if ch.isdigit())[:6]
        if len(code)!=6: continue
        try: conf=float(row.get("confidence")) if row.get("confidence") not in (None,"") else 0.5
        except Exception: conf=0.5
        if conf>1: conf=conf/100
        rows.append({"code":code,"description":_clean(row.get("description")),"level":6,"leaf":True,"source":row.get("source_name") or urlparse(str(row.get("source_url"))).hostname,"source_url":row.get("source_url"),"relative_confidence":max(0,min(1,conf)),"method":"source-backed AI web research"})
    # Keep one strongest observation per code.
    best={}
    for row in rows:
        if row["code"] not in best or row["relative_confidence"]>best[row["code"]]["relative_confidence"]: best[row["code"]]=row
    out=sorted(best.values(),key=lambda x:x["relative_confidence"],reverse=True)[:max(1,min(int(limit),20))]
    return {"query":text,"candidates":out,"count":len(out),"source":"AI Evidence Recovery","method":"source-backed native web research; user confirmation required"}

def recovery_capabilities() -> dict[str,Any]:
    cfg=_config();protocol=cfg.get("protocol")
    native=_supports_native_web(cfg)
    return {
        "configured":bool(protocol and cfg.get("base_url") and cfg.get("model")),
        "protocol":protocol,
        "native_web_search":native,
        "adaptive_web_search":protocol=="openai_compatible" and native,
        "registered_source_extraction":bool(protocol and cfg.get("base_url") and cfg.get("model")),
        "max_model_calls_per_market":4,
        "protected_user_inputs":True,
    }
