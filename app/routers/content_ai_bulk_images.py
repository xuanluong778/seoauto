"""Bulk semantic image fetch for Content AI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db import get_db
from app.models.user import User
from app.services.content_ai_content_images import (
    bulk_fetch_images_for_projects,
    bulk_image_status_for_projects,
    clear_project_images,
)
from app.services.content_ai_entitlement import assert_content_ai_feature
from app.services.content_ai_image_finder import image_providers_status
from app.services.trial_access import require_active_trial
from sqlalchemy.orm import Session

router = APIRouter(tags=["content-ai-bulk-images"])


class BulkFetchImagesRequest(BaseModel):
    project_ids: list[str] = Field(default_factory=list)
    max_inline: int = 4
    force: bool = False
    only_without_images: bool = True


@router.get("/content-ai/bulk-images/providers")
def api_bulk_image_providers(
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    return JSONResponse({"ok": True, "providers": image_providers_status()})


class BulkClearImagesRequest(BaseModel):
    project_id: str


class BulkFetchOneRequest(BaseModel):
    project_id: str
    max_inline: int = 4
    force: bool = False


@router.get("/content-ai/bulk-images/status")
def api_bulk_image_status(
    project_ids: str = Query("", description="Comma-separated project IDs"),
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    ids = [x.strip() for x in str(project_ids or "").split(",") if x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Thiếu project_ids.")
    return JSONResponse(bulk_image_status_for_projects(ids, user_id=current_user.id))


@router.post("/content-ai/bulk-images/fetch-one")
def api_bulk_fetch_one(
    payload: BulkFetchOneRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    from app.services.content_ai_content_images import auto_insert_images_to_project

    assert_content_ai_feature(db, current_user, "image_generate", quantity=1)
    pid = str(payload.project_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="Thiếu project_id.")
    try:
        out = auto_insert_images_to_project(
            pid,
            user_id=current_user.id,
            max_inline=max(0, min(int(payload.max_inline or 4), 6)),
            update_featured=True,
            force=bool(payload.force),
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    st = bulk_image_status_for_projects([pid], user_id=current_user.id)
    item = (st.get("items") or [{}])[0]
    db.commit()
    return JSONResponse({**out, "image_status": item})


@router.post("/content-ai/bulk-images/clear")
def api_bulk_clear_images(
    payload: BulkClearImagesRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    pid = str(payload.project_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="Thiếu project_id.")
    try:
        out = clear_project_images(pid, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(out)


@router.post("/content-ai/bulk-images/fetch-batch")
def api_bulk_fetch_images(
    payload: BulkFetchImagesRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_content_ai_feature(db, current_user, "image_generate", quantity=max(1, len(payload.project_ids or [])))
    ids = [str(x).strip() for x in (payload.project_ids or []) if str(x).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Danh sách project_ids trống.")
    try:
        out = bulk_fetch_images_for_projects(
            ids,
            user_id=current_user.id,
            max_inline=max(0, min(int(payload.max_inline or 4), 6)),
            force=bool(payload.force),
            only_without_images=bool(payload.only_without_images),
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return JSONResponse(out)
