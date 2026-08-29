from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app import storage
from app.providers.csv_provider import CsvProvider
from app.source_runtime import cached_call


def _temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "runtime.db")
    storage.init_db()


def test_persistent_source_cache_reuses_and_falls_back_to_stale(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    calls = {"count": 0}

    def live_fetch():
        calls["count"] += 1
        return {"value": 42}

    first, first_meta = cached_call(
        provider="UN Comtrade",
        key="same-query",
        fetcher=live_fetch,
        ttl_seconds=3600,
        stale_ttl_seconds=86400,
    )
    second, second_meta = cached_call(
        provider="UN Comtrade",
        key="same-query",
        fetcher=live_fetch,
        ttl_seconds=3600,
        stale_ttl_seconds=86400,
    )

    assert first == second == {"value": 42}
    assert first_meta["mode"] == "live"
    assert second_meta["mode"] == "cache"
    assert calls["count"] == 1

    def offline_fetch():
        raise RuntimeError("temporary outage")

    stale, stale_meta = cached_call(
        provider="UN Comtrade",
        key="same-query",
        fetcher=offline_fetch,
        ttl_seconds=3600,
        stale_ttl_seconds=86400,
        force_refresh=True,
    )
    assert stale == {"value": 42}
    assert stale_meta["mode"] == "stale-cache"
    assert "temporary outage" in stale_meta["network_error"]


def test_cache_status_does_not_fake_a_live_success_timestamp(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch)
    storage.source_health_record("ECB", ok=True, status="cached", latency_ms=0)
    row = next(x for x in storage.source_runtime_summary() if x["provider"] == "ECB")
    assert row["status"] == "cached"
    assert row["last_success_at"] is None


def test_marketplace_csv_accepts_common_export_aliases_and_currency():
    payload = (
        "Listing ID,Product Title,Listing Price,Shipping,Seller,Snapshot Date\n"
        'A-1,"Robot Vacuum Pro","$1,299.00",19.95,Store A,2026-08-20\n'
    ).encode("utf-8")
    rows = CsvProvider().parse_bytes(payload, filename="observations.csv")
    assert rows[0]["item_id"] == "A-1"
    assert rows[0]["title"] == "Robot Vacuum Pro"
    assert rows[0]["price"] == 1299.0
    assert rows[0]["currency"] == "USD"
    assert rows[0]["shipping_cost"] == 19.95
    assert rows[0]["seller"] == "Store A"


def test_marketplace_xlsx_is_supported():
    wb = Workbook()
    ws = wb.active
    ws.append(["item_id", "title", "price", "currency", "seller", "observed_at"])
    ws.append(["B-2", "Robot Vacuum X", 499.9, "EUR", "Store B", "2026-08-21"])
    stream = BytesIO()
    wb.save(stream)
    wb.close()

    rows = CsvProvider().parse_bytes(stream.getvalue(), filename="observations.xlsx")
    assert len(rows) == 1
    assert rows[0]["item_id"] == "B-2"
    assert rows[0]["price"] == 499.9
    assert rows[0]["currency"] == "EUR"
    assert rows[0]["seller"] == "Store B"


def test_wits_timeout_uses_one_bounded_attempt_and_opens_breaker(tmp_path, monkeypatch):
    import requests
    from app.sources import wits
    _temp_db(tmp_path, monkeypatch)
    calls={"count":0}
    def timeout_get(*args, **kwargs):
        calls["count"] += 1
        raise requests.Timeout("slow")
    monkeypatch.setattr(wits.requests,"get",timeout_get)
    monkeypatch.setattr(wits,"_BREAKER_FAILURES",0)
    monkeypatch.setattr(wits,"_BREAKER_OPEN_UNTIL",0.0)
    try:
        wits._request_tariff(reporter_code="124",partner_code="156",hs_code="852589",year="2025",datatype="reported",force_refresh=True)
        assert False, "expected timeout"
    except RuntimeError as exc:
        assert "timed out after 1 attempt" in str(exc)
    assert calls["count"] == 1

    # A second live query is rejected immediately while the circuit is open.
    try:
        wits._request_tariff(reporter_code="276",partner_code="156",hs_code="852589",year="2025",datatype="reported",force_refresh=True)
        assert False, "expected circuit breaker"
    except RuntimeError as exc:
        assert "WITS_NETWORK_PAUSED" in str(exc)
    assert calls["count"] == 1


def test_wits_cached_tariff_never_calls_network(tmp_path, monkeypatch):
    from app.sources import wits
    _temp_db(tmp_path, monkeypatch)
    _, _, key = wits._request_identity(reporter_code="124",partner_code="156",hs_code="852589",year="2025",datatype="reported")
    storage.source_cache_put("UNCTAD TRAINS / WITS",key,{"Series":{"Obs":{"@YEAR":"2025","@OBS_VALUE":"4.25"}}})
    monkeypatch.setattr(wits.requests,"get",lambda *a,**k: (_ for _ in ()).throw(AssertionError("network must not be called")))
    out=wits.fetch_tariff_cached(reporter_code="124",partner_code="156",hs_code="852589",year="2025")
    assert out is not None
    assert out["rate"] == 4.25
    assert out["source_type"] == "cached-historical-reference"
