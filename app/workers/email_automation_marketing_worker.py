"""Celery tasks for Email Automation + Email Marketing."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.queue.celery_app import celery_app
from app.services.email_automation_marketing_engine import build_outbox_email_html
from app.services.mail_smtp import send_email
from app.models.email_automation_marketing import (
    AUTOMATION_EMAIL_TYPES,
    CAMPAIGN_STATUS_CANCELLED,
    CAMPAIGN_STATUS_FAILED,
    CAMPAIGN_STATUS_SCHEDULED,
    CAMPAIGN_STATUS_SENDING,
    CAMPAIGN_STATUS_SENT,
    EmailAutomationTemplate,
    EmailMarketingCampaign,
    EmailMarketingUnsubscribe,
    EmailSend,
    EmailSendLog,
)
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.models.user import User


_LOG = logging.getLogger(__name__)

TASK_AUTOMATION_TICK = "email.automation_tick"
TASK_AUTOMATION_SEND = "email.send_outbox"
TASK_MARKETING_TICK = "email.marketing_tick"
TASK_MARKETING_SEND_CAMPAIGN = "email.send_campaign"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_utc(d: datetime | None = None) -> date:
    x = d or _utc_now()
    return x.astimezone(timezone.utc).date()


def _subscription_statuses_for_due() -> tuple[str, ...]:
    # Keep broad coverage; `renewed` check is done before sending.
    return ("trialing", "active", "expired")


def _is_renewed_after(db: SessionLocal, *, user_id: int, expiry_date: date) -> bool:
    # Renewed if user has any still-active subscription ending after this expiry_date.
    row = (
        db.execute(
            text(
                "SELECT MAX(current_period_end) AS mx "
                "FROM subscriptions "
                "WHERE user_id = :uid AND status IN ('trialing','active')"
            ),
            {"uid": int(user_id)},
        ).first()
        or None
    )
    mx = row[0] if row else None
    if not mx:
        return False
    try:
        d = mx.date() if isinstance(mx, datetime) else date.fromisoformat(str(mx)[:10])
    except Exception:
        return False
    return d > expiry_date


def _user_name_from_email(email: str) -> str:
    raw = str(email or "").strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    raw = raw.replace(".", " ").replace("_", " ").replace("-", " ")
    raw = " ".join(x for x in raw.split() if x)
    return raw[:120]


def _enqueue_send(outbox_id: int, *, countdown: int = 0) -> None:
    # Defer to worker queue (not API thread).
    email_send_outbox_task.apply_async(args=[int(outbox_id)], countdown=max(0, int(countdown)))


def _create_outbox_if_needed_automation(
    db,
    *,
    owner_user_id: int,
    recipient_user_id: int,
    recipient_email: str,
    recipient_name: str,
    plan_name: str,
    expiry_date: date,
    email_type: str,
) -> EmailSend | None:
    event_token = uuid.uuid4().hex
    outbox = EmailSend(
        owner_user_id=int(owner_user_id),
        campaign_id=None,
        recipient_user_id=int(recipient_user_id),
        recipient_email=str(recipient_email).strip().lower(),
        recipient_name=str(recipient_name).strip() or None,
        automation_email_type=str(email_type),
        plan_name=str(plan_name or "").strip() or None,
        expiry_date=expiry_date,
        status="queued",
        max_retries=3,
        attempt_count=0,
        event_token=event_token,
        unsub_token=None,
        click_target_url=None,
        discount_code=None,
    )
    db.add(outbox)
    try:
        db.commit()
        db.refresh(outbox)
        db.add(
            EmailSendLog(
                owner_user_id=int(owner_user_id),
                email_send_id=int(outbox.id),
                recipient_email=str(outbox.recipient_email or ""),
                status="queued",
                detail=f"automation:{email_type}",
            )
        )
        db.commit()
        return outbox
    except IntegrityError:
        db.rollback()
        return None


def _mark_failed(db, outbox: EmailSend, *, last_error: str) -> None:
    now = _utc_now()
    err = str(last_error or "")
    is_bounce = any(x in err.lower() for x in ("bounce", "hard bounce", "mailbox_unavailable", "550 ", "551 ", "553 "))
    outbox.status = "bounced" if is_bounce else "failed"
    outbox.last_error = err[:200] if err else None
    outbox.failed_at = now
    if is_bounce and hasattr(outbox, "bounced_at"):
        try:
            outbox.bounced_at = now
        except Exception:
            pass
    db.add(
        EmailSendLog(
            owner_user_id=int(outbox.owner_user_id),
            email_send_id=int(outbox.id),
            recipient_email=str(outbox.recipient_email or ""),
            status=outbox.status,
            detail="max_retries",
        )
    )
    db.commit()


@celery_app.task(bind=True, name=TASK_AUTOMATION_SEND, acks_late=True, max_retries=3)
def email_send_outbox_task(self, outbox_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        outbox = db.get(EmailSend, int(outbox_id))
        if outbox is None:
            return {"ok": False, "reason": "outbox_not_found"}
        if outbox.status not in {"queued", "failed"}:
            return {"ok": True, "reason": "skipped_status", "status": outbox.status}

        if outbox.automation_email_type and outbox.expiry_date:
            renewed = _is_renewed_after(db, user_id=int(outbox.recipient_user_id or 0), expiry_date=outbox.expiry_date)
            if renewed:
                outbox.status = "failed"
                outbox.last_error = "renewed_skip"
                outbox.failed_at = _utc_now()
                db.add(
                    EmailSendLog(
                        owner_user_id=int(outbox.owner_user_id),
                        email_send_id=int(outbox.id),
                        recipient_email=str(outbox.recipient_email or ""),
                        status="failed",
                        detail="renewed_skip",
                    )
                )
                db.commit()
                return {"ok": True, "reason": "renewed_skip"}

        # Render and send.
        email_parts = build_outbox_email_html(db, outbox)
        provider = send_email(
            to=outbox.recipient_email,
            subject=email_parts["subject"],
            html_body=email_parts["html"],
            text_body=email_parts["text"],
            idempotency_key=f"email-outbox-{outbox.id}",
        )

        now = _utc_now()
        outbox.status = "sent"
        outbox.sent_at = now
        db.add(
            EmailSendLog(
                owner_user_id=int(outbox.owner_user_id),
                email_send_id=int(outbox.id),
                recipient_email=str(outbox.recipient_email or ""),
                status="sent",
                detail=f"provider={provider.get('provider') if isinstance(provider, dict) else ''}",
            )
        )
        db.commit()

        outbox.status = "delivered"
        outbox.delivered_at = now
        outbox.last_error = None
        db.add(
            EmailSendLog(
                owner_user_id=int(outbox.owner_user_id),
                email_send_id=int(outbox.id),
                recipient_email=str(outbox.recipient_email or ""),
                status="delivered",
                detail=f"provider={provider.get('provider') if isinstance(provider, dict) else ''}",
            )
        )
        db.commit()
        return {"ok": True, "reason": "delivered", "provider": provider.get("provider")}
    except RuntimeError as exc:
        # Retry with bounded attempts.
        now = _utc_now()
        outbox = None
        try:
            outbox = db.get(EmailSend, int(outbox_id))
        except Exception:
            pass
        if outbox is not None:
            outbox.attempt_count = int(outbox.attempt_count or 0) + 1
            db.add(
                EmailSendLog(
                    owner_user_id=int(outbox.owner_user_id),
                    email_send_id=int(outbox.id),
                    recipient_email=str(outbox.recipient_email or ""),
                    status="failed",
                    detail="retrying",
                )
            )
            db.commit()
            if int(outbox.attempt_count) >= int(outbox.max_retries or 3):
                _mark_failed(db, outbox, last_error=str(exc))
                return {"ok": False, "reason": "max_retries_failed"}
        raise self.retry(exc=exc, countdown=30) from exc
    except Exception as exc:
        now = _utc_now()
        outbox = None
        try:
            outbox = db.get(EmailSend, int(outbox_id))
        except Exception:
            pass
        if outbox is not None:
            outbox.attempt_count = int(outbox.attempt_count or 0) + 1
            outbox.status = "failed"
            outbox.failed_at = now
            outbox.last_error = str(exc)[:200]
            db.add(
                EmailSendLog(
                    owner_user_id=int(outbox.owner_user_id),
                    email_send_id=int(outbox.id),
                    recipient_email=str(outbox.recipient_email or ""),
                    status="failed",
                    detail="fatal",
                )
            )
            db.commit()
        raise
    finally:
        db.close()


def _iterate_due_expiry_subscriptions(db, *, expiry_date: date) -> list[Subscription]:
    return (
        db.execute(
            select(Subscription).where(
                func.date(Subscription.current_period_end) == expiry_date.isoformat(),
                Subscription.status.in_(tuple(_subscription_statuses_for_due())),
            )
        )
        .scalars()
        .all()
    )


def _owners_with_type(db, email_type: str) -> list[int]:
    return [
        int(x)
        for x in db.execute(
            select(func.distinct(EmailAutomationTemplate.owner_user_id)).where(
                EmailAutomationTemplate.enabled.is_(True),
                EmailAutomationTemplate.email_type == str(email_type),
            )
        )
        .scalars()
        .all()
    ]


def _user_plan_and_expiry(db, user_id: int) -> tuple[str, date | None]:
    row = db.execute(
        text(
            "SELECT p.name, s.current_period_end FROM subscriptions s "
            "JOIN plans p ON p.id=s.plan_id WHERE s.user_id=:uid "
            "ORDER BY s.current_period_end DESC LIMIT 1"
        ),
        {"uid": int(user_id)},
    ).first()
    if not row:
        return "SEOAuto plan", None
    plan_name = str(row[0] or "") or "SEOAuto plan"
    exp_dt = row[1]
    exp_date = exp_dt.date() if isinstance(exp_dt, datetime) else None
    return plan_name, exp_date


def _enqueue_user_automation(
    db,
    *,
    owner_id: int,
    user: User,
    email_type: str,
    expiry_date: date,
) -> EmailSend | None:
    email = str(user.email or "").strip().lower()
    if not email or "@" not in email:
        return None
    plan_name, _exp = _user_plan_and_expiry(db, int(user.id))
    return _create_outbox_if_needed_automation(
        db,
        owner_user_id=int(owner_id),
        recipient_user_id=int(user.id),
        recipient_email=email,
        recipient_name=_user_name_from_email(email),
        plan_name=plan_name,
        expiry_date=expiry_date,
        email_type=email_type,
    )


def _enqueue_extended_automations(db, *, now_d: date) -> dict[str, int]:
    created = 0
    enqueued = 0

    def _push(outbox: EmailSend | None) -> None:
        nonlocal created, enqueued
        if outbox is None:
            return
        created += 1
        _enqueue_send(outbox.id)
        enqueued += 1

    # welcome — users created today
    for owner_id in _owners_with_type(db, "welcome"):
        users = (
            db.execute(
                select(User).where(
                    User.status == "active",
                    func.date(User.created_at) == now_d.isoformat(),
                )
            )
            .scalars()
            .all()
        )
        for u in users:
            _push(_enqueue_user_automation(db, owner_id=owner_id, user=u, email_type="welcome", expiry_date=now_d))

    # trial ending in 3 days
    trial_d = now_d + timedelta(days=3)
    for owner_id in _owners_with_type(db, "trial_ending"):
        subs = _iterate_due_expiry_subscriptions(db, expiry_date=trial_d)
        for sub in subs:
            if str(sub.status) != "trialing" or sub.user_id is None:
                continue
            user = db.get(User, int(sub.user_id))
            if user is None:
                continue
            _push(
                _enqueue_user_automation(
                    db, owner_id=owner_id, user=user, email_type="trial_ending", expiry_date=trial_d
                )
            )

    # expired today (period ended yesterday, still expired)
    expired_d = now_d - timedelta(days=1)
    for owner_id in _owners_with_type(db, "expired"):
        subs = (
            db.execute(
                select(Subscription).where(
                    func.date(Subscription.current_period_end) == expired_d.isoformat(),
                    Subscription.status == "expired",
                )
            )
            .scalars()
            .all()
        )
        for sub in subs:
            if sub.user_id is None:
                continue
            user = db.get(User, int(sub.user_id))
            if user is None:
                continue
            _push(
                _enqueue_user_automation(
                    db, owner_id=owner_id, user=user, email_type="expired", expiry_date=expired_d
                )
            )

    for owner_id in _owners_with_type(db, "low_credit"):
        users = (
            db.execute(select(User).where(User.status == "active", User.credit_balance < 50))
            .scalars()
            .all()
        )
        for u in users:
            _push(_enqueue_user_automation(db, owner_id=owner_id, user=u, email_type="low_credit", expiry_date=now_d))

    try:
        from app.models.payment_order import PaymentOrder
    except Exception:
        PaymentOrder = None  # type: ignore[misc, assignment]

    if PaymentOrder is not None:
        try:
            for owner_id in _owners_with_type(db, "payment_success"):
                orders = (
                    db.execute(
                        select(PaymentOrder).where(
                            PaymentOrder.status == "paid",
                            PaymentOrder.paid_at.is_not(None),
                            func.date(PaymentOrder.paid_at) == now_d.isoformat(),
                        )
                    )
                    .scalars()
                    .all()
                )
                seen: set[int] = set()
                for od in orders:
                    uid = int(od.user_id)
                    if uid in seen:
                        continue
                    seen.add(uid)
                    user = db.get(User, uid)
                    if user is None:
                        continue
                    _push(
                        _enqueue_user_automation(
                            db, owner_id=owner_id, user=user, email_type="payment_success", expiry_date=now_d
                        )
                    )
            for owner_id in _owners_with_type(db, "payment_fail"):
                orders = (
                    db.execute(
                        select(PaymentOrder).where(
                            PaymentOrder.status == "failed",
                            func.date(PaymentOrder.updated_at) == now_d.isoformat(),
                        )
                    )
                    .scalars()
                    .all()
                )
                seen_f: set[int] = set()
                for od in orders:
                    uid = int(od.user_id)
                    if uid in seen_f:
                        continue
                    seen_f.add(uid)
                    user = db.get(User, uid)
                    if user is None:
                        continue
                    _push(
                        _enqueue_user_automation(
                            db, owner_id=owner_id, user=user, email_type="payment_fail", expiry_date=now_d
                        )
                    )
        except Exception:
            _LOG.debug("payment automation skipped", exc_info=True)

    inactive_before = now_d - timedelta(days=14)
    for owner_id in _owners_with_type(db, "inactive_user"):
        users = (
            db.execute(
                select(User).where(
                    User.status == "active",
                    func.date(User.created_at) <= inactive_before.isoformat(),
                )
            )
            .scalars()
            .all()
        )
        for u in users:
            live = db.execute(
                text(
                    "SELECT 1 FROM subscriptions WHERE user_id=:uid "
                    "AND status IN ('trialing','active') AND current_period_end > :now LIMIT 1"
                ),
                {"uid": int(u.id), "now": _utc_now()},
            ).first()
            if live:
                continue
            # Dedupe once-ever via created_at date
            created_d = u.created_at.date() if isinstance(u.created_at, datetime) else now_d
            _push(
                _enqueue_user_automation(
                    db, owner_id=owner_id, user=u, email_type="inactive_user", expiry_date=created_d
                )
            )

    return {"created": created, "enqueued": enqueued}


@celery_app.task(bind=True, name=TASK_AUTOMATION_TICK, acks_late=True, max_retries=1)
def email_automation_tick_task(self) -> dict[str, Any]:
    from app.services.celery_beat_lock import acquire_beat_tick_lock

    if not acquire_beat_tick_lock(TASK_AUTOMATION_TICK):
        return {"ok": True, "skipped": "beat_lock"}
    db = SessionLocal()
    try:
        now_d = _date_utc()

        # email_type -> target expiry_date
        due_map: dict[str, date] = {
            "exp_before_7": now_d + timedelta(days=7),
            "exp_before_3": now_d + timedelta(days=3),
            "exp_before_1": now_d + timedelta(days=1),
            "exp_on": now_d,
            "exp_after_3": now_d - timedelta(days=3),
        }

        # Only run enabled templates.
        tpl_owners = (
            db.execute(
                select(func.distinct(EmailAutomationTemplate.owner_user_id)).where(
                    EmailAutomationTemplate.enabled.is_(True),
                    EmailAutomationTemplate.email_type.in_(tuple(AUTOMATION_EMAIL_TYPES)),
                )
            )
            .scalars()
            .all()
        )

        enqueued = 0
        created = 0
        for owner_id in tpl_owners:
            for email_type, expiry_date in due_map.items():
                tpl_ok = (
                    db.execute(
                        select(EmailAutomationTemplate.id).where(
                            EmailAutomationTemplate.owner_user_id == int(owner_id),
                            EmailAutomationTemplate.email_type == str(email_type),
                            EmailAutomationTemplate.enabled.is_(True),
                        )
                    ).first()
                    is not None
                )
                if not tpl_ok:
                    continue
                subs = _iterate_due_expiry_subscriptions(db, expiry_date=expiry_date)
                # Dedupe: same due subscription can be found multiple times per owner.
                for sub in subs:
                    if sub.user_id is None:
                        continue
                    # Skip if renewed.
                    if _is_renewed_after(db, user_id=int(sub.user_id), expiry_date=expiry_date):
                        continue

                    # Pull user email/name.
                    user_row = db.execute(
                        text("SELECT email FROM users WHERE id=:uid"),
                        {"uid": int(sub.user_id)},
                    ).first()
                    if not user_row:
                        continue
                    recipient_email = str(user_row[0] or "").strip().lower()
                    if not recipient_email or "@" not in recipient_email:
                        continue
                    recipient_name = _user_name_from_email(recipient_email)
                    plan_name_row = db.execute(
                        text("SELECT name FROM plans WHERE id=:pid"),
                        {"pid": int(sub.plan_id)},
                    ).first()
                    plan_name = str(plan_name_row[0] or "") if plan_name_row else ""
                    if not plan_name:
                        plan_name = "SEOAuto plan"

                    outbox = _create_outbox_if_needed_automation(
                        db,
                        owner_user_id=int(owner_id),
                        recipient_user_id=int(sub.user_id),
                        recipient_email=recipient_email,
                        recipient_name=recipient_name,
                        plan_name=plan_name,
                        expiry_date=expiry_date,
                        email_type=email_type,
                    )
                    if outbox is not None:
                        created += 1
                        _enqueue_send(outbox.id)
                        enqueued += 1

        extra = _enqueue_extended_automations(db, now_d=now_d)
        created += int(extra.get("created") or 0)
        enqueued += int(extra.get("enqueued") or 0)

        return {"ok": True, "created": created, "enqueued": enqueued}
    finally:
        db.close()


def _list_recipients_for_campaign(db, *, campaign: EmailMarketingCampaign) -> list[dict[str, Any]]:
    """Return [{user_id, email, name, plan_name, expiry_date}].

    If campaign already has EmailSend rows (admin picked specific recipients),
    only those are returned — never expand to the full segment.
    """
    from app.services.email_automation_marketing_engine import list_segment_recipients

    preseeded = (
        db.execute(
            select(EmailSend).where(EmailSend.campaign_id == int(campaign.id))
        )
        .scalars()
        .all()
    )
    if preseeded:
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in preseeded:
            uid = int(row.recipient_user_id or 0)
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            email = str(row.recipient_email or "").strip().lower()
            if not email or "@" not in email:
                continue
            out.append(
                {
                    "user_id": uid or 0,
                    "email": email,
                    "name": row.recipient_name or _user_name_from_email(email),
                    "plan_name": row.plan_name or "SEOAuto plan",
                    "expiry_date": row.expiry_date,
                }
            )
        return out

    rows = list_segment_recipients(
        db,
        segment_kind=str(campaign.segment_kind or "all"),
        segment_plan_id=int(campaign.segment_plan_id) if campaign.segment_plan_id else None,
        limit=2000,
    )
    out2: list[dict[str, Any]] = []
    for r in rows:
        out2.append(
            {
                "user_id": int(r["user_id"]),
                "email": r["email"],
                "name": r["name"],
                "plan_name": r["plan_name"],
                "expiry_date": r.get("expiry_date_obj"),
            }
        )
    return out2


@celery_app.task(bind=True, name=TASK_MARKETING_SEND_CAMPAIGN, acks_late=True, max_retries=2)
def email_marketing_send_campaign_task(self, campaign_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        camp = db.get(EmailMarketingCampaign, int(campaign_id))
        if camp is None:
            return {"ok": False, "reason": "campaign_not_found"}
        if str(camp.status) == CAMPAIGN_STATUS_CANCELLED:
            return {"ok": True, "reason": "cancelled"}
        if str(camp.status) == CAMPAIGN_STATUS_SENDING:
            # Another worker already claimed this campaign.
            pass

        camp.status = CAMPAIGN_STATUS_SENDING
        db.commit()

        recipients = _list_recipients_for_campaign(db, campaign=camp)
        created = 0
        sent = 0
        failed = 0

        for rcpt in recipients:
            email = rcpt["email"]
            owner_id = int(camp.owner_user_id)

            # Unsubscribe check.
            unsub = db.execute(
                select(EmailMarketingUnsubscribe).where(
                    EmailMarketingUnsubscribe.owner_user_id == owner_id,
                    EmailMarketingUnsubscribe.recipient_email == email,
                )
            ).scalar_one_or_none()

            if unsub is not None and unsub.unsubscribed_at is not None:
                continue

            if unsub is None:
                unsub = EmailMarketingUnsubscribe(
                    owner_user_id=owner_id,
                    recipient_email=email,
                    unsub_token=uuid.uuid4().hex,
                    unsubscribed_at=None,
                )
                db.add(unsub)
                db.commit()
                db.refresh(unsub)

            event_token = uuid.uuid4().hex
            outbox = EmailSend(
                owner_user_id=owner_id,
                campaign_id=int(camp.id),
                recipient_user_id=int(rcpt["user_id"]),
                recipient_email=email,
                recipient_name=rcpt["name"],
                automation_email_type=None,
                plan_name=rcpt["plan_name"],
                expiry_date=rcpt["expiry_date"],
                discount_code=camp.discount_code,
                status="queued",
                attempt_count=0,
                max_retries=3,
                event_token=event_token,
                unsub_token=unsub.unsub_token,
                click_target_url=None,
            )
            db.add(outbox)
            is_new = True
            try:
                db.commit()
                db.refresh(outbox)
                db.add(
                    EmailSendLog(
                        owner_user_id=int(outbox.owner_user_id),
                        email_send_id=int(outbox.id),
                        recipient_email=str(outbox.recipient_email or ""),
                        status="queued",
                        detail=f"marketing:{camp.id}",
                    )
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                is_new = False
                # Existing outbox: try to resend if it was never successfully delivered yet.
                outbox = (
                    db.execute(
                        select(EmailSend).where(
                            EmailSend.owner_user_id == owner_id,
                            EmailSend.campaign_id == int(camp.id),
                            EmailSend.recipient_email == email,
                        )
                    )
                    .scalars()
                    .first()
                )
                if outbox is None:
                    continue
                if outbox.status not in {"queued", "failed"}:
                    continue
                if int(outbox.attempt_count or 0) >= int(outbox.max_retries or 3):
                    continue
            if is_new:
                created += 1

            # Send immediately in this worker task (with bounded retry).
            max_attempts = int(outbox.max_retries or 3)
            while True:
                try:
                    email_parts = build_outbox_email_html(db, outbox)
                    send_email(
                        to=outbox.recipient_email,
                        subject=email_parts["subject"],
                        html_body=email_parts["html"],
                        text_body=email_parts["text"],
                        idempotency_key=f"email-outbox-{outbox.id}",
                    )
                    now = _utc_now()
                    outbox.status = "sent"
                    outbox.sent_at = now
                    db.add(
                        EmailSendLog(
                            owner_user_id=int(outbox.owner_user_id),
                            email_send_id=int(outbox.id),
                            recipient_email=str(outbox.recipient_email or ""),
                            status="sent",
                            detail="provider=ok",
                        )
                    )
                    db.commit()

                    outbox.status = "delivered"
                    outbox.delivered_at = now
                    outbox.last_error = None
                    db.add(
                        EmailSendLog(
                            owner_user_id=int(outbox.owner_user_id),
                            email_send_id=int(outbox.id),
                            recipient_email=str(outbox.recipient_email or ""),
                            status="delivered",
                            detail="provider=ok",
                        )
                    )
                    db.commit()
                    sent += 1
                    break
                except Exception as exc:
                    db.rollback()
                    outbox = db.get(EmailSend, int(outbox.id))
                    if outbox is None:
                        failed += 1
                        break

                    outbox.attempt_count = int(outbox.attempt_count or 0) + 1
                    outbox.last_error = str(exc)[:200]

                    if int(outbox.attempt_count) >= max_attempts:
                        outbox.status = "failed"
                        outbox.failed_at = _utc_now()
                        db.add(
                            EmailSendLog(
                                owner_user_id=int(outbox.owner_user_id),
                                email_send_id=int(outbox.id),
                                recipient_email=str(outbox.recipient_email or ""),
                                status="failed",
                                detail="send_exception",
                            )
                        )
                        db.commit()
                        failed += 1
                        break
                    else:
                        # Keep for later retry; worker loop will retry again now.
                        outbox.status = "queued"
                        db.commit()
                        continue

        camp = db.get(EmailMarketingCampaign, int(campaign_id))
        if camp is not None and str(camp.status) != CAMPAIGN_STATUS_CANCELLED:
            if failed and sent == 0:
                camp.status = CAMPAIGN_STATUS_FAILED
            else:
                camp.status = CAMPAIGN_STATUS_SENT
            db.commit()
        return {"ok": True, "created": created, "sent": sent, "failed": failed, "campaign_id": int(campaign_id)}
    finally:
        db.close()


@celery_app.task(bind=True, name=TASK_MARKETING_TICK, acks_late=True, max_retries=1)
def email_marketing_tick_task(self) -> dict[str, Any]:
    from app.services.celery_beat_lock import acquire_beat_tick_lock

    if not acquire_beat_tick_lock(TASK_MARKETING_TICK):
        return {"ok": True, "skipped": "beat_lock"}
    db = SessionLocal()
    try:
        now = _utc_now()
        due = db.execute(
            select(EmailMarketingCampaign).where(
                EmailMarketingCampaign.status == CAMPAIGN_STATUS_SCHEDULED,
                EmailMarketingCampaign.scheduled_at.is_not(None),
                EmailMarketingCampaign.scheduled_at <= now,
            )
        ).scalars().all()

        enqueued = 0
        for c in due:
            if str(c.status) == CAMPAIGN_STATUS_CANCELLED:
                continue
            # scheduled -> sending to avoid duplicate ticks.
            c.status = CAMPAIGN_STATUS_SENDING
            db.commit()
            email_marketing_send_campaign_task.apply_async(args=[int(c.id)], countdown=0)
            enqueued += 1
        return {"ok": True, "enqueued": enqueued}
    finally:
        db.close()

