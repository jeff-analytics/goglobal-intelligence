from pathlib import Path

from app import main


def test_interactive_market_sync_does_not_call_live_wits(monkeypatch):
    monkeypatch.setattr(main,"fetch_import_history_compact",lambda **kwargs: [])
    monkeypatch.setattr(main,"fetch_tariff_cached",lambda **kwargs: None)
    monkeypatch.setattr(main,"fetch_tariff",lambda **kwargs: (_ for _ in ()).throw(AssertionError("live WITS must not run")))
    monkeypatch.setattr(main,"lookup_official_tariff",lambda **kwargs: None)
    monkeypatch.setattr(main,"fetch_eur_reference_rate",lambda currency: {"rate":1.0,"currency":currency})
    monkeypatch.setattr(main,"fetch_supplier_structure",lambda **kwargs: None)
    monkeypatch.setattr(main,"get_tariff_override",lambda *args,**kwargs: None)
    monkeypatch.setattr(main,"save_snapshot",lambda payload: payload)
    out=main.market_sync(market="CA",hs="852589",origin="",start_year=2024,end_year=2025)
    assert out["market"] == "CA"
    assert out["tariff"] is None


def test_chinese_ui_maps_decision_and_hides_single_market_opportunity_chart():
    root=Path(__file__).resolve().parents[2]
    decision=(root/"frontend/src/pages/Decision.jsx").read_text(encoding="utf-8")
    explorer=(root/"frontend/src/pages/Explorer.jsx").read_text(encoding="utf-8")
    assert "'Market price benchmark is unavailable':'市场价格基准不可用'" in decision
    assert "locale==='zh'?'证据完整度':'Evidence'" in decision
    assert "AI 决策研究" in decision
    assert "Decision Research Agent" in decision
    assert "comparisonReady=visible.length>=3" in explorer
    assert "'市场对比':'Market comparison'" in explorer
    assert "'3年复合增长率':'3Y CAGR'" in explorer


def test_ai_ui_is_one_click_and_still_runs_free_gap_guard_first():
    root=Path(__file__).resolve().parents[2]
    component=(root/"frontend/src/components/AiRecovery.jsx").read_text(encoding="utf-8")
    decision=(root/"frontend/src/pages/Decision.jsx").read_text(encoding="utf-8")
    setup=(root/"frontend/src/pages/Setup.jsx").read_text(encoding="utf-8")
    assert "/ai/plan?" in component
    assert "/ai/recover-all?" in component
    assert "setArmedPlan" not in component
    assert "确认补全" not in component
    assert "aiArmed" not in decision
    assert "确认生成" not in decision
    assert "aiHsArmed" not in setup
    assert "确认 AI" not in setup


def test_ai_validation_ui_explicitly_says_no_generation():
    root=Path(__file__).resolve().parents[2]
    sources=(root/"frontend/src/pages/DataSources.jsx").read_text(encoding="utf-8")
    assert "未生成内容" in sources
    assert "未发送生成请求" in sources


def test_normal_run_analysis_never_calls_ai_without_explicit_flag(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "run.db")
    storage.init_db()
    project=storage.create_project({"product_type_id":"generic","title":"Keyboard","description":"","origin":"China","hs_code":"847160","attributes":{},"markets":["CA"],"assumptions":{},"status":"draft"})
    monkeypatch.setattr(main,"resolve_partner",lambda text:{"code":"156","name":"China","iso2":"CN","iso3":"CHN"})
    monkeypatch.setattr(main,"market_sync",lambda **kwargs:{"market":"CA","trade":{"latest_total_imports":1},"tariff":{"rate":None},"fx":{"rate":1},"suppliers":{}})
    monkeypatch.setattr(main,"recover_market",lambda *a,**k: (_ for _ in ()).throw(AssertionError("normal analysis must not call AI")))
    client=TestClient(main.app)
    r=client.post(f"/api/projects/{project['id']}/run-analysis")
    assert r.status_code==200
    assert r.json()["ai_recovery"]==[]


