"""Permissive CORS for embeddable Chatbot CSKH public API (any customer website)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response

_PUBLIC_PREFIX = "/api/chatbot/public"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


class ChatbotPublicCorsMiddleware:
    """ASGI CORS so widget origins always get headers, including 4xx/5xx."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if not path.startswith(_PUBLIC_PREFIX):
            await self.app(scope, receive, send)
            return
        if str(scope.get("method") or "").upper() == "OPTIONS":
            response = Response(status_code=204, headers=dict(_CORS_HEADERS))
            await response(scope, receive, send)
            return

        async def send_with_cors(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in _CORS_HEADERS.items():
                    if key not in headers:
                        headers[key] = value
            await send(message)

        await self.app(scope, receive, send_with_cors)
