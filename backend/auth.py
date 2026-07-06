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


def is_domain_allowed(host: str | None) -> bool:
    if host is None:
        return True
    for domains in settings.site_domains.values():
        for domain in domains:
            if domain.startswith("*."):
                suffix = domain[1:]  # e.g. ".onrender.com"
                if host.endswith(suffix) or host == domain[2:]:
                    return True
            elif host == domain or host.endswith(f".{domain}"):
                return True
    return False


def validate_site_request(site_key: str, origin: str | None, referer: str | None) -> None:
    host = _host(origin) or _host(referer)
    if host is not None and not is_domain_allowed(host):
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_admin_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.admin_auth_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Admin token required")
