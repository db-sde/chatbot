from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/degreebaba_ai"
    # Provider API keys
    groq_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = "https://api.deepseek.com"


    allowed_site_keys: str = '{"degreebaba_dev":["localhost","127.0.0.1"],"degreebaba_prod":["degreebaba.com","www.degreebaba.com"]}'
    crm_webhook_url: str | None = None
    admin_auth_token: str = "change-me"
    rate_limit_per_minute: int = 10
    daily_message_cap_per_site: int = 2000
    postgres_password: str = "postgres"

    # Comma-separated list of IPs that are trusted to set X-Forwarded-For
    # (your reverse proxy — Nginx/Caddy/Cloudflare Tunnel). Required for
    # SlowAPI's get_remote_address to see the real visitor IP instead of the
    # proxy's IP once this is deployed behind Nginx/Caddy/Cloudflare.
    # "*" is rejected at startup because it allows any client to spoof
    # X-Forwarded-For and bypass per-IP rate limits.
    trusted_proxies_raw: str = Field(default="127.0.0.1", alias="TRUSTED_PROXIES")

    @field_validator("trusted_proxies_raw")
    @classmethod
    def _reject_wildcard_trusted_proxies(cls, value: str) -> str:
        if value.strip() == "*":
            raise ValueError(
                "TRUSTED_PROXIES='*' is not allowed because it lets any client "
                "spoof X-Forwarded-For and bypass per-IP rate limits. "
                "Set explicit proxy IPs instead."
            )
        return value

    @property
    def trusted_proxies(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies_raw.split(",") if p.strip()]

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

    @property
    def allowed_origins(self) -> list[str]:
        """
        CORS origins, derived from site_domains so there is one source of
        truth for "which domains may talk to this API" — previously this was
        a separately configured ALLOWED_ORIGINS env var that could silently
        drift out of sync with allowed_site_keys (the value validate_site_request
        actually enforces). CORS is a browser-side courtesy layer; the real
        security boundary remains validate_site_request's Origin/Referer check.
        """
        origins: set[str] = set()
        for domains in self.site_domains.values():
            for domain in domains:
                if domain in ("localhost", "127.0.0.1"):
                    for port in ("", ":8080", ":3000", ":5173", ":2323"):
                        origins.add(f"http://{domain}{port}")
                        origins.add(f"https://{domain}{port}")
                else:
                    origins.add(f"https://{domain}")
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
