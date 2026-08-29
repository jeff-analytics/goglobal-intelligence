from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .ai_layer import (
    _config,
    _ensure_success,
    _extract_anthropic_text,
    _extract_gemini_text,
    _headers,
    _is_deepseek,
    _parse_json_loose,
    _post_prompt,
    _require_core,
    _structured_responses_call,
    _usage_from_payload,
)
from .ai_recovery import _responses_web_research, _supports_native_web
from .config import refresh_settings, settings

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _report_schema() -> dict[str, Any]:
    dimension = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assessment": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["assessment", "evidence"],
    }
    source = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "url": {"type": "string"},
            "source_type": {"type": "string"},
            "used_for": {"type": "string"},
        },
        "required": ["title", "url", "source_type", "used_for"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "headline": {"type": "string"},
            "decision": {
                "type": "string",
                "enum": ["PROCEED", "PROCEED_WITH_CONDITIONS", "HOLD", "INSUFFICIENT_EVIDENCE"],
            },
            "executive_summary": {"type": "string"},
            "research_plan": {"type": "array", "items": {"type": "string"}},
            "market_demand": dimension,
            "supply_competition": dimension,
            "market_access": dimension,
            "pricing_economics": dimension,
            "risks": {"type": "array", "items": {"type": "string"}},
            "evidence_gaps": {"type": "array", "items": {"type": "string"}},
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "decision_language": {"type": "string"},
            "sources": {"type": "array", "items": source},
        },
        "required": [
            "headline",
            "decision",
            "executive_summary",
            "research_plan",
            "market_demand",
            "supply_competition",
            "market_access",
            "pricing_economics",
            "risks",
            "evidence_gaps",
            "next_actions",
            "decision_language",
            "sources",
        ],
    }


def _load_skill_text() -> str:
    wanted = [
        "market-demand",
        "trade-supply",
        "tariff-tax",
        "market-access",
        "pricing-economics",
        "evidence-validation",
        "decision-research",
    ]
    parts: list[str] = []
    for name in wanted:
        path = SKILLS_DIR / name / "SKILL.md"
        if path.exists():
            parts.append(path.read_text(encoding="utf-8")[:2200])
    return "\n\n".join(parts)


def skill_catalog() -> list[dict[str, str]]:
    labels = {
        "market-demand": ("市场需求", "Market demand"),
        "trade-supply": ("贸易与供给", "Trade & supply"),
        "tariff-tax": ("关税与税费", "Tariff & tax"),
        "market-access": ("市场准入", "Market access"),
        "pricing-economics": ("价格与经济性", "Pricing & economics"),
        "evidence-validation": ("证据校验", "Evidence validation"),
        "decision-research": ("决策研究", "Decision research"),
    }
    rows = []
    for key, (zh, en) in labels.items():
        rows.append({"id": key, "label_zh": zh, "label_en": en, "enabled": (SKILLS_DIR / key / "SKILL.md").exists()})
    return rows


def research_capabilities() -> dict[str, Any]:
    refresh_settings()
    cfg = _config()
    native = bool(_supports_native_web(cfg))
    tavily = bool(settings.tavily_api_key)
    selected = settings.web_research_provider or "auto"
    if selected == "none":
        active = "none"
    elif selected == "native":
        active = "native" if native else "unavailable"
    elif selected == "tavily":
        active = "tavily" if tavily else "unavailable"
    else:
        active = "native" if native else ("tavily" if tavily else "none")
    return {
        "provider": selected,
        "active_provider": active,
        "native_available": native,
        "tavily_configured": tavily,
        "web_search_available": active in {"native", "tavily"},
        "model_configured": bool(cfg.get("protocol") and cfg.get("base_url") and cfg.get("model")),
        "structured_output": bool(cfg.get("protocol") and cfg.get("base_url") and cfg.get("model")),
        "skills": skill_catalog(),
        "protected_user_inputs": True,
        "decision_agent": True,
    }


