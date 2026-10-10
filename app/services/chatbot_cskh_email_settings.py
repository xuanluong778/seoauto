"""Per-tenant settings + status logs for Chatbot CSKH email notifications."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotEmailNotifyLog, ChatbotEmailNotifySetting
from app.models.user import User
from app.services.tenant_org import personal_organization_id

ALLOWED_DELAY_SECONDS = (0, 120, 300, 600)
DEFAULT_DELAY_SECONDS = 120

LOG_QUEUED = "queued"
LOG_SENT = "sent"
LOG_SKIPPED_READ = "skipped_read"
LOG_SKIPPED_DISABLED = "skipped_disabled"
LOG_FAILED = "failed"
LOG_STATUSES = frozenset({LOG_QUEUED, LOG_SENT, LOG_SKIPPED_READ, LOG_SKIPPED_DISABLED, LOG_FAILED})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer\s+\S+|re_[A-Za-z0-9]+|password|secret)[^\s,;]*"
)


class NotifySettingsError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid") -> None:
        self.code = code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_log_detail(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    text = _SECRET_RE.sub("[redacted]", text)
    if "resend_http_" in text:
        text = text.split(":", 1)[0]
    return text[:80]


def validate_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise NotifySettingsError("Email nhận thông báo không hợp lệ.", code="invalid_email")
    return email[:255]


def normalize_delay_seconds(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise NotifySettingsError("Thời gian chờ không hợp lệ.", code="invalid_delay") from exc
    if n not in ALLOWED_DELAY_SECONDS:
        raise NotifySettingsError("Thời gian chờ phải là ngay, 2, 5 hoặc 10 phút.", code="invalid_delay")
    return n


def get_setting_row(
    db: Session, *, user_id: int, organization_id: int
) -> ChatbotEmailNotifySetting | None:
    return db.execute(
        select(ChatbotEmailNotifySetting).where(
            ChatbotEmailNotifySetting.organization_id == int(organization_id),
            ChatbotEmailNotifySetting.user_id == int(user_id),
        )
    ).scalar_one_or_none()


def resolve_notify_prefs(
    db: Session,
    *,
    user_id: int,
    organization_id: int | None = None,
    owner: User | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id) if organization_id else personal_organization_id(uid)
    row = get_setting_row(db, user_id=uid, organization_id=oid)
    if owner is None:
        owner = db.get(User, uid)
    account_email = str(getattr(owner, "email", "") or "").strip() if owner is not None else ""
    custom = str(row.notify_email or "").strip() if row is not None else ""
    enabled = True if row is None else bool(row.enabled)
    delay = int(row.delay_seconds) if row is not None else DEFAULT_DELAY_SECONDS
    if delay not in ALLOWED_DELAY_SECONDS:
        delay = DEFAULT_DELAY_SECONDS
    notify_email = custom or account_email
    return {
        "enabled": enabled,
        "notify_email": notify_email,
        "notify_email_custom": bool(custom),
        "delay_seconds": delay,
        "organization_id": oid,
        "user_id": uid,
        "account_email": account_email,
    }


def save_notify_settings(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    enabled: bool | None = None,
    notify_email: str | None = None,
    delay_seconds: int | None = None,
    owner: User | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    row = get_setting_row(db, user_id=uid, organization_id=oid)
    if owner is None:
        owner = db.get(User, uid)
    account_email = str(getattr(owner, "email", "") or "").strip().lower() if owner is not None else ""
    if row is None:
        row = ChatbotEmailNotifySetting(
            organization_id=oid,
            user_id=uid,
            enabled=True,
            notify_email=None,
            delay_seconds=DEFAULT_DELAY_SECONDS,
        )
        db.add(row)

    if enabled is not None:
        row.enabled = bool(enabled)
    if delay_seconds is not None:
        row.delay_seconds = normalize_delay_seconds(delay_seconds)
    if notify_email is not None:
        raw = str(notify_email).strip()
        if not raw:
            row.notify_email = None
        else:
            email = validate_email(raw)
            row.notify_email = None if account_email and email == account_email else email
    row.updated_at = _now()
    if commit:
        db.commit()
        db.refresh(row)

    if enabled is False:
        from app.services.chatbot_cskh_email_notify import cancel_pending_jobs_for_owner

        cancel_pending_jobs_for_owner(
            db, user_id=uid, organization_id=oid, reason="disabled", commit=commit
        )

    return resolve_notify_prefs(db, user_id=uid, organization_id=oid, owner=owner)


def append_notify_log(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    status: str,
    conversation_id: int | None = None,
    job_id: int | None = None,
    detail: str | None = None,
    recipient: str | None = None,
    commit: bool = False,
) -> ChatbotEmailNotifyLog | None:
    code = str(status or "").strip().lower()
    if code not in LOG_STATUSES:
        return None
    row = ChatbotEmailNotifyLog(
        organization_id=int(organization_id),
        user_id=int(user_id),
        conversation_id=int(conversation_id) if conversation_id else None,
        job_id=int(job_id) if job_id else None,
        status=code,
        detail=sanitize_log_detail(detail),
        recipient=(str(recipient).strip()[:255] or None) if recipient else None,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def log_status_for_skip_reason(reason: str) -> str | None:
    raw = str(reason or "").strip().lower()
    if raw in {"already_read", "already_replied", "read"}:
        return LOG_SKIPPED_READ
    if raw in {"disabled", "skipped_disabled"}:
        return LOG_SKIPPED_DISABLED
    if raw in {"sent"}:
        return LOG_SENT
    return None
