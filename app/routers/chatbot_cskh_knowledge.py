"""Chatbot CSKH — knowledge API (/api/chatbot/knowledge)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.chatbot_cskh_entitlement import assert_chatbot_cskh_manage
from app.services.chatbot_cskh_knowledge_service import (
    add_knowledge_source,
    crawl_website_knowledge,
    delete_knowledge_source,
    list_knowledge_for_bot,
    update_knowledge_source,
)

router = APIRouter(tags=["chatbot-cskh-knowledge"])


class KnowledgeAddBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    source_type: str = Field(..., min_length=2, max_length=32)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=10, max_length=100_000)


class KnowledgeCrawlBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=160)
    source_id: int | None = Field(default=None, ge=1)


class KnowledgeUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    content: str | None = Field(default=None, max_length=100_000)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.post("/knowledge/add")
def knowledge_add(
    body: KnowledgeAddBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = add_knowledge_source(
        db,
        user.id,
        bot_id=body.bot_id,
        source_type=body.source_type,
        title=body.title,
        content=body.content,
    )
    return _ok(row)


@router.post("/knowledge/crawl")
def knowledge_crawl(
    body: KnowledgeCrawlBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = crawl_website_knowledge(
        db,
        user.id,
        bot_id=body.bot_id,
        url=body.url,
        title=body.title,
        source_id=body.source_id,
    )
    return _ok(row)


@router.get("/knowledge/{bot_id}")
def knowledge_list(
    bot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_knowledge_for_bot(db, user.id, bot_id)
    return _ok(items)


@router.put("/knowledge/{source_id}")
def knowledge_update(
    source_id: int,
    body: KnowledgeUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = update_knowledge_source(
        db,
        user.id,
        source_id,
        title=body.title,
        content=body.content,
    )
    return _ok(row)


@router.delete("/knowledge/{source_id}")
def knowledge_delete(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_knowledge_source(db, user.id, source_id)
    return {"ok": True}
