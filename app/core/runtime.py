"""Runtime flags — production vs development."""

from __future__ import annotations

import os


def is_production() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if env in ("production", "prod", "live"):
        return True
    return (os.getenv("SEOAUTO_PRODUCTION") or "").strip().lower() in ("1", "true", "yes")


def allowed_hosts() -> list[str]:
    raw = (os.getenv("ALLOWED_HOSTS") or "").strip()
    if raw:
        return [h.strip() for h in raw.split(",") if h.strip()]
    if is_production():
        base = (os.getenv("APP_BASE_URL") or "https://seoauto.vn").strip()
        from urllib.parse import urlparse

        host = urlparse(base).hostname
        hosts = [host] if host else ["seoauto.vn", "www.seoauto.vn"]
        for internal in ("127.0.0.1", "localhost"):
            if internal not in hosts:
                hosts.append(internal)
        return hosts
    return ["*"]


def cors_allowed_origins() -> list[str]:
    raw = (os.getenv("CORS_ALLOWED_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if is_production():
        base = (os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")
        return [base, base.replace("://www.", "://"), base.replace("://", "://www.")]
    return []
