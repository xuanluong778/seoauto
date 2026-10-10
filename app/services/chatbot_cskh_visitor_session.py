"""Chatbot CSKH — anonymous visitor session (bot_id + visitor_id, 24h idle TTL)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot, ChatbotConversation, ChatbotLead, ChatbotMessage
from app.services.chatbot_cskh_security import normalize_session_id

VISITOR_SESSION_TTL_HOURS = max(1, int(os.getenv("CHATBOT_VISITOR_SESSION_TTL_HOURS", "24") or "24"))


def normalize_visitor_id(visitor_id: str | None) -> str:
    """Return a stable anonymous visitor id or empty string if invalid."""
    return normalize_session_id(visitor_id)


def new_visitor_id() -> str:
    return uuid.uuid4().hex


def resolve_visitor_id(visitor_id: str | None, session_id: str | None = None) -> str:
    vid = normalize_visitor_id(visitor_id) or normalize_visitor_id(session_id)
    return vid or new_visitor_id()


def conversation_last_activity(conv: ChatbotConversation) -> datetime:
    for ts in (conv.last_user_message_at, conv.updated_at, conv.created_at):
        if ts is None:
            continue
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    return datetime.now(timezone.utc)


def is_conversation_expired(conv: ChatbotConversation, *, ttl_hours: int | None = None) -> bool:
    ttl = int(ttl_hours if ttl_hours is not None else VISITOR_SESSION_TTL_HOURS)
    last = conversation_last_activity(conv)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
    return last < cutoff


def purge_visitor_conversation(db: Session, conv: ChatbotConversation) -> None:
    """Delete conversation and all messages/leads — used after idle TTL."""
    cid = int(conv.id)
    db.execute(delete(ChatbotMessage).where(ChatbotMessage.conversation_id == cid))
    db.execute(delete(ChatbotLead).where(ChatbotLead.conversation_id == cid))
    db.delete(conv)
    db.commit()


def find_visitor_conversation(
    db: Session,
    *,
    bot_id: int,
    visitor_id: str,
) -> ChatbotConversation | None:
    vid = normalize_visitor_id(visitor_id)
    if not vid:
        return None
    return db.execute(
        select(ChatbotConversation).where(
            ChatbotConversation.bot_id == int(bot_id),
            ChatbotConversation.session_id == vid,
            ChatbotConversation.channel == "website",
        )
    ).scalar_one_or_none()


def get_or_create_visitor_conversation(
    db: Session,
    bot: ChatbotBot,
    visitor_id: str,
) -> tuple[ChatbotConversation, str, bool]:
    """
    Return (conversation, visitor_id, was_expired_reset).
    Expired conversations are purged before creating a fresh one.
    """
    vid = resolve_visitor_id(visitor_id)
    row = find_visitor_conversation(db, bot_id=bot.id, visitor_id=vid)
    if row is not None and is_conversation_expired(row):
        purge_visitor_conversation(db, row)
        row = None
        expired_reset = True
    else:
        expired_reset = False

    if row is not None:
        return row, vid, expired_reset

    row = ChatbotConversation(
        bot_id=bot.id,
        user_id=bot.user_id,
        session_id=vid,
        status="open",
        organization_id=int(bot.user_id),
        channel="website",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, vid, expired_reset


def list_public_messages(db: Session, conversation_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ChatbotMessage)
        .where(ChatbotMessage.conversation_id == int(conversation_id))
        .order_by(ChatbotMessage.created_at.asc())
        .limit(max(1, min(int(limit), 500)))
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.role or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        text = str(row.message or "").strip()
        if not text:
            continue
        created = row.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        out.append(
            {
                "role": "user" if role == "user" else "bot",
                "text": text[:4000],
                "created_at": created.isoformat() if created else None,
            }
        )
    return out


def load_public_history(
    db: Session,
    *,
    bot: ChatbotBot,
    visitor_id: str,
) -> dict[str, Any]:
    vid = normalize_visitor_id(visitor_id)
    if not vid:
        return {
            "visitor_id": "",
            "session_id": "",
            "expired": False,
            "messages": [],
            "has_conversation": False,
        }

    conv = find_visitor_conversation(db, bot_id=bot.id, visitor_id=vid)
    if conv is None:
        return {
            "visitor_id": vid,
            "session_id": vid,
            "expired": False,
            "messages": [],
            "has_conversation": False,
        }

    if is_conversation_expired(conv):
        purge_visitor_conversation(db, conv)
        return {
            "visitor_id": vid,
            "session_id": vid,
            "expired": True,
            "messages": [],
            "has_conversation": False,
        }

    messages = list_public_messages(db, conv.id)
    return {
        "visitor_id": vid,
        "session_id": vid,
        "expired": False,
        "messages": messages,
        "has_conversation": bool(messages),
        "show_lead_form": conv.status == "needs_staff",
        "lead_submitted": bool(conv.visitor_phone),
    }
