from __future__ import annotations

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.sources import ebay


class _FakeTokenResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"access_token": "test-token", "expires_in": 7200}


def _isolate_env(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend.env"
    example = tmp_path / ".env.example"
    example.write_text("EBAY_ENV=sandbox\nEBAY_CLIENT_ID=\nEBAY_CLIENT_SECRET=\n", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT_ENV", root_env)
    monkeypatch.setattr(config, "BACKEND_ENV", backend_env)
    monkeypatch.setattr(config, "ENV_EXAMPLE", example)
    for key in ("EBAY_ENV", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_MARKETPLACE_ID"):
        monkeypatch.delenv(key, raising=False)
    config.refresh_settings()
    ebay.reset_token_cache()
    return root_env


def test_ebay_reads_env_changes_without_backend_restart(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    assert config.settings.ebay_client_id == ""

    # Simulates a user editing .env after the backend process has already started.
    root_env.write_text(
        "EBAY_ENV=sandbox\nEBAY_CLIENT_ID=my-client-id\nEBAY_CLIENT_SECRET=my-client-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ebay.requests, "post", lambda *args, **kwargs: _FakeTokenResponse())

    assert ebay.get_application_token() == "test-token"
    assert config.settings.ebay_client_id == "my-client-id"
    assert config.settings.ebay_client_secret == "my-client-secret"


def test_local_ebay_config_endpoint_saves_and_hot_reloads(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/local-config/ebay",
        json={
            "environment": "sandbox",
            "client_id": "saved-client-id",
            "client_secret": "saved-client-secret",
            "marketplace_id": "EBAY_AU",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["restart_required"] is False
    assert "saved-client-secret" in root_env.read_text(encoding="utf-8")

    status = client.get("/api/data/status")
    assert status.status_code == 200
    ebay_status = status.json()["ebay"]
    assert ebay_status["configured"] is True
    assert ebay_status["hot_reload"] is True
    assert ebay_status["client_id_masked"]
