from __future__ import annotations

from fastapi.testclient import TestClient

from app import main


def test_ebay_test_route_calls_ebay_oauth_not_model_api(monkeypatch):
    called = {"ebay": 0, "ai": 0}

    def fake_ebay():
        called["ebay"] += 1
        return {
            "ok": True,
            "environment": "sandbox",
            "credentials_present": True,
            "token_received": True,
        }

    def fake_ai(*args, **kwargs):
        called["ai"] += 1
        raise AssertionError("model API validator must not be used for eBay OAuth")

    monkeypatch.setattr(main, "test_ebay_connection", fake_ebay)
    monkeypatch.setattr(main, "test_ai_connection", fake_ai)

    client = TestClient(main.app)
    response = client.get("/api/data/ebay/test")

    assert response.status_code == 200
    assert response.json()["token_received"] is True
    assert called == {"ebay": 1, "ai": 0}


def test_ebay_validate_route_uses_unsaved_form_credentials(monkeypatch):
    seen = {}

    def fake_validate(*, environment, client_id, client_secret):
        seen.update({"environment": environment, "client_id": client_id, "client_secret": client_secret})
        return {"ok": True, "environment": environment, "credentials_present": True, "token_received": True}

    def fake_ai(*args, **kwargs):
        raise AssertionError("model API validator must not be used for eBay OAuth")

    monkeypatch.setattr(main, "validate_ebay_connection", fake_validate)
    monkeypatch.setattr(main, "test_ai_connection", fake_ai)

    client = TestClient(main.app)
    response = client.post(
        "/api/local-config/ebay/validate",
        json={
            "environment": "sandbox",
            "client_id": "draft-client",
            "client_secret": "draft-secret",
            "marketplace_id": "EBAY_AU",
        },
    )

    assert response.status_code == 200
    assert response.json()["token_received"] is True
    assert seen == {"environment": "sandbox", "client_id": "draft-client", "client_secret": "draft-secret"}
