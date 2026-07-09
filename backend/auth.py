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


def is_domain_allowed(host: str | None, site_key: str | None = None) -> bool:
    if host is None:
        return False

    site_domains = settings.site_domains
    domains_to_check = (
        [site_domains.get(site_key, [])]
        if site_key is not None
        else site_domains.values()
    )
    for domains in domains_to_check:
        for domain in domains:
            if domain.startswith("*."):
                suffix = domain[1:]  # e.g. ".onrender.com"
                if host.endswith(suffix) or host == domain[2:]:
                    return True
            elif host == domain or host.endswith(f".{domain}"):
                return True
    return False


def validate_site_request(site_key: str, origin: str | None, referer: str | None) -> None:
    if site_key not in settings.site_domains:
        raise HTTPException(status_code=403, detail="Invalid site key")

    host = _host(origin) or _host(referer)
    if not host:
        raise HTTPException(status_code=403, detail="Origin or Referer required")
    if not is_domain_allowed(host, site_key):
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_admin_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.admin_auth_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Admin token required")
