"""Set seo_token cookie after OAuth login — HTTPS-safe behind nginx."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import Response

from app.core.security import access_token_max_age_seconds


def _is_https_request(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip().lower()
    if proto == "https":
        return True
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").lower()
    return host.endswith("seoauto.vn")


def attach_seo_token_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key="seo_token",
        value=token,
        path="/",
        max_age=access_token_max_age_seconds(),
        samesite="lax",
        secure=_is_https_request(request),
        httponly=False,
    )
