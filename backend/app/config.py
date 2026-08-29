from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV = PROJECT_ROOT / ".env"
BACKEND_ENV = PROJECT_ROOT / "backend" / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _read_file_values() -> tuple[dict[str, str], list[str]]:
    """Load supported local .env files without mutating os.environ.

    backend/.env is accepted for compatibility with older/manual setups.
    The project-root .env takes precedence when both are present.
    """
    values: dict[str, str] = {}
    sources: list[str] = []
    for path in (BACKEND_ENV, ROOT_ENV):
        if not path.exists():
            continue
        parsed = dotenv_values(path)
        for key, value in parsed.items():
            if value is not None:
                values[str(key)] = str(value)
        sources.append("backend/.env" if path == BACKEND_ENV else ".env")
    return values, sources


def _resolve(values: dict[str, str], key: str, default: str = "") -> str:
    process_value = os.environ.get(key)
    if process_value is not None and str(process_value).strip():
        return str(process_value).strip()
    file_value = values.get(key)
    if file_value is not None and str(file_value).strip():
        return str(file_value).strip()
    return default


@dataclass
class Settings:
    app_env: str = "development"
    database_url: str = "sqlite:///./bordermargin.db"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    comtrade_subscription_key: str = ""
    ebay_env: str = "sandbox"
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace_id: str = ""
    ai_provider: str = ""
    ai_protocol: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    web_research_provider: str = "auto"
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    config_sources: tuple[str, ...] = field(default_factory=tuple)

    def reload(self) -> "Settings":
        values, sources = _read_file_values()
        self.app_env = _resolve(values, "APP_ENV", "development")
        self.database_url = _resolve(values, "DATABASE_URL", "sqlite:///./bordermargin.db")
        self.cors_origins = tuple(_split_csv(_resolve(values, "CORS_ORIGINS", "http://localhost:5173")))
        self.comtrade_subscription_key = _resolve(values, "COMTRADE_SUBSCRIPTION_KEY")
        self.ebay_env = _resolve(values, "EBAY_ENV", "sandbox").lower()
        if self.ebay_env not in {"sandbox", "production"}:
            self.ebay_env = "sandbox"
        self.ebay_client_id = _resolve(values, "EBAY_CLIENT_ID")
        self.ebay_client_secret = _resolve(values, "EBAY_CLIENT_SECRET")
        self.ebay_marketplace_id = _resolve(values, "EBAY_MARKETPLACE_ID")
        self.ai_provider = _resolve(values, "AI_PROVIDER")
        self.ai_protocol = _resolve(values, "AI_PROTOCOL").lower()
        self.ai_base_url = _resolve(values, "AI_BASE_URL")
        self.ai_api_key = _resolve(values, "AI_API_KEY")
        self.ai_model = _resolve(values, "AI_MODEL")
        self.web_research_provider = _resolve(values, "WEB_RESEARCH_PROVIDER", "auto").lower()
        if self.web_research_provider not in {"auto", "native", "tavily", "none"}:
            self.web_research_provider = "auto"
        self.tavily_api_key = _resolve(values, "TAVILY_API_KEY")
        self.tavily_base_url = _resolve(values, "TAVILY_BASE_URL", "https://api.tavily.com")
        self.config_sources = tuple(sources)
        return self


settings = Settings().reload()


def refresh_settings() -> Settings:
    """Refresh the existing settings object so imported references stay valid."""
    return settings.reload()


def mask_client_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * max(4, len(value))
    return f"{value[:4]}…{value[-4:]}"


def mask_secret(value: str) -> str:
    return mask_client_id(value)


def update_local_env(updates: dict[str, Any]) -> Settings:
    """Persist local configuration in project-root .env and refresh in-memory values."""
    if not ROOT_ENV.exists():
        if ENV_EXAMPLE.exists():
            ROOT_ENV.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ROOT_ENV.touch()
    for key, raw_value in updates.items():
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        set_key(str(ROOT_ENV), key, value, quote_mode="auto")
    return refresh_settings()
