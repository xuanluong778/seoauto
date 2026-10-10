"""Rank Tracking — PostgreSQL store (tenant-scoped, transactional)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.rank_tracking import RankTrackingKeyword, RankTrackingProject, RankTrackingResult
from app.services.tenant_org import personal_organization_id

MAX_PROJECTS = 50
MAX_KEYWORDS_PER_PROJECT = 500
MAX_RESULTS_PER_KEYWORD = 500
CHECK_LOCK_TTL_SEC = 300

DEVICES = frozenset({"desktop", "mobile", "tablet"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _resolve_org(user_id: int, organization_id: int | None) -> int:
    return int(organization_id) if organization_id is not None else personal_organization_id(int(user_id))


def _project_dict(row: RankTrackingProject) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "organization_id": row.organization_id,
        "name": row.name,
        "domain": row.domain,
        "location_name": row.location_name,
        "language_name": row.language_name,
        "device": row.device,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_checked_at": _iso(row.last_checked_at),
    }


def _keyword_dict(row: RankTrackingKeyword) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "keyword": row.keyword,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_checked_at": _iso(row.last_checked_at),
    }


def _result_dict(row: RankTrackingResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "keyword_id": row.keyword_id,
        "keyword": row.keyword,
        "domain": row.domain,
        "rank_absolute": row.rank_absolute,
        "rank_group": row.rank_group,
        "url": row.url,
        "title": row.title,
        "rank_change": row.rank_change,
        "found": bool(row.found),
        "mock": bool(row.mock),
        "serp_depth": row.serp_depth,
        "checked_at": _iso(row.checked_at),
    }


def _get_project_row(
    db: Session,
    project_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
    for_update: bool = False,
) -> RankTrackingProject:
    org_id = _resolve_org(user_id, organization_id)
    stmt = select(RankTrackingProject).where(
        RankTrackingProject.id == str(project_id),
        RankTrackingProject.user_id == int(user_id),
        RankTrackingProject.organization_id == org_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy project.")
    return row


def _get_keyword_row(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
    for_update: bool = False,
) -> RankTrackingKeyword:
    org_id = _resolve_org(user_id, organization_id)
    stmt = select(RankTrackingKeyword).where(
        RankTrackingKeyword.id == str(keyword_id),
        RankTrackingKeyword.user_id == int(user_id),
        RankTrackingKeyword.organization_id == org_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy keyword.")
    return row


def acquire_keyword_check_lock(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
    ttl_sec: int = CHECK_LOCK_TTL_SEC,
) -> RankTrackingKeyword:
    """Row lock + in-flight guard — prevents duplicate concurrent SERP checks."""
    now = _now()
    row = _get_keyword_row(
        db, keyword_id, user_id, organization_id=organization_id, for_update=True
    )
    if row.checking_until is not None and _ensure_utc(row.checking_until) > now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "rank_check_in_progress",
                "message": "Keyword đang được check — vui lòng đợi hoàn tất.",
                "keyword_id": keyword_id,
            },
        )
    row.checking_until = now + timedelta(seconds=max(30, int(ttl_sec)))
    db.flush()
    return row


def release_keyword_check_lock(db: Session, keyword_row: RankTrackingKeyword) -> None:
    keyword_row.checking_until = None
    db.flush()


def clear_keyword_check_lock(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> None:
    org_id = _resolve_org(user_id, organization_id)
    row = _get_keyword_row(
        db, keyword_id, user_id, organization_id=org_id, for_update=True
    )
    row.checking_until = None
    db.flush()


def get_keyword(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    return _keyword_dict(
        _get_keyword_row(db, keyword_id, user_id, organization_id=organization_id)
    )


def list_projects(
    db: Session,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    org_id = _resolve_org(user_id, organization_id)
    rows = (
        db.query(RankTrackingProject)
        .filter(
            RankTrackingProject.user_id == int(user_id),
            RankTrackingProject.organization_id == org_id,
        )
        .order_by(desc(RankTrackingProject.created_at))
        .all()
    )
    return [_project_dict(r) for r in rows]


def get_project(
    db: Session,
    project_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    return _project_dict(_get_project_row(db, project_id, user_id, organization_id=organization_id))


def create_project(
    db: Session,
    *,
    user_id: int,
    name: str,
    domain: str,
    location_name: str = "Vietnam",
    language_name: str = "Vietnamese",
    device: str = "desktop",
    organization_id: int | None = None,
) -> dict[str, Any]:
    org_id = _resolve_org(user_id, organization_id)
    owned = (
        db.query(func.count(RankTrackingProject.id))
        .filter(
            RankTrackingProject.user_id == int(user_id),
            RankTrackingProject.organization_id == org_id,
        )
        .scalar()
        or 0
    )
    if int(owned) >= MAX_PROJECTS:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn project rank tracking.")
    dev = device if device in DEVICES else "desktop"
    row = RankTrackingProject(
        id=str(uuid.uuid4()),
        user_id=int(user_id),
        organization_id=org_id,
        name=str(name or domain or "Project").strip()[:200],
        domain=str(domain or "").strip().lower()[:253],
        location_name=str(location_name or "Vietnam").strip()[:120],
        language_name=str(language_name or "Vietnamese").strip()[:120],
        device=dev,
    )
    db.add(row)
    db.flush()
    return _project_dict(row)


def list_keywords(
    db: Session,
    user_id: int,
    *,
    project_id: str | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    org_id = _resolve_org(user_id, organization_id)
    q = db.query(RankTrackingKeyword).filter(
        RankTrackingKeyword.user_id == int(user_id),
        RankTrackingKeyword.organization_id == org_id,
    )
    if project_id:
        q = q.filter(RankTrackingKeyword.project_id == str(project_id))
    rows = q.order_by(desc(RankTrackingKeyword.created_at)).all()
    return [_keyword_dict(r) for r in rows]


def create_keyword(
    db: Session,
    *,
    user_id: int,
    project_id: str,
    keyword: str,
    organization_id: int | None = None,
) -> dict[str, Any]:
    org_id = _resolve_org(user_id, organization_id)
    _get_project_row(db, project_id, user_id, organization_id=org_id)
    kw = str(keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Keyword không được để trống.")
    if len(kw) > 200:
        raise HTTPException(status_code=400, detail="Keyword quá dài.")
    existing_count = (
        db.query(func.count(RankTrackingKeyword.id))
        .filter(
            RankTrackingKeyword.user_id == int(user_id),
            RankTrackingKeyword.organization_id == org_id,
            RankTrackingKeyword.project_id == str(project_id),
        )
        .scalar()
        or 0
    )
    if int(existing_count) >= MAX_KEYWORDS_PER_PROJECT:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn keyword cho project.")
    low = kw.lower()
    dup = (
        db.query(RankTrackingKeyword.id)
        .filter(
            RankTrackingKeyword.user_id == int(user_id),
            RankTrackingKeyword.organization_id == org_id,
            RankTrackingKeyword.project_id == str(project_id),
            func.lower(RankTrackingKeyword.keyword) == low,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Keyword đã tồn tại trong project.")
    row = RankTrackingKeyword(
        id=str(uuid.uuid4()),
        user_id=int(user_id),
        organization_id=org_id,
        project_id=str(project_id),
        keyword=kw,
    )
    db.add(row)
    db.flush()
    return _keyword_dict(row)


def list_results(
    db: Session,
    user_id: int,
    *,
    project_id: str | None = None,
    keyword_id: str | None = None,
    organization_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    org_id = _resolve_org(user_id, organization_id)
    q = db.query(RankTrackingResult).filter(
        RankTrackingResult.user_id == int(user_id),
        RankTrackingResult.organization_id == org_id,
    )
    if project_id:
        q = q.filter(RankTrackingResult.project_id == str(project_id))
    if keyword_id:
        q = q.filter(RankTrackingResult.keyword_id == str(keyword_id))
    lim = max(1, min(int(limit or 200), 1000))
    rows = q.order_by(desc(RankTrackingResult.checked_at)).limit(lim).all()
    return [_result_dict(r) for r in rows]


def latest_result_for_keyword(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    rows = list_results(
        db,
        user_id,
        keyword_id=keyword_id,
        organization_id=organization_id,
        limit=1,
    )
    return rows[0] if rows else None


def previous_result_for_keyword(
    db: Session,
    keyword_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    rows = list_results(
        db,
        user_id,
        keyword_id=keyword_id,
        organization_id=organization_id,
        limit=2,
    )
    return rows[1] if len(rows) > 1 else None


def append_result(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    project_id: str,
    keyword_id: str,
    keyword: str,
    domain: str,
    rank_absolute: int | None,
    rank_group: int | None,
    url: str | None,
    title: str | None,
    rank_change: int | None,
    mock: bool = False,
    serp_depth: int = 100,
) -> dict[str, Any]:
    org_id = int(organization_id)
    checked = _now()
    row = RankTrackingResult(
        id=str(uuid.uuid4()),
        user_id=int(user_id),
        organization_id=org_id,
        project_id=str(project_id),
        keyword_id=str(keyword_id),
        keyword=str(keyword),
        domain=str(domain),
        rank_absolute=rank_absolute,
        rank_group=rank_group,
        url=url,
        title=title,
        rank_change=rank_change,
        found=rank_absolute is not None,
        mock=bool(mock),
        serp_depth=int(serp_depth),
        checked_at=checked,
    )
    db.add(row)

    kw_row = _get_keyword_row(db, keyword_id, user_id, organization_id=org_id, for_update=True)
    kw_row.last_checked_at = checked
    kw_row.updated_at = checked

    proj_row = _get_project_row(db, project_id, user_id, organization_id=org_id, for_update=True)
    proj_row.last_checked_at = checked
    proj_row.updated_at = checked

    # Trim old results per keyword
    excess = (
        db.query(RankTrackingResult.id)
        .filter(
            RankTrackingResult.keyword_id == str(keyword_id),
            RankTrackingResult.user_id == int(user_id),
        )
        .order_by(desc(RankTrackingResult.checked_at))
        .offset(MAX_RESULTS_PER_KEYWORD)
        .all()
    )
    if excess:
        ids = [x[0] for x in excess]
        db.query(RankTrackingResult).filter(RankTrackingResult.id.in_(ids)).delete(
            synchronize_session=False
        )

    db.flush()
    return _result_dict(row)
