from __future__ import annotations

import ast
import json
import re
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .config import refresh_settings, settings

SUPPORTED_PROTOCOLS = {"openai_compatible", "openai_responses", "anthropic", "gemini"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize_base_url(value: str) -> str:
    url = _clean(value).rstrip("/")
    if not url:
        raise RuntimeError("API Base URL is not configured")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("API Base URL must be a valid http or https URL")
    return url


def _config(overrides: dict[str, Any] | None = None) -> dict[str, str]:
    refresh_settings()
    overrides = overrides or {}
    protocol = _clean(overrides.get("protocol") or settings.ai_protocol).lower()
    return {
        "provider": _clean(overrides.get("provider") or settings.ai_provider),
        "protocol": protocol,
        "base_url": _clean(overrides.get("base_url") or settings.ai_base_url),
        "api_key": _clean(overrides.get("api_key") or settings.ai_api_key),
        "model": _clean(overrides.get("model") or settings.ai_model),
    }


def _require_core(cfg: dict[str, str], *, need_model: bool = True) -> dict[str, str]:
    if cfg["protocol"] not in SUPPORTED_PROTOCOLS:
        raise RuntimeError("API protocol is not configured")
    cfg["base_url"] = _normalize_base_url(cfg["base_url"])
    # DeepSeek documents https://api.deepseek.com as the API base. Accept a
    # user-entered trailing /v1 as well, but normalize it before building paths
    # so /v1/responses or /v1/models is never produced accidentally.
    if _is_deepseek(cfg) and cfg["base_url"].endswith("/v1"):
        cfg["base_url"] = cfg["base_url"][:-3]
    cfg["model"] = normalize_ai_model_id(provider=cfg["provider"], base_url=cfg["base_url"], model=cfg["model"])
    if need_model and not cfg["model"]:
        raise RuntimeError("Model ID is not configured")
    return cfg


def _is_deepseek(cfg: dict[str, str]) -> bool:
    try:
        host = (urlparse(cfg.get("base_url") or "").hostname or "").lower()
    except Exception:
        host = ""
    provider = _clean(cfg.get("provider")).lower()
    model = _clean(cfg.get("model")).lower()
    return "deepseek" in host or "deepseek" in provider or model.startswith("deepseek-")




def normalize_ai_model_id(*, provider: str = "", base_url: str = "", model: str = "") -> str:
    """Return the provider-canonical model ID used for persistence and validation.

    DeepSeek model IDs are lowercase hyphenated identifiers. The UI may show a
    human-readable label such as ``DeepSeek-V4-Flash``; normalize that display
    form so validation is performed against the canonical ``/models`` IDs.
    Other providers are left untouched because their IDs may be case-sensitive.
    """
    raw = _clean(model)
    probe = {"provider": _clean(provider), "base_url": _clean(base_url), "model": raw}
    if not raw or not _is_deepseek(probe):
        return raw
    raw = raw.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    raw = re.sub(r"[\s_]+", "-", raw.strip().lower())
    raw = re.sub(r"-+", "-", raw)
    return raw

def ai_status() -> dict[str, Any]:
    cfg = _config()
    configured = bool(cfg["protocol"] in SUPPORTED_PROTOCOLS and cfg["base_url"] and cfg["model"])
    return {
        "configured": configured,
        "provider": cfg["provider"],
        "protocol": cfg["protocol"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "mode": "evidence-recovery",
    }


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "evidence_gaps": {"type": "array", "items": {"type": "string"}},
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "decision_language": {"type": "string"},
        },
        "required": ["headline", "summary", "strengths", "risks", "evidence_gaps", "next_actions", "decision_language"],
    }


def _ensure_success(response: requests.Response) -> None:
    try:
        response.raise_for_status()
        return
    except requests.HTTPError as exc:
        status = getattr(response, "status_code", None)
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = _clean(error.get("message") or error.get("status") or error.get("type"))
                elif error:
                    detail = _clean(error)
                if not detail:
                    detail = _clean(payload.get("message") or payload.get("detail"))
        except Exception:
            detail = ""
        if status in {401, 403}:
            message = "Authentication failed. Check the API key and provider permissions."
        elif status == 404:
            message = "Endpoint or model not found. Check the API Base URL, protocol and Model ID."
        elif status == 429:
            message = "Provider rate limit or quota was exceeded."
        elif status == 400:
            message = "Provider rejected the request. Check the protocol, endpoint and model settings."
        elif status is not None:
            message = f"Provider request failed with HTTP {status}."
        else:
            message = "Provider request failed."
        if detail:
            message = f"{message} {detail[:300]}"
        raise RuntimeError(message) from exc


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    if cfg["protocol"] == "anthropic":
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        if cfg["api_key"]:
            headers["x-api-key"] = cfg["api_key"]
        return headers
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    return headers


