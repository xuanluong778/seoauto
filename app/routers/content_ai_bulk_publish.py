"""Content AI bulk publish & schedule API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.trial_access import require_active_trial
from app.services.content_ai_publish_schedule_service import (
    build_bulk_publish_board,
    cancel_schedules,
    create_schedule,
    create_schedule_batch,
    list_schedules,
    publish_now_batch,
    publish_now_one,
    retry_failed_schedule,
    update_schedule_time,
)
from app.services.content_ai_bulk_publish_readiness import bulk_publish_readiness
from app.services.rbac import normalize_role
from app.services.user_scope import is_admin_role

router = APIRouter(tags=["content-ai-bulk-publish"])


class WpSiteCredentials(BaseModel):
    wp_site_id: str | None = None
    wp_url: str | None = None
    username: str | None = None
    app_password: str | None = None


class ScheduleOneRequest(WpSiteCredentials):
    project_id: str
    scheduled_at: str
    wp_category_id: int | None = None
    bulk_job_id: str | None = None
    seo_plugin: str | None = "auto"


class ScheduleBatchItem(BaseModel):
    project_id: str
    scheduled_at: str | None = None
    wp_category_id: int | None = None
    wp_site_id: str | None = None
    bulk_job_id: str | None = None


class ScheduleBatchRequest(WpSiteCredentials):
    items: list[ScheduleBatchItem] = Field(default_factory=list)
    scheduled_at: str | None = None
    bulk_job_id: str | None = None


class PublishOneRequest(WpSiteCredentials):
    project_id: str
    wp_category_id: int | None = None
    bulk_job_id: str | None = None


class PublishBatchRequest(WpSiteCredentials):
    project_ids: list[str] = Field(default_factory=list)
    bulk_job_id: str | None = None


class CancelScheduleRequest(BaseModel):
    schedule_ids: list[int] | None = None
    project_ids: list[str] | None = None


class UpdateScheduleRequest(BaseModel):
    schedule_id: int
    scheduled_at: str


class ReadinessBatchRequest(BaseModel):
    project_ids: list[str] = Field(default_factory=list)
    require_image: bool = False
    require_category: bool = False
    wp_category_id: int | None = None


class BoardRequest(BaseModel):
    project_ids: list[str] = Field(default_factory=list)
    bulk_job_id: str | None = None
    status: str | None = None
    q: str | None = None
    website: str | None = None
    category_id: str | None = None
    limit: int = 120
    include_sites: bool = True


class RetryScheduleRequest(BaseModel):
    schedule_id: int


@router.post("/content-ai/bulk-publish/board")
def api_publish_board(
    payload: BoardRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    out = build_bulk_publish_board(
        db,
        current_user,
        project_ids=payload.project_ids,
        bulk_job_id=payload.bulk_job_id,
        status=payload.status,
        q=payload.q,
        website=payload.website,
        category_id=payload.category_id,
        limit=payload.limit,
        include_sites=payload.include_sites,
    )
    return JSONResponse(out)


@router.post("/content-ai/bulk-publish/retry")
def api_retry_schedule(
    request: Request,
    payload: RetryScheduleRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    item = retry_failed_schedule(
        db,
        current_user,
        payload.schedule_id,
        request=request,
    )
    return JSONResponse({"ok": True, "item": item})


@router.post("/content-ai/bulk-publish/readiness-batch")
def api_readiness_batch(
    payload: ReadinessBatchRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    ids = [str(x).strip() for x in (payload.project_ids or []) if str(x).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Danh sách project_ids trống.")
    out = bulk_publish_readiness(
        ids,
        user_id=current_user.id,
        require_image=bool(payload.require_image),
        require_category=bool(payload.require_category),
        wp_category_id=payload.wp_category_id,
    )
    return JSONResponse(out)


@router.post("/content-ai/bulk-publish/schedule-one")
def api_schedule_one(
    request: Request,
    payload: ScheduleOneRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    item = create_schedule(
        db,
        current_user,
        project_id=payload.project_id,
        scheduled_at=payload.scheduled_at,
        wp_site_id=payload.wp_site_id,
        wp_url=payload.wp_url,
        username=payload.username,
        app_password=payload.app_password,
        wp_category_id=payload.wp_category_id,
        bulk_job_id=payload.bulk_job_id,
        seo_plugin=str(payload.seo_plugin or "auto"),
    )
    return JSONResponse({"ok": True, "item": item})


@router.post("/content-ai/bulk-publish/schedule-batch")
def api_schedule_batch(
    request: Request,
    payload: ScheduleBatchRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not payload.items:
        raise HTTPException(status_code=400, detail="Danh sách items trống.")
    items = [x.model_dump() for x in payload.items]
    result = create_schedule_batch(
        db,
        current_user,
        items,
        scheduled_at=payload.scheduled_at,
        wp_site_id=payload.wp_site_id,
        wp_url=payload.wp_url,
        username=payload.username,
        app_password=payload.app_password,
        bulk_job_id=payload.bulk_job_id,
    )
    return JSONResponse(result)


@router.post("/content-ai/bulk-publish/publish-now-one")
def api_publish_now_one(
    request: Request,
    payload: PublishOneRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    item = publish_now_one(
        db,
        current_user,
        project_id=payload.project_id,
        wp_site_id=payload.wp_site_id,
        wp_url=payload.wp_url,
        username=payload.username,
        app_password=payload.app_password,
        wp_category_id=payload.wp_category_id,
        bulk_job_id=payload.bulk_job_id,
        request=request,
    )
    return JSONResponse({"ok": True, "item": item})


@router.post("/content-ai/bulk-publish/publish-now-batch")
def api_publish_now_batch(
    request: Request,
    payload: PublishBatchRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not payload.project_ids:
        raise HTTPException(status_code=400, detail="Danh sách project_ids trống.")
    result = publish_now_batch(
        db,
        current_user,
        payload.project_ids,
        wp_site_id=payload.wp_site_id,
        wp_url=payload.wp_url,
        username=payload.username,
        app_password=payload.app_password,
        bulk_job_id=payload.bulk_job_id,
        request=request,
    )
    return JSONResponse(result)


@router.post("/content-ai/bulk-publish/cancel-schedule")
def api_cancel_schedule(
    payload: CancelScheduleRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    result = cancel_schedules(
        db,
        current_user,
        schedule_ids=payload.schedule_ids,
        project_ids=payload.project_ids,
    )
    return JSONResponse(result)


@router.post("/content-ai/bulk-publish/update-schedule")
def api_update_schedule(
    payload: UpdateScheduleRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    item = update_schedule_time(
        db,
        current_user,
        payload.schedule_id,
        payload.scheduled_at,
    )
    return JSONResponse({"ok": True, "item": item})


@router.get("/content-ai/bulk-publish/schedules")
def api_list_schedules(
    bulk_job_id: str | None = Query(None),
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    all_users: bool = Query(False, alias="all"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    admin_all = bool(all_users and is_admin_role(normalize_role(current_user.role)))
    items = list_schedules(
        db,
        current_user,
        bulk_job_id=bulk_job_id,
        project_id=project_id,
        status=status,
        limit=limit,
        admin_all=admin_all,
    )
    return JSONResponse({"ok": True, "items": items, "count": len(items)})
