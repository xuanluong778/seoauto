"""Chatbot CSKH — conversations & leads API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.chatbot_cskh_entitlement import assert_chatbot_cskh_manage
from app.services.chatbot_cskh_inbox_service import (
    get_conversation_detail,
    list_conversations,
    list_leads,
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
