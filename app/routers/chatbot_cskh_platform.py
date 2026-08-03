"""Chatbot CSKH platform API — /api/chatbot/bots, overview, usage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user, get_optional_current_user
from app.services.chatbot_cskh_db_service import (
    count_user_bots,
    create_bot_db,
    delete_bot_db,
    get_bot_db,
    get_overview_db,
    list_bots_db,
    list_usage_db,
    update_bot_db,
)
from app.services.chatbot_cskh_entitlement import (
    assert_bot_limit,
    assert_chatbot_cskh_manage,
    bot_limit_for_plan,
    build_chatbot_cskh_access,
)
from app.services.chatbot_cskh_credits import build_usage_snapshot

router = APIRouter(tags=["chatbot-cskh-platform"])


class BotCreateBody(BaseModel):
    bot_name: str = Field(..., min_length=1, max_length=120)
    website_url: str = Field(default="", max_length=2000)
    business_name: str = Field(default="", max_length=160)
    industry: str = Field(default="", max_length=120)
    hotline: str = Field(default="", max_length=64)
    main_services: str = Field(default="", max_length=4000)
    consultation_tone: str = Field(default="friendly", max_length=64)
    greeting: str = Field(default="", max_length=500)
    status: str = Field(default="draft", max_length=32)


class BotUpdateBody(BaseModel):
    bot_name: str | None = Field(default=None, max_length=120)
    website_url: str | None = Field(default=None, max_length=2000)
    business_name: str | None = Field(default=None, max_length=160)
    industry: str | None = Field(default=None, max_length=120)
    hotline: str | None = Field(default=None, max_length=64)
    main_services: str | None = Field(default=None, max_length=4000)
    consultation_tone: str | None = Field(default=None, max_length=64)
    greeting: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=32)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _parse_bot_id(bot_id: str) -> int:
    try:
        return int(str(bot_id).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bot_id không hợp lệ.")


@router.get("/access")
def platform_access(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    payload = build_chatbot_cskh_access(db, user)
    if user and payload.get("allowed"):
        payload["bots_count"] = count_user_bots(db, user.id)
    return {"ok": True, **payload}


@router.get("/overview")
def platform_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    plan_slug = assert_chatbot_cskh_manage(db, user)
    data = get_overview_db(db, user.id)
    usage = build_usage_snapshot(db, user.id, plan_slug)
    data["bot_limit"] = bot_limit_for_plan(plan_slug)
    data["bots_count"] = data.get("bots_total", 0)
    data["monthly_reply_limit"] = usage["plan_monthly_limit"]
    data["monthly_replies_used"] = usage["ai_replies_used"]
    data["chatbot_bonus_credits"] = usage["bonus_credits"]
    data["effective_reply_limit"] = usage["effective_limit"]
    data["replies_remaining"] = usage["remaining"]
    from app.services.chatbot_cskh_facebook_service import list_facebook_pages

    data["channels_total"] = len(list_facebook_pages(db, user.id)) + int(data.get("bots_active") or 0)
    return _ok(data)


@router.get("/usage")
def platform_usage(
    month: str | None = Query(default=None, max_length=7),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_usage_db(db, user.id, month=month))


@router.get("/bots")
def platform_list_bots(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_bots_db(db, user.id))


@router.post("/bots")
def platform_create_bot(
    body: BotCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    current = count_user_bots(db, user.id)
    assert_bot_limit(db, user, current)
    row = create_bot_db(
        db,
        user.id,
        bot_name=body.bot_name,
        website_url=body.website_url,
        business_name=body.business_name,
        industry=body.industry,
        hotline=body.hotline,
        main_services=body.main_services,
        consultation_tone=body.consultation_tone,
        greeting=body.greeting,
        status=body.status,
    )
    return _ok(row)


@router.get("/bots/{bot_id}")
def platform_get_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(get_bot_db(db, user.id, _parse_bot_id(bot_id)))


@router.put("/bots/{bot_id}")
def platform_update_bot(
    bot_id: str,
    body: BotUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    patch = body.model_dump(exclude_unset=True)
    return _ok(update_bot_db(db, user.id, _parse_bot_id(bot_id), patch))


@router.delete("/bots/{bot_id}")
def platform_delete_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_bot_db(db, user.id, _parse_bot_id(bot_id))
    return {"ok": True}
