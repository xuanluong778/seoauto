"""Chatbot CSKH — conversations & leads API."""

from __future__ import annotations

from typing import Any

import asyncio
import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models.user import User
from app.services.auth import get_current_user, user_from_token
from app.services.chatbot_cskh_entitlement import assert_chatbot_cskh_manage
from app.services.chatbot_cskh_inbox_service import (
    get_conversation_detail,
    list_conversations,
    list_leads,
    list_unread_notifications,
    update_conversation_status,
    update_lead_status,
)

router = APIRouter(tags=["chatbot-cskh-inbox"])


class ConversationStatusBody(BaseModel):
    status: str = Field(..., max_length=32)


class LeadStatusBody(BaseModel):
    status: str = Field(..., max_length=32)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.get("/conversations")
def inbox_list_conversations(
    bot_id: int | None = Query(default=None, ge=1),
    filter: str = Query(default="all", max_length=32),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_conversations(db, user.id, bot_id=bot_id, filter_key=filter, limit=limit)
    return _ok(items)


@router.get("/conversations/{conversation_id}")
def inbox_get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(get_conversation_detail(db, user.id, conversation_id))


@router.patch("/conversations/{conversation_id}")
def inbox_update_conversation(
    conversation_id: int,
    body: ConversationStatusBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = update_conversation_status(db, user.id, conversation_id, status=body.status)
    return _ok(row)


@router.get("/leads")
def inbox_list_leads(
    bot_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_leads(db, user.id, bot_id=bot_id, status=status, limit=limit)
    return _ok(items)


@router.patch("/leads/{lead_id}")
def inbox_update_lead(
    lead_id: int,
    body: LeadStatusBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = update_lead_status(db, user.id, lead_id, status=body.status)
    return _ok(row)


@router.get("/inbox-notifications")
def inbox_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_unread_notifications(db, user.id))


@router.post("/inbox-notifications/{conversation_id}/read")
def inbox_mark_notification_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    from app.services.chatbot_cskh_email_notify import mark_conversation_read
    from app.services.chatbot_cskh_inbox_service import count_unread_conversations, list_unread_notifications

    n = mark_conversation_read(db, int(user.id), int(conversation_id), commit=True)
    snap = list_unread_notifications(db, user.id)
    snap["marked"] = n
    snap["unread_count"] = count_unread_conversations(db, user.id)
    return _ok(snap)


def _ws_token(websocket: WebSocket) -> str:
    q = str(websocket.query_params.get("token") or "").strip()
    if q:
        return q
    return str(websocket.cookies.get("seo_token") or "").strip()


@router.websocket("/inbox-ws")
async def inbox_notifications_ws(websocket: WebSocket) -> None:
    from app.services.chatbot_cskh_inbox_realtime import bind_event_loop, register, unregister, send_user

    token = _ws_token(websocket)
    if not token:
        await websocket.close(code=4401)
        return
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        assert_chatbot_cskh_manage(db, user)
        snap = list_unread_notifications(db, user.id)
        uid = int(user.id)
    except Exception:
        db.close()
        await websocket.close(code=4403)
        return
    db.close()

    await websocket.accept()
    bind_event_loop(asyncio.get_running_loop())
    await register(uid, websocket)
    try:
        await send_user(uid, {"type": "inbox_snapshot", **snap})
        while True:
            raw = await websocket.receive_text()
            ping = False
            try:
                obj = json.loads(raw) if (raw or "").lstrip().startswith("{") else {}
                ping = str(obj.get("type") or "").lower() == "ping"
            except Exception:
                ping = str(raw or "").strip().lower() == "ping"
            if ping:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await unregister(uid, websocket)
