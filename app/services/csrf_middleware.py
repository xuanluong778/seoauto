"""CSRF protection for cookie-authenticated write requests."""

from __future__ import annotations

import hmac
import secrets
from typing import Callable
from urllib.parse import urlparse

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.runtime import cors_allowed_origins, is_production
from app.services.oauth_cookie import CSRF_COOKIE, SEO_TOKEN_COOKIE, attach_csrf_cookie

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Auth endpoints that establish session (CSRF not required until cookie exists)
_CSRF_EXEMPT_PREFIXES = (
    "/auth/login",
    "/auth/register",
    "/auth/otp",
    "/auth/google",
    "/auth/logout",
    "/auth/refresh",
    "/api/auth/login",
    "/api/auth/register",
    "/api/payments/sepay/webhook",
    "/api/wordpress-plugin/",  # uses HMAC / API keys
    "/health",
    "/ready",
    "/metrics",
    "/api/chatbot/public/",
    "/api/chatbot-cskh/public/",
    "/chatbot/public/",
)


def _origin_allowed(request: Request, origin: str) -> bool:
    origin = (origin or "").strip().rstrip("/")
    if not origin:
        return False
    allowed = set(cors_allowed_origins() or [])
    # Always allow same host
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    if host:
        allowed.add(f"{scheme}://{host}".rstrip("/"))
        if host.startswith("www."):
            allowed.add(f"{scheme}://{host[4:]}".rstrip("/"))
        else:
            allowed.add(f"{scheme}://www.{host}".rstrip("/"))
    # Dev localhost
    if not is_production():
        allowed.update({"http://127.0.0.1:8899", "http://localhost:8899", "http://127.0.0.1:8000"})
    return origin in allowed or origin.rstrip("/") in {a.rstrip("/") for a in allowed}


def _has_bearer(request: Request) -> bool:
    auth = (request.headers.get("authorization") or "").strip()
    return auth.lower().startswith("bearer ") and len(auth) > 10


def _cookie_auth_present(request: Request) -> bool:
    return bool((request.cookies.get(SEO_TOKEN_COOKIE) or "").strip())


def _is_exempt(path: str) -> bool:
    p = path or ""
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if p == prefix or p.startswith(prefix):
            return True
    return False


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class CookieCsrfMiddleware(BaseHTTPMiddleware):
    """
    For state-changing requests authenticated only via seo_token cookie
    (no Authorization Bearer):
    - require matching X-CSRF-Token header with readable csrf cookie, OR
    - require Origin/Referer from allowed origins.
    Bearer-header APIs are CSRF-safe (custom header not sent cross-site by browsers).
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = (request.method or "GET").upper()
        path = request.url.path or ""

        if method not in _SAFE_METHODS and not _is_exempt(path):
            if _cookie_auth_present(request) and not _has_bearer(request):
                csrf_cookie = (request.cookies.get(CSRF_COOKIE) or "").strip()
                csrf_header = (
                    request.headers.get("x-csrf-token")
                    or request.headers.get("x-xsrf-token")
                    or ""
                ).strip()
                origin = (request.headers.get("origin") or "").strip()
                referer = (request.headers.get("referer") or "").strip()
                origin_ok = False
                if origin and _origin_allowed(request, origin):
                    origin_ok = True
                elif referer:
                    try:
                        ref_o = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
                        origin_ok = _origin_allowed(request, ref_o)
                    except Exception:
                        origin_ok = False
                token_ok = bool(csrf_cookie and csrf_header and hmac.compare_digest(csrf_cookie, csrf_header))
                if not (token_ok or origin_ok):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF check failed. Gửi Origin hợp lệ hoặc X-CSRF-Token."},
                    )

        response = await call_next(request)

        # Ensure CSRF cookie exists for browser sessions (readable)
        if SEO_TOKEN_COOKIE in request.cookies or path.startswith("/auth"):
            if not request.cookies.get(CSRF_COOKIE):
                # Only set when response is mutable and we might have a session
                try:
                    attach_csrf_cookie(response, request, new_csrf_token())
                except Exception:
                    pass
        return response
