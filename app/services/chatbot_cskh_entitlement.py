"""Entitlement — Chatbot CSKH theo gói SEOAuto."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.rbac import is_admin

from app.services.plan_quota_registry import (
    CHATBOT_BOT_LIMITS,
    PLAN_DISPLAY_NAMES,
    chatbot_monthly_reply_limit,
    plan_feature,
)

PLAN_DISPLAY_NAMES = PLAN_DISPLAY_NAMES  # re-export

FREE_DEMO_MESSAGE = (
    "Gói Free chỉ xem demo. Nâng cấp Basic, Pro, Agency hoặc Business để tạo chatbot và dùng AI trả lời."
)
UPGRADE_MESSAGE = "Nâng cấp gói Basic trở lên để sử dụng Chatbot CSKH."
BOT_LIMIT_MESSAGE = "Đã đạt giới hạn số chatbot theo gói hiện tại. Nâng cấp gói để tạo thêm bot."
REPLY_LIMIT_MESSAGE = (
    "Đã đạt giới hạn lượt AI trả lời tháng này. Nâng cấp gói hoặc liên hệ admin để mua thêm credit chatbot."
)
FEATURE_KEY = "chatbot_cskh"
FACEBOOK_FEATURE_KEY = "chatbot_cskh_facebook"

FACEBOOK_PLAN_SLUGS = frozenset(
    slug
    for slug in CHATBOT_BOT_LIMITS
    if slug == "admin" or plan_feature(slug, "chatbot_facebook", False)
)
FACEBOOK_UPGRADE_MESSAGE = "Kết nối Facebook Fanpage chỉ dành cho gói Pro trở lên (beta)."

BOT_LIMIT_BY_PLAN: dict[str, int] = dict(CHATBOT_BOT_LIMITS)

MONTHLY_REPLY_LIMIT_BY_PLAN: dict[str, int] = {
    slug: (999_999 if slug == "admin" else chatbot_monthly_reply_limit(slug))
    for slug in CHATBOT_BOT_LIMITS
}

CONSULTATION_TONES = frozenset({"friendly", "professional", "enthusiastic", "concise"})

NO_DATA_REPLY = "Hiện tại tôi chưa có đủ thông tin chính xác về nội dung này."

CREDIT_EXHAUSTED_MESSAGE = REPLY_LIMIT_MESSAGE

LLM_UNAVAILABLE_MESSAGE = (
    "Chatbot chưa sẵn sàng trả lời AI. Chủ website cần cấu hình khóa API trong SEOAuto."
)


def monthly_reply_limit_for_plan(plan_slug: str | None) -> int:
    if not plan_slug:
        return 0
    return int(MONTHLY_REPLY_LIMIT_BY_PLAN.get(str(plan_slug).lower(), 0))


def build_embed_code(bot_id: int, *, base_url: str = "https://seoauto.vn") -> str:
    base = (base_url or "https://seoauto.vn").rstrip("/")
    return f'<script src="{base}/chatbot/widget.js?v=4" data-bot-id="{int(bot_id)}"></script>'


def default_greeting(bot_name: str, business_name: str, tone: str) -> str:
    name = (business_name or bot_name or "SEOAuto").strip()
    tone = (tone or "friendly").strip().lower()
    if tone == "professional":
        return f"Xin chào, tôi là trợ lý ảo của {name}. Tôi có thể hỗ trợ thông tin dịch vụ cho bạn."
    if tone == "enthusiastic":
        return f"Chào bạn! {name} rất vui được hỗ trợ — hỏi mình bất cứ điều gì nhé!"
    if tone == "concise":
        return f"Xin chào — {name}. Bạn cần hỗ trợ gì?"
    return f"Xin chào! Mình là chatbot của {name}, rất vui được hỗ trợ bạn."


def bot_limit_for_plan(plan_slug: str | None) -> int:
    if not plan_slug:
        return 0
    return int(BOT_LIMIT_BY_PLAN.get(str(plan_slug).lower(), 0))


def build_chatbot_cskh_access(db: Session, user: User | None) -> dict[str, Any]:
    if user is None:
        return {
            "logged_in": False,
            "allowed": False,
            "can_manage": False,
            "is_demo": True,
            "plan_slug": None,
            "plan_name": None,
            "message": "Đăng nhập để xem Chatbot CSKH.",
            "upgrade_url": "/pricing",
            "feature_key": FEATURE_KEY,
        }

    plan_slug = resolve_cau_ai_plan_slug(db, user)
    can_manage = plan_slug is not None
    bot_limit = bot_limit_for_plan(plan_slug)
    usage = None
    if can_manage:
        from app.services.chatbot_cskh_credits import build_usage_snapshot

        usage = build_usage_snapshot(db, user.id, plan_slug)
    return {
        "logged_in": True,
        "allowed": can_manage,
        "can_manage": can_manage,
        "is_demo": not can_manage,
        "plan_slug": plan_slug,
        "plan_name": PLAN_DISPLAY_NAMES.get(plan_slug or "", None),
        "bot_limit": bot_limit,
        "monthly_reply_limit": usage["plan_monthly_limit"] if usage else 0,
        "monthly_replies_used": usage["ai_replies_used"] if usage else 0,
        "chatbot_bonus_credits": usage["bonus_credits"] if usage else 0,
        "effective_reply_limit": usage["effective_limit"] if usage else 0,
        "replies_remaining": usage["remaining"] if usage else 0,
        "message": FREE_DEMO_MESSAGE if not can_manage else "",
        "upgrade_url": "/pricing",
        "feature_key": FEATURE_KEY,
        "is_admin": is_admin(user),
        "facebook_beta_allowed": facebook_channel_allowed(db, user) if can_manage else False,
    }


def assert_chatbot_cskh_manage(db: Session, user: User) -> str:
    """Raise 403 nếu user không có gói trả phí. Trả về plan_slug khi hợp lệ."""
    plan_slug = resolve_cau_ai_plan_slug(db, user)
    if not plan_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "plan_required",
                "message": FREE_DEMO_MESSAGE,
                "feature_key": FEATURE_KEY,
                "upgrade_url": "/pricing",
            },
        )
    return plan_slug


def assert_bot_limit(db: Session, user: User, current_count: int) -> str:
    """Raise 403 nếu vượt giới hạn bot theo gói."""
    plan_slug = assert_chatbot_cskh_manage(db, user)
    limit = bot_limit_for_plan(plan_slug)
    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "bot_limit_exceeded",
                "message": BOT_LIMIT_MESSAGE,
                "feature_key": FEATURE_KEY,
                "plan_slug": plan_slug,
                "bot_limit": limit,
                "current_count": current_count,
                "upgrade_url": "/pricing",
            },
        )
    return plan_slug


def assert_facebook_channel_allowed(db: Session, user: User) -> str:
    """Pro+ required for Facebook Fanpage beta."""
    plan_slug = resolve_cau_ai_plan_slug(db, user)
    if not plan_slug or plan_slug not in FACEBOOK_PLAN_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "facebook_plan_required",
                "message": FACEBOOK_UPGRADE_MESSAGE,
                "feature_key": FACEBOOK_FEATURE_KEY,
                "upgrade_url": "/pricing",
            },
        )
    return plan_slug


def facebook_channel_allowed(db: Session, user: User | None) -> bool:
    if user is None:
        return False
    plan_slug = resolve_cau_ai_plan_slug(db, user)
    return bool(plan_slug and plan_slug in FACEBOOK_PLAN_SLUGS)
