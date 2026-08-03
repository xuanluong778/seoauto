"""Chatbot CSKH — database service (user-scoped)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import (
    ChatbotBot,
    ChatbotConversation,
    ChatbotKnowledgeSource,
    ChatbotLead,
    ChatbotMessage,
    ChatbotUsage,
)
from app.services.chatbot_cskh_entitlement import CONSULTATION_TONES, default_greeting
from app.services.chatbot_cskh_widget_service import enrich_bot_dict

BOT_STATUSES = frozenset({"draft", "active", "paused", "archived"})
SOURCE_STATUSES = frozenset({"pending", "ready", "failed"})
SOURCE_TYPES = frozenset({"faq", "business", "website"})


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _bot_to_dict(row: ChatbotBot) -> dict[str, Any]:
    data = {
        "bot_id": row.id,
        "user_id": row.user_id,
        "website_url": row.website_url or "",
        "bot_name": row.bot_name,
        "business_name": row.business_name or "",
        "industry": row.industry or "",
        "hotline": row.hotline or "",
        "main_services": getattr(row, "main_services", None) or "",
        "consultation_tone": getattr(row, "consultation_tone", None) or "friendly",
        "greeting": getattr(row, "greeting", None) or "",
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    return enrich_bot_dict(data)


def _get_user_bot(db: Session, user_id: int, bot_id: int) -> ChatbotBot:
    row = db.execute(
        select(ChatbotBot).where(ChatbotBot.id == int(bot_id), ChatbotBot.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    return row


def count_user_bots(db: Session, user_id: int) -> int:
    return int(
        db.execute(select(func.count()).select_from(ChatbotBot).where(ChatbotBot.user_id == int(user_id))).scalar()
        or 0
    )


def list_bots_db(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ChatbotBot)
        .where(ChatbotBot.user_id == int(user_id))
        .order_by(ChatbotBot.created_at.desc())
    ).scalars().all()
    return [_bot_to_dict(r) for r in rows]


def get_bot_db(db: Session, user_id: int, bot_id: int) -> dict[str, Any]:
    return _bot_to_dict(_get_user_bot(db, user_id, bot_id))


def create_bot_db(
    db: Session,
    user_id: int,
    *,
    bot_name: str,
    website_url: str = "",
    business_name: str = "",
    industry: str = "",
    hotline: str = "",
    main_services: str = "",
    consultation_tone: str = "friendly",
    greeting: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    name = str(bot_name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bot_name không được để trống.")
    st = str(status or "draft").strip().lower()
    if st not in BOT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status không hợp lệ.")
    tone = str(consultation_tone or "friendly").strip().lower()
    if tone not in CONSULTATION_TONES:
        tone = "friendly"
    biz = str(business_name or "").strip()[:160] or None
    greet = str(greeting or "").strip()[:500] or default_greeting(name, biz or "", tone)
    row = ChatbotBot(
        user_id=int(user_id),
        bot_name=name[:120],
        website_url=str(website_url or "").strip()[:2000] or None,
        business_name=biz,
        industry=str(industry or "").strip()[:120] or None,
        hotline=str(hotline or "").strip()[:64] or None,
        main_services=str(main_services or "").strip() or None,
        consultation_tone=tone,
        greeting=greet,
        status=st,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _bot_to_dict(row)


def update_bot_db(db: Session, user_id: int, bot_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    row = _get_user_bot(db, user_id, bot_id)
    if "bot_name" in patch:
        name = str(patch.get("bot_name") or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bot_name không được để trống.")
        row.bot_name = name[:120]
    if "website_url" in patch:
        row.website_url = str(patch.get("website_url") or "").strip()[:2000] or None
    if "business_name" in patch:
        row.business_name = str(patch.get("business_name") or "").strip()[:160] or None
    if "industry" in patch:
        row.industry = str(patch.get("industry") or "").strip()[:120] or None
    if "hotline" in patch:
        row.hotline = str(patch.get("hotline") or "").strip()[:64] or None
    if "main_services" in patch:
        row.main_services = str(patch.get("main_services") or "").strip() or None
    if "consultation_tone" in patch:
        tone = str(patch.get("consultation_tone") or "friendly").strip().lower()
        if tone in CONSULTATION_TONES:
            row.consultation_tone = tone
    if "greeting" in patch:
        row.greeting = str(patch.get("greeting") or "").strip()[:500] or None
    if "status" in patch:
        st = str(patch.get("status") or "").strip().lower()
        if st not in BOT_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status không hợp lệ.")
        row.status = st
    # legacy alias from JSON store UI
    if "name" in patch and "bot_name" not in patch:
        name = str(patch.get("name") or "").strip()
        if name:
            row.bot_name = name[:120]
    if "description" in patch:
        pass  # no column — ignore safely
    db.commit()
    db.refresh(row)
    return _bot_to_dict(row)


def delete_bot_db(db: Session, user_id: int, bot_id: int) -> None:
    row = _get_user_bot(db, user_id, bot_id)
    db.delete(row)
    db.commit()


def get_overview_db(db: Session, user_id: int) -> dict[str, Any]:
    uid = int(user_id)
    bots_total = count_user_bots(db, uid)
    bots_active = int(
        db.execute(
            select(func.count())
            .select_from(ChatbotBot)
            .where(ChatbotBot.user_id == uid, ChatbotBot.status == "active")
        ).scalar()
        or 0
    )
    sources_total = int(
        db.execute(
            select(func.count()).select_from(ChatbotKnowledgeSource).where(ChatbotKnowledgeSource.user_id == uid)
        ).scalar()
        or 0
    )
    conversations_total = int(
        db.execute(
            select(func.count()).select_from(ChatbotConversation).where(ChatbotConversation.user_id == uid)
        ).scalar()
        or 0
    )
    leads_total = int(
        db.execute(select(func.count()).select_from(ChatbotLead).where(ChatbotLead.user_id == uid)).scalar() or 0
    )
    leads_won = int(
        db.execute(
            select(func.count()).select_from(ChatbotLead).where(
                ChatbotLead.user_id == uid, ChatbotLead.status == "won"
            )
        ).scalar()
        or 0
    )
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    conversations_today = int(
        db.execute(
            select(func.count())
            .select_from(ChatbotConversation)
            .where(ChatbotConversation.user_id == uid, ChatbotConversation.created_at >= today_start)
        ).scalar()
        or 0
    )
    usage_row = db.execute(
        select(
            func.coalesce(func.sum(ChatbotUsage.ai_replies), 0),
            func.coalesce(func.sum(ChatbotUsage.credits_used), 0),
        ).where(ChatbotUsage.user_id == uid, ChatbotUsage.month == month)
    ).one()
    conv_total = int(conversations_total or 0)
    lead_conv_rate = round((leads_total / conv_total) * 100, 1) if conv_total > 0 else 0.0
    return {
        "bots_total": bots_total,
        "bots_active": bots_active,
        "sources_total": sources_total,
        "channels_total": 0,
        "conversations_total": conv_total,
        "conversations_today": conversations_today,
        "leads_total": leads_total,
        "leads_won": leads_won,
        "lead_conversion_rate": lead_conv_rate,
        "ai_replies_month": int(usage_row[0] or 0),
        "credits_used_month": int(usage_row[1] or 0),
        "month": month,
    }


def list_usage_db(db: Session, user_id: int, *, month: str | None = None) -> list[dict[str, Any]]:
    uid = int(user_id)
    q = select(ChatbotUsage).where(ChatbotUsage.user_id == uid)
    if month:
        q = q.where(ChatbotUsage.month == str(month).strip()[:7])
    rows = db.execute(q.order_by(ChatbotUsage.month.desc(), ChatbotUsage.bot_id.asc())).scalars().all()
    return [
        {
            "user_id": r.user_id,
            "bot_id": r.bot_id,
            "month": r.month,
            "ai_replies": r.ai_replies,
            "credits_used": r.credits_used,
            "updated_at": _iso(r.updated_at),
        }
        for r in rows
    ]


def create_knowledge_source_db(
    db: Session,
    user_id: int,
    bot_id: int,
    *,
    source_type: str,
    title: str,
    url: str = "",
    content: str = "",
    status: str = "active",
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    st = str(source_type or "").strip().lower()
    legacy_map = {"manual": "faq", "url": "website", "file": "business"}
    st = legacy_map.get(st, st)
    if st not in SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_type không hợp lệ.")
    title_s = str(title or "").strip()
    if not title_s:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title không được để trống.")
    stat = str(status or "ready").strip().lower()
    if stat not in SOURCE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status không hợp lệ.")
    row = ChatbotKnowledgeSource(
        bot_id=int(bot_id),
        user_id=int(user_id),
        source_type=st,
        title=title_s[:160],
        url=str(url or "").strip()[:2000] or None,
        content=str(content or "").strip() or None,
        status=stat,
        crawl_error=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_id": row.id,
        "bot_id": row.bot_id,
        "source_type": row.source_type,
        "type": row.source_type,
        "title": row.title,
        "url": row.url or "",
        "content": row.content or "",
        "status": row.status,
        "error_message": getattr(row, "crawl_error", None) or "",
        "created_at": _iso(row.created_at),
        "updated_at": _iso(getattr(row, "updated_at", None) or row.created_at),
    }


def list_knowledge_sources_db(db: Session, user_id: int, bot_id: int | None = None) -> list[dict[str, Any]]:
    q = select(ChatbotKnowledgeSource).where(ChatbotKnowledgeSource.user_id == int(user_id))
    if bot_id is not None:
        q = q.where(ChatbotKnowledgeSource.bot_id == int(bot_id))
    rows = db.execute(q.order_by(ChatbotKnowledgeSource.created_at.desc())).scalars().all()
    return [
        {
            "id": r.id,
            "source_id": r.id,
            "bot_id": r.bot_id,
            "source_type": r.source_type,
            "type": r.source_type,
            "title": r.title,
            "url": r.url or "",
            "content": (r.content or "")[:500],
            "content_preview": (r.content or "")[:280],
            "status": r.status,
            "error_message": getattr(r, "crawl_error", None) or "",
            "created_at": _iso(r.created_at),
            "updated_at": _iso(getattr(r, "updated_at", None) or r.created_at),
        }
        for r in rows
    ]


def delete_knowledge_source_db(db: Session, user_id: int, source_id: int) -> None:
    row = db.execute(
        select(ChatbotKnowledgeSource).where(
            ChatbotKnowledgeSource.id == int(source_id),
            ChatbotKnowledgeSource.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nguồn dữ liệu.")
    db.delete(row)
    db.commit()


def list_conversations_db(db: Session, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ChatbotConversation)
        .where(ChatbotConversation.user_id == int(user_id))
        .order_by(ChatbotConversation.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for c in rows:
        last_msg = db.execute(
            select(ChatbotMessage)
            .where(ChatbotMessage.conversation_id == c.id)
            .order_by(ChatbotMessage.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        out.append(
            {
                "conversation_id": c.id,
                "bot_id": c.bot_id,
                "session_id": c.session_id,
                "visitor": c.visitor_name or "Khách",
                "visitor_name": c.visitor_name or "",
                "visitor_phone": c.visitor_phone or "",
                "preview": (last_msg.message[:120] if last_msg else ""),
                "status": c.status,
                "created_at": _iso(c.created_at),
            }
        )
    return out
