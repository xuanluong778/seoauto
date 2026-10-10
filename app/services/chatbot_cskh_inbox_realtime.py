"""In-process WebSocket hub for Chatbot CSKH inbox notifications (single PM2 fork)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotConversation, ChatbotMessage

_LOG = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_clients: dict[int, set[WebSocket]] = {}
_lock = asyncio.Lock()


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _payload_json(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


async def register(user_id: int, ws: WebSocket) -> None:
    uid = int(user_id)
    async with _lock:
        _clients.setdefault(uid, set()).add(ws)


async def unregister(user_id: int, ws: WebSocket) -> None:
    uid = int(user_id)
    async with _lock:
        bucket = _clients.get(uid)
        if not bucket:
            return
        bucket.discard(ws)
        if not bucket:
            _clients.pop(uid, None)


async def send_user(user_id: int, payload: dict[str, Any]) -> None:
    uid = int(user_id)
    async with _lock:
        sockets = list(_clients.get(uid) or [])
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_json(_payload_json(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        await unregister(uid, ws)


def publish(user_id: int, payload: dict[str, Any]) -> None:
    """Thread-safe: widget/facebook run in the FastAPI threadpool."""
    uid = int(user_id)
    loop = _loop
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(send_user(uid, payload), loop)
    except Exception:
        _LOG.exception("inbox ws publish failed user=%s", uid)


def publish_inbox_new(db: Session, conversation: ChatbotConversation, message: ChatbotMessage) -> None:
    from app.services.chatbot_cskh_inbox_service import (
        count_unread_conversations,
        notification_item_from_message,
    )

    uid = int(conversation.user_id)
    try:
        item = notification_item_from_message(db, conversation, message)
        payload = {
            "type": "inbox_new",
            "item": item,
            "unread_count": count_unread_conversations(db, uid),
        }
    except Exception:
        _LOG.exception("build inbox_new payload failed conv=%s", getattr(conversation, "id", None))
        return
    publish(uid, payload)


def publish_inbox_read(user_id: int, conversation_id: int, unread_count: int) -> None:
    publish(
        int(user_id),
        {
            "type": "inbox_read",
            "conversation_id": int(conversation_id),
            "unread_count": max(0, int(unread_count)),
        },
    )
