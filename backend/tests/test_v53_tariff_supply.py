from app import tariff_supply
from app.sources import comtrade


def test_export_request_uses_export_flow(monkeypatch):
    seen = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"data": []}
    def fake_get(url, params=None, timeout=None):
        seen.update(params or {})
        return R()
    monkeypatch.setattr(comtrade.requests, "get", fake_get)
    monkeypatch.setattr(comtrade, "cached_call", lambda **kwargs: (kwargs["fetcher"](), {"cache_hit":False}))
    comtrade.fetch_exports(reporter_code="156", hs_code="850440", period="2024", partner_code="276")
    assert seen["flowCode"] == "X"
    assert seen["reportercode"] == "156"
    assert seen["partnerCode"] == "276"


def test_supply_profile_keeps_demand_and_supply_observable(monkeypatch):
    monkeypatch.setattr(tariff_supply, "fetch_export_history_compact", lambda **kwargs: [
        {"year": 2022, "trade_value": 100.0},
        {"year": 2023, "trade_value": 120.0},
        {"year": 2024, "trade_value": 150.0},
    ])
    monkeypatch.setattr(tariff_supply, "fetch_export_destination_structure", lambda **kwargs: {
        "year": 2024, "total_partner_exports": 150.0, "destination_count": 2,
        "cr3": 1.0, "cr5": 1.0, "hhi": 0.52,
        "destinations": [
            {"partner_code": "276", "partner_name": "Germany", "trade_value": 90.0, "share": .6, "rank": 1},
            {"partner_code": "842", "partner_name": "USA", "trade_value": 60.0, "share": .4, "rank": 2},
        ],
    })
    out = tariff_supply.build_supply_profile(origin={"code":"156","name":"China"}, hs6="850440", years=[2022,2023,2024], target_markets=["DE","US","UK"])
    assert out["metrics"]["latest_value"] == 150.0
    assert out["target_corridors"][0]["trade_value"] == 90.0
    assert out["target_corridors"][1]["trade_value"] == 60.0
    assert out["target_corridors"][2]["trade_value"] is None
    assert out["quality"]["coverage_ratio"] == 1.0


def test_tariff_row_preserves_missing(monkeypatch):
    monkeypatch.setattr(tariff_supply, "fetch_tariff", lambda **kwargs: {"rate":None,"year":None,"source":"UNCTAD TRAINS / WITS"})
    row = tariff_supply._tariff_row(market="DE", hs6="850440", origin_code="156", year=2024)
    assert row["status"] == "missing"
    assert row["rate"] is None
    assert row["source"] == "UNCTAD TRAINS / WITS"
