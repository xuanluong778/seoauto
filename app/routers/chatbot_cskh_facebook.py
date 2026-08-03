"""Chatbot CSKH — Facebook Fanpage channels + Messenger webhook."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.chatbot_cskh_entitlement import assert_chatbot_cskh_manage, assert_facebook_channel_allowed
from app.services.chatbot_cskh_facebook_service import (
    disconnect_page,
    handle_oauth_callback,
    list_channels_overview,
    list_facebook_pages,
    mock_oauth_connect,
    oauth_configured,
    oauth_start_url,
    process_messenger_webhook,
    set_ai_enabled,
    webhook_verify_token,
)

router = APIRouter(tags=["chatbot-cskh-facebook"])


class FacebookAiToggleBody(BaseModel):
    ai_enabled: bool


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.get("/facebook/status")
def facebook_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    try:
        assert_facebook_channel_allowed(db, user)
        allowed = True
        message = ""
    except HTTPException as exc:
        allowed = False
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        message = str(detail.get("message") or "")
    return {
        "ok": True,
        "beta": True,
        "allowed": allowed,
        "message": message,
        "oauth_configured": oauth_configured(),
        "webhook_path": "/api/chatbot/facebook/webhook",
    }


@router.get("/channels/overview")
def channels_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_channels_overview(db, user.id))


@router.get("/facebook/pages")
def facebook_list_pages(
    bot_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    assert_facebook_channel_allowed(db, user)
    return _ok(list_facebook_pages(db, user.id, bot_id=bot_id))


@router.get("/facebook/oauth/start")
def facebook_oauth_start(
    request: Request,
    bot_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    assert_facebook_channel_allowed(db, user)
    return {"ok": True, **oauth_start_url(request, user.id, bot_id)}


@router.get("/facebook/oauth/callback")
def facebook_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not code or not state:
        raise HTTPException(status_code=400, detail="Thiếu code hoặc state OAuth.")
    result = handle_oauth_callback(db, request, code, state)
    count = int(result.get("count") or len(result.get("pages") or []))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Kết nối Fanpage</title></head>
<body><p>Đã kết nối {count} Fanpage. Đang chuyển về Chatbot CSKH…</p>
<script>window.location.href="/chatbot-cskh?tab=channels&fb_connected=1";</script></body></html>"""
    return HTMLResponse(content=html)


@router.get("/facebook/oauth/mock-callback")
def facebook_mock_callback(
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    mock_oauth_connect(db, state)
    html = """<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body><p>Mock Fanpage connected.</p>
<script>window.location.href="/chatbot-cskh?tab=channels&fb_connected=1";</script></body></html>"""
    return HTMLResponse(content=html)


@router.patch("/facebook/pages/{page_row_id}")
def facebook_toggle_ai(
    page_row_id: int,
    body: FacebookAiToggleBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    assert_facebook_channel_allowed(db, user)
    return _ok(set_ai_enabled(db, user.id, page_row_id, enabled=body.ai_enabled))


@router.delete("/facebook/pages/{page_row_id}")
def facebook_disconnect(
    page_row_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    assert_facebook_channel_allowed(db, user)
    disconnect_page(db, user.id, page_row_id)
    return {"ok": True}


@router.get("/facebook/webhook")
def facebook_webhook_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> PlainTextResponse:
    if hub_mode == "subscribe" and hub_verify_token == webhook_verify_token():
        return PlainTextResponse(content=str(hub_challenge or ""))
    raise HTTPException(status_code=403, detail="Webhook verify failed.")


@router.post("/facebook/webhook")
async def facebook_webhook_receive(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        process_messenger_webhook(db, payload)
    return JSONResponse(content={"ok": True})
