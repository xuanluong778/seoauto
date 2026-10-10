"""Unread inbound email notifications for Chatbot CSKH (Resend, delayed, batched)."""

from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot, ChatbotConversation, ChatbotEmailNotifyJob, ChatbotMessage
from app.models.user import User
from app.services.chatbot_cskh_email_settings import (
    LOG_FAILED,
    LOG_QUEUED,
    LOG_SENT,
    LOG_SKIPPED_DISABLED,
    LOG_SKIPPED_READ,
    append_notify_log,
    log_status_for_skip_reason,
    resolve_notify_prefs,
    sanitize_log_detail,
)
from app.services.tenant_org import personal_organization_id

_LOG = logging.getLogger(__name__)

CUSTOMER_ROLES = frozenset({"user"})
STAFF_ROLES = frozenset({"staff", "admin", "agent"})
ASSISTANT_ROLES = frozenset({"assistant", "bot", "chatbot"})

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_SENT = "sent"
STATUS_CANCELLED = "cancelled"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def delay_seconds() -> int:
    try:
        return max(0, int(os.getenv("CHATBOT_NOTIFY_DELAY_SECONDS", "120") or 120))
    except (TypeError, ValueError):
        return 120


def cooldown_seconds() -> int:
    try:
        return max(0, int(os.getenv("CHATBOT_NOTIFY_COOLDOWN_SECONDS", "900") or 900))
    except (TypeError, ValueError):
        return 900


def org_id_for_conversation(conv: ChatbotConversation) -> int:
    if conv.organization_id:
        try:
            return int(conv.organization_id)
        except (TypeError, ValueError):
            pass
    return personal_organization_id(int(conv.user_id))


def is_customer_inbound(role: str) -> bool:
    return str(role or "").strip().lower() in CUSTOMER_ROLES


def is_staff_outbound(role: str) -> bool:
    return str(role or "").strip().lower() in STAFF_ROLES


def is_chatbot_outbound(role: str) -> bool:
    return str(role or "").strip().lower() in ASSISTANT_ROLES


def _pick_env(key: str, default: str = "") -> str:
    """Non-empty env.local wins; empty file keys must not wipe process env (PM2 secrets)."""
    try:
        from pathlib import Path

        from dotenv import dotenv_values

        path = Path(__file__).resolve().parents[2] / "env.local"
        file_vals = dotenv_values(path) if path.is_file() else {}
        file_v = str(file_vals.get(key) or "").strip()
        if file_v:
            return file_v
    except Exception:
        pass
    return (os.getenv(key) or default).strip()


def _resend_settings() -> dict[str, str]:
    from app.core.settings import get_resend_settings

    cfg = get_resend_settings()
    from_email = (
        str(cfg.get("from_email") or "").strip()
        or _pick_env("SMTP_FROM_EMAIL")
        or "SEOAuto <no-reply@mail.seoauto.vn>"
    )
    return {
        "api_key": str(cfg.get("api_key") or ""),
        "from_email": from_email,
        "app_base": (_pick_env("APP_BASE_URL") or "https://seoauto.vn").rstrip("/"),
    }


def conversation_inbox_url(conversation_id: int) -> str:
    base = _resend_settings()["app_base"]
    return f"{base}/chatbot-cskh?tab=conversations&conversation_id={int(conversation_id)}"


def unread_customer_messages(db: Session, conversation_id: int, *, user_id: int) -> list[ChatbotMessage]:
    return list(
        db.execute(
            select(ChatbotMessage)
            .where(
                ChatbotMessage.conversation_id == int(conversation_id),
                ChatbotMessage.user_id == int(user_id),
                ChatbotMessage.role.in_(tuple(CUSTOMER_ROLES)),
                ChatbotMessage.read_at.is_(None),
            )
            .order_by(ChatbotMessage.created_at.asc())
        ).scalars().all()
    )


def mark_conversation_read(db: Session, user_id: int, conversation_id: int, *, commit: bool = True) -> int:
    """Staff opened the inbox thread — customer inbound is READ."""
    now = _now()
    result = db.execute(
        update(ChatbotMessage)
        .where(
            ChatbotMessage.conversation_id == int(conversation_id),
            ChatbotMessage.user_id == int(user_id),
            ChatbotMessage.role.in_(tuple(CUSTOMER_ROLES)),
            ChatbotMessage.read_at.is_(None),
        )
        .values(read_at=now)
    )
    n = int(result.rowcount or 0)
    cancel_pending_jobs(db, user_id=int(user_id), conversation_id=int(conversation_id), reason="already_read")
    if commit:
        db.commit()
        try:
            from app.services.chatbot_cskh_inbox_realtime import publish_inbox_read
            from app.services.chatbot_cskh_inbox_service import count_unread_conversations

            publish_inbox_read(
                int(user_id),
                int(conversation_id),
                count_unread_conversations(db, int(user_id)),
            )
        except Exception:
            _LOG.exception("inbox ws read publish failed conv=%s", conversation_id)
    return n