def test_global_plan_marks_vat_missing_when_only_official_source_name_exists(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "vat.db")
    storage.init_db()
    project=storage.create_project({"product_type_id":"generic","title":"Keyboard","description":"","origin":"China","hs_code":"847160","attributes":{"origin_partner_code":"156"},"markets":["UK"],"assumptions":{"tax_rate":0.2},"status":"active"})
    storage.save_snapshot({"market":"UK","reporter_code":"826","currency":"GBP","hs_code":"847160","origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,"trade":{"latest_total_imports":10,"latest_origin_share":0.1},"suppliers":{"suppliers":[{"partner_name":"China"}]},"tariff":{"rate":0},"tax":{},"fx":{"rate":0.78},"quality":{}})
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True,"native_web_search":True,"max_model_calls_per_market":1})
    plan=main._ai_recovery_plan(project,scope="all",market_codes=["UK"])
    assert "tax" in plan["markets"][0]["missing"]
    assert plan["summary"]["max_model_calls"]==1


def test_full_ai_recover_route_with_deepseek_official_response_contract(tmp_path, monkeypatch):
    """One UI recovery request can go from missing fields to persisted usable data.

    The mock mirrors DeepSeek's documented Responses shape: output contains a
    web_search_call followed by a message/content/output_text item.
    """
    import json
    from fastapi.testclient import TestClient
    from app import ai_recovery, storage

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "e2e-ai.db")
    storage.init_db()
    project=storage.create_project({
        "product_type_id":"generic","title":"Home Fragrance","description":"reed diffuser",
        "origin":"China","hs_code":"330749","attributes":{"origin_partner_code":"156"},
        "markets":["UK"],"assumptions":{},"status":"active"
    })
    storage.save_snapshot({
        "market":"UK","reporter_code":"826","currency":"GBP","hs_code":"330749",
        "origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,
        "trade":{},"suppliers":{},"tariff":{},"tariff_official_lookup":{},"tax":{},"fx":{},"quality":{}
    })
    monkeypatch.setattr(ai_recovery, "_config", lambda: {
        "provider":"DeepSeek","protocol":"openai_responses","base_url":"https://api.deepseek.com",
        "api_key":"k","model":"deepseek-v4-flash"
    })
    monkeypatch.setattr(ai_recovery, "refresh_settings", lambda: None)
    monkeypatch.setattr(ai_recovery, "_registered_sources", lambda market: [])

    structured={
        "evidence":[
            {"field":"trade.latest_total_imports","value":"100000000","unit":"USD","source_name":"UK Trade Info","source_url":"https://www.uktradeinfo.com/","source_type":"official","observed_at":"2025","confidence":"high","excerpt":"imports"},
            {"field":"trade.latest_imports_from_origin","value":"20000000","unit":"USD","source_name":"UK Trade Info","source_url":"https://www.uktradeinfo.com/","source_type":"official","observed_at":"2025","confidence":"high","excerpt":"China imports"},
            {"field":"trade.latest_origin_share","value":"0.2","unit":"ratio","source_name":"UK Trade Info","source_url":"https://www.uktradeinfo.com/","source_type":"official","observed_at":"2025","confidence":"high","excerpt":"share"},
            {"field":"supply.top_suppliers","value":json.dumps([{"partner_name":"China","share":0.2,"rank":1},{"partner_name":"France","share":0.15,"rank":2}]),"unit":"list","source_name":"UK Trade Info","source_url":"https://www.uktradeinfo.com/","source_type":"official","observed_at":"2025","confidence":"high","excerpt":"origins"},
            {"field":"tariff.rate","value":"6.5","unit":"percent","source_name":"UK Trade Tariff","source_url":"https://www.trade-tariff.service.gov.uk/","source_type":"official","observed_at":"2026","confidence":"high","excerpt":"duty"},
            {"field":"tariff.local_code","value":"3307490000","unit":"code","source_name":"UK Trade Tariff","source_url":"https://www.trade-tariff.service.gov.uk/","source_type":"official","observed_at":"2026","confidence":"high","excerpt":"commodity code"},
            {"field":"tax.rate","value":"20","unit":"percent","source_name":"HMRC","source_url":"https://www.gov.uk/vat-rates","source_type":"official","observed_at":"2026","confidence":"high","excerpt":"standard VAT"},
            {"field":"fx.rate","value":"0.78","unit":"GBP per USD","source_name":"Bank of England","source_url":"https://www.bankofengland.co.uk/boeapps/database/Rates.asp","source_type":"official","observed_at":"2026-08-28","confidence":"medium","excerpt":"rate"},
        ],
        "market_access":[{"requirement":"UK product safety","status":"check product-specific requirements","source_name":"GOV.UK","source_url":"https://www.gov.uk/product-safety-advice-for-businesses","confidence":"medium","excerpt":"product safety"}],
        "marketplace_observations":[{"title":"Home Fragrance Reed Diffuser","brand":"Example","price":29.99,"currency":"GBP","source_url":"https://shop.example.com/home-fragrance","source_name":"Example retailer","observed_at":"2026-08-28"}],
        "gaps":[]
    }
    calls=[]
    class R:
        status_code=200
        def __init__(self,payload): self._payload=payload
        def raise_for_status(self): return None
        def json(self): return self._payload
    def fake_post(url, **kwargs):
        body=kwargs.get("json") or {}; calls.append(body)
        if body.get("tools"):
            return R({"id":"search","object":"response","status":"completed","model":"deepseek-v4-flash","output":[
                {"type":"web_search_call","status":"completed","action":{"type":"search","query":"UK home fragrance tariff VAT trade"}},
                {"type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":"Research complete with official sources: https://www.gov.uk/vat-rates https://www.trade-tariff.service.gov.uk/ https://www.uktradeinfo.com/"}]}
            ],"usage":{"input_tokens":100,"output_tokens":100,"total_tokens":200}})
        return R({"id":"structure","object":"response","status":"completed","model":"deepseek-v4-flash","output":[
            {"type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":json.dumps(structured)}]}
        ],"usage":{"input_tokens":120,"output_tokens":180,"total_tokens":300}})
    monkeypatch.setattr(ai_recovery.requests, "post", fake_post)

    client=TestClient(main.app)
    r=client.post(f"/api/projects/{project['id']}/ai/recover-all?scope=all&market_codes=UK")
    assert r.status_code==200, r.text
    body=r.json()
    assert body["status"]=="recovered"
    assert body["summary"]["saved"] >= 9
    assert body["summary"]["applied"] >= 7
    assert body["summary"]["prices"] == 1
    assert body["summary"]["model_calls"] == 2
    latest=storage.latest_snapshot("UK","330749",origin_code="156")
    assert latest["tax"]["rate"]==20.0
    assert latest["tariff"]["rate"]==6.5
    assert latest["tariff_official_lookup"]["local_code"]=="3307490000"
    assert latest["trade"]["latest_total_imports"]==100000000.0
    assert latest["trade"]["latest_origin_share"]==0.2
    assert len(calls)==2
    assert calls[0]["tools"]==[{"type":"web_search"}]
    assert calls[1]["text"]["format"]["type"]=="json_schema"


