"""Shared helpers for affiliate user/admin JSON APIs."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.schemas.affiliate import AffiliateApiResponse
from app.services.safe_errors import client_message


AFFILIATE_API_PATH_MARKERS = (
    "/affiliate/",
    "/admin/affiliate/",
    "/admin/api/affiliate",
    "/api/admin/affiliate",
)


def is_affiliate_json_api(path: str) -> bool:
    p = path or ""
    if p == "/affiliate" or p.startswith("/affiliate/"):
        return True
    return any(p.startswith(m) for m in AFFILIATE_API_PATH_MARKERS if m.endswith("/")) or any(
        p.startswith(m) for m in AFFILIATE_API_PATH_MARKERS if not m.endswith("/")
    )


def api_ok(data: Any = None, message: str = "") -> AffiliateApiResponse:
    return AffiliateApiResponse(success=True, message=message, data=data)


def api_fail(
    message: str,
    error: str,
    status_code: int = 400,
    data: Any = None,
) -> JSONResponse:
    payload = AffiliateApiResponse(success=False, message=message, data=data, error=error)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def http_error_to_affiliate_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    msg = client_message(exc.status_code, detail)
    error = _error_code(exc.status_code, detail)
    return api_fail(msg, error, status_code=exc.status_code)


def _error_code(status_code: int, detail: Any) -> str:
    if isinstance(detail, dict) and detail.get("error"):
        return str(detail["error"])
    mapping = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        422: "validation_error",
        429: "rate_limited",
    }
    if status_code >= 500:
        return "server_error"
    if status_code == 400:
        return "bad_request"
    return mapping.get(status_code, "error")
