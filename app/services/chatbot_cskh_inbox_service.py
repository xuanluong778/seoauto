"""Chatbot CSKH — conversations & leads inbox (user-scoped)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot, ChatbotConversation, ChatbotLead, ChatbotMessage
from app.services.chatbot_cskh_lead_detect import detect_lead_from_text

CONVERSATION_FILTERS = frozenset({"all", "has_phone", "unprocessed", "handled", "needs_staff"})
CONVERSATION_STATUSES = frozenset({"open", "needs_staff", "handled"})
LEAD_STATUSES = frozenset({"new", "consulting", "won", "no_potential"})

LEAD_STATUS_LABELS = {
    "new": "Mới",
    "consulting": "Đang tư vấn",
    "won": "Đã chốt",
    "no_potential": "Không tiềm năng",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _get_user_bot(db: Session, user_id: int, bot_id: int) -> ChatbotBot:
    row = db.execute(
        select(ChatbotBot).where(ChatbotBot.id == int(bot_id), ChatbotBot.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    return row


def _get_user_conversation(db: Session, user_id: int, conversation_id: int) -> ChatbotConversation:
    row = db.execute(
        select(ChatbotConversation).where(
            ChatbotConversation.id == int(conversation_id),
            ChatbotConversation.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy hội thoại.")
    return row


def _get_user_lead(db: Session, user_id: int, lead_id: int) -> ChatbotLead:
    row = db.execute(
        select(ChatbotLead).where(ChatbotLead.id == int(lead_id), ChatbotLead.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy lead.")
    return row


def _conversation_leads(db: Session, conversation_id: int) -> list[ChatbotLead]:
    return list(
        db.execute(
            select(ChatbotLead)
            .where(ChatbotLead.conversation_id == int(conversation_id))
            .order_by(ChatbotLead.created_at.desc())
        ).scalars().all()
    )


def _lead_to_dict(row: ChatbotLead) -> dict[str, Any]:
    st = str(row.status or "new").lower()
    return {
        "lead_id": row.id,
        "id": row.id,
        "bot_id": row.bot_id,
        "conversation_id": row.conversation_id,
        "name": row.name or "",
        "phone": row.phone or "",
        "need": row.need or "",
        "page_url": row.page_url or "",
        "status": st,
        "status_label": LEAD_STATUS_LABELS.get(st, st),
        "created_at": _iso(row.created_at),
    }


def _conversation_summary(db: Session, conv: ChatbotConversation) -> dict[str, Any]:
    last_msg = db.execute(
        select(ChatbotMessage)
        .where(ChatbotMessage.conversation_id == conv.id)
        .order_by(ChatbotMessage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    leads = _conversation_leads(db, conv.id)
    primary_lead = leads[0] if leads else None
    msg_count = int(
        db.execute(select(func.count()).select_from(ChatbotMessage).where(ChatbotMessage.conversation_id == conv.id)).scalar()
        or 0
    )
    st = str(conv.status or "open").lower()
    channel = str(conv.channel or "website").strip().lower() or "website"
    channel_labels = {"website": "Website", "facebook": "Facebook"}
    return {
        "conversation_id": conv.id,
        "bot_id": conv.bot_id,
        "session_id": conv.session_id,
        "channel": channel,
        "channel_label": channel_labels.get(channel, channel),
        "channel_ref": conv.channel_ref or "",
        "visitor_name": conv.visitor_name or (primary_lead.name if primary_lead else "") or "",
        "visitor_phone": conv.visitor_phone or (primary_lead.phone if primary_lead else "") or "",
        "visitor": conv.visitor_name or (primary_lead.name if primary_lead else "") or "Khách",
        "preview": (last_msg.message[:160] if last_msg else ""),
        "status": st,
        "message_count": msg_count,
        "has_phone": bool((conv.visitor_phone or "").strip() or any((l.phone or "").strip() for l in leads)),
        "has_lead": bool(leads),
        "lead_status": primary_lead.status if primary_lead else None,
        "lead_id": primary_lead.id if primary_lead else None,
        "created_at": _iso(conv.created_at),
        "updated_at": _iso(conv.updated_at),
    }


def list_conversations(
    db: Session,
    user_id: int,
    *,
    bot_id: int | None = None,
    filter_key: str = "all",
    limit: int = 100,
) -> list[dict[str, Any]]:
    fk = str(filter_key or "all").strip().lower()
    if fk not in CONVERSATION_FILTERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="filter không hợp lệ.")
    if bot_id is not None:
        _get_user_bot(db, user_id, bot_id)

    q = select(ChatbotConversation).where(ChatbotConversation.user_id == int(user_id))
    if bot_id is not None:
        q = q.where(ChatbotConversation.bot_id == int(bot_id))

    if fk == "has_phone":
        q = q.where(
            or_(
                ChatbotConversation.visitor_phone.isnot(None),
                ChatbotConversation.visitor_phone != "",
            )
        )
    elif fk == "unprocessed":
        q = q.where(ChatbotConversation.status == "open")
    elif fk == "handled":
        q = q.where(ChatbotConversation.status == "handled")
    elif fk == "needs_staff":
        q = q.where(ChatbotConversation.status == "needs_staff")

    rows = db.execute(
        q.order_by(ChatbotConversation.updated_at.desc()).limit(max(1, min(limit, 200)))
    ).scalars().all()

    items = [_conversation_summary(db, c) for c in rows]
    if fk == "has_phone":
        items = [i for i in items if i.get("has_phone")]
    return items


def get_conversation_detail(db: Session, user_id: int, conversation_id: int) -> dict[str, Any]:
    conv = _get_user_conversation(db, user_id, conversation_id)
    messages = db.execute(
        select(ChatbotMessage)
        .where(ChatbotMessage.conversation_id == conv.id)
        .order_by(ChatbotMessage.created_at.asc())
    ).scalars().all()
    leads = [_lead_to_dict(l) for l in _conversation_leads(db, conv.id)]
    bot = db.get(ChatbotBot, conv.bot_id)
    summary = _conversation_summary(db, conv)
    summary["bot_name"] = bot.bot_name if bot else ""
    summary["messages"] = [
        {
            "id": m.id,
            "role": m.role,
            "message": m.message,
            "created_at": _iso(m.created_at),
        }
        for m in messages
    ]
    summary["leads"] = leads
    return summary


def update_conversation_status(
    db: Session,
    user_id: int,
    conversation_id: int,
    *,
    status: str,
) -> dict[str, Any]:
    conv = _get_user_conversation(db, user_id, conversation_id)
    st = str(status or "").strip().lower()
    if st not in CONVERSATION_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status hội thoại không hợp lệ.")
    conv.status = st
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return _conversation_summary(db, conv)


def list_leads(
    db: Session,
    user_id: int,
    *,
    bot_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if bot_id is not None:
        _get_user_bot(db, user_id, bot_id)
    q = select(ChatbotLead).where(ChatbotLead.user_id == int(user_id))
    if bot_id is not None:
        q = q.where(ChatbotLead.bot_id == int(bot_id))
    if status:
        st = str(status).strip().lower()
        if st not in LEAD_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status lead không hợp lệ.")
        q = q.where(ChatbotLead.status == st)
    rows = db.execute(q.order_by(ChatbotLead.created_at.desc()).limit(max(1, min(limit, 200)))).scalars().all()
    return [_lead_to_dict(r) for r in rows]


def update_lead_status(db: Session, user_id: int, lead_id: int, *, status: str) -> dict[str, Any]:
    row = _get_user_lead(db, user_id, lead_id)
    st = str(status or "").strip().lower()
    if st not in LEAD_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status lead không hợp lệ.")
    row.status = st
    db.commit()
    db.refresh(row)
    if row.conversation_id:
        conv = db.get(ChatbotConversation, row.conversation_id)
        if conv and conv.user_id == int(user_id):
            if st in ("won", "no_potential"):
                conv.status = "handled"
            elif st == "consulting":
                conv.status = "needs_staff"
            conv.updated_at = datetime.now(timezone.utc)
            db.commit()
    return _lead_to_dict(row)


def upsert_detected_lead(
    db: Session,
    *,
    bot: ChatbotBot,
    conversation: ChatbotConversation,
    text: str,
    page_url: str = "",
) -> ChatbotLead | None:
    detected = detect_lead_from_text(text)
    phone = detected.get("phone") or ""
    name = detected.get("name") or ""
    need = detected.get("need") or ""
    if not phone and not (name and need):
        return None

    if phone:
        conversation.visitor_phone = phone[:32]
    if name:
        conversation.visitor_name = name[:120]
    if conversation.status == "open":
        conversation.status = "needs_staff"
    conversation.updated_at = datetime.now(timezone.utc)

    existing = db.execute(
        select(ChatbotLead)
        .where(
            ChatbotLead.conversation_id == conversation.id,
            ChatbotLead.user_id == bot.user_id,
        )
        .order_by(ChatbotLead.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if existing:
        if phone and not existing.phone:
            existing.phone = phone[:32]
        if name and not existing.name:
            existing.name = name[:120]
        if need and not existing.need:
            existing.need = need[:2000]
        if page_url and not existing.page_url:
            existing.page_url = page_url[:2000]
        db.commit()
        db.refresh(existing)
        return existing

    lead = ChatbotLead(
        bot_id=bot.id,
        conversation_id=conversation.id,
        user_id=bot.user_id,
        name=name[:120] or None,
        phone=phone[:32] or None,
        need=need[:2000] or None,
        page_url=str(page_url or "").strip()[:2000] or None,
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def mark_conversation_needs_staff(db: Session, conversation: ChatbotConversation) -> None:
    if str(conversation.status or "").lower() == "open":
        conversation.status = "needs_staff"
        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
