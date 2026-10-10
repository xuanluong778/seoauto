from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.email_automation_marketing import (
    EmailAutomationTemplate,
    EmailMarketingCampaign,
    EmailMarketingUnsubscribe,
    EmailSend,
    EmailSendLog,
)
from app.workers import email_automation_marketing_worker as worker_mod
from app.routers.email_tracking import track_open, track_click


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Session = sessionmaker(bind=engine)

    # Import models that other mappers reference via string relationships,
    # so SQLAlchemy can resolve all class names.
    import app.models.email_automation_marketing  # noqa: F401
    import app.models.usage_limit  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Plan.__table__,
            Subscription.__table__,
            EmailAutomationTemplate.__table__,
            EmailMarketingCampaign.__table__,
            EmailMarketingUnsubscribe.__table__,
            EmailSend.__table__,
            EmailSendLog.__table__,
        ],
    )

    # Make worker use test SessionLocal
    monkeypatch.setattr(worker_mod, "SessionLocal", Session, raising=False)
    monkeypatch.setenv("APP_BASE_URL", "https://test.local")

    session = Session()
    yield session, engine
    session.close()
    engine.dispose()


def _create_user(session, *, email: str) -> User:
    u = User(
        email=email,
        password_hash="x",
        has_password=True,
        role="user",
        status="active",
        credit_balance=0,
    )
    session.add(u)
    session.flush()
    return u


def _create_plan(session, *, slug: str = "p1", name: str = "Plan 1") -> Plan:
    p = Plan(slug=slug, name=name, price_amount=0)
    session.add(p)
    session.flush()
    return p


def _create_subscription(session, *, user_id: int, plan_id: int, status: str, end_dt: datetime) -> Subscription:
    now = datetime.now(timezone.utc)
    sub = Subscription(
        user_id=int(user_id),
        plan_id=int(plan_id),
        status=status,
        started_at=now - timedelta(days=30),
        current_period_start=now - timedelta(days=30),
        current_period_end=end_dt,
    )
    session.add(sub)
    session.flush()
    return sub


def test_automation_tick_creates_outbox_and_sends(db, monkeypatch):
    session, _engine = db

    # stub sender
    sent: list[dict] = []

    def _send_email(*, to, subject, html_body, text_body, idempotency_key):
        sent.append(
            {"to": to, "subject": subject, "html": html_body, "text": text_body, "idem": idempotency_key}
        )
        return {"ok": True, "provider": "stub", "email_id": "x"}

    monkeypatch.setattr(worker_mod, "send_email", _send_email, raising=True)

    admin = _create_user(session, email="admin@test.local")
    customer = _create_user(session, email="alice@test.local")
    plan = _create_plan(session, slug="plan1", name="SEOPlan")

    expiry = (datetime.now(timezone.utc) + timedelta(days=7)).date()
    end_dt = datetime.combine(expiry, datetime.min.time()).replace(tzinfo=timezone.utc)
    _create_subscription(session, user_id=customer.id, plan_id=plan.id, status="active", end_dt=end_dt)
    session.commit()

    tpl = EmailAutomationTemplate(
        owner_user_id=admin.id,
        email_type="exp_before_7",
        enabled=True,
        name="TPL",
        subject_template="Hi {{name}} — {{plan}}",
        html_body_template="<p>Plan: {{plan}}</p><p>Expiry: {{expiry_date}}</p>",
        text_body_template="Plan {{plan}}. Exp {{expiry_date}}.",
    )
    session.add(tpl)
    session.commit()

    enqueued: list[int] = []
    monkeypatch.setattr(worker_mod, "_enqueue_send", lambda outbox_id, countdown=0: enqueued.append(outbox_id))
    monkeypatch.setattr(
        "app.services.celery_beat_lock.acquire_beat_tick_lock",
        lambda *a, **k: True,
    )

    out = worker_mod.email_automation_tick_task.run()
    assert out["created"] >= 1
    assert len(enqueued) == 1

    outbox_id = enqueued[0]
    worker_mod.email_send_outbox_task.run(outbox_id)

    outbox = session.get(EmailSend, outbox_id)
    assert outbox is not None
    assert outbox.status == "delivered"

    statuses = [r.status for r in session.query(EmailSendLog).filter(EmailSendLog.email_send_id == outbox_id).all()]
    assert "queued" in statuses
    assert "sent" in statuses
    assert "delivered" in statuses

    assert sent and sent[0]["to"] == customer.email.lower()
    assert "{{" not in sent[0]["subject"]


