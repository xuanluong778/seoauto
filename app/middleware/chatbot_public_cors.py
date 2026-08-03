"""Permissive CORS for embeddable Chatbot CSKH public API (any customer website)."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_PUBLIC_PREFIX = "/api/chatbot/public"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


class ChatbotPublicCorsMiddleware(BaseHTTPMiddleware):
    """Handle CORS preflight for widget embeds before global CORSMiddleware rejects unknown origins."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if not path.startswith(_PUBLIC_PREFIX):
            return await call_next(request)

        if request.method == "OPTIONS":
            return Response(status_code=204, headers=dict(_CORS_HEADERS))

        response = await call_next(request)
        for key, value in _CORS_HEADERS.items():
            if key.lower() not in {h.lower() for h in response.headers}:
                response.headers[key] = value
        return response
