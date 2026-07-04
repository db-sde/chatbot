from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import Header, HTTPException

from settings import settings


def _host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return (parsed.hostname or value).lower()


def validate_site_request(site_key: str, origin: str | None, referer: str | None) -> None:
    allowed_domains = settings.site_domains.get(site_key)
    if not allowed_domains:
        raise HTTPException(status_code=403, detail="Invalid site key")
    host = _host(origin) or _host(referer)
    if host is None:
        raise HTTPException(status_code=403, detail="Origin or Referer required")
    if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_admin_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.admin_auth_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Admin token required")
