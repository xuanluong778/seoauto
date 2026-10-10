"""WAVE 4 — WordPress publish worker: single Beat scheduler, idempotent Celery jobs."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.content_ai_publish_schedule import ContentAIPublishSchedule
from app.models.user import User
from app.models.wordpress_plugin import WordpressConnection, WordpressPublishJob
from app.services.wordpress_plugin_security import encrypt_site_secret, personal_organization_id
from app.services.wp_publish_scheduler_rollout import (
    use_celery_wp_scheduler,
    uvicorn_publish_worker_enabled,
)


@pytest.fixture()
def wp_db():
    import app.models.payment_order  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.wordpress_plugin  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(
        email="wave4-wp@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    org = personal_organization_id(int(user.id))
    conn = WordpressConnection(
        user_id=int(user.id),
        organization_id=org,
        publishing_site_id="wps_wave4",
        domain_normalized="wave4.test",
        site_url="https://wave4.test",
        status="active",
        site_secret_encrypted=encrypt_site_secret("test-secret-32bytes-long-xxxx"),
    )
    db.add(conn)
    db.commit()
    yield db, user, conn
    db.close()


def test_celery_scheduler_disables_uvicorn_worker(monkeypatch):
    monkeypatch.setenv("WP_PUBLISH_CELERY_SCHEDULER", "1")
    monkeypatch.setenv("CONTENT_AI_PUBLISH_WORKER_AUTO", "1")
    assert use_celery_wp_scheduler() is True
    assert uvicorn_publish_worker_enabled() is False


def test_schedule_due_publish_noop_when_celery_scheduler(monkeypatch):
    monkeypatch.setenv("WP_PUBLISH_CELERY_SCHEDULER", "1")
    from app.services.content_ai_publish_schedule_service import _schedule_due_publish

    with patch("threading.Thread") as mock_thread:
        _schedule_due_publish(99, datetime.now(timezone.utc))
        mock_thread.assert_not_called()


def test_claim_skips_future_schedule(wp_db):
    db, user, _conn = wp_db
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    db.add(
        ContentAIPublishSchedule(
            user_id=user.id,
            project_id="p-future",
            keyword="kw",
            title="T",
            content_html="<p>x</p>",
            scheduled_at=future,
            status="scheduled",
        )
    )
    db.commit()
    from app.services.content_ai_publish_schedule_service import claim_next_due_schedule

    assert claim_next_due_schedule(db) is None


def test_execute_publish_job_duplicate_delivery(wp_db):
    db, user, conn = wp_db
    from app.services.wordpress_plugin_publish_service import create_publish_job, execute_publish_job
    from app.services.plugin_entitlement_service import PluginEntitlement

    ent = PluginEntitlement(
        allowed=True,
        reason="active",
        plan_code="pro",
        subscription_status="active",
        expires_at=None,
        grace_until=None,
        max_sites=5,
        enabled_features=["seo_helper"],
    )
    payload = {"title": "T", "content": "<p>x</p>", "status": "draft"}

    with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
        with patch("app.services.wordpress_plugin_publish_service._count_org_sites", return_value=1):
            with patch("app.workers.wordpress_publish_worker.enqueue_publish_job", return_value="task-1"):
                job = create_publish_job(
                    db,
                    user=user,
                    payload=payload,
                    connection_id=int(conn.id),
                    request_id="wave4-dup-1",
                    enqueue=False,
                )

    ok_result = {
        "post_id": 42,
        "permalink": "https://wave4.test/p/42",
    }
    with patch("app.services.wordpress_plugin_publish_service.plugin_post_json", return_value=(ok_result, None)):
        with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
            r1 = execute_publish_job(db, job.id)
            r2 = execute_publish_job(db, job.id)

    assert r1.get("ok") is True
    assert r2.get("deduped") is True or r2.get("status") == "success"
    db.refresh(job)
    assert job.status == "success"
    assert job.wp_post_id == 42


def test_create_publish_job_idempotent_request_id(wp_db):
    db, user, conn = wp_db
    from app.services.wordpress_plugin_publish_service import create_publish_job
    from app.services.plugin_entitlement_service import PluginEntitlement

    ent = PluginEntitlement(
        allowed=True,
        reason="active",
        plan_code="pro",
        subscription_status="active",
        expires_at=None,
        grace_until=None,
        max_sites=5,
        enabled_features=["seo_helper"],
    )
    with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
        with patch("app.services.wordpress_plugin_publish_service._count_org_sites", return_value=1):
            with patch("app.workers.wordpress_publish_worker.enqueue_publish_job", return_value="t1"):
                j1 = create_publish_job(
                    db,
                    user=user,
                    payload={"title": "A"},
                    connection_id=int(conn.id),
                    request_id="schedule-100",
                    schedule_id=100,
                    enqueue=True,
                )
                j2 = create_publish_job(
                    db,
                    user=user,
                    payload={"title": "A"},
                    connection_id=int(conn.id),
                    request_id="schedule-100",
                    schedule_id=100,
                    enqueue=True,
                )
    assert j1.id == j2.id


def test_publish_schedule_tick_skipped_when_flag_off(monkeypatch):
    monkeypatch.setenv("WP_PUBLISH_CELERY_SCHEDULER", "0")
    from app.workers.wordpress_schedule_tasks import publish_schedule_tick_task

    out = publish_schedule_tick_task()
    assert out.get("skipped") == "WP_PUBLISH_CELERY_SCHEDULER=0"


def test_publish_schedule_tick_runs_worker(monkeypatch, wp_db):
    monkeypatch.setenv("WP_PUBLISH_CELERY_SCHEDULER", "1")
    db, user, _conn = wp_db
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.add(
        ContentAIPublishSchedule(
            user_id=user.id,
            project_id="p-due",
            keyword="kw",
            title="T",
            content_html="<p>x</p>",
            scheduled_at=past,
            status="scheduled",
            wp_site_id="wps_wave4",
        )
    )
    db.commit()

    from app.workers import wordpress_schedule_tasks as wst

    monkeypatch.setattr(wst, "SessionLocal", lambda: db)
    with patch("app.services.celery_beat_lock.acquire_beat_tick_lock", return_value=True):
        with patch(
            "app.services.content_ai_publish_schedule_service._publish_claimed_row",
            return_value={"ok": True, "async": True, "job_id": 1},
        ):
            out = wst.publish_schedule_tick_task()
    assert out.get("ok") is True
    assert int(out.get("count") or 0) >= 1


def test_cancel_schedule(wp_db):
    db, user, _conn = wp_db
    row = ContentAIPublishSchedule(
        user_id=user.id,
        project_id="p-cancel",
        keyword="kw",
        title="T",
        content_html="<p>x</p>",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="scheduled",
    )
    db.add(row)
    db.commit()
    from app.services.content_ai_publish_schedule_service import cancel_schedules

    out = cancel_schedules(db, user, schedule_ids=[int(row.id)])
    assert out["cancelled"] == 1
    db.refresh(row)
    assert row.status == "cancelled"


def test_tenant_job_isolation(wp_db):
    db, user, conn = wp_db
    user2 = User(
        email="wave4-other@test.local",
        password_hash=hash_password("y"),
        has_password=True,
        role="user",
        status="active",
    )
    db.add(user2)
    db.commit()
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        connection_id=int(conn.id),
        request_id="tenant-job-1",
        command_type="post_create",
        status="queued",
        payload_json="{}",
    )
    db.add(job)
    db.commit()
    from app.services.wordpress_plugin_publish_service import get_job_for_user

    assert get_job_for_user(db, job.id, user) is not None
    assert get_job_for_user(db, job.id, user2) is None


def test_concurrent_claim_only_one_succeeds(wp_db):
    db, user, _conn = wp_db
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.add(
        ContentAIPublishSchedule(
            user_id=user.id,
            project_id="p-race",
            keyword="kw",
            title="T",
            content_html="<p>x</p>",
            scheduled_at=past,
            status="scheduled",
        )
    )
    db.commit()

    from app.services.content_ai_publish_schedule_service import claim_next_due_schedule

    results: list = []

    def _claim():
        eng = db.get_bind()
        Session = sessionmaker(bind=eng)
        s = Session()
        try:
            results.append(claim_next_due_schedule(s))
        finally:
            s.close()

    t1 = threading.Thread(target=_claim)
    t2 = threading.Thread(target=_claim)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    claimed = [r for r in results if r is not None]
    assert len(claimed) <= 1