def cancel_pending_jobs(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    reason: str,
) -> int:
    rows = list(
        db.execute(
            select(ChatbotEmailNotifyJob).where(
                ChatbotEmailNotifyJob.user_id == int(user_id),
                ChatbotEmailNotifyJob.conversation_id == int(conversation_id),
                ChatbotEmailNotifyJob.status == STATUS_PENDING,
            )
        ).scalars().all()
    )
    n = 0
    log_status = log_status_for_skip_reason(reason)
    for job in rows:
        job.status = STATUS_CANCELLED
        job.skip_reason = str(reason or "cancelled")[:64]
        job.updated_at = _now()
        n += 1
        _revoke_celery(job.celery_task_id)
        if log_status:
            append_notify_log(
                db,
                organization_id=int(job.organization_id),
                user_id=int(job.user_id),
                status=log_status,
                conversation_id=int(job.conversation_id),
                job_id=int(job.id),
                detail=reason,
            )
    return n


def cancel_pending_jobs_for_owner(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    reason: str,
    commit: bool = False,
) -> int:
    rows = list(
        db.execute(
            select(ChatbotEmailNotifyJob).where(
                ChatbotEmailNotifyJob.user_id == int(user_id),
                ChatbotEmailNotifyJob.organization_id == int(organization_id),
                ChatbotEmailNotifyJob.status == STATUS_PENDING,
            )
        ).scalars().all()
    )
    n = 0
    for job in rows:
        n += cancel_pending_jobs(
            db, user_id=int(user_id), conversation_id=int(job.conversation_id), reason=reason
        )
    if commit:
        db.commit()
    return n


def _revoke_celery(task_id: str | None) -> None:
    tid = str(task_id or "").strip()
    if not tid:
        return
    try:
        from celery.result import AsyncResult

        from app.queue.celery_app import celery_app

        AsyncResult(tid, app=celery_app).revoke(terminate=False)
    except Exception:
        _LOG.debug("revoke notify task skipped", exc_info=True)


def _enqueue_celery(job_id: int, countdown: int) -> str | None:
    try:
        from app.workers.chatbot_cskh_notify_worker import enqueue_unread_email_job

        return enqueue_unread_email_job(int(job_id), countdown=max(0, int(countdown)))
    except Exception:
        _LOG.exception("enqueue unread email job failed job_id=%s", job_id)
        return None


def compute_run_after(
    conv: ChatbotConversation,
    *,
    now: datetime | None = None,
    delay_sec: int | None = None,
) -> datetime:
    now = now or _now()
    wait = delay_seconds() if delay_sec is None else max(0, int(delay_sec))
    eta = now + timedelta(seconds=wait)
    last = _aware(conv.last_email_notified_at)
    if last is not None:
        cool = last + timedelta(seconds=cooldown_seconds())
        if cool > eta:
            eta = cool
    return eta


