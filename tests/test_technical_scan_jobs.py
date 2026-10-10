"""Technical scan 504 fix — crawl deadline + async job reuse."""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.services.crawler import crawl_site_detailed
from app.services.technical_scan_job import JOB_TYPE, find_technical_job_by_idempotency


def test_crawl_site_detailed_stops_when_deadline_passed():
    t0 = time.monotonic()
    out = crawl_site_detailed(
        "https://example.com/",
        max_pages=20,
        deadline_monotonic=time.monotonic() - 1,
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0
    assert out.get("partial_data") is True
    assert out.get("truncated") is True
    assert out.get("pages") == []


def test_find_technical_job_by_idempotency_is_user_scoped(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    from app.db import Base
    from app.models.keyword_cluster_job import KeywordClusterJob
    from app.models.user import User
    from app.services.job_store import create_job

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)
    monkeypatch.setattr("app.services.technical_scan_job.SessionLocal", Session)

    db = Session()
    a = User(email="a-tech@test.local", password_hash="x", has_password=True, role="user", status="active")
    b = User(email="b-tech@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)

    def _no_org(uid, oid=None, db=None):
        return oid or uid

    monkeypatch.setattr("app.services.tenant_org.resolve_organization_id", _no_org)

    st = create_job(
        job_type=JOB_TYPE,
        message="queued",
        payload={"idempotency_key": "technical_analyze:1:abc", "user_id": a.id},
        user_id=a.id,
        organization_id=a.id,
    )
    hit = find_technical_job_by_idempotency(a.id, "technical_analyze:1:abc")
    assert hit is not None
    assert hit.job_id == st.job_id
    miss = find_technical_job_by_idempotency(b.id, "technical_analyze:1:abc")
    assert miss is None
    db.close()


def test_analyze_technical_jobs_start_and_poll(monkeypatch):
    pytest.importorskip("fastapi")
    import uuid

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token, hash_password
    from app.db import Base, SessionLocal, engine
    from app.models import seo as seo_models  # noqa: F401
    from app.models import knowledge as knowledge_models  # noqa: F401
    from app.models.user import User
    from app.routers.analyze import router as analyze_router
    from app.services.job_store import finish_job

    Base.metadata.create_all(bind=engine)
    app = FastAPI()
    app.include_router(analyze_router)

    db = SessionLocal()
    try:
        user = User(
            email=f"tech-job-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user_id=user.id)
        from app.services.auth import get_current_user
        from app.services.trial_access import require_active_trial

        app.dependency_overrides[require_active_trial] = lambda: user
        app.dependency_overrides[get_current_user] = lambda: user

        @contextmanager
        def fake_gate(*_a, **_k):
            ctx = MagicMock()
            ctx.reservation_id = None
            ctx.reserved_amount = 0
            ctx.committed = False
            ctx.release = MagicMock()
            yield ctx

        started = {}

        def fake_start(job_id, payload):
            started["job_id"] = job_id
            finish_job(
                job_id,
                result={
                    "domain": "example.com",
                    "pages_scanned": 1,
                    "audit_id": "aud-1",
                    "technical_summary": {"health_score": 80, "partial_data": False},
                    "issues": [],
                },
            )

        monkeypatch.setattr("app.services.saas_gate.saas_action_gate", fake_gate)
        monkeypatch.setattr("app.routers.analyze.saas_action_gate", fake_gate)
        monkeypatch.setattr("app.routers.analyze.credits_enforced", lambda: False)
        monkeypatch.setattr("app.services.technical_scan_job.start_technical_scan_thread", fake_start)
        monkeypatch.setattr("app.routers.analyze.assert_public_http_url", lambda *a, **k: None)

        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "retry-key-1"}
        r = client.post(
            "/analyze/technical/jobs",
            headers=headers,
            json={"url": "https://example.com/", "max_pages": 5},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("job_id")
        assert body.get("poll_url")
        assert started.get("job_id") == body["job_id"]

        poll = client.get(f"/analyze/technical/jobs/{body['job_id']}", headers=headers)
        assert poll.status_code == 200
        pdata = poll.json()
        assert pdata["state"] == "SUCCESS"
        assert pdata["result"]["domain"] == "example.com"
        assert pdata["result"]["pages_scanned"] == 1
    finally:
        db.close()
