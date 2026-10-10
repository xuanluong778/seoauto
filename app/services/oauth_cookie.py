"""Set seo_token cookie after OAuth/login — HttpOnly + Secure + SameSite."""

from __future__ import annotations

import secrets

from fastapi import Request
from starlette.responses import Response

from app.core.security import access_token_max_age_seconds
from app.services.session_auth_rollout import refresh_token_expire_days, server_sessions_enabled

SEO_TOKEN_COOKIE = "seo_token"
SEO_REFRESH_COOKIE = "seo_refresh"
CSRF_COOKIE = "seo_csrf"


def refresh_cookie_max_age_seconds() -> int:
    return refresh_token_expire_days() * 86400


def _is_https_request(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip().lower()
    if proto == "https":
        return True
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").lower()
    return host.endswith("seoauto.vn")


def attach_seo_token_cookie(response: Response, request: Request, token: str) -> None:
    """HttpOnly session cookie + readable CSRF cookie for browser sessions."""
    response.set_cookie(
        key=SEO_TOKEN_COOKIE,
        value=token,
        path="/",
        max_age=access_token_max_age_seconds(),
        samesite="lax",
        secure=_is_https_request(request),
        httponly=True,
    )
    attach_csrf_cookie(response, request, secrets.token_urlsafe(32))


def attach_session_cookies(
    response: Response,
    request: Request,
    *,
    access_token: str,
    refresh_token: str | None = None,
) -> None:
    attach_seo_token_cookie(response, request, access_token)
    # Empty refresh_token means concurrent-refresh grace — keep existing seo_refresh cookie.
    if refresh_token and server_sessions_enabled():
        response.set_cookie(
            key=SEO_REFRESH_COOKIE,
            value=refresh_token,
            path="/",
            max_age=refresh_cookie_max_age_seconds(),
            samesite="lax",
            secure=_is_https_request(request),
            httponly=True,
        )


def clear_seo_token_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=SEO_TOKEN_COOKIE,
        path="/",
        samesite="lax",
        secure=_is_https_request(request),
        httponly=True,
    )
    response.delete_cookie(
        key=SEO_REFRESH_COOKIE,
        path="/",
        samesite="lax",
        secure=_is_https_request(request),
        httponly=True,
    )
    response.delete_cookie(
        key=CSRF_COOKIE,
        path="/",
        samesite="lax",
        secure=_is_https_request(request),
        httponly=False,
    )


def attach_csrf_cookie(response: Response, request: Request, token: str) -> None:
    """Readable double-submit CSRF cookie (not HttpOnly)."""
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        path="/",
        max_age=access_token_max_age_seconds(),
        samesite="lax",
        secure=_is_https_request(request),
        httponly=False,
    )