def test_automation_skip_if_renewed_before_send(db, monkeypatch):
    session, _engine = db

    monkeypatch.setattr(worker_mod, "send_email", lambda **kw: {"ok": True, "provider": "stub"}, raising=True)

    admin = _create_user(session, email="admin2@test.local")
    customer = _create_user(session, email="bob@test.local")
    plan = _create_plan(session, slug="plan1", name="SEOPlan")

    expiry = (datetime.now(timezone.utc) + timedelta(days=7)).date()
    end_dt = datetime.combine(expiry, datetime.min.time()).replace(tzinfo=timezone.utc)
    _create_subscription(session, user_id=customer.id, plan_id=plan.id, status="active", end_dt=end_dt)
    session.commit()

    session.add(
        EmailAutomationTemplate(
            owner_user_id=admin.id,
            email_type="exp_before_7",
            enabled=True,
            name="TPL",
            subject_template="S {{name}}",
            html_body_template="<p>{{plan}} {{expiry_date}}</p>",
            text_body_template=None,
        )
    )
    session.commit()

    enqueued: list[int] = []
    monkeypatch.setattr(worker_mod, "_enqueue_send", lambda outbox_id, countdown=0: enqueued.append(outbox_id))
    monkeypatch.setattr(
        "app.services.celery_beat_lock.acquire_beat_tick_lock",
        lambda *a, **k: True,
    )
    worker_mod.email_automation_tick_task.run()

    assert enqueued
    outbox_id = enqueued[0]

    # Renewal: extend period end beyond old expiry
    new_end = datetime.combine(expiry + timedelta(days=30), datetime.min.time()).replace(tzinfo=timezone.utc)
    subs = session.query(Subscription).filter(Subscription.user_id == customer.id).all()
    assert subs
    subs[0].current_period_end = new_end
    session.commit()

    worker_mod.email_send_outbox_task.run(outbox_id)

    outbox = session.get(EmailSend, outbox_id)
    assert outbox.status == "failed"
    assert outbox.last_error == "renewed_skip"


def test_marketing_campaign_segment_and_unsubscribe_and_tracking(db, monkeypatch):
    session, _engine = db

    sent: list[str] = []

    def _send_email(*, to, subject, html_body, text_body, idempotency_key):
        sent.append(to)
        return {"ok": True, "provider": "stub", "email_id": "x"}

    monkeypatch.setattr(worker_mod, "send_email", _send_email, raising=True)

    admin = _create_user(session, email="adm@test.local")
    p = _create_plan(session, slug="planX", name="Plan X")

    # recipients
    u_trial = _create_user(session, email="trial@test.local")
    u_active = _create_user(session, email="act@test.local")
    u_expired = _create_user(session, email="exp@test.local")

    now = datetime.now(timezone.utc)
    _create_subscription(session, user_id=u_trial.id, plan_id=p.id, status="trialing", end_dt=now + timedelta(days=5))
    _create_subscription(session, user_id=u_active.id, plan_id=p.id, status="active", end_dt=now + timedelta(days=10))
    _create_subscription(session, user_id=u_expired.id, plan_id=p.id, status="expired", end_dt=now - timedelta(days=2))

    session.commit()

    # Unsubscribe active user
    unsub = EmailMarketingUnsubscribe(owner_user_id=admin.id, recipient_email=u_active.email.lower(), unsub_token="tokx")
    session.add(unsub)
    session.commit()

    camp = EmailMarketingCampaign(
        owner_user_id=admin.id,
        name="C1",
        subject="Hello {{name}} {{discount_code}}",
        html_body="<p>{{name}} {{email}} {{plan}} {{expiry_date}}</p>",
        text_body=None,
        cta_label="Go",
        cta_url="https://example.com/cta",
        discount_code="DISC20",
        segment_kind="active",
        segment_plan_id=None,
        send_mode="now",
        scheduled_at=None,
        status="scheduled",
    )
    session.add(camp)
    session.commit()

    # mark unsubscribed
    unsub.unsubscribed_at = datetime.now(timezone.utc)
    session.commit()

    out = worker_mod.email_marketing_send_campaign_task.run(int(camp.id))
    assert out["ok"] is True

    # Segment = active: only u_active would match but it's unsubscribed => 0 sends.
    assert sent == []

    # Now change segment to all (should include trial+active+expired)
    camp.segment_kind = "all"
    camp.status = "scheduled"
    session.commit()

    out = worker_mod.email_marketing_send_campaign_task.run(int(camp.id))
    assert out["ok"] is True
    # Should send to trial + expired (active is unsubscribed)
    assert set(sent) == {u_trial.email.lower(), u_expired.email.lower()}

    # Pick one outbox and test open/click endpoints directly.
    outbox = (
        session.query(EmailSend)
        .filter(EmailSend.campaign_id == int(camp.id))
        .order_by(EmailSend.id.asc())
        .first()
    )
    assert outbox is not None

    # Open
    track_open(token=outbox.event_token, db=session)
    outbox2 = session.get(EmailSend, outbox.id)
    assert outbox2.status in {"opened", "clicked"}

    # Click
    scope = {"type": "http", "method": "GET", "path": "/api/email/track/click", "headers": []}
    req = Request(scope=scope)
    track_click(token=outbox.event_token, request=req, db=session)

    outbox3 = session.get(EmailSend, outbox.id)
    assert outbox3.status == "clicked"

