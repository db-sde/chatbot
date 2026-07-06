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
    host = _host(origin) or _host(referer)
    if host is None:
        # Allow requests without origin/referer for development/testing
        return
    allowed = False
    for domains in settings.site_domains.values():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            allowed = True
            break
    if not allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_admin_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.admin_auth_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Admin token required")
