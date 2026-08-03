"""Chatbot CSKH — API UI (legacy /api/chatbot-cskh) + delegates platform DB."""

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
    create_knowledge_source_db,
    delete_bot_db,
    delete_knowledge_source_db,
    get_overview_db,
    list_bots_db,
    list_conversations_db,
    list_knowledge_sources_db,
    update_bot_db,
)
from app.services.chatbot_cskh_entitlement import assert_bot_limit, assert_chatbot_cskh_manage, build_chatbot_cskh_access
from app.services.chatbot_cskh_store import (
    create_channel,
    delete_channel,
    get_settings,
    list_channels,
    update_settings,
)

router = APIRouter(tags=["chatbot-cskh"])


class BotCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    website_url: str = Field(default="", max_length=2000)
    business_name: str = Field(default="", max_length=160)
    industry: str = Field(default="", max_length=120)
    hotline: str = Field(default="", max_length=64)
    main_services: str = Field(default="", max_length=4000)
    consultation_tone: str = Field(default="friendly", max_length=64)
    greeting: str = Field(default="", max_length=500)


class BotUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: str | None = None
    website_url: str | None = None
    business_name: str | None = None
    industry: str | None = None
    hotline: str | None = None
    main_services: str | None = None
    consultation_tone: str | None = None
    greeting: str | None = None


class SourceCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    type: str = Field(..., min_length=1, max_length=32)
    content: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=2000)
    bot_id: int | None = None


class ChannelCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., min_length=1, max_length=32)
    bot_id: str | None = None


class SettingsUpdateBody(BaseModel):
    model: str | None = Field(default=None, max_length=64)
    temperature: float | None = None
    system_prompt: str | None = Field(default=None, max_length=8000)
    greeting: str | None = Field(default=None, max_length=500)
    fallback_reply: str | None = Field(default=None, max_length=1000)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _first_bot_id(db: Session, user_id: int) -> int:
    bots = list_bots_db(db, user_id)
    if not bots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tạo chatbot trước khi thêm nguồn dữ liệu.",
        )
    return int(bots[0]["bot_id"])


@router.get("/access")
def chatbot_cskh_access(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    payload = build_chatbot_cskh_access(db, user)
    if user and payload.get("allowed"):
        payload["bots_count"] = count_user_bots(db, user.id)
    return {"ok": True, **payload}


@router.get("/overview")
def chatbot_cskh_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    overview = get_overview_db(db, user.id)
    overview["channels_total"] = len(list_channels(user.id))
    return _ok(overview)


@router.get("/bots")
def chatbot_cskh_list_bots(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_bots_db(db, user.id)
    # UI legacy fields
    for b in items:
        b["name"] = b.get("bot_name", "")
        b["description"] = ""
        b["id"] = str(b.get("bot_id"))
    return _ok(items)


@router.post("/bots")
def chatbot_cskh_create_bot(
    body: BotCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    current = count_user_bots(db, user.id)
    assert_bot_limit(db, user, current)
    row = create_bot_db(
        db,
        user.id,
        bot_name=body.name,
        website_url=body.website_url,
        business_name=body.business_name,
        industry=body.industry,
        hotline=body.hotline,
        main_services=body.main_services,
        consultation_tone=body.consultation_tone,
        greeting=body.greeting,
    )
    row["name"] = row.get("bot_name", "")
    row["description"] = body.description
    row["id"] = str(row.get("bot_id"))
    return _ok(row)


@router.patch("/bots/{bot_id}")
def chatbot_cskh_update_bot(
    bot_id: str,
    body: BotUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    patch = body.model_dump(exclude_unset=True)
    row = update_bot_db(db, user.id, int(bot_id), patch)
    row["name"] = row.get("bot_name", "")
    row["id"] = str(row.get("bot_id"))
    return _ok(row)


@router.delete("/bots/{bot_id}")
def chatbot_cskh_delete_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_bot_db(db, user.id, int(bot_id))
    return {"ok": True}


@router.get("/sources")
def chatbot_cskh_list_sources(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_knowledge_sources_db(db, user.id)
    for s in items:
        s["type"] = s.get("source_type")
    return _ok(items)


@router.post("/sources")
def chatbot_cskh_create_source(
    body: SourceCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    bot_id = body.bot_id or _first_bot_id(db, user.id)
    row = create_knowledge_source_db(
        db,
        user.id,
        bot_id,
        source_type=body.type,
        title=body.title,
        content=body.content,
        url=body.url,
    )
    row["type"] = row.get("source_type")
    return _ok(row)


@router.delete("/sources/{source_id}")
def chatbot_cskh_delete_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_knowledge_source_db(db, user.id, int(source_id))
    return {"ok": True}


@router.get("/channels")
def chatbot_cskh_list_channels(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_channels(user.id))


@router.post("/channels")
def chatbot_cskh_create_channel(
    body: ChannelCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(create_channel(user.id, name=body.name, channel_type=body.type, bot_id=body.bot_id))


@router.delete("/channels/{channel_id}")
def chatbot_cskh_delete_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_channel(user.id, channel_id)
    return {"ok": True}


@router.get("/conversations")
def chatbot_cskh_list_conversations(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(list_conversations_db(db, user.id, limit=limit))


@router.get("/settings")
def chatbot_cskh_get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(get_settings(user.id))


@router.put("/settings")
def chatbot_cskh_update_settings(
    body: SettingsUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    patch = body.model_dump(exclude_unset=True)
    return _ok(update_settings(user.id, patch))
