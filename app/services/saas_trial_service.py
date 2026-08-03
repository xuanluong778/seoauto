"""SEOAuto 3-day SaaS trial — activation, quotas, credit cap."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models.saas_trial import SaasTrialClaim, SaasTrialDailyUsage
from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.rbac import is_admin

TRIAL_PLAN_SLUG = "trial_3d"
TRIAL_DAYS = 3
TRIAL_CREDIT_LIMIT = 1000

TRIAL_DAILY_LIMITS: dict[str, int] = {
    "content_ai_article": 5,
    "content_auto_update_fetch": 5,
    "content_auto_update_generate": 5,
    "content_auto_update_publish": 5,
    "seo_score": 5,
    "technical_audit": 3,
}

TRIAL_BLOCKED_FEATURES: frozenset[str] = frozenset(
    {
        "keyword_research",
        "keyword_cluster",
        "index_control_submit",
    }
)

AUTO_UPDATE_FEATURES: frozenset[str] = frozenset(
    {
        "content_auto_update_fetch",
        "content_auto_update_generate",
        "content_auto_update_publish",
        "content_auto_update_restore",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def current_usage_date(*, dt: datetime | None = None) -> str:
    return (dt or _utc_now()).strftime("%Y-%m-%d")


def trial_days_remaining(user: User, *, now: datetime | None = None) -> int:
    end = _aware(getattr(user, "trial_expires_at", None))
    if end is None:
        return 0
    now = now or _utc_now()
    if end <= now:
        return 0
    return max(0, (end.date() - now.date()).days)


def is_saas_trial_active(user: User, *, now: datetime | None = None) -> bool:
    if is_admin(user):
        return False
    if not bool(getattr(user, "trial_used", False)):
        return False
    end = _aware(getattr(user, "trial_expires_at", None))
    if end is None:
        return False
    return end > (now or _utc_now())


def is_saas_trial_user(db: Session, user: User) -> bool:
    if not is_saas_trial_active(user):
        return False
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return True
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    if plan is None:
        return True
    return str(plan.slug or "").lower() == TRIAL_PLAN_SLUG


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _hash_claim(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _claim_exists(db: Session, claim_kind: str, claim_value: str, *, user_id: int) -> bool:
    row = (
        db.query(SaasTrialClaim)
        .filter(
            SaasTrialClaim.claim_kind == claim_kind,
            SaasTrialClaim.claim_value == claim_value,
        )
        .first()
    )
    return row is not None and int(row.user_id) != int(user_id)


def _register_claims(
    db: Session,
    *,
    user_id: int,
    email: str,
    device_fingerprint: str | None,
    ip_address: str | None,
) -> None:
    claims: list[tuple[str, str]] = [("email", _normalize_email(email))]
    if device_fingerprint:
        claims.append(("device", _hash_claim(device_fingerprint.strip())))
    if ip_address:
        claims.append(("ip", _hash_claim(ip_address.strip())))
    for kind, value in claims:
        if not value:
            continue
        existing = (
            db.query(SaasTrialClaim)
            .filter(SaasTrialClaim.claim_kind == kind, SaasTrialClaim.claim_value == value)
            .first()
        )
        if existing is None:
            db.add(SaasTrialClaim(user_id=int(user_id), claim_kind=kind, claim_value=value))


def activate_saas_trial(
    db: Session,
    user: User,
    *,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    if is_admin(user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tài khoản admin không cần dùng thử.")
    from app.services.free_usage_service import has_active_free_usage

    if has_active_free_usage(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn đang có ngày dùng phần mềm được tặng — không cần kích hoạt dùng thử 3 ngày.",
        )
    if bool(getattr(user, "trial_used", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn đã sử dụng gói dùng thử — mỗi tài khoản chỉ kích hoạt một lần.",
        )
    if subscription_service.get_active_subscription(db, user.id) is not None:
        paid = subscription_service.get_active_subscription(db, user.id)
        if paid:
            plan = plan_service.get_plan_by_id(db, paid.plan_id)
            if plan and str(plan.slug or "").lower() not in (TRIAL_PLAN_SLUG, "free_trial_5d"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tài khoản đã có gói — không thể kích hoạt dùng thử.",
                )

    email = _normalize_email(user.email)
    if _claim_exists(db, "email", email, user_id=user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email này đã kích hoạt dùng thử.")
    if device_fingerprint and _claim_exists(db, "device", _hash_claim(device_fingerprint.strip()), user_id=user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiết bị này đã kích hoạt dùng thử.")
    if ip_address and _claim_exists(db, "ip", _hash_claim(ip_address.strip()), user_id=user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="IP này đã kích hoạt dùng thử.")

    plan = plan_service.get_plan_by_slug(db, TRIAL_PLAN_SLUG)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gói dùng thử chưa được cấu hình.")

    now = _utc_now()
    ends = now + timedelta(days=TRIAL_DAYS)
    user.trial_started_at = now
    user.trial_expires_at = ends
    user.trial_used = True
    user.trial_credit_used = 0

    subscription_service.expire_active_subscriptions_for_user(db, user.id, now=now)
    subscription_service.extend_or_create_subscription(
        db,
        user.id,
        plan.id,
        period_days=TRIAL_DAYS,
        status="trialing",
        source="saas_trial_3d",
        notes="activate_trial",
    )
    _register_claims(db, user_id=user.id, email=email, device_fingerprint=device_fingerprint, ip_address=ip_address)
    db.flush()
    return trial_status_payload(db, user)


def end_saas_trial_state(db: Session, user_id: int, *, reason: str = "trial_to_paid") -> None:
    user = db.get(User, int(user_id))
    if user is None:
        return
    now = _utc_now()
    if is_saas_trial_active(user, now=now):
        user.trial_expires_at = now
    db.flush()


def _trial_claim_blocks_activation(
    db: Session,
    user: User,
    *,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> bool:
    email = _normalize_email(user.email)
    if _claim_exists(db, "email", email, user_id=user.id):
        return True
    if device_fingerprint and _claim_exists(
        db, "device", _hash_claim(device_fingerprint.strip()), user_id=user.id
    ):
        return True
    if ip_address and _claim_exists(db, "ip", _hash_claim(ip_address.strip()), user_id=user.id):
        return True
    return False


def trial_status_payload(
    db: Session,
    user: User,
    *,
    device_fingerprint: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    from app.services import credits as credits_svc
    from app.services.free_usage_service import has_active_free_usage

    active = is_saas_trial_active(user)
    days = trial_days_remaining(user)
    balance = int(credits_svc.get_available_balance(db, user.id))
    credit_used = int(getattr(user, "trial_credit_used", 0) or 0)
    credit_remaining = max(0, TRIAL_CREDIT_LIMIT - credit_used)
    free_usage_active = has_active_free_usage(db, user.id)
    claim_blocked = _trial_claim_blocks_activation(
        db,
        user,
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
    )
    can_activate = (
        not bool(getattr(user, "trial_used", False))
        and not is_admin(user)
        and not free_usage_active
        and not claim_blocked
    )

    if active:
        banner = (
            f"Bạn còn {days} ngày dùng thử. Credit trial khả dụng tối đa: "
            f"{TRIAL_CREDIT_LIMIT:,} credit.".replace(",", ".")
        )
        if balance <= 0:
            need_credit_msg = f"Bạn có {days} ngày dùng thử, vui lòng mua credit để sử dụng tính năng."
        else:
            need_credit_msg = None
    elif bool(getattr(user, "trial_used", False)):
        banner = "Gói dùng thử đã hết hạn. Vui lòng nâng cấp Basic, Pro, Agency hoặc Business để tiếp tục."
        need_credit_msg = None
    else:
        banner = (
            "Dùng thử SEOAuto 3 ngày — trải nghiệm Content AI, Auto Update, SEO Score và Technical Audit. "
            "Cần mua credit để sử dụng."
        )
        need_credit_msg = None

    return {
        "plan": TRIAL_PLAN_SLUG,
        "subscription_status": "trialing" if active else ("expired" if user.trial_used else None),
        "trial_active": active,
        "trial_used": bool(getattr(user, "trial_used", False)),
        "can_activate": can_activate,
        "trial_started_at": _aware(user.trial_started_at).isoformat() if user.trial_started_at else None,
        "trial_expires_at": _aware(user.trial_expires_at).isoformat() if user.trial_expires_at else None,
        "trial_days_remaining": days,
        "trial_credit_limit": TRIAL_CREDIT_LIMIT,
        "trial_credit_used": credit_used,
        "trial_credit_remaining": credit_remaining if active else 0,
        "credit_balance": balance,
        "needs_credit": bool(active and balance <= 0),
        "banner": banner,
        "need_credit_message": need_credit_msg,
        "activate_banner": banner if can_activate else None,
        "free_usage_active": free_usage_active,
        "trial_claim_blocked": claim_blocked,
    }


def get_daily_usage(db: Session, user_id: int, feature_key: str, usage_date: str | None = None) -> int:
    day = usage_date or current_usage_date()
    row = (
        db.query(SaasTrialDailyUsage)
        .filter(
            SaasTrialDailyUsage.user_id == int(user_id),
            SaasTrialDailyUsage.usage_date == day,
            SaasTrialDailyUsage.feature_key == feature_key,
        )
        .one_or_none()
    )
    return int(row.quantity_used) if row else 0


def record_daily_usage(db: Session, user_id: int, feature_key: str, quantity: int = 1) -> int:
    day = current_usage_date()
    qty = max(1, int(quantity))
    row = (
        db.query(SaasTrialDailyUsage)
        .filter(
            SaasTrialDailyUsage.user_id == int(user_id),
            SaasTrialDailyUsage.usage_date == day,
            SaasTrialDailyUsage.feature_key == feature_key,
        )
        .one_or_none()
    )
    if row is None:
        row = SaasTrialDailyUsage(user_id=int(user_id), usage_date=day, feature_key=feature_key, quantity_used=qty)
        db.add(row)
    else:
        row.quantity_used = int(row.quantity_used or 0) + qty
    db.flush()
    return int(row.quantity_used)


def _effective_daily_feature(feature_key: str) -> str | None:
    key = str(feature_key or "").strip()
    if key in AUTO_UPDATE_FEATURES:
        return "content_auto_update_fetch"
    return key if key in TRIAL_DAILY_LIMITS else None


def check_trial_feature_allowed(
    db: Session,
    user: User,
    feature_key: str,
    *,
    quantity: int = 1,
) -> dict[str, Any]:
    """Return {allowed, message, code, upgrade_url}."""
    if not is_saas_trial_user(db, user):
        if bool(getattr(user, "trial_used", False)) and not is_saas_trial_active(user):
            return {
                "allowed": False,
                "code": "trial_expired",
                "message": "Gói dùng thử đã hết hạn. Vui lòng nâng cấp Basic, Pro, Agency hoặc Business để tiếp tục.",
                "upgrade_url": "/pricing",
            }
        return {"allowed": True}

    key = str(feature_key or "").strip()
    if key in TRIAL_BLOCKED_FEATURES:
        return {
            "allowed": False,
            "code": "trial_feature_locked",
            "message": "Tính năng này không có trong gói dùng thử. Nâng cấp để sử dụng.",
            "upgrade_url": "/pricing",
        }

    from app.services import credits as credits_svc

    balance = int(credits_svc.get_available_balance(db, user.id))
    days = trial_days_remaining(user)
    if balance <= 0:
        return {
            "allowed": False,
            "code": "trial_need_credit",
            "message": f"Bạn có {days} ngày dùng thử, vui lòng mua credit để sử dụng tính năng.",
            "upgrade_url": "/account/billing",
        }

    daily_key = _effective_daily_feature(key)
    if daily_key:
        limit = TRIAL_DAILY_LIMITS.get(daily_key, 0)
        used = get_daily_usage(db, user.id, daily_key)
        need = max(1, int(quantity))
        if used + need > limit:
            labels = {
                "content_ai_article": "Content AI",
                "content_auto_update_fetch": "Auto Update",
                "seo_score": "SEO Score",
                "technical_audit": "Technical Audit",
            }
            label = labels.get(daily_key, daily_key)
            return {
                "allowed": False,
                "code": "trial_daily_limit",
                "message": f"Đã đạt giới hạn {limit}/ngày cho {label} trong gói dùng thử.",
                "upgrade_url": "/pricing",
            }

    credit_used = int(getattr(user, "trial_credit_used", 0) or 0)
    if credit_used >= TRIAL_CREDIT_LIMIT:
        return {
            "allowed": False,
            "code": "trial_credit_cap",
            "message": (
                f"Đã dùng hết {TRIAL_CREDIT_LIMIT:,} credit trong gói dùng thử. "
                "Nâng cấp Basic, Pro, Agency hoặc Business để tiếp tục."
            ).replace(",", "."),
            "upgrade_url": "/pricing",
        }

    return {"allowed": True}


def assert_trial_credit_cap(db: Session, user_id: int, amount: int) -> None:
    user = db.get(User, int(user_id))
    if user is None or not is_saas_trial_user(db, user):
        return
    need = max(0, int(amount))
    used = int(getattr(user, "trial_credit_used", 0) or 0)
    if used + need > TRIAL_CREDIT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "trial_credit_cap",
                "message": (
                    f"Đã dùng {used:,}/{TRIAL_CREDIT_LIMIT:,} credit trial. "
                    "Nâng cấp gói để dùng tiếp credit còn lại trong ví."
                ).replace(",", "."),
                "trial_credit_used": used,
                "trial_credit_limit": TRIAL_CREDIT_LIMIT,
                "upgrade_url": "/pricing",
            },
        )


def add_trial_credit_used(db: Session, user_id: int, amount: int) -> None:
    user = db.get(User, int(user_id))
    if user is None or not is_saas_trial_user(db, user):
        return
    user.trial_credit_used = int(getattr(user, "trial_credit_used", 0) or 0) + max(0, int(amount))
    db.flush()


def record_trial_feature_success(db: Session, user_id: int, feature_key: str, *, quantity: int = 1) -> None:
    user = db.get(User, int(user_id))
    if user is None or not is_saas_trial_user(db, user):
        return
    daily_key = _effective_daily_feature(feature_key)
    if daily_key:
        record_daily_usage(db, user_id, daily_key, quantity)


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client:
        return str(request.client.host)[:64]
    return None


def log_trial_audit(
    db: Session,
    *,
    action: str,
    user_id: int,
    admin_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    from app.models.security_audit_log import SecurityAuditLog

    payload = {"action": action, "user_id": user_id, **(detail or {})}
    if admin_id is not None:
        payload["admin_id"] = admin_id
    db.add(
        SecurityAuditLog(
            user_id=admin_id or user_id,
            action=f"saas.trial.{action}",
            resource_type="user",
            resource_id=str(user_id),
            detail_json=json.dumps(payload, ensure_ascii=False)[:4000],
            ip_address="",
        )
    )
