"""Admin: list users, inspect per-user data, update role/status."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.keyword_cluster_job import KeywordClusterJob
from app.models.security_audit_log import SecurityAuditLog
from app.models.seo import Project
from app.models.user import User
from app.schemas.admin import AdminUserSummary
from app.services.ai_knowledge_store import list_bases
from app.services.api_keys_store import list_keys
from app.services.content_ai_project_store import list_content_ai_projects
from app.services.publishing_sites_store import list_sites
from app.services.rbac import ROLES, STATUSES, is_admin, normalize_role, normalize_status
from app.services.user_account_policy import is_retained_user_email
from app.services.user_trial_service import trial_status_snapshot


USER_SEGMENTS = frozenset(
    {"all", "activated", "trial_pending", "trial_active", "trial_expired", "no_trial_row"}
)
TRIAL_STATUS_FILTERS = frozenset({"pending", "active", "expired", "admin", "api_granted", "none"})


def _trial_status_key(trial: dict[str, Any], *, role: str) -> str:
    if trial.get("is_admin_bypass"):
        return "admin"
    if trial.get("is_api_grant_bypass"):
        return "api_granted"
    if trial.get("never_used"):
        return "pending"
    if trial.get("is_active"):
        return "active"
    if trial.get("has_trial"):
        return "expired"
    return "none"


def user_to_summary(db: Session, user: User) -> AdminUserSummary:
    role = normalize_role(user.role)
    trial = trial_status_snapshot(db, user.id, role=role)
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        role=role,
        status=normalize_status(getattr(user, "status", None)),
        credit_balance=int(user.credit_balance or 0),
        has_password=bool(user.has_password),
        api_access_enabled=bool(getattr(user, "api_access_enabled", False)),
        use_admin_api_pool=bool(getattr(user, "use_admin_api_pool", False)),
        created_at=user.created_at,
        account_activated=bool(user.has_password),
        trial_status=_trial_status_key(trial, role=role),
        trial_started_at=trial.get("started_at"),
        trial_ends_at=trial.get("ends_at"),
        trial_days_remaining=int(trial.get("days_remaining") or 0),
        trial_is_active=bool(trial.get("is_active")),
        trial_never_used=bool(trial.get("never_used")),
        trial_message=str(trial.get("message") or ""),
    )


def _matches_trial_status(summary: AdminUserSummary, trial_status: str | None) -> bool:
    if not trial_status:
        return True
    key = trial_status.strip().lower()
    if key not in TRIAL_STATUS_FILTERS:
        return True
    return summary.trial_status == key


def _matches_use_admin_api(summary: AdminUserSummary, use_admin_api: bool | None) -> bool:
    if use_admin_api is None:
        return True
    return summary.use_admin_api_pool is use_admin_api


def _matches_segment(summary: AdminUserSummary, segment: str) -> bool:
    seg = (segment or "all").strip().lower()
    if seg == "all" or seg not in USER_SEGMENTS:
        return True
    if seg == "activated":
        return summary.account_activated
    if seg == "trial_pending":
        return summary.trial_never_used and summary.role != "admin"
    if seg == "trial_active":
        return summary.trial_is_active and summary.trial_status == "active"
    if seg == "trial_expired":
        return summary.trial_status == "expired"
    if seg == "no_trial_row":
        return summary.trial_never_used and not summary.account_activated
    return True


def list_users(
    db: Session,
    *,
    q: str = "",
    role: str | None = None,
    status: str | None = None,
    segment: str = "all",
    trial_status: str | None = None,
    use_admin_api: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AdminUserSummary], int]:
    query = db.query(User)
    term = (q or "").strip().lower()
    if term:
        if term.isdigit():
            query = query.filter(or_(User.id == int(term), func.lower(User.email).contains(term)))
        else:
            query = query.filter(func.lower(User.email).contains(term))
    if role:
        r = normalize_role(role)
        if r in ROLES:
            query = query.filter(func.lower(User.role) == r)
    if status:
        s = normalize_status(status)
        if s in STATUSES:
            query = query.filter(func.lower(User.status) == s)

    seg = (segment or "all").strip().lower()
    if seg not in USER_SEGMENTS:
        seg = "all"

    rows = [u for u in query.order_by(User.created_at.desc()).all() if is_retained_user_email(u.email)]
    summaries = [user_to_summary(db, u) for u in rows]
    if seg != "all":
        summaries = [s for s in summaries if _matches_segment(s, seg)]
    summaries = [
        s
        for s in summaries
        if _matches_trial_status(s, trial_status) and _matches_use_admin_api(s, use_admin_api)
    ]

    total = len(summaries)
    start = max(0, offset)
    end = start + max(1, min(limit, 500))
    return summaries[start:end], total


def _bulk_jobs_for_user(db: Session, user_id: int, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = (
        db.query(KeywordClusterJob)
        .filter(KeywordClusterJob.job_type == "content_ai_bulk")
        .order_by(KeywordClusterJob.created_at.desc())
        .limit(500)
        .all()
    )
    out: list[dict[str, Any]] = []
    uid = int(user_id)
    for row in rows:
        payload: dict[str, Any] | None = None
        if row.payload_json:
            try:
                payload = json.loads(row.payload_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = None
        owner = 0
        if isinstance(payload, dict):
            try:
                owner = int(payload.get("user_id") or 0)
            except (TypeError, ValueError):
                owner = 0
        if owner != uid:
            continue
        kw_count = 0
        if isinstance(payload, dict):
            kws = payload.get("keywords") or []
            if isinstance(kws, list):
                kw_count = len(kws)
        out.append(
            {
                "job_id": row.job_id,
                "state": row.state,
                "progress": int(row.progress or 0),
                "message": str(row.message or "")[:200],
                "keyword_count": kw_count,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                "error": (str(row.error or "")[:300] if row.error else ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _audit_for_user(db: Session, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        db.query(SecurityAuditLog)
        .filter(SecurityAuditLog.user_id == int(user_id))
        .order_by(SecurityAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail_json": (r.detail_json or "")[:500],
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


def get_user_detail(db: Session, user_id: int) -> dict[str, Any]:
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy user.")

    seo_projects = (
        db.query(Project)
        .filter(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .limit(50)
        .all()
    )
    seo_list = [
        {
            "id": p.id,
            "domain": p.domain,
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in seo_projects
    ]

    content_ai = list_content_ai_projects(user_id=user.id, limit=80)
    kb_list = [
        {
            "id": b.get("id"),
            "name": b.get("name"),
            "scope": b.get("scope"),
            "doc_count": b.get("doc_count"),
            "created_at": b.get("created_at"),
        }
        for b in list_bases(user_id=user.id)
    ]
    api_keys = []
    for row in list_keys(user_id=user.id):
        safe = {k: v for k, v in row.items() if k != "api_key"}
        safe.setdefault("api_key_masked", row.get("api_key_masked") or "••••")
        api_keys.append(safe)
    pub_sites = list_sites(user_id=user.id)
    trial = trial_status_snapshot(db, user.id, role=normalize_role(user.role))

    return {
        "user": user_to_summary(db, user),
        "seo_projects": seo_list,
        "content_ai_projects": content_ai,
        "knowledge_bases": kb_list,
        "bulk_jobs": _bulk_jobs_for_user(db, user.id),
        "api_keys": api_keys,
        "publishing_sites": pub_sites,
        "trial": trial,
        "audit_logs": _audit_for_user(db, user.id),
    }


def _count_admins(db: Session) -> int:
    return db.query(User).filter(func.lower(User.role) == "admin").count()


def update_user_role(
    db: Session,
    *,
    target_user_id: int,
    new_role: str,
    actor: User,
) -> AdminUserSummary:
    if int(target_user_id) == int(actor.id) and normalize_role(new_role) != "admin":
        raise HTTPException(status_code=400, detail="Không thể tự hạ quyền admin của chính mình.")
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    role = normalize_role(new_role)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Role không hợp lệ.")
    if is_admin(user) and role != "admin" and _count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Không thể hạ quyền admin cuối cùng.")
    user.role = role
    db.commit()
    db.refresh(user)
    return user_to_summary(db, user)


def update_user_status(
    db: Session,
    *,
    target_user_id: int,
    new_status: str,
    actor: User,
) -> AdminUserSummary:
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    st = normalize_status(new_status)
    if st not in STATUSES:
        raise HTTPException(status_code=400, detail="Status không hợp lệ.")
    if int(target_user_id) == int(actor.id) and st != "active":
        raise HTTPException(status_code=400, detail="Không thể tự khóa tài khoản admin của chính mình.")
    if is_admin(user) and st != "active" and _count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Không thể khóa admin cuối cùng.")
    user.status = st
    db.commit()
    db.refresh(user)
    return user_to_summary(db, user)


def update_user_api_access(
    db: Session,
    *,
    target_user_id: int,
    api_access_enabled: bool | None = None,
    use_admin_api_pool: bool | None = None,
    actor: User,
) -> AdminUserSummary:
    _ = actor
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    if is_admin(user) and api_access_enabled is False:
        raise HTTPException(status_code=400, detail="Không thể tắt quyền API của tài khoản admin.")
    if api_access_enabled is not None:
        user.api_access_enabled = bool(api_access_enabled)
        if not user.api_access_enabled:
            user.use_admin_api_pool = False
    if use_admin_api_pool is not None:
        user.use_admin_api_pool = bool(use_admin_api_pool)
        if user.use_admin_api_pool:
            user.api_access_enabled = True
    db.commit()
    db.refresh(user)
    return user_to_summary(db, user)


def list_admin_audit_logs(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        db.query(SecurityAuditLog)
        .filter(SecurityAuditLog.action.like("admin.%"))
        .order_by(SecurityAuditLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail_json": (r.detail_json or "")[:800],
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]
