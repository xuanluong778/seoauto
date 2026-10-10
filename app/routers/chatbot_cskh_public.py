"""Chatbot CSKH — public widget API (cross-origin, rate-limited)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.chatbot_cskh_security import (
    PublicRequestContext,
    client_ip_from_headers,
    validate_bot_id,
)
from app.services.chatbot_cskh_widget_service import (
    get_public_config,
    get_public_history,
    process_public_message,
    submit_public_lead,
)

router = APIRouter(tags=["chatbot-cskh-public"])

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _cors_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code, headers=_CORS_HEADERS)


def _request_ctx(request: Request) -> PublicRequestContext:
    return PublicRequestContext(
        client_ip=client_ip_from_headers(
            forwarded_for=request.headers.get("x-forwarded-for") or "",
            direct_host=str(request.client.host if request.client else ""),
        ),
        origin=str(request.headers.get("origin") or "").strip(),
        referer=str(request.headers.get("referer") or "").strip(),
        user_agent=str(request.headers.get("user-agent") or "").strip()[:300],
    )


class PublicMessageBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1, max_length=2000)
    visitor_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    page_url: str = Field(default="", max_length=2000)


class PublicLeadBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    visitor_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=120)
    phone: str = Field(..., min_length=6, max_length=32)
    need: str = Field(default="", max_length=2000)
    page_url: str = Field(default="", max_length=2000)


@router.options("/public/message")
@router.options("/public/lead")
@router.options("/public/config")
@router.options("/public/history")
def public_preflight() -> JSONResponse:
    return JSONResponse(content={"ok": True}, headers=_CORS_HEADERS)


@router.get("/public/config")
def public_config(
    request: Request,
    bot_id: int = Query(..., ge=1),
    page_url: str = Query(default=""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    bid = validate_bot_id(bot_id)
    if bid is None:
        return _cors_json({"ok": True, "blocked": True, "code": "invalid_bot", "message": "Chatbot không hợp lệ."})
    return _cors_json(get_public_config(db, bid, ctx=_request_ctx(request), page_url=page_url))


@router.get("/public/history")
def public_history(
    request: Request,
    bot_id: int = Query(..., ge=1),
    visitor_id: str = Query(default=""),
    session_id: str = Query(default=""),
    page_url: str = Query(default=""),
    db: Session = Depends(get_db),
) -> JSONResponse:
    bid = validate_bot_id(bot_id)
    if bid is None:
        return _cors_json({"ok": True, "blocked": True, "code": "invalid_bot", "message": "Chatbot không hợp lệ."})
    return _cors_json(
        get_public_history(
            db,
            bid,
            visitor_id=visitor_id or None,
            session_id=session_id or None,
            ctx=_request_ctx(request),
            page_url=page_url,
        )
    )


@router.post("/public/message")
def public_message(
    body: PublicMessageBody,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    bid = validate_bot_id(body.bot_id)
    if bid is None:
        return _cors_json({
            "ok": False,
            "message": "Chatbot không hợp lệ.",
            "reply": "Chatbot không hợp lệ.",
        }, status_code=400)
    payload = process_public_message(
        db,
        bot_id=bid,
        message=body.message,
        session_id=body.session_id,
        visitor_id=body.visitor_id,
        page_url=body.page_url,
        ctx=_request_ctx(request),
    )
    status_code = 429 if payload.get("code") == "rate_limited" else 200
    return _cors_json(payload, status_code=status_code)


@router.post("/public/lead")
def public_lead(
    body: PublicLeadBody,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    bid = validate_bot_id(body.bot_id)
    if bid is None:
        return _cors_json({"ok": False, "message": "Chatbot không hợp lệ."}, status_code=400)
    payload = submit_public_lead(
        db,
        bot_id=bid,
        session_id=body.session_id,
        visitor_id=body.visitor_id,
        name=body.name,
        phone=body.phone,
        need=body.need,
        page_url=body.page_url,
        ctx=_request_ctx(request),
    )
    status_code = 429 if payload.get("code") == "rate_limited" else 200
    return _cors_json(payload, status_code=status_code)
