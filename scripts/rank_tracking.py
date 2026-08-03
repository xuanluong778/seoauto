"""Rank Tracking API — projects, keywords, SERP checks via DataForSEO."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.user import User
from app.services.auth import get_current_user
from app.services.rank_tracking_service import (
    build_summary,
    check_keyword_now,
    check_project_now,
    keyword_dashboard_rows,
)
from app.services.rank_tracking_store import (
    create_keyword,
    create_project,
    get_project,
    list_keywords,
    list_projects,
    list_results,
)

router = APIRouter(tags=["rank-tracking"])


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
def api_list_projects(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"items": list_projects(current_user.id)}


@router.post("/projects")
def api_create_project(
    body: ProjectCreateBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = create_project(
        user_id=current_user.id,
        name=body.name or body.domain,
        domain=body.domain,
        location_name=body.location_name,
        language_name=body.language_name,
        device=body.device,
    )
    return {"item": item}


@router.get("/keywords")
def api_list_keywords(
    project_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if project_id:
        get_project(project_id, current_user.id)
    return {"items": list_keywords(current_user.id, project_id=project_id)}


@router.post("/keywords")
def api_create_keyword(
    body: KeywordCreateBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = create_keyword(
        user_id=current_user.id,
        project_id=body.project_id,
        keyword=body.keyword,
    )
    return {"item": item}


@router.post("/check-now")
def api_check_now(
    body: CheckNowBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if body.keyword_id:
        out = check_keyword_now(current_user.id, body.keyword_id, depth=body.depth)
        return {"mode": "keyword", **out}
    if body.project_id:
        out = check_project_now(current_user.id, body.project_id, depth=body.depth)
        return {"mode": "project", **out}
    raise HTTPException(status_code=400, detail="Cần project_id hoặc keyword_id.")


@router.get("/results")
def api_list_results(
    project_id: str | None = Query(default=None),
    keyword_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if project_id:
        get_project(project_id, current_user.id)
    return {
        "items": list_results(
            current_user.id,
            project_id=project_id,
            keyword_id=keyword_id,
            limit=limit,
        )
    }


@router.get("/summary")
def api_summary(
    project_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if project_id:
        get_project(project_id, current_user.id)
    summary = build_summary(current_user.id, project_id=project_id)
    dashboard: list[dict[str, Any]] = []
    if project_id:
        dashboard = keyword_dashboard_rows(current_user.id, project_id)
    return {"summary": summary, "dashboard": dashboard}
