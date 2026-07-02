from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/degreebaba_ai"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    allowed_site_keys: str = '{"degreebaba_dev":["localhost","127.0.0.1"],"degreebaba_prod":["degreebaba.com","www.degreebaba.com"]}'
    allowed_origins_raw: str = Field(default="http://localhost:8000,http://localhost:8080", alias="ALLOWED_ORIGINS")
    crm_webhook_url: str | None = None
    admin_auth_token: str = "change-me"
    rate_limit_per_minute: int = 10
    daily_message_cap_per_site: int = 2000
    postgres_password: str = "postgres"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]

    @property
    def site_domains(self) -> dict[str, list[str]]:
        try:
            parsed = json.loads(self.allowed_site_keys)
            return {str(k): [str(item).lower() for item in v] for k, v in parsed.items()}
        except json.JSONDecodeError:
            pairs: dict[str, list[str]] = {}
            for item in self.allowed_site_keys.split(","):
                if ":" not in item:
                    continue
                key, domains = item.split(":", 1)
                pairs[key.strip()] = [d.strip().lower() for d in domains.split("|") if d.strip()]
            return pairs


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