def validate_tavily(api_key: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    key = _clean(api_key or settings.tavily_api_key)
    if not key:
        raise RuntimeError("Tavily API key is not configured")
    base = _clean(base_url or settings.tavily_base_url or "https://api.tavily.com").rstrip("/")
    url = f"{base}/search"
    payload = {
        "api_key": key,
        "query": "World Trade Organization official website",
        "search_depth": "basic",
        "max_results": 1,
        "include_answer": False,
        "include_raw_content": False,
    }
    r = requests.post(url, json=payload, timeout=25)
    _ensure_success(r)
    data = r.json()
    results = data.get("results") or []
    return {"ok": True, "provider": "tavily", "results": len(results), "endpoint": url}


def _tavily_search(query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    refresh_settings()
    key = _clean(settings.tavily_api_key)
    if not key:
        raise RuntimeError("Tavily API key is not configured")
    base = _clean(settings.tavily_base_url or "https://api.tavily.com").rstrip("/")
    payload = {
        "api_key": key,
        "query": query,
        "search_depth": "advanced",
        "max_results": max(1, min(int(max_results), 8)),
        "include_answer": False,
        "include_raw_content": False,
    }
    r = requests.post(f"{base}/search", json=payload, timeout=35)
    _ensure_success(r)
    data = r.json()
    rows = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"))
        if not url.startswith("http"):
            continue
        rows.append(
            {
                "title": _clean(item.get("title")) or (urlparse(url).hostname or url),
                "url": url,
                "content": _clean(item.get("content"))[:1800],
                "score": item.get("score"),
            }
        )
    return rows


def _default_plan(project: dict[str, Any], market: str, decision: dict[str, Any], market_contract: dict[str, Any], language: str = "en") -> list[str]:
    product = _clean(project.get("title")) or ("商品" if str(language).lower().startswith("zh") else "product")
    hs = _clean(project.get("hs_code"))
    origin = _clean(project.get("origin"))
    gaps = list((decision.get("evidence_quality") or {}).get("missing") or [])
    zh = str(language).lower().startswith("zh")
    if zh:
        plan = [
            f"验证 {product} 在{market}的当前需求与市场背景",
            f"审视 HS {hs or '未确认'}、原产地 {origin or '未确认'} 的供给与竞争结构",
            "核验当前产品合规、认证及进口准入要求",
            "将 BorderMargin 的确定性经济性结果与当前公开渠道和价格证据进行比较",
        ]
        if gaps:
            plan.insert(0, "补齐或解释当前证据缺口：" + "、".join(str(x) for x in gaps[:6]))
    else:
        plan = [
            f"Validate current demand and market context for {product} in {market}",
            f"Review supply and competitive structure for HS {hs or 'unconfirmed'} and origin {origin or 'unconfirmed'}",
            "Check current product compliance, certification and import-access requirements",
            "Compare deterministic BorderMargin economics with current public channel and pricing evidence",
        ]
        if gaps:
            plan.insert(0, "Close or explain current evidence gaps: " + ", ".join(str(x) for x in gaps[:6]))
    tariff = (market_contract or {}).get("tariff") or {}
    tax = (market_contract or {}).get("tax") or {}
    if tariff.get("rate") is None or tax.get("rate") is None:
        plan.append("从权威来源核验尚未解决的关税或消费税处理" if zh else "Verify unresolved tariff or consumption-tax treatment from primary sources")
    return plan[:6]


def _search_queries(project: dict[str, Any], market_name: str, market_code: str, plan: list[str]) -> list[str]:
    product = _clean(project.get("title"))
    hs = _clean(project.get("hs_code"))
    origin = _clean(project.get("origin"))
    base = f'"{product}" {market_name} {market_code}'.strip()
    queries = [
        f"{base} market demand imports competition {hs}",
        f"{base} product compliance certification import requirements government regulator",
        f"{base} retail price marketplace current",
        f"{hs} {origin} to {market_name} tariff customs tax official",
    ]
    if any("tariff" in x.lower() or "tax" in x.lower() for x in plan):
        queries[-1] = f"{hs} {origin} {market_name} customs tariff VAT tax official"
    return [q for q in queries if q.strip()][:4]


def _sanitize_sources(result: dict[str, Any], allowed_urls: set[str] | None = None) -> None:
    rows = []
    seen: set[str] = set()
    for row in result.get("sources") or []:
        if not isinstance(row, dict):
            continue
        url = _clean(row.get("url"))
        if not url.startswith("http"):
            continue
        if allowed_urls is not None and url not in allowed_urls:
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "title": _clean(row.get("title")) or (urlparse(url).hostname or url),
                "url": url,
                "source_type": _clean(row.get("source_type")) or "web",
                "used_for": _clean(row.get("used_for")) or "research",
            }
        )
    result["sources"] = rows[:20]


