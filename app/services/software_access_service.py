"""Software access (subscription / trial_3d / free usage) and auto-trial on credit."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.free_usage_service import has_active_free_usage
from app.services.rbac import is_admin
from app.services.saas_trial_service import TRIAL_PLAN_SLUG, is_saas_trial_active

_LOG = logging.getLogger(__name__)


def user_has_software_access(db: Session, user_id: int) -> bool:
    """User may use platform features (any active subscription, trial_3d, or free usage)."""
    user = db.get(User, int(user_id))
    if user is None:
        return False
    if is_admin(user):
        return True
    if has_active_free_usage(db, user_id):
        return True
    if is_saas_trial_active(user):
        return True
    sub = subscription_service.get_active_subscription(db, user_id)
    if sub is not None and subscription_service.is_subscription_active(sub):
        plan = plan_service.get_plan_by_id(db, sub.plan_id)
        slug = str(plan.slug if plan else "").strip().lower()
        if slug == TRIAL_PLAN_SLUG:
            return False
        return True
    return False


def maybe_auto_activate_trial_3d(
    db: Session,
    user: User,
    *,
    source: str,
    admin_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """
    Kích hoạt trial_3d nếu user chưa có quyền dùng phần mềm và chưa từng dùng trial.
    Trả True nếu đã kích hoạt.
    """
    if is_admin(user):
        return False
    if user_has_software_access(db, user.id):
        return False
    if bool(getattr(user, "trial_used", False)):
        return False

    from app.services.saas_trial_service import activate_saas_trial, log_trial_audit

    try:
        activate_saas_trial(db, user, device_fingerprint=None, ip_address=None)
    except Exception as exc:
        _LOG.warning(
            "auto_trial_3d_skipped user_id=%s source=%s error=%s",
            user.id,
            source,
            exc,
        )
        return False

    detail: dict[str, Any] = {"source": source, **(extra or {})}
    if admin_id is not None:
        detail["admin_id"] = int(admin_id)
    log_trial_audit(
        db,
        action=source,
        user_id=int(user.id),
        admin_id=admin_id,
        detail=detail,
    )
    return True
