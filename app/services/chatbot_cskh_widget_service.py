"""Chatbot CSKH — public website widget (message, lead, config)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import (
    ChatbotBot,
    ChatbotConversation,
    ChatbotLead,
    ChatbotMessage,
)
from app.models.user import User
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.chatbot_cskh_credits import (
    build_usage_snapshot,
    monthly_replies_used,
    record_cskh_ai_reply,
)
from app.services.chatbot_cskh_entitlement import (
    CREDIT_EXHAUSTED_MESSAGE,
    NO_DATA_REPLY,
    build_embed_code,
    default_greeting,
    monthly_reply_limit_for_plan,
)
from app.services.chatbot_cskh_ai_service import generate_ai_reply
from app.services.chatbot_cskh_inbox_service import mark_conversation_needs_staff, upsert_detected_lead
from app.services.chatbot_cskh_logging import log_widget_error, log_widget_message
from app.services.chatbot_cskh_security import (
    PublicRequestContext,
    check_public_rate_limit,
    sanitize_public_payload,
    validate_request_origin,
)
SITE_BASE = (os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")
AVATAR_URL = f"{SITE_BASE}/static/chatbot/cskh-launcher.png?v=1"

_BLOCKED_MESSAGES = {
    "plan_required": "Chatbot tạm ngưng — chủ website cần nâng cấp gói SEOAuto.",
    "bot_inactive": "Chatbot đang tạm dừng. Vui lòng liên hệ trực tiếp qua website.",
    "bot_paused": "Chatbot đang bảo trì. Bạn có thể gọi hotline trên website.",
    "limit_exceeded": "Đã đạt giới hạn lượt AI trả lời tháng này. Vui lòng liên hệ trực tiếp.",
    "credit_exhausted": CREDIT_EXHAUSTED_MESSAGE,
    "not_found": "Chatbot không khả dụng.",
    "rate_limited": "Bạn gửi tin nhắn quá nhanh. Vui lòng đợi vài giây rồi thử lại.",
    "origin_denied": "Chatbot không khả dụng trên website này.",
    "invalid_bot": "Chatbot không hợp lệ.",
}


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_bot_row(db: Session, bot_id: int) -> ChatbotBot | None:
    return db.execute(select(ChatbotBot).where(ChatbotBot.id == int(bot_id))).scalar_one_or_none()


def _monthly_replies_used(db: Session, user_id: int, bot_id: int | None = None) -> int:
    return monthly_replies_used(db, user_id)


def _increment_usage(db: Session, user_id: int, bot_id: int, *, replies: int = 1, credits: int = 0) -> None:
    plan_slug = resolve_cau_ai_plan_slug(db, db.get(User, user_id))
    for _ in range(max(1, int(replies))):
        record_cskh_ai_reply(db, user_id, bot_id, plan_slug)


def evaluate_public_bot(
    db: Session,
    bot_id: int,
    *,
    ctx: PublicRequestContext | None = None,
    page_url: str = "",
) -> dict[str, Any]:
    bot = _get_bot_row(db, bot_id)
    if bot is None:
        return {"allowed": False, "code": "not_found", "message": _BLOCKED_MESSAGES["not_found"]}

    if ctx is not None:
        ok_origin, origin_msg = validate_request_origin(
            bot, origin=ctx.origin, referer=ctx.referer, page_url=page_url
        )
        if not ok_origin:
            log_widget_error(bot_id=bot.id, code="origin_denied", client_ip=ctx.client_ip, detail=origin_msg)
            return {"allowed": False, "code": "origin_denied", "message": origin_msg or _BLOCKED_MESSAGES["origin_denied"]}

    owner_plan = resolve_cau_ai_plan_slug(db, db.get(User, bot.user_id))
    if not owner_plan:
        return {"allowed": False, "code": "plan_required", "message": _BLOCKED_MESSAGES["plan_required"]}

    status = str(bot.status or "").lower()
    if status != "active":
        code = "bot_paused" if status == "paused" else "bot_inactive"
        return {"allowed": False, "code": code, "message": _BLOCKED_MESSAGES.get(code, _BLOCKED_MESSAGES["bot_inactive"])}

    used = _monthly_replies_used(db, bot.user_id)
    usage = build_usage_snapshot(db, bot.user_id, owner_plan)
    if not usage.get("allowed"):
        return {
            "allowed": False,
            "code": "limit_exceeded",
            "message": _BLOCKED_MESSAGES["limit_exceeded"],
            "usage": {
                "used": usage.get("ai_replies_used", used),
                "limit": usage.get("effective_limit", monthly_reply_limit_for_plan(owner_plan)),
                "remaining": usage.get("remaining", 0),
            },
        }

    greeting = (bot.greeting or "").strip() or default_greeting(
        bot.bot_name, bot.business_name or "", bot.consultation_tone or "friendly"
    )
    return {
        "allowed": True,
        "code": "ok",
        "bot_id": bot.id,
        "bot_name": bot.bot_name,
        "business_name": bot.business_name or "",
        "hotline": bot.hotline or "",
        "greeting": greeting,
        "avatar_url": AVATAR_URL,
    }


def _bot_public_dict(bot: ChatbotBot) -> dict[str, Any]:
    greeting = (bot.greeting or "").strip() or default_greeting(
        bot.bot_name, bot.business_name or "", bot.consultation_tone or "friendly"
    )
    return {
        "bot_id": bot.id,
        "bot_name": bot.bot_name,
        "website_url": bot.website_url or "",
        "business_name": bot.business_name or "",
        "industry": bot.industry or "",
        "hotline": bot.hotline or "",
        "main_services": bot.main_services or "",
        "consultation_tone": bot.consultation_tone or "friendly",
        "greeting": greeting,
        "status": bot.status,
        "embed_code": build_embed_code(bot.id, base_url=SITE_BASE),
    }


def enrich_bot_dict(bot_dict: dict[str, Any]) -> dict[str, Any]:
    bot_dict["embed_code"] = build_embed_code(int(bot_dict["bot_id"]), base_url=SITE_BASE)
    if not bot_dict.get("greeting"):
        bot_dict["greeting"] = default_greeting(
            str(bot_dict.get("bot_name") or ""),
            str(bot_dict.get("business_name") or ""),
            str(bot_dict.get("consultation_tone") or "friendly"),
        )
    return bot_dict


def _normalize_session_id(session_id: str | None) -> str:
    s = str(session_id or "").strip()
    if len(s) >= 8 and len(s) <= 64:
        return s
    return uuid.uuid4().hex


def _get_or_create_conversation(db: Session, bot: ChatbotBot, session_id: str) -> ChatbotConversation:
    row = db.execute(
        select(ChatbotConversation).where(
            ChatbotConversation.bot_id == bot.id,
            ChatbotConversation.session_id == session_id,
        )
    ).scalar_one_or_none()
    if row:
        return row
    row = ChatbotConversation(
        bot_id=bot.id,
        user_id=bot.user_id,
        session_id=session_id,
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def process_public_message(
    db: Session,
    *,
    bot_id: int,
    message: str,
    session_id: str | None,
    page_url: str = "",
    ctx: PublicRequestContext | None = None,
) -> dict[str, Any]:
    if ctx is not None:
        allowed, rate_msg = check_public_rate_limit(
            endpoint="message", bot_id=bot_id, ctx=ctx, session_id=session_id
        )
        if not allowed:
            log_widget_error(bot_id=bot_id, code="rate_limited", client_ip=ctx.client_ip, detail=rate_msg)
            return sanitize_public_payload({
                "ok": True,
                "blocked": True,
                "code": "rate_limited",
                "message": rate_msg or _BLOCKED_MESSAGES["rate_limited"],
                "reply": rate_msg or _BLOCKED_MESSAGES["rate_limited"],
            })

    state = evaluate_public_bot(db, bot_id, ctx=ctx, page_url=page_url)
    if not state.get("allowed"):
        return sanitize_public_payload({
            "ok": True,
            "blocked": True,
            "code": state.get("code"),
            "message": state.get("message"),
            "reply": state.get("message"),
            "show_lead_form": state.get("code") in ("credit_exhausted", "limit_exceeded"),
        })

    bot = _get_bot_row(db, bot_id)
    if bot is None:
        return sanitize_public_payload({
            "ok": True,
            "blocked": True,
            "message": _BLOCKED_MESSAGES["not_found"],
            "reply": _BLOCKED_MESSAGES["not_found"],
        })

    sid = _normalize_session_id(session_id)
    conv = _get_or_create_conversation(db, bot, sid)
    user_text = str(message or "").strip()[:2000]
    if not user_text:
        return sanitize_public_payload({
            "ok": False,
            "message": "Tin nhắn trống.",
            "reply": "Vui lòng nhập nội dung tin nhắn.",
        })

    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=bot.user_id,
            role="user",
            message=user_text,
        )
    )
    db.commit()

    upsert_detected_lead(db, bot=bot, conversation=conv, text=user_text, page_url=page_url)

    try:
        ai_result = generate_ai_reply(
            db,
            bot=bot,
            conversation_id=conv.id,
            user_text=user_text,
            greeting_fallback=str(state.get("greeting") or ""),
        )
    except Exception as exc:
        log_widget_error(bot_id=bot.id, code="ai_crash", client_ip=ctx.client_ip if ctx else "", detail=str(exc))
        ai_result = {
            "reply": NO_DATA_REPLY,
            "used_ai": False,
            "show_lead": False,
            "blocked_code": "ai_error",
            "debug": {"reason": "ai_crash", "lead_form_triggered": False},
        }

    if ai_result.get("blocked_code") == "credit_exhausted":
        reply = str(ai_result.get("reply") or _BLOCKED_MESSAGES["credit_exhausted"])
        db.add(
            ChatbotMessage(
                conversation_id=conv.id,
                user_id=bot.user_id,
                role="assistant",
                message=reply,
            )
        )
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "ok": True,
            "blocked": True,
            "code": "credit_exhausted",
            "session_id": sid,
            "message": reply,
            "reply": reply,
            # Offer CTA only — widget never auto-opens form.
            "show_lead_form": True,
            "lead_offer_only": True,
        }

    reply = str(ai_result.get("reply") or NO_DATA_REPLY)
    show_lead = bool(ai_result.get("show_lead"))
    debug = ai_result.get("debug") if isinstance(ai_result.get("debug"), dict) else {}
    if show_lead:
        mark_conversation_needs_staff(db, conv)

    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=bot.user_id,
            role="assistant",
            message=reply,
        )
    )
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    if ai_result.get("used_ai"):
        _increment_usage(db, bot.user_id, bot.id, replies=1)

    payload = sanitize_public_payload({
        "ok": True,
        "blocked": False,
        "session_id": sid,
        "reply": reply,
        # Widget shows a CTA button; form opens only when visitor clicks.
        "show_lead_form": show_lead,
        "lead_offer_only": True,
        "detected_intent": debug.get("detected_intent") or "none",
        "bot_name": bot.bot_name,
        "avatar_url": AVATAR_URL,
        "ai_used": bool(ai_result.get("used_ai")),
    })
    log_widget_message(
        bot_id=bot.id,
        session_id=sid,
        status_code="ok",
        client_ip=ctx.client_ip if ctx else "",
        detail=(
            f"ai_used={payload.get('ai_used')} intent={debug.get('detected_intent') or 'none'} "
            f"lead={show_lead} conf={debug.get('answer_confidence')} reason={debug.get('reason')}"
        ),
    )
    return payload


def get_public_config(
    db: Session,
    bot_id: int,
    *,
    ctx: PublicRequestContext | None = None,
    page_url: str = "",
) -> dict[str, Any]:
    if ctx is not None:
        allowed, rate_msg = check_public_rate_limit(endpoint="config", bot_id=bot_id, ctx=ctx)
        if not allowed:
            log_widget_error(bot_id=bot_id, code="rate_limited", client_ip=ctx.client_ip, detail=rate_msg)
            return sanitize_public_payload({
                "ok": True,
                "blocked": True,
                "code": "rate_limited",
                "message": rate_msg,
            })

    state = evaluate_public_bot(db, bot_id, ctx=ctx, page_url=page_url)
    if not state.get("allowed"):
        return sanitize_public_payload({
            "ok": True,
            "blocked": True,
            "code": state.get("code"),
            "message": state.get("message"),
            "bot_name": state.get("bot_name") or "Chatbot",
            "avatar_url": AVATAR_URL,
        })
    return sanitize_public_payload({
        "ok": True,
        "blocked": False,
        "bot_id": state["bot_id"],
        "bot_name": state["bot_name"],
        "business_name": state.get("business_name") or "",
        "greeting": state["greeting"],
        "hotline": state.get("hotline") or "",
        "avatar_url": state["avatar_url"],
    })


def submit_public_lead(
    db: Session,
    *,
    bot_id: int,
    session_id: str | None,
    name: str,
    phone: str,
    need: str = "",
    page_url: str = "",
    ctx: PublicRequestContext | None = None,
) -> dict[str, Any]:
    if ctx is not None:
        allowed, rate_msg = check_public_rate_limit(
            endpoint="lead", bot_id=bot_id, ctx=ctx, session_id=session_id
        )
        if not allowed:
            log_widget_error(bot_id=bot_id, code="rate_limited", client_ip=ctx.client_ip, detail=rate_msg)
            return sanitize_public_payload({"ok": False, "code": "rate_limited", "message": rate_msg})

    state = evaluate_public_bot(db, bot_id, ctx=ctx, page_url=page_url)
    bot = _get_bot_row(db, bot_id)
    if bot is None:
        return {"ok": False, "message": _BLOCKED_MESSAGES["not_found"]}

    sid = _normalize_session_id(session_id)
    conv = _get_or_create_conversation(db, bot, sid)
    lead = ChatbotLead(
        bot_id=bot.id,
        conversation_id=conv.id,
        user_id=bot.user_id,
        name=str(name or "").strip()[:120] or None,
        phone=str(phone or "").strip()[:32] or None,
        need=str(need or "").strip()[:2000] or None,
        page_url=str(page_url or "").strip()[:2000] or None,
        status="new",
    )
    db.add(lead)
    if name:
        conv.visitor_name = str(name).strip()[:120]
    if phone:
        conv.visitor_phone = str(phone).strip()[:32]
    mark_conversation_needs_staff(db, conv)
    db.commit()

    thank_you = "Cảm ơn bạn! Chúng tôi đã ghi nhận và sẽ liên hệ sớm."
    if not state.get("allowed"):
        thank_you = "Cảm ơn bạn! Thông tin đã được ghi nhận."

    return sanitize_public_payload({"ok": True, "message": thank_you, "session_id": sid})