def _instructions(language: str) -> str:
    output_language = "Simplified Chinese" if str(language).lower().startswith("zh") else "English"
    return (
        "You are BorderMargin's Decision Research Agent for cross-border product entry decisions. "
        "Use the deterministic BorderMargin data as the numeric baseline. Never alter user-entered costs, confirmed classification, manual overrides or uploaded observations. "
        "Keep the rule-based decision status separate from your advisory recommendation. If web evidence conflicts with BorderMargin or another source, report the conflict instead of silently choosing a value. "
        "Any new web-derived factual claim must be supported by a source URL supplied by the research tool. Do not invent URLs. "
        "Prefer government, customs, tax authority, regulator, WTO/UN/World Bank and other primary sources. Use retailers or marketplaces only for current public pricing/channel context. "
        "Do not create unsupported market-size forecasts or numeric facts. Missing information must remain an evidence gap. "
        "Write for a commercial decision-maker. The executive_summary should be concise but substantive, normally 120-220 words in English or an equivalent length in Chinese. "
        "Each of the four dimension assessments should explain the implication for market entry in 2-4 sentences and include 2-5 concrete evidence bullets when evidence exists. "
        "Risks and evidence gaps should be specific and non-duplicative. Next actions should be prioritized, operational, and tied to the identified evidence or economics. "
        "The decision_language should be suitable for a management review or investment/market-entry memo and should clearly state conditions, thresholds, or unresolved checks when relevant. "
        f"MANDATORY LANGUAGE RULE: write every user-facing narrative field in {output_language}, including headline, executive_summary, research_plan, all dimension assessments/evidence, risks, evidence_gaps, next_actions and decision_language. "
        "Do not mirror the language of search snippets when it differs from the requested output language. Keep brand names, currency codes, HS codes and standard acronyms unchanged. "
        "Return exactly one JSON object and no markdown. Required schema: "
        + json.dumps(_report_schema(), ensure_ascii=False)
        + "\nProfessional operating skills:\n"
        + _load_skill_text()
    )


def _report_language_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("headline", "executive_summary", "decision_language"):
        parts.append(_clean(result.get(key)))
    for key in ("research_plan", "risks", "evidence_gaps", "next_actions"):
        parts.extend(_clean(x) for x in (result.get(key) or []))
    for key in ("market_demand", "supply_competition", "market_access", "pricing_economics"):
        row = result.get(key) or {}
        if isinstance(row, dict):
            parts.append(_clean(row.get("assessment")))
            parts.extend(_clean(x) for x in (row.get("evidence") or []))
    return " ".join(x for x in parts if x)


def _language_mismatch(result: dict[str, Any], language: str) -> bool:
    text = _report_language_text(result)
    if not text:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if str(language).lower().startswith("zh"):
        return latin > 80 and (cjk < 20 or latin > cjk * 2.5)
    return cjk > 40 and cjk > latin * 0.5


def report_matches_language(saved: dict[str, Any] | None, language: str) -> bool:
    if not isinstance(saved, dict):
        return False
    result = saved.get("result") if isinstance(saved.get("result"), dict) else saved
    return not _language_mismatch(result, language)


