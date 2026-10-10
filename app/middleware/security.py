"""Production security middleware — headers, rate limit, docs lockdown."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.runtime import cors_allowed_origins, is_production
from app.services.rate_limiter import check_request_rate_limit, _client_ip

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.tiny.cloud; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tiny.cloud; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self' https: wss: ws:; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}

_DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


class SecurityMiddleware(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if is_production() and path in _DOC_PATHS:
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        ok, rule = check_request_rate_limit(path, _client_ip(request), method=request.method)
        if not ok:
            if rule == "/auth/otp/send":
                detail = (
                    "Bạn đã yêu cầu OTP quá nhiều lần. "
                    "Kiểm tra Gmail (cả Spam/Promotions) lấy mã gần nhất, "
                    "hoặc đợi khoảng 1 giờ rồi bấm «Nhận mã OTP» lại."
                )
            else:
                detail = "Quá nhiều yêu cầu — vui lòng thử lại sau."
            return JSONResponse(
                status_code=429,
                content={"detail": detail},
            )

        if request.method == "OPTIONS" and cors_allowed_origins():
            if not path.startswith("/api/chatbot/public"):
                origin = request.headers.get("origin", "")
                if origin and origin not in cors_allowed_origins():
                    return JSONResponse(status_code=403, content={"detail": "CORS origin denied"})

        response: Response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            if k not in response.headers:
                response.headers[k] = v
        return response
