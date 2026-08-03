"""Admin: list users, inspect per-user data, update role/status."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core.password_policy import validate_password_strength
from app.core.security import hash_password
from app.models.credit_ledger import CreditLedger
from app.models.keyword_cluster_job import KeywordClusterJob
from app.models.security_audit_log import SecurityAuditLog
from app.models.seo import Project
from app.models.user import User
from app.schemas.admin import AdminUserSummary
from app.services.chatbot_cskh_credits import adjust_bonus_credits
from app.services.admin_auth import ensure_admin_user_fields, is_configured_admin_email
from app.services.ai_knowledge_store import list_bases
from app.services.api_keys_store import list_keys
from app.services.content_ai_project_store import list_content_ai_projects
from app.services.credits import apply_signup_bonus_if_configured, get_available_balance, grant_credits
from app.services.software_access_service import maybe_auto_activate_trial_3d
from app.services.publishing_sites_store import list_sites
from app.services.rbac import ROLES, STATUSES, is_admin, normalize_role, normalize_status
from app.services.user_account_policy import is_retained_user_email
from app.services.user_trial_service import trial_status_snapshot
from app.services.user_api_access import describe_user_llm_source


USER_SEGMENTS = frozenset(
    {"all", "activated", "trial_pending", "trial_active", "trial_expired", "no_trial_row"}
)
TRIAL_STATUS_FILTERS = frozenset({"pending", "active", "expired", "admin", "api_granted", "none"})

CREDIT_TYPE_LABELS = {
    "plan_monthly": "Gói tháng",
    "purchased": "Mua thêm",
    "admin_adjustment": "Điều chỉnh admin",
    "refund": "Hoàn credit",
}

TRANSACTION_TYPE_LABELS = {
    "admin_grant": "Admin tặng",
    "admin_create_user": "Admin tạo user",
    "signup_bonus": "Bonus đăng ký",
    "plan_activation_bonus": "Kích hoạt gói",
    "plan_monthly_refresh": "Credit gói tháng",
    "credit_pack_purchase": "Mua gói credit",
    "legacy_balance_migration": "Migration",
    "refund": "Hoàn credit",
}


def _credit_source_label(row: CreditLedger) -> str:
    tx = str(getattr(row, "reason", "") or "").strip().lower()
    if tx in TRANSACTION_TYPE_LABELS:
        return TRANSACTION_TYPE_LABELS[tx]
    ct = str(getattr(row, "credit_type", "") or "").strip().lower()
    if ct in CREDIT_TYPE_LABELS:
        return CREDIT_TYPE_LABELS[ct]
    return tx or "Khác"


def _credit_history_for_user(db: Session, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == int(user_id))
        .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    admin_ids = {int(r.admin_id) for r in rows if getattr(r, "admin_id", None)}
    admin_emails: dict[int, str] = {}
    if admin_ids:
        for admin in db.query(User).filter(User.id.in_(admin_ids)).all():
            admin_emails[int(admin.id)] = str(admin.email or "")

    out: list[dict[str, Any]] = []
    for row in rows:
        ct = getattr(row, "credit_type", None)
        out.append(
            {
                "id": int(row.id),
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "credit_type": ct,
                "amount": int(row.delta or 0),
                "transaction_type": str(row.reason or ""),
                "grant_reason": getattr(row, "grant_reason", None),
                "internal_note": row.note if str(row.reason or "") == "admin_grant" else None,
                "source_label": _credit_source_label(row),
                "admin_id": int(row.admin_id) if getattr(row, "admin_id", None) else None,
                "admin_email": admin_emails.get(int(row.admin_id)) if getattr(row, "admin_id", None) else None,
                "balance_after": int(row.balance_after or 0),
                "module": getattr(row, "module", None),
                "action": getattr(row, "action", None),
                "credit_used": getattr(row, "credit_used", None),
                "request_id": getattr(row, "request_id", None),
                "source": getattr(row, "source", None),
            }
        )
    return out


def grant_credits_to_user_by_admin(
    db: Session,
    *,
    target_user_id: int,
    credit_type: str,
    amount: int,
    reason: str,
    note: str | None,
    actor: User,
) -> tuple[AdminUserSummary, int, bool]:
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy user.")

    amt = int(amount)
    if amt <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số credit không hợp lệ.")

    grant_reason = str(reason or "").strip()
    if not grant_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lý do tặng không được để trống.")

    ct = str(credit_type or "").strip().lower()
    new_balance = grant_credits(
        db,
        user_id=user.id,
        amount=amt,
        reason="admin_grant",
        source_type=ct,
        grant_reason=grant_reason,
        internal_note=(note or "").strip() or None,
        admin_id=int(actor.id),
    )
    trial_auto = maybe_auto_activate_trial_3d(
        db,
        user,
        source="admin_gift_credit_auto_trial_activated",
        admin_id=int(actor.id),
        extra={"amount": amt, "grant_reason": grant_reason, "credit_type": ct},
    )
    db.commit()
    db.refresh(user)
    return user_to_summary(db, user), new_balance, trial_auto


def grant_chatbot_credits_to_user_by_admin(
    db: Session,
    *,
    target_user_id: int,
    amount: int,
    operation: str,
    reason: str,
    note: str | None,
    actor: User,
) -> tuple[AdminUserSummary, int]:
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy user.")

    amt = int(amount)
    if amt <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số credit không hợp lệ.")

    op = str(operation or "add").strip().lower()
    delta = amt if op == "add" else -amt
    new_balance = adjust_bonus_credits(
        db,
        user_id=user.id,
        delta=delta,
        reason=str(reason or "").strip(),
        admin_id=int(actor.id),
        internal_note=(note or "").strip() or None,
    )
    db.refresh(user)
    return user_to_summary(db, user), new_balance


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
    credit_balance = get_available_balance(db, user.id, sync=True)
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        role=role,
        status=normalize_status(getattr(user, "status", None)),
        credit_balance=int(credit_balance),
        chatbot_cskh_bonus_credits=int(getattr(user, "chatbot_cskh_bonus_credits", 0) or 0),
        has_password=bool(user.has_password),
        api_access_enabled=bool(getattr(user, "api_access_enabled", False)),
        use_admin_api_pool=bool(getattr(user, "use_admin_api_pool", False)),
        allow_custom_api_key=bool(getattr(user, "allow_custom_api_key", False)),
        llm_source=describe_user_llm_source(db, user),
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
        "credit_history": _credit_history_for_user(db, user.id),
    }


def _count_admins(db: Session) -> int:
    return db.query(User).filter(func.lower(User.role).in_(("admin", "super_admin"))).count()


def update_user_role(
    db: Session,
    *,
    target_user_id: int,
    new_role: str,
    actor: User,
) -> AdminUserSummary:
    if int(target_user_id) == int(actor.id) and normalize_role(new_role) not in ("admin", "super_admin"):
        raise HTTPException(status_code=400, detail="Không thể tự hạ quyền admin của chính mình.")
    user = db.query(User).filter(User.id == int(target_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    role = normalize_role(new_role)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Role không hợp lệ.")
    if is_admin(user) and role not in ("admin", "super_admin") and _count_admins(db) <= 1:
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


def delete_user_by_admin(
    db: Session,
    *,
    target_user_id: int,
    actor: User,
) -> dict[str, Any]:
    """Permanently delete a user and their account-owned relational data."""
    target = db.query(User).filter(User.id == int(target_user_id)).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    if int(target.id) == int(actor.id):
        raise HTTPException(status_code=400, detail="Không thể tự xóa tài khoản admin đang đăng nhập.")
    if is_configured_admin_email(str(target.email or "")):
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản admin hệ thống.")
    if is_admin(target) and _count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Không thể xóa admin cuối cùng.")

    target_email = str(target.email or "")
    uid = int(target.id)

    # Tables without ON DELETE CASCADE/SET NULL must be handled before users.
    # Child rows are removed first where another restricted parent is involved.
    delete_tables = (
        "user_quota_addons",
        "payment_transactions",
        "usage_events",
        "monthly_usage",
        "payment_orders",
        "subscriptions",
        "seo_score_apply_logs",
        "cau_seo_fix_credit_logs",
        "chatbot_workflow_credit_logs",
        "credit_ledger_entries",
        "dataforseo_usage_logs",
        "keyword_cluster_projects",
        "keyword_research_projects",
    )
    try:
        # Project children that do not declare database-level cascades.
        db.execute(
            text(
                "DELETE FROM distributed_crawl_results WHERE job_id IN "
                "(SELECT id FROM distributed_crawl_jobs WHERE project_id IN "
                "(SELECT id FROM projects WHERE user_id = :uid))"
            ),
            {"uid": uid},
        )
        for project_child in (
            "distributed_crawl_jobs",
            "seo_keyword_url_mappings",
            "seo_keyword_clusters",
            "seo_keyword_entities",
        ):
            db.execute(
                text(
                    f'DELETE FROM "{project_child}" WHERE project_id IN '
                    "(SELECT id FROM projects WHERE user_id = :uid)"
                ),
                {"uid": uid},
            )

        # Preserve grants made by this user to other accounts while removing
        # the FK to the deleted admin.
        db.execute(
            text("UPDATE credit_ledgers SET admin_id = NULL WHERE admin_id = :uid"),
            {"uid": uid},
        )
        db.execute(text("DELETE FROM credit_ledgers WHERE user_id = :uid"), {"uid": uid})
        for table_name in delete_tables:
            db.execute(text(f'DELETE FROM "{table_name}" WHERE user_id = :uid'), {"uid": uid})

        # ORM cascades projects -> scans -> pages -> issues and knowledge bases;
        # database cascades the remaining user-owned module tables.
        db.delete(target)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa user vì còn dữ liệu liên kết. Hãy khóa tài khoản hoặc thử lại.",
        ) from exc

    return {"id": uid, "email": target_email}


def update_user_api_access(
    db: Session,
    *,
    target_user_id: int,
    api_access_enabled: bool | None = None,
    use_admin_api_pool: bool | None = None,
    allow_custom_api_key: bool | None = None,
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
    if allow_custom_api_key is not None:
        user.allow_custom_api_key = bool(allow_custom_api_key)
    db.commit()
    db.refresh(user)
    return user_to_summary(db, user)


def create_user_by_admin(
    db: Session,
    *,
    email: str,
    password: str,
    role: str = "user",
    status: str = "active",
    api_access_enabled: bool = False,
    use_admin_api_pool: bool = False,
    initial_credits: int = 0,
    actor: User,
) -> AdminUserSummary:
    _ = actor
    email_norm = email.strip().lower()
    if db.query(User).filter(User.email == email_norm).first():
        raise HTTPException(status_code=400, detail="Email đã tồn tại.")

    role_norm = normalize_role(role)
    if role_norm not in ROLES:
        raise HTTPException(status_code=400, detail="Role không hợp lệ.")

    status_norm = normalize_status(status)
    if status_norm not in STATUSES:
        raise HTTPException(status_code=400, detail="Status không hợp lệ.")

    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pool_on = bool(use_admin_api_pool)
    api_on = bool(api_access_enabled) or pool_on

    user = User(
        email=email_norm,
        password_hash=hash_password(password),
        has_password=True,
        role=role_norm,
        status=status_norm,
        api_access_enabled=api_on,
        use_admin_api_pool=pool_on,
    )
    if role_norm == "admin" or is_configured_admin_email(email_norm):
        ensure_admin_user_fields(user)

    db.add(user)
    db.flush()
    apply_signup_bonus_if_configured(db, user)

    extra_credits = int(initial_credits or 0)
    if extra_credits > 0:
        grant_credits(
            db,
            user_id=user.id,
            amount=extra_credits,
            reason="admin_create_user",
            note="Admin tạo user",
            source_type="admin_grant",
        )

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
