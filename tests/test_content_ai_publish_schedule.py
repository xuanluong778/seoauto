"""Tests for Content AI publish schedule service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.content_ai_publish_schedule import ContentAIPublishSchedule
from app.services.content_ai_publish_schedule_service import (
    DEFAULT_TZ,
    _sanitize_error_message,
    cancel_schedules,
    claim_next_due_schedule,
    list_due_schedules,
    parse_scheduled_at,
    run_publish_worker_tick,
)


@pytest.fixture()
def db_session():
    import app.models.payment_order  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.knowledge  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class _FakeUser:
    def __init__(self, uid: int, role: str = "user"):
        self.id = uid
        self.role = role


def test_parse_scheduled_at_naive_uses_hcm_tz():
    dt = parse_scheduled_at("2026-06-10T14:30")
    assert dt.tzinfo is not None
    local = dt.astimezone(DEFAULT_TZ)
    assert local.hour == 14
    assert local.minute == 30


def test_parse_scheduled_at_invalid():
    with pytest.raises(HTTPException) as exc:
        parse_scheduled_at("not-a-date")
    assert exc.value.status_code == 400


def test_list_due_schedules(db_session: Session):
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)
    future = now + timedelta(hours=2)
    db_session.add(
        ContentAIPublishSchedule(
            user_id=1,
            project_id="p1",
            keyword="kw",
            title="T",
            content_html="<p>x</p>",
            scheduled_at=past,
            status="scheduled",
        )
    )
    db_session.add(
        ContentAIPublishSchedule(
            user_id=1,
            project_id="p2",
            keyword="kw2",
            title="T2",
            content_html="<p>y</p>",
            scheduled_at=future,
            status="scheduled",
        )
    )
    db_session.commit()
    due = list_due_schedules(db_session, limit=10)
    assert len(due) == 1
    assert due[0].project_id == "p1"


def test_sanitize_error_strips_secrets():
    msg = _sanitize_error_message(Exception('app_password=secret123 Bearer abc.def.ghi'))
    assert "secret123" not in msg
    assert "***" in msg


def test_claim_next_due_schedule_atomic(db_session: Session):
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=2)
    db_session.add(
        ContentAIPublishSchedule(
            user_id=1,
            project_id="p-claim",
            keyword="kw",
            title="T",
            content_html="<p>x</p>",
            scheduled_at=past,
            status="scheduled",
        )
    )
    db_session.commit()
    claimed = claim_next_due_schedule(db_session)
    assert claimed is not None
    assert claimed.status == "publishing"
    assert claimed.project_id == "p-claim"
    second = claim_next_due_schedule(db_session)
    assert second is None


def test_run_publish_worker_tick_no_due(db_session: Session):
    out = run_publish_worker_tick(db_session, limit=5)
    assert out["ok"] is True
    assert out["count"] == 0


def test_cancel_schedules_by_project(db_session: Session):
    db_session.add(
        ContentAIPublishSchedule(
            user_id=7,
            project_id="px",
            keyword="k",
            title="t",
            content_html="c",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status="scheduled",
        )
    )
    db_session.commit()
    user = _FakeUser(7)
    out = cancel_schedules(db_session, user, project_ids=["px"])
    assert out["cancelled"] == 1
    row = db_session.query(ContentAIPublishSchedule).first()
    assert row.status == "cancelled"
