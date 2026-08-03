"""Chatbot CSKH — knowledge map API (/api/chatbot/kb)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.chatbot_cskh_entitlement import assert_chatbot_cskh_manage
from app.services.chatbot_kb_service import (
    create_kb_node,
    delete_kb_node,
    get_kb_for_bot,
    import_kb_from_sources,
    import_kb_text,
    import_kb_xlsx,
    list_import_sources,
    toggle_kb_node,
    update_kb_node,
)
from app.services.chatbot_cskh_ai_service import preview_kb_reply

router = APIRouter(tags=["chatbot-cskh-kb"])


class KbNodeCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)
    node_type: str = Field(default="node", max_length=32)
    parent_id: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=1000)
    is_active: bool = Field(default=True)
    target_node_id: int | None = Field(default=None, ge=1)
    relation_type: str = Field(default="child", max_length=32)


class KbNodeUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=100_000)
    node_type: str | None = Field(default=None, max_length=32)
    parent_id: int | None = Field(default=None, ge=1)
    clear_parent: bool = Field(default=False)
    tags: list[str] | None = Field(default=None)
    priority: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = Field(default=None)


class KbImportSourcesBody(BaseModel):
    source_ids: list[int] = Field(default_factory=list)
    parent_id: int | None = Field(default=None, ge=1)


class KbImportBody(BaseModel):
    bot_id: int = Field(..., ge=1)
    source_ids: list[int] = Field(default_factory=list)
    parent_id: int | None = Field(default=None, ge=1)


class KbImportTextBody(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = Field(..., min_length=2, max_length=500_000)
    tags: list[str] = Field(default_factory=list)
    format: str = Field(default="plain", max_length=16)
    parent_id: int | None = Field(default=None, ge=1)
    filename: str = Field(default="", max_length=255)
    on_duplicate: str = Field(default="update", max_length=16)


class KbImportXlsxBody(BaseModel):
    filename: str = Field(default="import.xlsx", max_length=255)
    content_base64: str = Field(..., min_length=8)
    tags: list[str] = Field(default_factory=list)
    parent_id: int | None = Field(default=None, ge=1)
    on_duplicate: str = Field(default="update", max_length=16)


class KbPreviewBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.get("/kb/{bot_id}")
def kb_get(
    bot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    return _ok(get_kb_for_bot(db, user.id, bot_id))


@router.post("/kb/{bot_id}/nodes")
def kb_create_node(
    bot_id: int,
    body: KbNodeCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = create_kb_node(
        db,
        user.id,
        bot_id,
        title=body.title,
        content=body.content,
        node_type=body.node_type,
        parent_id=body.parent_id,
        tags=body.tags,
        priority=body.priority,
        is_active=body.is_active,
        target_node_id=body.target_node_id,
        relation_type=body.relation_type,
    )
    return _ok(row)


@router.put("/kb/nodes/{node_id}")
def kb_update_node(
    node_id: int,
    body: KbNodeUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    parent_id_set = body.clear_parent or body.parent_id is not None
    parent_id = None if body.clear_parent else body.parent_id
    row = update_kb_node(
        db,
        user.id,
        node_id,
        title=body.title,
        content=body.content,
        node_type=body.node_type,
        parent_id=parent_id,
        parent_id_set=parent_id_set,
        tags=body.tags,
        priority=body.priority,
        is_active=body.is_active,
    )
    return _ok(row)


@router.delete("/kb/nodes/{node_id}")
def kb_delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    delete_kb_node(db, user.id, node_id)
    return {"ok": True}


@router.post("/kb/nodes/{node_id}/toggle")
def kb_toggle_node(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    row = toggle_kb_node(db, user.id, node_id)
    return _ok(row)


@router.get("/kb/{bot_id}/import/sources")
def kb_import_sources_list(
    bot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    items = list_import_sources(db, user.id, bot_id)
    return _ok({"sources": items, "total": len(items)})


@router.post("/kb/{bot_id}/import/text")
def kb_import_text(
    bot_id: int,
    body: KbImportTextBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    result = import_kb_text(
        db,
        user.id,
        bot_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
        format=body.format,
        parent_id=body.parent_id,
        filename=body.filename,
        on_duplicate=body.on_duplicate,
    )
    payload = get_kb_for_bot(db, user.id, bot_id)
    payload["imported"] = result.get("imported", 0)
    payload["updated"] = result.get("updated", 0)
    payload["skipped"] = result.get("skipped", 0)
    payload["skipped_duplicate"] = result.get("skipped_duplicate", 0)
    payload["skipped_empty"] = result.get("skipped_empty", 0)
    return _ok(payload)


@router.post("/kb/import")
def kb_import_body(
    body: KbImportBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    source_ids = body.source_ids if body.source_ids else None
    result = import_kb_from_sources(
        db, user.id, body.bot_id, source_ids=source_ids, parent_id=body.parent_id
    )
    payload = get_kb_for_bot(db, user.id, body.bot_id)
    payload["imported"] = result.get("imported", 0)
    payload["updated"] = result.get("updated", 0)
    payload["skipped"] = result.get("skipped", 0)
    return _ok(payload)


@router.post("/kb/{bot_id}/import")
def kb_import_sources(
    bot_id: int,
    body: KbImportSourcesBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    source_ids = None
    parent_id = None
    if body and body.source_ids:
        source_ids = body.source_ids
    if body:
        parent_id = body.parent_id
    result = import_kb_from_sources(
        db, user.id, bot_id, source_ids=source_ids, parent_id=parent_id
    )
    payload = get_kb_for_bot(db, user.id, bot_id)
    payload["imported"] = result.get("imported", 0)
    payload["updated"] = result.get("updated", 0)
    payload["skipped"] = result.get("skipped", 0)
    return _ok(payload)


@router.post("/kb/{bot_id}/import/xlsx")
def kb_import_xlsx(
    bot_id: int,
    body: KbImportXlsxBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    import base64
    import binascii

    assert_chatbot_cskh_manage(db, user)
    try:
        raw = base64.b64decode(body.content_base64, validate=False)
    except (binascii.Error, ValueError) as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File Excel không hợp lệ.") from exc
    result = import_kb_xlsx(
        db,
        user.id,
        bot_id,
        raw=raw,
        tags=body.tags,
        parent_id=body.parent_id,
        on_duplicate=body.on_duplicate,
    )
    payload = get_kb_for_bot(db, user.id, bot_id)
    payload["imported"] = result.get("imported", 0)
    payload["updated"] = result.get("updated", 0)
    payload["skipped"] = result.get("skipped", 0)
    payload["skipped_duplicate"] = result.get("skipped_duplicate", 0)
    payload["skipped_empty"] = result.get("skipped_empty", 0)
    return _ok(payload)


@router.post("/kb/{bot_id}/preview")
def kb_preview(
    bot_id: int,
    body: KbPreviewBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    assert_chatbot_cskh_manage(db, user)
    result = preview_kb_reply(db, user_id=user.id, bot_id=bot_id, user_text=body.message)
    return _ok(result)
