from __future__ import annotations

from fastapi.testclient import TestClient

from app import config, main


def _isolate_env(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend.env"
    example = tmp_path / ".env.example"
    example.write_text("COMTRADE_SUBSCRIPTION_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT_ENV", root_env)
    monkeypatch.setattr(config, "BACKEND_ENV", backend_env)
    monkeypatch.setattr(config, "ENV_EXAMPLE", example)
    monkeypatch.delenv("COMTRADE_SUBSCRIPTION_KEY", raising=False)
    config.refresh_settings()
    return root_env


def test_comtrade_validate_uses_unsaved_form_key(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    seen = {}

    def fake_validate(api_key: str):
        seen["api_key"] = api_key
        return {"ok": True, "provider": "UN Comtrade", "mode": "free-key", "records": 3, "year": 2025}

    monkeypatch.setattr(main, "validate_subscription_key", fake_validate)
    client = TestClient(main.app)
    response = client.post("/api/local-config/comtrade/validate", json={"api_key": "draft-comtrade-key"})

    assert response.status_code == 200
    assert response.json()["records"] == 3
    assert seen["api_key"] == "draft-comtrade-key"
    assert not root_env.exists() or "draft-comtrade-key" not in root_env.read_text(encoding="utf-8")


def test_comtrade_save_can_follow_successful_validation(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)

    monkeypatch.setattr(
        main,
        "validate_subscription_key",
        lambda api_key: {"ok": True, "provider": "UN Comtrade", "mode": "free-key", "records": 1, "year": 2025},
    )
    client = TestClient(main.app)

    validate = client.post("/api/local-config/comtrade/validate", json={"api_key": "valid-key"})
    assert validate.status_code == 200
    assert not root_env.exists() or "valid-key" not in root_env.read_text(encoding="utf-8")

    save = client.post("/api/local-config/comtrade", json={"api_key": "valid-key"})
    assert save.status_code == 200
    assert "valid-key" in root_env.read_text(encoding="utf-8")


def test_frontend_comtrade_test_only_posts_current_form_value():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "DataSources.jsx").read_text(encoding="utf-8")
    assert "'/api/local-config/comtrade/validate'" in source
    assert "body:JSON.stringify(forms.comtrade)" in source