def _merge_usage(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
    left = a or {}
    right = b or {}
    return {
        "input_tokens": int(left.get("input_tokens") or 0) + int(right.get("input_tokens") or 0),
        "output_tokens": int(left.get("output_tokens") or 0) + int(right.get("output_tokens") or 0),
        "total_tokens": int(left.get("total_tokens") or 0) + int(right.get("total_tokens") or 0),
    }


def _rewrite_report_language(cfg: dict[str, Any], result: dict[str, Any], language: str) -> tuple[dict[str, Any], dict[str, int], str]:
    if not _language_mismatch(result, language):
        return result, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, ""
    target = "Simplified Chinese" if str(language).lower().startswith("zh") else "English"
    original_sources = list(result.get("sources") or [])
    original_decision = result.get("decision")
    system = (
        f"Rewrite the supplied BorderMargin Decision Research JSON so every user-facing narrative field is in {target}. "
        "This is a translation/localization pass only. Preserve every fact, number, currency, HS code, named entity, recommendation condition and array structure. "
        "Do not add or remove evidence. Keep the decision enum unchanged. Keep source URLs and source titles unchanged. "
        "Return exactly one JSON object matching the provided schema and no markdown. Schema: "
        + json.dumps(_report_schema(), ensure_ascii=False)
    )
    data, text, endpoint = _post_prompt(
        cfg,
        system=system,
        user=json.dumps(result, ensure_ascii=False),
        max_tokens=4200,
        json_mode=True,
    )
    translated = _parse_json_loose(text)
    missing = [key for key in _report_schema()["required"] if key not in translated]
    if missing:
        raise RuntimeError("Language localization returned incomplete Decision Research JSON: " + ", ".join(missing))
    translated["sources"] = original_sources
    translated["decision"] = original_decision
    if _language_mismatch(translated, language):
        raise RuntimeError(f"Decision Research output language did not match requested locale: {target}")
    return translated, _usage_from_payload(data), endpoint


def _native_research(cfg: dict[str, Any], user_payload: dict[str, Any], language: str) -> tuple[dict[str, Any], dict[str, int], int, str]:
    system = _instructions(language)
    user = json.dumps(user_payload, ensure_ascii=False)
    protocol = _clean(cfg.get("protocol")).lower()
    if protocol == "openai_responses" or (protocol == "openai_compatible" and _is_deepseek(cfg)):
        result = _responses_web_research(cfg, system=system, user=user, max_tokens=5200, schema=_report_schema())
        usage = result.pop("_model_usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        calls = int(result.pop("_model_calls", 1) or 1)
        endpoint = _clean(result.pop("_endpoint", ""))
        result.pop("_web_urls", None)
        _sanitize_sources(result, None)
        return result, usage, calls, endpoint

    if protocol == "anthropic":
        base = _clean(cfg.get("base_url")).rstrip("/")
        url = f"{base}/messages"
        body = {
            "model": cfg["model"],
            "max_tokens": 4200,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        }
        r = requests.post(url, headers=_headers(cfg), json=body, timeout=100)
        _ensure_success(r)
        data = r.json()
        result = _parse_json_loose(_extract_anthropic_text(data))
        _sanitize_sources(result, None)
        return result, _usage_from_payload(data), 1, url

    if protocol == "gemini":
        base = _clean(cfg.get("base_url")).rstrip("/")
        model = cfg["model"] if str(cfg["model"]).startswith("models/") else f"models/{cfg['model']}"
        url = f"{base}/{quote(model, safe='/')}:generateContent"
        params = {"key": cfg["api_key"]} if cfg.get("api_key") else {}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 4200, "responseMimeType": "application/json"},
        }
        r = requests.post(url, params=params, headers={"Content-Type": "application/json"}, json=body, timeout=100)
        _ensure_success(r)
        data = r.json()
        result = _parse_json_loose(_extract_gemini_text(data))
        _sanitize_sources(result, None)
        return result, _usage_from_payload(data), 1, url

    raise RuntimeError("The configured model protocol does not provide provider-native web research")


