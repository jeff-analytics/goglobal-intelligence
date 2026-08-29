from __future__ import annotations

from fastapi.testclient import TestClient

from app import ai_recovery, main, storage


def _temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "global-ai.db")
    storage.init_db()


def test_ai_evidence_can_seed_missing_snapshot_and_fill_trade_history(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project={"id":1,"title":"Camera","origin":"China","hs_code":"852589","attributes":{"origin_partner_code":"156"},"assumptions":{}}
    saved=[{
        "project_id":1,"market":"CA","field_name":"trade.history",
        "value":[{"year":2024,"total_imports":100.0,"imports_from_origin":20.0},{"year":2025,"total_imports":120.0,"imports_from_origin":30.0}],
        "metadata":{"unit":"USD"},"source_name":"Stats Canada","source_url":"https://statcan.gc.ca/x","retrieval_method":"web","confidence":"high"
    }]
    out=ai_recovery._apply_evidence(project,None,saved)
    assert out["market"]=="CA"
    assert out["trade"]["latest_total_imports"]==120.0
    assert out["trade"]["latest_origin_share"]==0.25
    assert out["trade"]["ai_recovered_history"] is True
    assert storage.latest_snapshot("CA","852589",origin_code="156") is not None


def test_explicit_non_usd_trade_evidence_is_not_written_into_usd_fields(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project={"id":1,"title":"Camera","origin":"China","hs_code":"852589","attributes":{"origin_partner_code":"156"},"assumptions":{}}
    saved=[{"project_id":1,"market":"CA","field_name":"trade.latest_total_imports","value":999,"metadata":{"unit":"CAD"},"source_name":"Official","source_url":"https://example.gov","retrieval_method":"web","confidence":"high"}]
    out=ai_recovery._apply_evidence(project,None,saved)
    assert out is not None
    assert out["trade"]["latest_total_imports"] is None


def test_scope_missing_detection_keeps_external_tariff_tax_missing_despite_cost_fallbacks(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project={"id":1,"title":"P","origin":"China","hs_code":"850440","assumptions":{"duty_rate":0.03,"tax_rate":0.19,"market_benchmarks":{"DE":{"median":99}}}}
    snap={"market":"DE","trade":{"latest_total_imports":10,"latest_origin_share":0.2},"suppliers":{"suppliers":[{"partner_name":"China"}]},"tariff":{},"tax":{},"fx":{"rate":1.0}}
    missing=main._missing_recovery_requests(project,"DE",snap,["trade","tariff","tax","fx","marketplace"])
    assert "tariff" in missing
    assert "tax" in missing
    assert "trade" not in missing
    assert "fx" not in missing
    assert "marketplace" not in missing


def test_market_scan_overlay_uses_ai_only_for_missing_fields(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    storage.save_ai_evidence({"project_id":7,"market":"DE","evidence_type":"field","field_name":"trade.latest_total_imports","value":200,"source_name":"Destatis","source_url":"https://example.gov/trade","evidence_level":"B"})
    row=main._overlay_scan_row(7,{"market":"DE","imports":None,"origin_share":0.4,"available":False,"source":"UN Comtrade"})
    assert row["imports"]==200
    assert row["origin_share"]==0.4
    assert row["available"] is True
    assert "imports" in row["ai_recovered_fields"]


def test_project_scope_calls_recovery_only_for_missing_data(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project=storage.create_project({"product_type_id":"generic","title":"P","description":"","origin":"China","hs_code":"850440","attributes":{"origin_partner_code":"156"},"markets":["DE"],"assumptions":{},"status":"active"})
    storage.save_snapshot({"market":"DE","reporter_code":"276","currency":"EUR","hs_code":"850440","origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,"trade":{"latest_total_imports":10,"latest_origin_share":0.2},"suppliers":{"suppliers":[{"partner_name":"China"}]},"tariff":{"rate":5},"tariff_official_lookup":{"local_code":"8504400010"},"tax":{"rate":19},"fx":{"rate":1},"quality":{}})
    monkeypatch.setattr(main,"_research_benchmark",lambda p,m:{"median":99})
    storage.save_ai_evidence({"project_id":project["id"],"market":"DE","evidence_type":"market_access","field_name":"CE","value":{"status":"applicable"},"source_name":"EU","source_url":"https://europa.eu","evidence_level":"B"})
    storage.save_supply_profile(project["id"], {"hs6":"850440","origin":{"code":"156","name":"China"},"years":[2025],"history":[],"metrics":{},"destination_structure":{},"target_corridors":[{"market":"DE","observed":False}],"quality":{},"synced_at":"2026-08-28T00:00:00Z"})
    called=[]
    monkeypatch.setattr(main,"recover_market",lambda *a,**k: called.append(1))
    result=main._recover_project_scope(project,scope="all")
    assert result["summary"]["requested"]==0
    assert called==[]


def test_recover_all_api_returns_aggregated_result(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project=storage.create_project({"product_type_id":"generic","title":"P","description":"","origin":"China","hs_code":"850440","attributes":{"origin_partner_code":"156"},"markets":["DE"],"assumptions":{},"status":"active"})
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True})
    monkeypatch.setattr(main,"_recover_project_scope",lambda p,scope,market_codes=None:{"project_id":p["id"],"scope":scope,"status":"recovered","markets":[],"summary":{"markets":1,"requested":1,"saved":2,"applied":1,"prices":0,"failures":0}})
    client=TestClient(main.app)
    r=client.post(f"/api/projects/{project['id']}/ai/recover-all?scope=trade")
    assert r.status_code==200
    assert r.json()["summary"]["saved"]==2


def test_trade_page_scope_includes_tariff_tax_and_fx_gaps(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project=storage.create_project({"product_type_id":"generic","title":"Keyboard","description":"","origin":"China","hs_code":"847160","attributes":{"origin_partner_code":"156"},"markets":["CA"],"assumptions":{},"status":"active"})
    storage.save_snapshot({"market":"CA","reporter_code":"124","currency":"CAD","hs_code":"847160","origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,"trade":{"latest_total_imports":12640000,"latest_origin_share":0.0,"history":[{"year":2025,"total_imports":12640000,"imports_from_origin":0}]},"suppliers":{"suppliers":[{"partner_name":"USA","share":0.904}]},"tariff":{"rate":None},"tax":{},"fx":{},"quality":{}})
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True,"native_web_search":True,"max_model_calls_per_market":4})
    plan=main._ai_recovery_plan(project,scope="trade",market_codes=["CA"])
    assert plan["summary"]["max_model_calls"]==1
    assert plan["status"]=="ready"
    assert set(plan["markets"][0]["missing"])=={"tariff","tax","fx"}


def test_plan_endpoint_is_free_and_never_invokes_recovery(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project=storage.create_project({"product_type_id":"generic","title":"P","description":"","origin":"China","hs_code":"850440","attributes":{"origin_partner_code":"156"},"markets":["DE"],"assumptions":{},"status":"active"})
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True,"native_web_search":True,"max_model_calls_per_market":1})
    monkeypatch.setattr(main,"recover_market",lambda *a,**k: (_ for _ in ()).throw(AssertionError("plan must not call model recovery")))
    client=TestClient(main.app)
    r=client.get(f"/api/projects/{project['id']}/ai/plan?scope=trade&market_codes=DE")
    assert r.status_code==200
    assert r.json()["summary"]["max_model_calls"]==1


def test_direct_recover_route_has_local_gap_guard(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    project=storage.create_project({"product_type_id":"generic","title":"P","description":"","origin":"China","hs_code":"850440","attributes":{"origin_partner_code":"156"},"markets":["DE"],"assumptions":{},"status":"active"})
    storage.save_snapshot({"market":"DE","reporter_code":"276","currency":"EUR","hs_code":"850440","origin":{"code":"156","name":"China"},"start_year":2024,"end_year":2025,"trade":{"latest_total_imports":10,"latest_origin_share":0.2,"history":[{"year":2025,"total_imports":10,"imports_from_origin":2}]},"suppliers":{"suppliers":[{"partner_name":"China"}]},"tariff":{},"tax":{},"fx":{},"quality":{}})
    monkeypatch.setattr(main,"recovery_capabilities",lambda:{"configured":True,"native_web_search":True})
    monkeypatch.setattr(main,"recover_market",lambda *a,**k: (_ for _ in ()).throw(AssertionError("complete trade must not call model")))
    client=TestClient(main.app)
    r=client.post(f"/api/projects/{project['id']}/ai/recover?market=DE&requested=trade")
    assert r.status_code==200
    assert r.json()["status"]=="complete"
    assert r.json()["model_calls"]==0


def test_normal_hs_suggest_never_silently_calls_ai(monkeypatch):
    monkeypatch.setattr(main,"suggest_hs_candidates",lambda **kwargs:{"query":"x","candidates":[],"count":0,"source":"official"})
    monkeypatch.setattr(main,"recover_hs_candidates",lambda *a,**k: (_ for _ in ()).throw(AssertionError("ordinary HS search must not spend model tokens")))
    out=main.hs_suggest(q="keyboard",project_id=None,limit=8)
    assert out["candidates"]==[]