def test_ai_brief_route_allows_incomplete_evidence_and_returns_suggestions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "brief.db")
    storage.init_db()
    project=storage.create_project({"product_type_id":"generic","title":"P","description":"","origin":"China","hs_code":"330749","attributes":{},"markets":["UK"],"assumptions":{},"status":"active"})
    monkeypatch.setattr(main, "generate_evidence_brief", lambda **kwargs: {
        "provider":"DeepSeek","protocol":"openai_responses","model":"deepseek-v4-flash","language":"zh","usage":{"total_tokens":77},
        "result":{"headline":"证据不足，暂缓","summary":"先补关键数据。","strengths":[],"risks":["关税缺失"],"evidence_gaps":["VAT"],"next_actions":["补齐税费"],"decision_language":"补齐证据后再决策。"}
    })
    client=TestClient(main.app)
    r=client.post(f"/api/projects/{project['id']}/ai/brief?market=UK&locale=zh")
    assert r.status_code==200, r.text
    assert r.json()["brief"]["result"]["next_actions"]==["补齐税费"]


def test_tariff_supply_ai_plan_is_not_complete_when_supply_profile_is_absent(tmp_path, monkeypatch):
    """The tariff/supply page must not show green while both supply panels are empty."""
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "supply-plan.db")
    storage.init_db()
    project=storage.create_project({
        "product_type_id":"generic","title":"Batteries","description":"","origin":"China",
        "hs_code":"8507600000","attributes":{"origin_partner_code":"156"},"markets":["UK"],
        "assumptions":{},"status":"active"
    })
    storage.save_snapshot({
        "market":"UK","reporter_code":"826","currency":"GBP","hs_code":"850760",
        "origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,
        "trade":{"latest_total_imports":100,"latest_origin_share":0.5},
        "suppliers":{"suppliers":[{"partner_name":"China","share":0.5}]},
        "tariff":{"rate":2.0,"nomenclature":"8507600000"},"tax":{"rate":20.0},"fx":{"rate":0.78},"quality":{}
    })
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True,"native_web_search":True,"max_model_calls_per_market":1})
    plan=main._ai_recovery_plan(project,scope="tariff",market_codes=["UK"])
    assert plan["status"] == "unsupported"
    assert plan["summary"]["max_model_calls"] == 0
    assert plan["markets"][0]["missing"] == ["origin_supply"]
    assert plan["markets"][0]["unsupported"] == ["origin_supply"]

    storage.save_supply_profile(project["id"], {
        "hs6":"850760","origin":{"code":"156","name":"China"},"years":[2024,2025],
        "history":[],"metrics":{},"destination_structure":{},
        "target_corridors":[{"market":"UK","observed":False}],"quality":{},"synced_at":"2026-08-28T00:00:00Z"
    })
    complete=main._ai_recovery_plan(project,scope="tariff",market_codes=["UK"])
    assert complete["status"] == "complete"