def _tavily_research(cfg: dict[str, Any], user_payload: dict[str, Any], queries: list[str], language: str) -> tuple[dict[str, Any], dict[str, int], int, str, int]:
    rows: list[dict[str, Any]] = []
    for query in queries:
        rows.extend(_tavily_search(query, max_results=5))
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["url"] not in unique or float(row.get("score") or 0) > float(unique[row["url"]].get("score") or 0):
            unique[row["url"]] = row
    material = sorted(unique.values(), key=lambda x: float(x.get("score") or 0), reverse=True)[:16]
    allowed_urls = {x["url"] for x in material}
    prompt = {
        **user_payload,
        "web_research": material,
        "source_rule": "Use only the URLs in web_research for new web-derived claims.",
    }
    data, text, endpoint = _post_prompt(
        cfg,
        system=_instructions(language),
        user=json.dumps(prompt, ensure_ascii=False),
        max_tokens=4200,
        json_mode=True,
    )
    result = _parse_json_loose(text)
    _sanitize_sources(result, allowed_urls)
    return result, _usage_from_payload(data), 1, endpoint, len(queries)


def generate_decision_research(
    *,
    project: dict[str, Any],
    market_code: str,
    market_name: str,
    market_contract: dict[str, Any],
    decision: dict[str, Any],
    existing_evidence: list[dict[str, Any]] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    cfg = _require_core(_config(), need_model=True)
    caps = research_capabilities()
    plan = _default_plan(project, market_name, decision, market_contract, language)
    queries = _search_queries(project, market_name, market_code, plan)
    payload = {
        "product": {
            "title": project.get("title"),
            "description": project.get("description"),
            "origin": project.get("origin"),
            "hs_code": project.get("hs_code"),
        },
        "market": {"code": market_code, "name": market_name},
        "output_locale": "zh-CN" if str(language).lower().startswith("zh") else "en-US",
        "deterministic_decision_case": decision,
        "border_margin_contract": market_contract,
        "existing_source_backed_evidence": existing_evidence or [],
        "research_plan": plan,
    }
    active = caps.get("active_provider")
    if active == "native":
        result, usage, model_calls, endpoint = _native_research(cfg, payload, language)
        web_queries = 1
    elif active == "tavily":
        result, usage, model_calls, endpoint, web_queries = _tavily_research(cfg, payload, queries, language)
    else:
        data, text, endpoint = _post_prompt(
            cfg,
            system=_instructions(language)
            + "\nLive web research is unavailable in this run. Base the report only on BorderMargin data and explicitly list web-dependent items as evidence gaps.",
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=3600,
            json_mode=True,
        )
        result = _parse_json_loose(text)
        usage = _usage_from_payload(data)
        model_calls = 1
        web_queries = 0
        _sanitize_sources(result, set())
    missing = [key for key in _report_schema()["required"] if key not in result]
    if missing:
        raise RuntimeError("Model returned incomplete Decision Research JSON: " + ", ".join(missing))
    localized, localization_usage, localization_endpoint = _rewrite_report_language(cfg, result, language)
    if localized is not result:
        result = localized
        usage = _merge_usage(usage, localization_usage)
        model_calls += 1
        if localization_endpoint:
            endpoint = localization_endpoint
    return {
        "provider": cfg.get("provider") or cfg.get("protocol"),
        "protocol": cfg.get("protocol"),
        "model": cfg.get("model"),
        "mode": "decision-research-agent",
        "language": "zh" if str(language).lower().startswith("zh") else "en",
        "web_research_provider": active,
        "web_queries": web_queries,
        "model_calls": model_calls,
        "endpoint": endpoint,
        "usage": usage,
        "skills": [x["id"] for x in skill_catalog() if x.get("enabled")],
        "result": result,
    }
