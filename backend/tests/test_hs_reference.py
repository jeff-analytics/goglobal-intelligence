from app.sources import hs_reference


def test_hs_suggestion_uses_reference_not_product_template(monkeypatch):
    monkeypatch.setattr(hs_reference,"get_hs_reference",lambda force=False:[
        {"code":"111111","description":"Portable electric vacuum cleaners","level":6,"leaf":True,"source":"x"},
        {"code":"222222","description":"Fresh apples","level":6,"leaf":True,"source":"x"},
    ])
    r=hs_reference.suggest_hs_candidates(query="electric vacuum cleaner",limit=2)
    assert r["candidates"][0]["code"]=="111111"


def test_hs_code_prefix_autocomplete(monkeypatch):
    monkeypatch.setattr(hs_reference,"get_hs_reference",lambda force=False:[
        {"code":"603450","description":"Example A","level":6,"leaf":True,"source":"x"},
        {"code":"603451","description":"Example B","level":6,"leaf":True,"source":"x"},
        {"code":"603499","description":"Example C","level":6,"leaf":True,"source":"x"},
        {"code":"870899","description":"Vehicle parts","level":6,"leaf":True,"source":"x"},
    ])
    r=hs_reference.search_hs_reference(query="60345",limit=12)
    assert [x["code"] for x in r["items"]] == ["603450","603451"]
    assert r["mode"] == "code_prefix"
