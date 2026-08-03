"""Sanitize API errors — no stack traces or secrets to clients."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

_LOG = logging.getLogger("seoauto.errors")

_GENERIC = "Không thể xử lý yêu cầu. Vui lòng thử lại sau."


def client_message(status_code: int, detail: Any = None) -> str:
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("detail")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()[:400]
    if isinstance(detail, str) and detail.strip():
        d = detail.strip()
        if status_code < 500 and len(d) <= 400:
            return d
    if status_code == 401:
        return "Đăng nhập để tiếp tục."
    if status_code == 403:
        return "Bạn không có quyền thực hiện thao tác này."
    if status_code == 404:
        return "Không tìm thấy tài nguyên."
    if status_code == 429:
        return "Quá nhiều yêu cầu — vui lòng thử lại sau."
    return _GENERIC


def sanitize_http_exception(exc: HTTPException) -> HTTPException:
    detail = exc.detail
    if isinstance(detail, dict):
        safe = dict(detail)
        for k in ("traceback", "stack", "secret", "password", "token", "api_key"):
            safe.pop(k, None)
        if "message" not in safe and exc.status_code >= 500:
            safe["message"] = _GENERIC
        return HTTPException(status_code=exc.status_code, detail=safe)
    if exc.status_code >= 500:
        return HTTPException(status_code=exc.status_code, detail=_GENERIC)
    return HTTPException(status_code=exc.status_code, detail=client_message(exc.status_code, detail))


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        safe = sanitize_http_exception(exc)
        return JSONResponse(status_code=safe.status_code, content={"detail": safe.detail})
    _LOG.exception("Unhandled error %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": _GENERIC})
