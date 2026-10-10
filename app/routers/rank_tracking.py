"""Rank Tracking API — projects, keywords, SERP checks via DataForSEO."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.cost_control.runtime import check_user_rate_limit
from app.services.credits import cost_rank_tracking_check, credits_enforced
from app.services.rank_tracking_service import (
    build_summary,
    check_keyword_now,
    check_project_now,
    keyword_dashboard_rows,
)
from app.services.rank_tracking_store import (
    create_keyword,
    create_project,
    get_keyword,
    get_project,
    list_keywords,
    list_projects,
    list_results,
)
from app.services.permissions import PERM_WORKSPACE_READ, PERM_WORKSPACE_WRITE, assert_permission
from app.services.saas_gate import build_job_id, saas_action_gate
from app.services.tenant_org import personal_organization_id
from app.services.trial_access import require_active_trial

router = APIRouter(tags=["rank-tracking"])

_CHECK_RATE_PER_MIN = 20


def _tenant_org_id(user: User) -> int:
    return personal_organization_id(int(user.id))


def _assert_workspace_read(db: Session, user: User, org_id: int) -> None:
    assert_permission(user, PERM_WORKSPACE_READ, db=db, organization_id=org_id)


def _assert_workspace_write(db: Session, user: User, org_id: int) -> None:
    assert_permission(user, PERM_WORKSPACE_WRITE, db=db, organization_id=org_id)


class ProjectCreateBody(BaseModel):
    name: str = Field(default="", max_length=200)
    domain: str = Field(..., min_length=3, max_length=253)
    location_name: str = Field(default="Vietnam", max_length=120)
    language_name: str = Field(default="Vietnamese", max_length=120)
    device: str = Field(default="desktop", max_length=32)


class KeywordCreateBody(BaseModel):
    project_id: str = Field(..., min_length=8, max_length=64)
    keyword: str = Field(..., min_length=1, max_length=200)


class CheckNowBody(BaseModel):
    project_id: str | None = Field(default=None, max_length=64)
    keyword_id: str | None = Field(default=None, max_length=64)
    depth: int = Field(default=100, ge=10, le=100)


@router.get("/projects")
def api_list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_read(db, current_user, org_id)
    return {"items": list_projects(db, current_user.id, organization_id=org_id)}


@router.post("/projects")
def api_create_project(
    body: ProjectCreateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_write(db, current_user, org_id)
    item = create_project(
        db,
        user_id=current_user.id,
        name=body.name or body.domain,
        domain=body.domain,
        location_name=body.location_name,
        language_name=body.language_name,
        device=body.device,
        organization_id=org_id,
    )
    db.commit()
    return {"item": item}


@router.get("/keywords")
def api_list_keywords(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_read(db, current_user, org_id)
    if project_id:
        get_project(db, project_id, current_user.id, organization_id=org_id)
    return {"items": list_keywords(db, current_user.id, project_id=project_id, organization_id=org_id)}


@router.post("/keywords")
def api_create_keyword(
    body: KeywordCreateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_write(db, current_user, org_id)
    item = create_keyword(
        db,
        user_id=current_user.id,
        project_id=body.project_id,
        keyword=body.keyword,
        organization_id=org_id,
    )
    db.commit()
    return {"item": item}


@router.post("/check-now")
def api_check_now(
    body: CheckNowBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    if not body.keyword_id and not body.project_id:
        raise HTTPException(status_code=400, detail="Cần project_id hoặc keyword_id.")

    check_user_rate_limit(
        scope="rank_tracking_check",
        user_id=int(current_user.id),
        limit_per_min=_CHECK_RATE_PER_MIN,
    )

    org_id = _tenant_org_id(current_user)
    _assert_workspace_write(db, current_user, org_id)
    unit_cost = cost_rank_tracking_check(db=db) if credits_enforced() else 0

    if body.keyword_id:
        get_keyword(db, body.keyword_id, current_user.id, organization_id=org_id)
        quota_units = 1
    else:
        get_project(db, body.project_id, current_user.id, organization_id=org_id)
        kws = list_keywords(db, current_user.id, project_id=body.project_id, organization_id=org_id)
        if not kws:
            raise HTTPException(status_code=400, detail="Project chưa có keyword nào.")
        quota_units = len(kws)

    credit_cost = unit_cost * max(1, quota_units)
    job_id = build_job_id(
        "rank_tracking_check",
        current_user.id,
        org_id,
        body.project_id or body.keyword_id,
        uuid.uuid4().hex[:10],
    )
    with saas_action_gate(
        db,
        current_user,
        feature_code="keyword_research",
        credit_cost=credit_cost,
        quota_units=max(1, quota_units),
        job_id=job_id,
        idempotency_key=job_id,
        organization_id=org_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            if body.keyword_id:
                out = check_keyword_now(
                    db,
                    current_user.id,
                    body.keyword_id,
                    organization_id=org_id,
                    depth=body.depth,
                )
                sgate.commit()
                sgate.record_usage(metadata={"mode": "keyword", "units": 1})
                return {"mode": "keyword", **out}
            out = check_project_now(
                db,
                current_user.id,
                body.project_id,
                organization_id=org_id,
                depth=body.depth,
            )
            sgate.commit()
            sgate.record_usage(metadata={"mode": "project", "units": quota_units})
            return {"mode": "project", **out}
        except HTTPException:
            sgate.release(reason="http_error")
            raise
        except Exception:
            sgate.release(reason="check_failed")
            raise


@router.get("/results")
def api_list_results(
    project_id: str | None = Query(default=None),
    keyword_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_read(db, current_user, org_id)
    if project_id:
        get_project(db, project_id, current_user.id, organization_id=org_id)
    return {
        "items": list_results(
            db,
            current_user.id,
            project_id=project_id,
            keyword_id=keyword_id,
            organization_id=org_id,
            limit=limit,
        )
    }


@router.get("/summary")
def api_summary(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _tenant_org_id(current_user)
    _assert_workspace_read(db, current_user, org_id)
    if project_id:
        get_project(db, project_id, current_user.id, organization_id=org_id)
    summary = build_summary(db, current_user.id, project_id=project_id, organization_id=org_id)
    dashboard: list[dict[str, Any]] = []
    if project_id:
        dashboard = keyword_dashboard_rows(
            db, current_user.id, project_id, organization_id=org_id
        )
    return {"summary": summary, "dashboard": dashboard}