def test_backend_launch_scripts_do_not_use_uvicorn_reload():
    """SQLite writes must never restart the local API process."""
    root=Path(__file__).resolve().parents[2]
    win=(root/"scripts/windows/start_backend.bat").read_text(encoding="utf-8")
    mac=(root/"run_mac.command").read_text(encoding="utf-8")
    assert "--reload" not in win
    assert "--reload" not in mac
    assert "uvicorn app.main:app --host 127.0.0.1 --port 8000" in win
    assert "uvicorn app.main:app --host 127.0.0.1 --port 8000" in mac
    assert "goto :api_loop" in win
    # macOS startup deliberately runs one supervised backend process so an
    # import/startup failure is surfaced immediately instead of being hidden
    # by an infinite restart loop.
    assert "goglobal_backend.log" in mac
    assert 'kill -0 \"$API_PID\"' in mac
    assert "tail -n 120" in mac


def test_saving_assumptions_keeps_project_routes_available(tmp_path, monkeypatch):
    """Regression for the UI 'Failed to fetch' seen immediately after Save assumptions."""
    from fastapi.testclient import TestClient
    from app import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "assumptions.db")
    storage.init_db()
    project=storage.create_project({
        "product_type_id":"generic","title":"Batteries","description":"","origin":"China",
        "hs_code":"850760","attributes":{"origin_partner_code":"156"},"markets":["UK"],
        "assumptions":{},"status":"active"
    })
    client=TestClient(main.app)
    payload={"assumptions":{"factory_cost":12.5,"packaging_cost":1.2,"freight_cost":2.0,"platform_fee_rate":0.12,"target_margin_rate":0.2}}
    saved=client.patch(f"/api/projects/{project['id']}",json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["assumptions"]["factory_cost"] == 12.5
    for path in [
        "/api/projects",
        f"/api/projects/{project['id']}/dashboard",
        f"/api/projects/{project['id']}/decision-cases",
        f"/api/projects/{project['id']}/explorer",
    ]:
        response=client.get(path)
        assert response.status_code == 200, (path,response.text)


def test_frontend_retries_transient_gets_and_localizes_network_failure():
    root=Path(__file__).resolve().parents[2]
    api_js=(root/"frontend/src/api.js").read_text(encoding="utf-8")
    utils=(root/"frontend/src/utils.js").read_text(encoding="utf-8")
    assert "const attempts = method === 'GET' ? 8 : 1" in api_js
    assert "Backend connection unavailable" in api_js
    assert "后端连接暂时不可用" in utils


def test_final_ui_interaction_fixes_are_present():
    root=Path(__file__).resolve().parents[2]
    setup=(root/"frontend/src/pages/Setup.jsx").read_text(encoding="utf-8")
    cost=(root/"frontend/src/pages/CostMargin.jsx").read_text(encoding="utf-8")
    supply=(root/"frontend/src/pages/TariffSupply.jsx").read_text(encoding="utf-8")
    styles=(root/"frontend/src/styles.css").read_text(encoding="utf-8")
    assert "/api/hs/search?q=" in setup
    assert "hs-autocomplete-menu" in setup
    assert "setOpen(false);setItems([]);onChange(x.name)" in setup
    assert "bordermargin:pricing:" in cost
    assert "writePricingCache" in cost
    assert "多年数据覆盖率" not in supply
    assert ".ai-filled" in styles


def test_hs_autocomplete_menu_is_fully_opaque():
    root=Path(__file__).resolve().parents[2]
    styles=(root/"frontend/src/styles.css").read_text(encoding="utf-8")
    assert ".hs-autocomplete-menu{position:absolute;z-index:140;isolation:isolate" in styles
    assert "background:#fff!important" in styles
    assert ".hs-autocomplete-menu button:hover,.hs-autocomplete-menu button:focus-visible{background:#f2f6fb!important}" in styles
    assert "background:var(--panel)" not in styles
    assert "background:var(--panel-2)" not in styles


def test_save_assumptions_does_not_force_immediate_dashboard_reload():
    root=Path(__file__).resolve().parents[2]
    cost=(root/"frontend/src/pages/CostMargin.jsx").read_text(encoding="utf-8")
    app=(root/"frontend/src/App.jsx").read_text(encoding="utf-8")
    save_block=cost[cost.index("async function save()"):cost.index("async function calculate()")]
    assert "onProjectUpdated?.(updated)" in save_block
    assert "onReload(project.id)" not in save_block
    assert "function onProjectUpdated(updated)" in app
    assert "setDashboard(prev=>prev&&prev.project?.id===updated.id?{...prev,project:updated}:prev)" in app


def test_launcher_prevents_stale_backend_and_ui_port_reuse():
    root=Path(__file__).resolve().parents[2]
    run=(root/"run_win.bat").read_text(encoding="utf-8")
    frontend=(root/"scripts/windows/start_frontend.bat").read_text(encoding="utf-8")
    preflight=(root/"scripts/windows/prepare_ports.ps1").read_text(encoding="utf-8")
    mac=(root/"run_mac.command").read_text(encoding="utf-8")
    assert "scripts\\windows\\prepare_ports.ps1" in run
    assert "v541-20260901-algorithms-ai-config-r3" in run
    assert run.index('start "GoGlobal Intelligence API"') < run.index('start "GoGlobal Intelligence UI"')
    assert "--port 5173 --strictPort" in frontend
    assert "Get-NetTCPConnection" in preflight
    assert "Stop-Process" in preflight
    assert "another application" in preflight
    assert "v541-20260901-algorithms-ai-config-r3" in mac
    assert "--port 5173 --strictPort" in mac


def test_health_exposes_exact_release_build_id():
    from fastapi.testclient import TestClient
    client=TestClient(main.app)
    body=client.get("/api/health").json()
    assert body["version"] == "5.4.1"
    assert body["build"] == "v541-20260901-algorithms-ai-config-r3"


def test_setup_origin_dropdown_uses_portal_overlay_and_hs_selection_clears_candidates():
    root=Path(__file__).resolve().parents[2]
    setup=(root/"frontend/src/pages/Setup.jsx").read_text(encoding="utf-8")
    styles=(root/"frontend/src/styles.css").read_text(encoding="utf-8")
    assert "createPortal" in setup
    assert "origin-menu-portal" in setup
    assert "hs-autocomplete-portal" in setup
    assert ".origin-menu-portal" in styles
    assert "position:fixed!important" in styles
    assert "setOpen(false);setItems([]);onChange(x.name)" in setup
    assert "onChange={v=>{setHsCandidates([]);setHsCandidatesOpen(false);setForm({...form,hs_code:v})}}" in setup
    assert "function useHs(item){" in setup
    assert "selected_code:item.code" in setup
    assert "setForm({...form,hs_code:item.code}); setHsCandidates([]); setHsCandidatesOpen(false); setHsRankMeta(null)" in setup


def test_v538_r2_layout_and_numeric_display_guards():
    root=Path(__file__).resolve().parents[2]
    styles=(root/"frontend/src/styles.css").read_text(encoding="utf-8")
    cost=(root/"frontend/src/pages/CostMargin.jsx").read_text(encoding="utf-8")
    utils=(root/"frontend/src/utils.js").read_text(encoding="utf-8")
    assert "editableNumber(a.platform_fee_rate,100)" in cost
    assert "Number((percent?parsed/100:parsed).toFixed(12))" in cost
    assert "export function editableNumber" in utils
    assert ".tariff-scan-card .tariff-scan-command{grid-template-columns:repeat(2,minmax(0,1fr))" in styles
    assert ".supplier-list>div{width:100%;min-width:0;grid-template-columns:28px minmax(0,1fr)" in styles
