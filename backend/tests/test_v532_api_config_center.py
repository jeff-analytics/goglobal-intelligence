from __future__ import annotations

from fastapi.testclient import TestClient

from app import ai_layer, config
from app.main import app


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _isolate_env(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend.env"
    example = tmp_path / ".env.example"
    example.write_text(
        "COMTRADE_SUBSCRIPTION_KEY=\nEBAY_ENV=sandbox\nEBAY_CLIENT_ID=\nEBAY_CLIENT_SECRET=\nAI_PROVIDER=\nAI_PROTOCOL=\nAI_BASE_URL=\nAI_API_KEY=\nAI_MODEL=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ROOT_ENV", root_env)
    monkeypatch.setattr(config, "BACKEND_ENV", backend_env)
    monkeypatch.setattr(config, "ENV_EXAMPLE", example)
    for key in (
        "COMTRADE_SUBSCRIPTION_KEY", "EBAY_ENV", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
        "EBAY_MARKETPLACE_ID", "AI_PROVIDER", "AI_PROTOCOL", "AI_BASE_URL", "AI_API_KEY", "AI_MODEL",
        "OPENAI_API_KEY", "OPENAI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    config.refresh_settings()
    return root_env


def test_model_api_starts_fully_blank(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.get("/api/local-config/apis")
    assert response.status_code == 200
    payload = response.json()["ai"]
    assert payload["configured"] is False
    assert payload["provider"] == ""
    assert payload["protocol"] == ""
    assert payload["base_url"] == ""
    assert payload["model"] == ""


def test_model_api_saves_user_selected_provider_without_exposing_secret(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/local-config/ai",
        json={
            "provider": "My Provider",
            "protocol": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "third-party-secret",
            "model": "custom-model-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "My Provider"
    assert payload["model"] == "custom-model-1"
    assert "third-party-secret" not in str(payload)
    env_text = root_env.read_text(encoding="utf-8")
    assert "AI_PROTOCOL=openai_compatible" in env_text or "AI_PROTOCOL='openai_compatible'" in env_text
    assert "AI_MODEL=custom-model-1" in env_text or "AI_MODEL='custom-model-1'" in env_text


def test_model_api_does_not_require_api_key_for_local_compatible_service(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/local-config/ai",
        json={"provider": "Local", "protocol": "openai_compatible", "base_url": "http://127.0.0.1:11434/v1", "api_key": "", "model": "local-model"},
    )
    assert response.status_code == 200
    assert response.json()["secret_stored"] is False


def test_model_api_requires_protocol_base_url_and_model(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post("/api/local-config/ai", json={"provider": "X", "protocol": "", "base_url": "", "model": ""})
    assert response.status_code == 422


def test_openai_compatible_model_list_uses_user_base_url_and_unsaved_key(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return _FakeResponse({"data": [{"id": "alpha"}, {"id": "beta"}]})

    monkeypatch.setattr(ai_layer.requests, "get", fake_get)
    client = TestClient(app)
    response = client.post(
        "/api/local-config/ai/models",
        json={"provider": "ThirdParty", "protocol": "openai_compatible", "base_url": "https://third.example/v1", "api_key": "unsaved-key", "model": ""},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "provider-models-api"
    assert payload["available"] == ["alpha", "beta"]
    assert seen["url"] == "https://third.example/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer unsaved-key"
    assert not root_env.exists() or "unsaved-key" not in root_env.read_text(encoding="utf-8")


def test_model_api_validation_is_token_free_for_openai_compatible(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    seen = {}
    def fake_get(url, **kwargs):
        seen["url"] = url; seen["headers"] = kwargs.get("headers")
        return _FakeResponse({"data":[{"id":"m"}]})
    def no_post(*args, **kwargs):
        raise AssertionError("validation must not send a paid generation request")
    monkeypatch.setattr(ai_layer.requests, "get", fake_get)
    monkeypatch.setattr(ai_layer.requests, "post", no_post)
    client = TestClient(app)
    response = client.post(
        "/api/local-config/ai/validate",
        json={"provider":"ThirdParty","protocol":"openai_compatible","base_url":"https://third.example/v1","api_key":"k","model":"m"},
    )
    assert response.status_code == 200
    payload=response.json()
    assert payload["verified"] is True
    assert payload["model_generation_used"] is False
    assert payload["usage"]["total_tokens"] == 0
    assert seen["url"] == "https://third.example/v1/models"


def test_deepseek_validation_normalizes_v1_and_uses_models_only(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    seen={}
    def fake_get(url, **kwargs):
        seen["url"]=url
        return _FakeResponse({"data":[{"id":"deepseek-v4-flash"}]})
    monkeypatch.setattr(ai_layer.requests,"get",fake_get)
    monkeypatch.setattr(ai_layer.requests,"post",lambda *a,**k: (_ for _ in ()).throw(AssertionError("no generation")))
    client=TestClient(app)
    response=client.post("/api/local-config/ai/validate",json={"provider":"DeepSeek","protocol":"openai_compatible","base_url":"https://api.deepseek.com/v1","api_key":"k","model":"deepseek-v4-flash"})
    assert response.status_code==200
    assert seen["url"]=="https://api.deepseek.com/models"


def test_model_api_validation_without_models_endpoint_never_generates(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    def broken_get(*args, **kwargs):
        raise RuntimeError("models endpoint unavailable")
    monkeypatch.setattr(ai_layer.requests,"get",broken_get)
    monkeypatch.setattr(ai_layer.requests,"post",lambda *a,**k: (_ for _ in ()).throw(AssertionError("no generation")))
    client=TestClient(app)
    response=client.post("/api/local-config/ai/validate",json={"provider":"Custom","protocol":"openai_compatible","base_url":"https://custom.example/v1","api_key":"k","model":"m"})
    assert response.status_code==200
    assert response.json()["verified"] is False
    assert response.json()["model_generation_used"] is False


def test_anthropic_validation_uses_token_free_models_endpoint(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    seen={}
    def fake_get(url, **kwargs):
        seen["url"]=url;seen["headers"]=kwargs.get("headers")
        return _FakeResponse({"data":[{"id":"model-a"}]})
    monkeypatch.setattr(ai_layer.requests,"get",fake_get)
    monkeypatch.setattr(ai_layer.requests,"post",lambda *a,**k: (_ for _ in ()).throw(AssertionError("no generation")))
    client=TestClient(app)
    response=client.post("/api/local-config/ai/validate",json={"provider":"Anthropic-like","protocol":"anthropic","base_url":"https://anthropic.example/v1","api_key":"a-key","model":"model-a"})
    assert response.status_code==200
    assert seen["url"]=="https://anthropic.example/v1/models"
    assert seen["headers"]["x-api-key"]=="a-key"


def test_gemini_validation_uses_token_free_models_endpoint(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    seen={}
    def fake_get(url, **kwargs):
        seen["url"]=url;seen["params"]=kwargs.get("params")
        return _FakeResponse({"models":[{"name":"models/model-g","supportedGenerationMethods":["generateContent"]}]})
    monkeypatch.setattr(ai_layer.requests,"get",fake_get)
    monkeypatch.setattr(ai_layer.requests,"post",lambda *a,**k: (_ for _ in ()).throw(AssertionError("no generation")))
    client=TestClient(app)
    response=client.post("/api/local-config/ai/validate",json={"provider":"Gemini-like","protocol":"gemini","base_url":"https://gemini.example/v1beta","api_key":"g-key","model":"model-g"})
    assert response.status_code==200
    assert seen["url"]=="https://gemini.example/v1beta/models"
    assert seen["params"]=={"key":"g-key"}


def test_comtrade_key_can_be_saved_from_browser(tmp_path, monkeypatch):
    root_env = _isolate_env(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post("/api/local-config/comtrade", json={"api_key": "comtrade-test-key"})
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert "comtrade-test-key" not in str(response.json())
    assert "comtrade-test-key" in root_env.read_text(encoding="utf-8")


def test_evidence_brief_uses_configured_generic_provider(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    config.update_local_env({
        "AI_PROVIDER": "Custom Service",
        "AI_PROTOCOL": "openai_compatible",
        "AI_BASE_URL": "https://custom.example/v1",
        "AI_API_KEY": "custom-key",
        "AI_MODEL": "custom-model",
    })
    seen = {}
    result_json = {
        "headline": "H",
        "summary": "S",
        "strengths": [],
        "risks": [],
        "evidence_gaps": [],
        "next_actions": [],
        "decision_language": "Conditional",
    }

    def fake_post(url, **kwargs):
        seen["url"] = url
        return _FakeResponse({"choices": [{"message": {"content": __import__('json').dumps(result_json)}}]})

    monkeypatch.setattr(ai_layer.requests, "post", fake_post)
    output = ai_layer.generate_evidence_brief(
        product={"title": "P", "origin": "CN", "hs_code": "850440"},
        market_contract={"market": "DE"},
        decision={"decision": "conditional"},
        language="en",
    )
    assert output["provider"] == "Custom Service"
    assert output["model"] == "custom-model"
    assert output["result"]["headline"] == "H"
    assert seen["url"] == "https://custom.example/v1/chat/completions"


def test_deepseek_display_model_id_is_normalized_for_validation(monkeypatch):
    from app import ai_layer

    class _FakeResponse:
        status_code = 200
        text = ""
        def raise_for_status(self):
            return None
        def json(self):
            return {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]}

    monkeypatch.setattr(ai_layer.requests, "get", lambda *args, **kwargs: _FakeResponse())
    out = ai_layer.test_connection({
        "provider": "DeepSeek",
        "protocol": "openai_responses",
        "base_url": "https://api.deepseek.com",
        "api_key": "k",
        "model": "DeepSeek-V4-Flash",
    })
    assert out["verified"] is True
    assert out["model"] == "deepseek-v4-flash"


def test_deepseek_model_normalizer_accepts_display_separators():
    from app.ai_layer import normalize_ai_model_id
    assert normalize_ai_model_id(provider="DeepSeek", base_url="https://api.deepseek.com", model=" DeepSeek V4_Flash ") == "deepseek-v4-flash"
    assert normalize_ai_model_id(provider="OpenAI", base_url="https://api.openai.com/v1", model="CaseSensitiveModel") == "CaseSensitiveModel"