def _extract_openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [str(x.get("text")) for x in content if isinstance(x, dict) and x.get("text")]
            if texts:
                return "\n".join(texts)
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    return ""


def _extract_responses_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") not in {None, "message"}:
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part["text"]))
    return "\n".join(texts)


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    parts = data.get("content") or []
    texts = [str(x.get("text")) for x in parts if isinstance(x, dict) and x.get("type") == "text" and x.get("text")]
    return "\n".join(texts)


def _extract_gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    texts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        for part in (content or {}).get("parts", []) if isinstance(content, dict) else []:
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part["text"]))
    return "\n".join(texts)


def _usage_from_payload(data: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(data, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    usage = data.get("usage") or data.get("usageMetadata") or {}
    def n(*keys: str) -> int:
        for key in keys:
            value = usage.get(key) if isinstance(usage, dict) else None
            if value is not None:
                try:
                    return int(value)
                except Exception:
                    pass
        return 0
    input_tokens = n("input_tokens", "prompt_tokens", "promptTokenCount")
    output_tokens = n("output_tokens", "completion_tokens", "candidatesTokenCount")
    total_tokens = n("total_tokens", "totalTokenCount") or input_tokens + output_tokens
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


def _post_prompt(
    cfg: dict[str, str],
    *,
    system: str,
    user: str,
    max_tokens: int = 900,
    json_mode: bool = False,
) -> tuple[dict[str, Any], str, str]:
    """Send exactly one model-generation request.

    There is intentionally no automatic provider retry or model-based JSON repair here.
    One UI action should never silently fan out into several paid model calls.
    """
    cfg = _require_core(dict(cfg), need_model=True)
    deepseek = _is_deepseek(cfg)

    if cfg["protocol"] == "openai_compatible":
        url = f"{cfg['base_url']}/chat/completions"
        payload: dict[str, Any] = {
            "model": cfg["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if deepseek:
            # DeepSeek defaults to thinking mode. Disable it for extraction/brief
            # tasks so reasoning tokens do not consume the structured-output budget.
            payload["thinking"] = {"type": "disabled"}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = requests.post(url, headers=_headers(cfg), json=payload, timeout=60)
        _ensure_success(response)
        data = response.json()
        return data, _extract_openai_text(data), url

    if cfg["protocol"] == "openai_responses":
        url = f"{cfg['base_url']}/responses"
        payload = {
            "model": cfg["model"],
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
        }
        if deepseek:
            payload["reasoning"] = {"effort": "none"}
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        response = requests.post(url, headers=_headers(cfg), json=payload, timeout=60)
        _ensure_success(response)
        data = response.json()
        if data.get("status") == "incomplete" and not _extract_responses_text(data):
            reason = ((data.get("incomplete_details") or {}).get("reason") or "unknown")
            raise RuntimeError(f"Model response was incomplete: {reason}")
        return data, _extract_responses_text(data), url

    if cfg["protocol"] == "anthropic":
        url = f"{cfg['base_url']}/messages"
        payload = {
            "model": cfg["model"],
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        response = requests.post(url, headers=_headers(cfg), json=payload, timeout=60)
        _ensure_success(response)
        data = response.json()
        return data, _extract_anthropic_text(data), url

    model = cfg["model"]
    model_path = model if model.startswith("models/") else f"models/{model}"
    url = f"{cfg['base_url']}/{quote(model_path, safe='/')}:generateContent"
    params = {"key": cfg["api_key"]} if cfg["api_key"] else {}
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
            **({"responseMimeType": "application/json"} if json_mode else {}),
        },
    }
    response = requests.post(url, params=params, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
    _ensure_success(response)
    data = response.json()
    return data, _extract_gemini_text(data), url


def _parse_json_object(text: str) -> dict[str, Any]:
    text = _clean(text)
    if not text:
        raise RuntimeError("MODEL_EMPTY_RESPONSE")
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    raise RuntimeError("MODEL_INVALID_JSON")


def _parse_json_loose(text: str) -> dict[str, Any]:
    """Local-only JSON recovery; never spends another model call."""
    try:
        return _parse_json_object(text)
    except RuntimeError:
        pass
    cleaned = _clean(text).replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.I | re.S)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        value = ast.literal_eval(cleaned)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    raise RuntimeError("MODEL_INVALID_JSON")


def _responses_text_call(
    cfg: dict[str, str],
    *,
    system: str,
    user: str,
    max_tokens: int = 4000,
    web_search: bool = False,
    reasoning_effort: str | None = None,
    json_format: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Call a Responses-compatible endpoint and return the final assistant text.

    The response reader follows the actual Responses shape used by DeepSeek and
    OpenAI: output[] -> message -> content[] -> output_text.  A provider may also
    expose a convenience top-level output_text field; both forms are accepted.
    """
    cfg = _require_core(dict(cfg), need_model=True)
    url = f"{cfg['base_url'].rstrip('/')}/responses"
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "instructions": system,
        "input": user,
        "max_output_tokens": int(max_tokens),
        "temperature": 0,
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    elif _is_deepseek(cfg):
        payload["reasoning"] = {"effort": "none"}
    if json_format:
        payload["text"] = {"format": json_format}
    if web_search:
        payload["tools"] = [{"type": "web_search"}]
        payload["tool_choice"] = {"type": "web_search"}
    response = requests.post(url, headers=_headers(cfg), json=payload, timeout=150 if web_search else 90)
    _ensure_success(response)
    data = response.json()
    text = _extract_responses_text(data)
    if isinstance(data, dict) and data.get("status") in {"failed", "incomplete"}:
        reason = ((data.get("incomplete_details") or {}).get("reason") or (data.get("error") or {}).get("message") or "unknown")
        if not text:
            raise RuntimeError(f"MODEL_RESPONSE_INCOMPLETE: {reason}")
    if not text:
        raise RuntimeError("MODEL_EMPTY_RESPONSE")
    return data, text, url


def _structured_responses_call(
    cfg: dict[str, str],
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int = 2400,
    web_search: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return structured JSON from a Responses endpoint.

    Providers differ slightly in structured-output strictness.  Try JSON Schema
    first, then JSON Object if the provider rejects or violates the schema.  This
    function is used for short extraction/brief stages; web research itself is
    separated in ai_recovery for DeepSeek so a search result can never be lost
    merely because a tool+schema combination behaved differently.
    """
    formats = [
        {"type": "json_schema", "name": schema_name, "schema": schema},
        {"type": "json_object"},
    ]
    last_exc: Exception | None = None
    for fmt in formats:
        try:
            data, text, url = _responses_text_call(
                cfg, system=system, user=user, max_tokens=max_tokens, web_search=web_search,
                reasoning_effort="none" if _is_deepseek(cfg) else None, json_format=fmt,
            )
            result = _parse_json_loose(text)
            return data, result, url
        except Exception as exc:
            last_exc = exc
            # Authentication, quota and endpoint errors will not improve by
            # changing the output format. Do not obscure those failures.
            msg = str(exc).lower()
            if any(x in msg for x in ("authentication failed", "rate limit", "quota", "endpoint or model not found")):
                raise
    # DeepSeek exposes both Responses and Chat Completions on the same base URL.
    # If a gateway/model accepts Responses web search but rejects structured
    # Responses formatting, use Chat Completions JSON mode as a final bounded
    # structuring fallback.  This call receives only the supplied extraction
    # material; it is not allowed to browse or invent additional facts.
    if _is_deepseek(cfg):
        try:
            chat_cfg=dict(cfg); chat_cfg["protocol"]="openai_compatible"
            data, text, url = _post_prompt(
                chat_cfg, system=system, user=user, max_tokens=max_tokens, json_mode=True
            )
            return data, _parse_json_loose(text), url
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("MODEL_INVALID_JSON")


def _sum_usage(*payloads: dict[str, Any] | None) -> dict[str, int]:
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for payload in payloads:
        usage = _usage_from_payload(payload)
        for key in total:
            total[key] += int(usage.get(key) or 0)
    return total

def _brief_example() -> str:
    return json.dumps({
        "headline": "Evidence-based conclusion",
        "summary": "One concise paragraph.",
        "strengths": ["Supported strength"],
        "risks": ["Supported risk"],
        "evidence_gaps": ["Missing evidence"],
        "next_actions": ["Concrete next action"],
        "decision_language": "Proceed conditionally after the listed evidence gap is closed.",
    }, ensure_ascii=False)


def generate_evidence_brief(*, product: dict[str, Any], market_contract: dict[str, Any], decision: dict[str, Any], language: str = "en") -> dict[str, Any]:
    cfg = _require_core(_config(), need_model=True)
    evidence = {
        "product": {"title": product.get("title"), "origin": product.get("origin"), "hs_code": product.get("hs_code")},
        "market": market_contract,
        "decision": decision,
    }
    output_language = "Simplified Chinese" if str(language).lower().startswith("zh") else "English"
    instructions = (
        "You are a cross-border commerce business analyst. Use only the supplied JSON evidence. "
        "Never invent missing numeric facts, tariffs, taxes, FX rates, marketplace prices, or regulations. "
        "If evidence is missing, list it explicitly. Give concrete, decision-oriented recommendations that follow from the supplied evidence. "
        f"Write every user-facing field in {output_language}. Keep brand names, API names, currency codes, HS codes and standard acronyms unchanged. "
        "Return exactly one valid JSON object and no markdown. The word JSON is intentional. "
        "Required JSON Schema: " + json.dumps(_schema(), ensure_ascii=False) + "\nJSON example: " + _brief_example()
    )
    if _is_deepseek(cfg) and cfg.get("model", "").lower() == "deepseek-v4-flash":
        data, result, endpoint = _structured_responses_call(
            cfg,
            system=instructions,
            user=json.dumps(evidence, ensure_ascii=False),
            schema=_schema(),
            schema_name="bordermargin_decision_brief",
            max_tokens=1600,
            web_search=False,
        )
    else:
        data, text, endpoint = _post_prompt(cfg, system=instructions, user=json.dumps(evidence, ensure_ascii=False), max_tokens=1600, json_mode=True)
        result = _parse_json_loose(text)
    missing = [key for key in _schema()["required"] if key not in result]
    if missing:
        raise RuntimeError("Model returned incomplete brief JSON: " + ", ".join(missing))
    return {
        "provider": cfg["provider"] or cfg["protocol"],
        "protocol": cfg["protocol"],
        "model": cfg["model"],
        "mode": "evidence-only",
        "language": "zh" if str(language).lower().startswith("zh") else "en",
        "endpoint": endpoint,
        "usage": _usage_from_payload(data),
        "result": result,
    }


def list_models(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _require_core(_config(overrides), need_model=False)
    selected = cfg["model"]
    try:
        if cfg["protocol"] in {"openai_compatible", "openai_responses", "anthropic"}:
            url = f"{cfg['base_url']}/models"
            r = requests.get(url, headers=_headers(cfg), timeout=20)
            _ensure_success(r)
            raw = r.json().get("data", [])
            ids = sorted({str(row.get("id")) for row in raw if isinstance(row, dict) and row.get("id")})
        else:
            url = f"{cfg['base_url']}/models"
            params = {"key": cfg["api_key"]} if cfg["api_key"] else {}
            r = requests.get(url, params=params, headers={"Content-Type": "application/json"}, timeout=20)
            _ensure_success(r)
            raw = r.json().get("models", [])
            ids = []
            for row in raw:
                if not isinstance(row, dict) or not row.get("name"):
                    continue
                methods = row.get("supportedGenerationMethods")
                if isinstance(methods, list) and "generateContent" not in methods:
                    continue
                ids.append(str(row["name"]).removeprefix("models/"))
            ids = sorted(set(ids))
        return {
            "configured": True,
            "available": ids,
            "selected": selected,
            "source": "provider-models-api",
            "provider": cfg["provider"],
            "protocol": cfg["protocol"],
        }
    except Exception as exc:
        return {
            "configured": True,
            "available": [],
            "selected": selected,
            "source": "unavailable",
            "provider": cfg["provider"],
            "protocol": cfg["protocol"],
            "warning": str(exc),
        }


def test_connection(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Token-free configuration check.

    Validation never sends a generation request. Providers exposing a model-list
    endpoint are verified there. If a custom compatible gateway has no model-list
    endpoint, the configuration can still be saved, but it is reported as
    unverified rather than spending tokens behind the user's back.
    """
    cfg = _require_core(_config(overrides), need_model=True)
    models = list_models(overrides)
    available = models.get("available") or []
    if models.get("source") == "provider-models-api":
        if available and cfg["model"] not in available:
            raise RuntimeError("Selected Model ID is not available to this API key")
        return {
            "ok": True,
            "verified": True,
            "provider": cfg["provider"] or cfg["protocol"],
            "protocol": cfg["protocol"],
            "model": cfg["model"],
            "endpoint": f"{cfg['base_url']}/models",
            "validation_mode": "models-api",
            "model_generation_used": False,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "message": "API credentials and model access were verified without a generation request",
        }
    warning = _clean(models.get("warning"))
    if warning and ("Authentication failed" in warning or "HTTP 401" in warning or "HTTP 403" in warning):
        raise RuntimeError(warning)
    return {
        "ok": True,
        "verified": False,
        "provider": cfg["provider"] or cfg["protocol"],
        "protocol": cfg["protocol"],
        "model": cfg["model"],
        "endpoint": f"{cfg['base_url']}/models",
        "validation_mode": "config-only",
        "model_generation_used": False,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "message": "Model-list validation is unavailable; no generation request was sent",
        "warning": warning,
    }
