from __future__ import annotations

import json

from app import research_agent


def _report():
    return {
        "headline": "UK launch remains conditional",
        "decision": "PROCEED_WITH_CONDITIONS",
        "executive_summary": "Evidence supports continued validation.",
        "research_plan": ["Check compliance"],
        "market_demand": {"assessment": "Demand exists", "evidence": ["Import evidence is available"]},
        "supply_competition": {"assessment": "Competition is concentrated", "evidence": ["CR3 is elevated"]},
        "market_access": {"assessment": "Compliance requires validation", "evidence": ["Official guidance found"]},
        "pricing_economics": {"assessment": "Economics need benchmark validation", "evidence": ["Cost model exists"]},
        "risks": ["Compliance uncertainty"],
        "evidence_gaps": ["Live price benchmark"],
        "next_actions": ["Validate UK requirements"],
        "decision_language": "Proceed only after compliance validation.",
        "sources": [{"title": "GOV.UK", "url": "https://www.gov.uk/example", "source_type": "official", "used_for": "market access"}],
    }


def test_skill_catalog_is_present():
    rows = research_agent.skill_catalog()
    ids = {row["id"] for row in rows}
    assert {"market-demand", "market-access", "evidence-validation", "decision-research"}.issubset(ids)
    assert all(row["enabled"] for row in rows)


def test_tavily_research_only_keeps_search_urls(monkeypatch):
    monkeypatch.setattr(research_agent, "_tavily_search", lambda query, max_results=5: [
        {"title": "GOV.UK", "url": "https://www.gov.uk/example", "content": "Official guidance", "score": 0.9}
    ])
    payload = _report()
    payload["sources"].append({"title": "Invented", "url": "https://invented.example/x", "source_type": "web", "used_for": "risk"})
    monkeypatch.setattr(research_agent, "_post_prompt", lambda *a, **k: (
        {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}},
        json.dumps(payload),
        "https://model.example/chat/completions",
    ))
    result, usage, calls, endpoint, web_queries = research_agent._tavily_research(
        {"protocol": "openai_compatible", "base_url": "https://model.example", "model": "m", "provider": "x", "api_key": "k"},
        {"product": {"title": "reader"}},
        ["q1", "q2"],
        "en",
    )
    assert [x["url"] for x in result["sources"]] == ["https://www.gov.uk/example"]
    assert usage["total_tokens"] == 30
    assert calls == 1
    assert web_queries == 2
    assert endpoint.endswith("/chat/completions")


def test_research_schema_has_decision_dimensions():
    schema = research_agent._report_schema()
    required = set(schema["required"])
    assert {"market_demand", "supply_competition", "market_access", "pricing_economics", "sources"}.issubset(required)


def test_chinese_research_plan_is_localized():
    plan = research_agent._default_plan(
        {"title": "Laptop Cases", "hs_code": "420212", "origin": "Vietnam"},
        "加拿大",
        {"evidence_quality": {"missing": ["market_access"]}},
        {"tariff": {"rate": None}, "tax": {"rate": 0.05}},
        "zh",
    )
    text = " ".join(plan)
    assert "验证" in text
    assert "加拿大" in text
    assert research_agent._language_mismatch({**_report(), "headline": "English headline"}, "zh") is True


def test_report_matches_language_rejects_legacy_wrong_locale_report():
    saved = {"language": "zh", "result": _report()}
    assert research_agent.report_matches_language(saved, "zh") is False
    zh = _report()
    zh.update({
        "headline": "加拿大市场建议有条件推进",
        "executive_summary": "当前证据显示市场需求存在，但仍需要核验合规要求、关税待遇和价格竞争力后再推进。建议在完成关键验证后进入下一阶段。",
        "research_plan": ["核验市场需求", "确认准入要求"],
        "market_demand": {"assessment": "市场需求具备基础", "evidence": ["已有进口数据支持"]},
        "supply_competition": {"assessment": "供给集中度较高", "evidence": ["CR3 较高"]},
        "market_access": {"assessment": "准入要求仍需核验", "evidence": ["已找到官方指引"]},
        "pricing_economics": {"assessment": "经济性需要继续验证", "evidence": ["已有成本模型"]},
        "risks": ["合规要求仍需确认"],
        "evidence_gaps": ["当前渠道价格证据不足"],
        "next_actions": ["核验官方准入要求"],
        "decision_language": "建议在完成准入与价格验证后有条件推进。",
    })
    assert research_agent.report_matches_language({"language": "zh", "result": zh}, "zh") is True


def test_language_rewrite_preserves_sources_and_decision(monkeypatch):
    original = _report()
    translated = _report()
    translated.update({
        "headline": "英国市场建议有条件推进",
        "executive_summary": "当前证据支持继续验证英国市场，并重点确认合规、价格和渠道条件后再推进。",
        "research_plan": ["核验英国准入要求"],
        "market_demand": {"assessment": "需求存在", "evidence": ["已有进口证据"]},
        "supply_competition": {"assessment": "竞争集中", "evidence": ["CR3 较高"]},
        "market_access": {"assessment": "合规仍需确认", "evidence": ["存在官方指引"]},
        "pricing_economics": {"assessment": "经济性需要价格验证", "evidence": ["已有成本模型"]},
        "risks": ["合规不确定性"],
        "evidence_gaps": ["实时价格基准"],
        "next_actions": ["核验英国要求"],
        "decision_language": "完成合规验证后再推进。",
        "sources": [{"title": "被模型改写", "url": "https://changed.example", "source_type": "web", "used_for": "x"}],
    })
    monkeypatch.setattr(research_agent, "_post_prompt", lambda *a, **k: (
        {"usage": {"prompt_tokens": 7, "completion_tokens": 11, "total_tokens": 18}},
        json.dumps(translated, ensure_ascii=False),
        "https://model.example/chat/completions",
    ))
    result, usage, endpoint = research_agent._rewrite_report_language(
        {"protocol": "openai_compatible", "base_url": "https://model.example", "model": "m", "provider": "x", "api_key": "k"},
        original,
        "zh",
    )
    assert result["decision"] == original["decision"]
    assert result["sources"] == original["sources"]
    assert "英国" in result["headline"]
    assert usage["total_tokens"] == 18
    assert endpoint.endswith("/chat/completions")
