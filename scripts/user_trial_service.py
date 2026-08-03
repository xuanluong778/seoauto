"""5-day trial activated once per user when a valid API key is saved."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_trial import TrialKeyClaim, UserTrial
from app.services.api_key_fingerprint import api_key_fingerprint
from app.services.rbac import is_admin

TRIAL_DAYS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_trial_row(db: Session, user_id: int) -> UserTrial | None:
    return db.query(UserTrial).filter(UserTrial.user_id == int(user_id)).first()


def _trial_payload(**kwargs: Any) -> dict[str, Any]:
    base = {"trial_days": TRIAL_DAYS}
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
        use_pool = bool(getattr(user, "use_admin_api_pool", False))
        msg = (
            f"Admin đã cấp quyền API — dùng được Content AI / LLM không cần trial {TRIAL_DAYS} ngày."
        )
        if use_pool:
            msg += " Đang dùng khóa hệ thống (API Admin bật)."
        else:
            msg += " User nhập khóa riêng tại Cài đặt → Khóa API (nếu cần)."
        return _trial_payload(
            has_trial=False,
            is_active=True,
            is_admin_bypass=False,
            is_api_grant_bypass=True,
            started_at=None,
            ends_at=None,
            days_remaining=0,
            never_used=False,
            message=msg,
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
            message=(
                f"Chưa kích hoạt dùng thử {TRIAL_DAYS} ngày. Thêm API key hợp lệ trong mục Khóa API, "
                "hoặc admin bật「Cho phép dùng API」."
            ),
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
            f"Dùng thử {TRIAL_DAYS} ngày — còn {remaining} ngày."
            if active
            else f"Dùng thử {TRIAL_DAYS} ngày đã hết hạn — chỉ xem dữ liệu cũ, không tạo mới."
        ),
    )


def user_can_mutate_with_trial(db: Session, user_id: int, *, role: str = "user") -> bool:
    snap = trial_status_snapshot(db, user_id, role=role)
    return bool(snap.get("is_active"))


def try_activate_trial(
    db: Session,
    *,
    user_id: int,
    plain_api_key: str,
) -> dict[str, Any]:
    """
    Kích hoạt trial (TRIAL_DAYS) nếu:
    - User chưa từng có bản ghi trial
    - Fingerprint chưa được user khác dùng để kích hoạt trial
  Không reset trial khi gọi lại với key mới.
    """
    fp = api_key_fingerprint(plain_api_key)
    existing = get_trial_row(db, user_id)
    if existing:
        return {
            "activated": False,
            "reason": "already_used_trial",
            "message": "Tài khoản đã từng dùng thử — không gia hạn khi thêm khóa mới.",
            "trial": trial_status_snapshot(db, user_id),
        }

    claim = db.query(TrialKeyClaim).filter(TrialKeyClaim.key_fingerprint == fp).first()
    if claim and int(claim.user_id) != int(user_id):
        return {
            "activated": False,
            "reason": "key_used_elsewhere",
            "message": "API key này đã kích hoạt dùng thử trên tài khoản khác.",
            "trial": trial_status_snapshot(db, user_id),
        }

    now = _utc_now()
    ends = now + timedelta(days=TRIAL_DAYS)
    db.add(
        UserTrial(
            user_id=int(user_id),
            started_at=now,
            ends_at=ends,
            activated_by_key_fingerprint=fp,
        )
    )
    if not claim:
        db.add(TrialKeyClaim(key_fingerprint=fp, user_id=int(user_id)))
    db.commit()

    return {
        "activated": True,
        "reason": "started",
        "message": f"Đã kích hoạt dùng thử {TRIAL_DAYS} ngày.",
        "trial": trial_status_snapshot(db, user_id),
    }
