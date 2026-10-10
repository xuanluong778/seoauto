"""WAVE 1 — PostgreSQL concurrent claim stress test for claim_job_by_id()."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from app.db import Base
from app.models.keyword_cluster_job import KeywordClusterJob
from app.models.user import User


def _is_postgresql() -> bool:
    url = os.getenv("DATABASE_URL", "")
    return url.startswith("postgresql") or url.startswith("postgres")


@pytest.mark.skipif(not _is_postgresql(), reason="requires PostgreSQL (DATABASE_URL)")
def test_claim_job_by_id_concurrent_pg_only_one_winner(monkeypatch):
    """Many workers racing on the same job_id — exactly one must claim."""
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.services.job_store import claim_job_by_id, get_job

    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, KeywordClusterJob.__table__])

    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.job_store.SessionLocal", Session)

    suffix = uuid.uuid4().hex[:12]
    job_id = f"wave1-claim-{suffix}"
    email = f"wave1-claim-{suffix}@test.local"

    db = Session()
    try:
        u = User(
            email=email,
            password_hash="x",
            has_password=True,
            role="user",
            status="active",
        )
        db.add(u)
        db.flush()
        now = datetime.now(timezone.utc)
        db.add(
            KeywordClusterJob(
                job_id=job_id,
                job_type="content_ai_bulk",
                user_id=u.id,
                organization_id=u.id,
                state="QUEUED",
                payload_json=f'{{"user_id": {u.id}}}',
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    winners: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def _race():
        barrier.wait(timeout=10)
        st = claim_job_by_id(job_id)
        if st is not None:
            with lock:
                winners.append(st.job_id)

    threads = [threading.Thread(target=_race) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert winners == [job_id], f"expected exactly one winner, got {len(winners)}: {winners}"
    st = get_job(job_id)
    assert st is not None and st.state == "RUNNING"

    # cleanup
    db = Session()
    try:
        db.execute(text("DELETE FROM keyword_cluster_jobs WHERE job_id = :jid"), {"jid": job_id})
        db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
        db.commit()
    finally:
        db.close()
