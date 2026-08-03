"""Legacy BYOK 5-day trial — disabled for new activations; use trial_3d instead."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_trial import TrialKeyClaim, UserTrial
from app.services.api_key_fingerprint import api_key_fingerprint
from app.services.rbac import is_admin

# Legacy constant — kept for existing rows / admin reference only.
TRIAL_DAYS = 5
_LEGACY_DISABLED_MSG = "Bạn chưa kích hoạt dùng thử 3 ngày."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_trial_row(db: Session, user_id: int) -> UserTrial | None:
    return db.query(UserTrial).filter(UserTrial.user_id == int(user_id)).first()


def _trial_payload(**kwargs: Any) -> dict[str, Any]:
    base = {"trial_days": TRIAL_DAYS, "legacy_byok_trial": True}
    base.update(kwargs)
    return base


def trial_status_snapshot(db: Session, user_id: int, *, role: str = "user") -> dict[str, Any]:
    if is_admin(type("U", (), {"role": role})()):
        return _trial_payload(
            has_trial=True,
            is_active=True,
            is_admin_bypass=True,
            is_api_grant_bypass=False,
            started_at=None,
            ends_at=None,
            days_remaining=TRIAL_DAYS,
            never_used=False,
            message="Tài khoản admin — không giới hạn trial.",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user and bool(getattr(user, "api_access_enabled", False)):
        return _trial_payload(
            has_trial=False,
            is_active=False,
            is_admin_bypass=False,
            is_api_grant_bypass=False,
            started_at=None,
            ends_at=None,
            days_remaining=0,
            never_used=True,
            message="Bạn chưa kích hoạt dùng thử 3 ngày.",
        )

    row = get_trial_row(db, user_id)
    now = _utc_now()
    if not row:
        return _trial_payload(
            has_trial=False,
            is_active=False,
            is_admin_bypass=False,
            is_api_grant_bypass=False,
            started_at=None,
            ends_at=None,
            days_remaining=0,
            never_used=True,
            message=_LEGACY_DISABLED_MSG,
        )

    ends = row.ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    started = row.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    active = now < ends
    remaining = max(0, (ends - now).days)
    if active and (ends - now).total_seconds() > remaining * 86400:
        remaining = remaining + 1

    return _trial_payload(
        has_trial=True,
        is_active=active,
        is_admin_bypass=False,
        is_api_grant_bypass=False,
        started_at=started.isoformat(),
        ends_at=ends.isoformat(),
        days_remaining=remaining if active else 0,
        never_used=False,
        message=(
            f"Legacy BYOK trial — còn {remaining} ngày."
            if active
            else "Legacy BYOK trial đã hết hạn."
        ),
    )


def user_can_mutate_with_trial(db: Session, user_id: int, *, role: str = "user") -> bool:
    """Only legacy users with an active BYOK trial row may mutate via this path."""
    snap = trial_status_snapshot(db, user_id, role=role)
    return bool(snap.get("is_active") and snap.get("has_trial"))


def try_activate_trial(
    db: Session,
    *,
    user_id: int,
    plain_api_key: str,
) -> dict[str, Any]:
    """
    Legacy BYOK trial activation — disabled for new users.
    trial_3d is the official trial path.
    """
    _ = api_key_fingerprint(plain_api_key)
    return {
        "activated": False,
        "reason": "legacy_disabled",
        "message": _LEGACY_DISABLED_MSG,
        "trial": {
            "legacy_byok_trial": True,
            "is_active": False,
            "never_used": True,
            "has_trial": False,
        },
    }
