"""Idempotent bulk-job lookup: same user+fingerprint reuses in-flight job."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.keyword_cluster_job import KeywordClusterJob
from app.models.user import User
from app.services.job_store import find_recent_job_by_fingerprint


def test_find_recent_job_by_fingerprint_tenant_and_state(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    db = Session()
    a = User(email="a@test.local", password_hash="x", has_password=True, role="user", status="active")
    b = User(email="b@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add_all([a, b])
    db.flush()
    now = datetime.now(timezone.utc)
    row_a = KeywordClusterJob(
        job_id="job-a-1",
        job_type="content_ai_bulk",
        user_id=a.id,
        organization_id=a.id,
        state="QUEUED",
        payload_json='{"user_id": %s, "job_fingerprint": "fp-same"}' % a.id,
        created_at=now,
        updated_at=now,
    )
    row_b = KeywordClusterJob(
        job_id="job-b-1",
        job_type="content_ai_bulk",
        user_id=b.id,
        organization_id=b.id,
        state="QUEUED",
        payload_json='{"user_id": %s, "job_fingerprint": "fp-same"}' % b.id,
        created_at=now,
        updated_at=now,
    )
    db.add_all([row_a, row_b])
    db.commit()
    aid, bid = int(a.id), int(b.id)
    db.close()

    found_a = find_recent_job_by_fingerprint(aid, "content_ai_bulk", "fp-same")
    found_b = find_recent_job_by_fingerprint(bid, "content_ai_bulk", "fp-same")
    assert found_a is not None and found_a.job_id == "job-a-1"
    assert found_b is not None and found_b.job_id == "job-b-1"
    assert find_recent_job_by_fingerprint(aid, "content_ai_bulk", "fp-other") is None
    assert find_recent_job_by_fingerprint(aid, "other_type", "fp-same") is None


def test_claim_job_by_id_and_skips_running(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.services.job_store import claim_job_by_id

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    db = Session()
    u = User(email="c@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(
        KeywordClusterJob(
            job_id="job-claim-1",
            job_type="content_ai_bulk",
            user_id=u.id,
            organization_id=u.id,
            state="QUEUED",
            payload_json='{"user_id": %s}' % u.id,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.close()

    first = claim_job_by_id("job-claim-1")
    assert first is not None and first.state == "RUNNING"
    second = claim_job_by_id("job-claim-1")
    assert second is None
    assert claim_job_by_id("") is None
    assert claim_job_by_id("missing-job") is None


def test_cancel_job_running_and_finished(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.services.job_store import cancel_job, claim_job_by_id

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    db = Session()
    u = User(email="d@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(
        KeywordClusterJob(
            job_id="job-cancel-1",
            job_type="content_ai_bulk",
            user_id=u.id,
            organization_id=u.id,
            state="QUEUED",
            payload_json='{"user_id": %s}' % u.id,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.close()

    assert claim_job_by_id("job-cancel-1") is not None
    cancelled = cancel_job("job-cancel-1", message="Đã dừng viết hàng loạt.")
    assert cancelled is not None and cancelled.state == "CANCELLED"
    again = cancel_job("job-cancel-1")
    assert again is not None and again.state == "CANCELLED"
    assert cancel_job("") is None
    assert cancel_job("missing-job") is None


def test_claim_job_cas_only_one_winner(monkeypatch):
    import threading

    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.services.job_store import claim_job_by_id, list_running_jobs

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    db = Session()
    u = User(email="race@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(
        KeywordClusterJob(
            job_id="job-race-1",
            job_type="content_ai_bulk",
            user_id=u.id,
            organization_id=u.id,
            state="QUEUED",
            payload_json='{"user_id": %s}' % u.id,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.close()

    won = []

    def _try():
        st = claim_job_by_id("job-race-1")
        if st is not None:
            won.append(st.job_id)

    threads = [threading.Thread(target=_try) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert won == ["job-race-1"]
    running = list_running_jobs(job_type="content_ai_bulk")
    assert len(running) == 1 and running[0].job_id == "job-race-1"


def test_update_job_persists_items_and_updated_at(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.services.job_store import create_job, get_job, update_job

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    job = create_job(job_type="content_ai_bulk", message="queued", payload={"user_id": 1})
    update_job(
        job.job_id,
        progress=12,
        message="Đã xong bài 3/12",
        result={
            "total": 12,
            "success": 3,
            "failed": 0,
            "items": [
                {"keyword": "a", "status": "success"},
                {"keyword": "b", "status": "success"},
                {"keyword": "c", "status": "success"},
                {"keyword": "d", "status": "pending"},
            ],
        },
    )
    st = get_job(job.job_id)
    assert st is not None
    assert st.progress == 12
    assert st.result is not None
    assert st.result["success"] == 3
    assert st.result["total"] == 12
    assert sum(1 for x in st.result["items"] if x.get("status") == "success") == 3


