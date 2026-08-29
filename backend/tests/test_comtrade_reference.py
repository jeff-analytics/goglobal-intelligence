from app.sources import comtrade_reference as ref


def test_partner_search_uses_reference_rows_not_built_in_country_map(monkeypatch):
    monkeypatch.setitem(ref._CACHE, "rows", [
        {"code": "101", "name": "Exampleland", "iso2": "EX", "iso3": "EXA"},
        {"code": "202", "name": "Sample Republic", "iso2": "SR", "iso3": "SMP"},
    ])
    monkeypatch.setitem(ref._CACHE, "loaded_at", __import__('time').time())
    result = ref.search_partners("EXA")
    assert result[0]["code"] == "101"
    assert ref.resolve_partner("Exampleland")["iso3"] == "EXA"