def schedule_unread_email_job(
    db: Session,
    *,
    conversation: ChatbotConversation,
    message: ChatbotMessage,
) -> ChatbotEmailNotifyJob | None:
    """Create at most one pending job per organizationId + conversationId."""
    if not is_customer_inbound(message.role):
        return None
    if is_chatbot_outbound(message.role) or is_staff_outbound(message.role):
        return None

    oid = org_id_for_conversation(conversation)
    uid = int(conversation.user_id)
    cid = int(conversation.id)
    if conversation.organization_id is None:
        conversation.organization_id = oid
    conversation.last_user_message_at = _aware(message.created_at) or _now()

    prefs = resolve_notify_prefs(db, user_id=uid, organization_id=oid)
    if not prefs["enabled"]:
        append_notify_log(
            db,
            organization_id=oid,
            user_id=uid,
            status=LOG_SKIPPED_DISABLED,
            conversation_id=cid,
            detail="disabled",
            commit=True,
        )
        return None

    existing = db.execute(
        select(ChatbotEmailNotifyJob).where(
            ChatbotEmailNotifyJob.organization_id == oid,
            ChatbotEmailNotifyJob.conversation_id == cid,
            ChatbotEmailNotifyJob.status == STATUS_PENDING,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.last_inbound_message_id = int(message.id) if message.id else existing.last_inbound_message_id
        existing.updated_at = _now()
        db.commit()
        db.refresh(existing)
        return existing

    run_after = compute_run_after(conversation, delay_sec=int(prefs["delay_seconds"]))
    countdown = max(0, int((run_after - _now()).total_seconds()))
    job = ChatbotEmailNotifyJob(
        organization_id=oid,
        user_id=uid,
        conversation_id=cid,
        bot_id=int(conversation.bot_id),
        status=STATUS_PENDING,
        run_after=run_after,
        last_inbound_message_id=int(message.id) if message.id else None,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        again = db.execute(
            select(ChatbotEmailNotifyJob).where(
                ChatbotEmailNotifyJob.organization_id == oid,
                ChatbotEmailNotifyJob.conversation_id == cid,
                ChatbotEmailNotifyJob.status == STATUS_PENDING,
            )
        ).scalar_one_or_none()
        if again is not None:
            again.last_inbound_message_id = int(message.id) if message.id else again.last_inbound_message_id
            again.updated_at = _now()
            db.commit()
            return again
        raise
    db.refresh(job)
    task_id = _enqueue_celery(int(job.id), countdown)
    if task_id:
        job.celery_task_id = task_id
        job.updated_at = _now()
    append_notify_log(
        db,
        organization_id=oid,
        user_id=uid,
        status=LOG_QUEUED,
        conversation_id=cid,
        job_id=int(job.id),
        recipient=prefs.get("notify_email") or None,
        detail="queued",
    )
    db.commit()
    db.refresh(job)
    return job


def should_cancel_send(
    db: Session,
    *,
    conversation: ChatbotConversation,
    unread: list[ChatbotMessage],
) -> str | None:
    if not unread:
        return "already_read"
    if str(conversation.status or "").lower() == "handled":
        return "already_replied"
    first = _aware(unread[0].created_at) or _now()
    staff = db.execute(
        select(ChatbotMessage.id)
        .where(
            ChatbotMessage.conversation_id == int(conversation.id),
            ChatbotMessage.user_id == int(conversation.user_id),
            ChatbotMessage.role.in_(tuple(STAFF_ROLES)),
            ChatbotMessage.created_at >= first,
        )
        .limit(1)
    ).first()
    if staff is not None:
        return "already_replied"
    return None


def _channel_label(channel: str) -> str:
    raw = str(channel or "website").strip().lower()
    return {"website": "Website", "facebook": "Facebook", "zalo": "Zalo"}.get(raw, raw or "Website")


def _fmt_vn(dt: datetime | None) -> str:
    d = _aware(dt)
    if d is None:
        return ""
    return d.astimezone(_VN_TZ).strftime("%H:%M %d/%m/%Y")


def build_email_payload(
    *,
    owner: User,
    bot: ChatbotBot | None,
    conversation: ChatbotConversation,
    unread: list[ChatbotMessage],
) -> dict[str, str]:
    visitor = (conversation.visitor_name or "").strip() or "Khách"
    channel = _channel_label(conversation.channel)
    latest = unread[-1] if unread else None
    body = (latest.message if latest else "").strip()
    preview = body if len(body) <= 600 else body[:597] + "…"
    count = len(unread)
    when = _fmt_vn(latest.created_at if latest else conversation.last_user_message_at)
    bot_name = (bot.bot_name if bot else "") or "Chatbot CSKH"
    url = conversation_inbox_url(int(conversation.id))
    subject = f"[SEOAuto] {count} tin nhắn chưa đọc — {visitor} ({channel})"
    safe_visitor = html.escape(visitor)
    safe_channel = html.escape(channel)
    safe_preview = html.escape(preview).replace("\n", "<br>")
    safe_bot = html.escape(bot_name)
    html_body = f"""
<p>Xin chào,</p>
<p>Bạn có tin nhắn mới trên <strong>{safe_bot}</strong> chưa được đọc trên inbox.</p>
<ul>
  <li><strong>Khách:</strong> {safe_visitor}</li>
  <li><strong>Kênh:</strong> {safe_channel}</li>
  <li><strong>Số tin chưa đọc:</strong> {count}</li>
  <li><strong>Thời gian:</strong> {html.escape(when)}</li>
</ul>
<p><strong>Nội dung mới nhất:</strong></p>
<blockquote>{safe_preview}</blockquote>
<p><a href="{html.escape(url)}" style="display:inline-block;padding:10px 16px;background:#2563eb;color:#fff;text-decoration:none;border-radius:8px;">Xem cuộc trò chuyện</a></p>
<p style="color:#64748b;font-size:13px;">Nếu bạn đã đọc hoặc đã trả lời trên SEOAuto, có thể bỏ qua email này.</p>
"""
    text_body = (
        f"Khách: {visitor}\nKênh: {channel}\nChưa đọc: {count}\nThời gian: {when}\n\n"
        f"Nội dung mới nhất:\n{preview}\n\nXem cuộc trò chuyện: {url}\n"
    )
    return {
        "to": str(owner.email or "").strip(),
        "subject": subject,
        "html": html_body.strip(),
        "text": text_body,
    }


def send_resend_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str = "",
    idempotency_key: str = "",
    user_id: int | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    from app.services.mail_smtp import send_email

    return send_email(
        to=to,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        idempotency_key=idempotency_key,
        meter=True,
        user_id=user_id,
        organization_id=organization_id,
        feature_key="email_user_notify",
        request_id=idempotency_key,
    )


def _finish_job(
    db: Session,
    job: ChatbotEmailNotifyJob,
    *,
    status: str,
    reason: str,
    log_status: str | None,
    ok: bool,
    extra: dict[str, Any] | None = None,
    recipient: str | None = None,
) -> dict[str, Any]:
    job.status = status
    job.skip_reason = str(reason or "")[:64] or None
    job.updated_at = _now()
    if log_status:
        append_notify_log(
            db,
            organization_id=int(job.organization_id),
            user_id=int(job.user_id),
            status=log_status,
            conversation_id=int(job.conversation_id),
            job_id=int(job.id),
            detail=sanitize_log_detail(reason),
            recipient=recipient,
        )
    db.commit()
    out: dict[str, Any] = {"ok": ok, "reason": reason}
    if extra:
        out.update(extra)
    return out


def execute_notify_job(
    db: Session,
    job_id: int,
    *,
    send_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    job = db.get(ChatbotEmailNotifyJob, int(job_id))
    if job is None:
        return {"ok": False, "reason": "job_not_found"}
    if job.status == STATUS_SENT:
        return {"ok": True, "reason": "already_sent", "duplicate": True}
    if job.status in (STATUS_CANCELLED, STATUS_SKIPPED, STATUS_FAILED):
        return {"ok": True, "reason": job.skip_reason or job.status, "skipped": True, "duplicate": job.status == STATUS_FAILED}

    if job.status == STATUS_PENDING:
        claimed = db.execute(
            update(ChatbotEmailNotifyJob)
            .where(
                ChatbotEmailNotifyJob.id == int(job.id),
                ChatbotEmailNotifyJob.status == STATUS_PENDING,
            )
            .values(status=STATUS_PROCESSING, updated_at=_now())
        )
        db.commit()
        db.refresh(job)
        if int(claimed.rowcount or 0) == 0:
            if job.status == STATUS_SENT:
                return {"ok": True, "reason": "already_sent", "duplicate": True}
            if job.status in (STATUS_CANCELLED, STATUS_SKIPPED, STATUS_FAILED):
                return {"ok": True, "reason": job.skip_reason or job.status, "skipped": True}
            return {"ok": True, "reason": "in_flight", "duplicate": True}

    conv = db.get(ChatbotConversation, int(job.conversation_id))
    if conv is None:
        return _finish_job(
            db, job, status=STATUS_CANCELLED, reason="conversation_gone", log_status=LOG_FAILED, ok=True, extra={"skipped": True}
        )

    owner_org = personal_organization_id(int(conv.user_id))
    conv_org = org_id_for_conversation(conv)
    if int(job.organization_id) not in (conv_org, owner_org) or int(job.user_id) != int(conv.user_id):
        _LOG.warning(
            "cskh notify tenant mismatch job=%s job_org=%s conv_org=%s job_user=%s conv_user=%s",
            job.id,
            job.organization_id,
            conv_org,
            job.user_id,
            conv.user_id,
        )
        return _finish_job(
            db, job, status=STATUS_SKIPPED, reason="tenant_mismatch", log_status=LOG_FAILED, ok=False
        )

    # Avoid db.get(User, ...) because in some worker environments SQLAlchemy mapper
    # may fail to initialize relationships from User -> Project -> KnowledgeBase.
    # We only need owner.email here.
    from types import SimpleNamespace

    owner_email = (
        db.execute(
            text("SELECT email FROM users WHERE id = :uid"),
            {"uid": int(conv.user_id)},
        ).scalar_one_or_none()
        or ""
    )
    owner = SimpleNamespace(email=owner_email)

    prefs = resolve_notify_prefs(
        db,
        user_id=int(conv.user_id),
        organization_id=int(job.organization_id),
        owner=owner,  # type: ignore[arg-type]
    )
    if not prefs["enabled"]:
        return _finish_job(
            db,
            job,
            status=STATUS_SKIPPED,
            reason="disabled",
            log_status=LOG_SKIPPED_DISABLED,
            ok=True,
            extra={"skipped": True},
        )

    unread = unread_customer_messages(db, int(conv.id), user_id=int(conv.user_id))
    cancel = should_cancel_send(db, conversation=conv, unread=unread)
    if cancel:
        return _finish_job(
            db,
            job,
            status=STATUS_CANCELLED,
            reason=cancel,
            log_status=LOG_SKIPPED_READ,
            ok=True,
            extra={"skipped": True},
        )

    last_sent = _aware(conv.last_email_notified_at)
    if last_sent is not None:
        wait = cooldown_seconds() - (_now() - last_sent).total_seconds()
        if wait > 1:
            return _finish_job(
                db, job, status=STATUS_SKIPPED, reason="cooldown", log_status=None, ok=True, extra={"skipped": True}
            )

    bot = db.get(ChatbotBot, int(conv.bot_id)) if conv.bot_id else None
    recipient = str(prefs.get("notify_email") or "").strip()
    if not recipient:
        return _finish_job(
            db, job, status=STATUS_SKIPPED, reason="no_owner_email", log_status=LOG_FAILED, ok=False
        )

    mail = build_email_payload(
        owner=owner if owner is not None else SimpleNamespace(email=""),
        bot=bot,
        conversation=conv,
        unread=unread,
    )
    mail["to"] = recipient
    sender = send_fn or send_resend_email
    try:
        try:
            sender(
                to=mail["to"],
                subject=mail["subject"],
                html_body=mail["html"],
                text_body=mail["text"],
                idempotency_key=f"cskh-notify-{int(job.id)}",
                user_id=int(job.user_id),
                organization_id=int(job.organization_id),
            )
        except TypeError:
            sender(
                to=mail["to"],
                subject=mail["subject"],
                html_body=mail["html"],
                text_body=mail["text"],
                idempotency_key=f"cskh-notify-{int(job.id)}",
            )
    except RuntimeError as exc:
        reason = sanitize_log_detail(str(exc)) or "send_failed"
        _LOG.warning("cskh notify send failed job=%s reason=%s", job.id, reason)
        extra = {"skipped": False}
        if reason.startswith("missing_resend_api_key"):
            extra["skipped"] = True
        return _finish_job(
            db,
            job,
            status=STATUS_FAILED,
            reason=reason,
            log_status=LOG_FAILED,
            ok=False,
            extra=extra,
            recipient=recipient,
        )

    now = _now()
    job.status = STATUS_SENT
    job.sent_at = now
    job.updated_at = now
    job.skip_reason = None
    conv.last_email_notified_at = now
    append_notify_log(
        db,
        organization_id=int(job.organization_id),
        user_id=int(job.user_id),
        status=LOG_SENT,
        conversation_id=int(conv.id),
        job_id=int(job.id),
        detail="sent",
        recipient=recipient,
    )
    db.commit()
    return {
        "ok": True,
        "reason": "sent",
        "unread_count": len(unread),
        "to": recipient,
        "conversation_id": int(conv.id),
        "organization_id": int(job.organization_id),
        "user_id": int(job.user_id),
    }


def hook_inbound_saved(db: Session, conversation: ChatbotConversation, message: ChatbotMessage) -> None:
    """Call after customer inbound is committed. Never raises into widget path."""
    try:
        schedule_unread_email_job(db, conversation=conversation, message=message)
    except Exception:
        _LOG.exception(
            "schedule unread email failed conv=%s user=%s",
            getattr(conversation, "id", None),
            getattr(conversation, "user_id", None),
        )
    try:
        from app.services.chatbot_cskh_inbox_realtime import publish_inbox_new

        publish_inbox_new(db, conversation, message)
    except Exception:
        _LOG.exception(
            "inbox ws new publish failed conv=%s user=%s",
            getattr(conversation, "id", None),
            getattr(conversation, "user_id", None),
        )
