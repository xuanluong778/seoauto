"""Multi-worker + IDOR tests for async task registry and crawl tenancy."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services.tenant_org import ensure_personal_organization, personal_organization_id


@pytest.fixture()
def db_env(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/15")  # unused port → Redis path fails soft

    import app.models.async_task_owner  # noqa: F401
    import app.models.crawl_job  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.affiliate  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.user_quota_addon  # noqa: F401
    import app.models.user_api_key  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.keyword_cluster_job  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    import app.db as dbmod
    import app.queue.crawl_queue as crawl_queue
    import app.services.async_task_registry as registry

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(crawl_queue, "SessionLocal", Session)
    monkeypatch.setattr(registry, "SessionLocal", Session)
    monkeypatch.setattr(registry, "_redis", lambda: None)

    u1 = User(email="async-a@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="async-b@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()
    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()

    yield session, u1, u2, Session
    session.close()


def test_async_task_owner_redis_shared_between_workers(db_env, monkeypatch):
    """Simulate two API workers sharing Redis ownership (no PG read on second)."""
    session, u1, u2, _Session = db_env
    from app.services import async_task_registry as registry

    store: dict[str, str] = {}

    class _FakeRedis:
        def setex(self, key, ttl, value):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(registry, "_redis", lambda: _FakeRedis())

    tid = f"task-redis-{uuid.uuid4().hex}"
    registry.register_task_owner(tid, u1.id, db=session)
    session.commit()

    # Second "worker" reads only Redis (PG still works, but assert Redis hit)
    assert registry._cache_get(tid)["user_id"] == u1.id
    registry.assert_task_owner(tid, u1.id, db=session)
    with pytest.raises(HTTPException) as exc:
        registry.assert_task_owner(tid, u2.id, db=session)
    assert exc.value.status_code == 404


def test_async_task_owner_rejects_foreign_organization(db_env):
    session, u1, u2, _Session = db_env
    from app.services.async_task_registry import register_task_owner

    tid = f"task-{uuid.uuid4().hex}"
    with pytest.raises(HTTPException) as exc:
        register_task_owner(
            tid,
            u1.id,
            organization_id=personal_organization_id(u2.id),
            db=session,
        )
    assert exc.value.status_code == 404


def test_revoke_owned_task_blocks_cross_tenant(db_env, monkeypatch):
    session, u1, u2, _Session = db_env
    from app.services import async_task_registry as registry

    tid = f"task-{uuid.uuid4().hex}"
    registry.register_task_owner(tid, u1.id, db=session)
    session.commit()

    class _FakeResult:
        def __init__(self, *a, **k):
            pass

        def revoke(self, terminate=False):
            raise AssertionError("must not revoke for other tenant")

    monkeypatch.setattr(registry, "AsyncResult", _FakeResult, raising=False)
    # Patch inside revoke_owned_task import path
    import celery.result as celery_result

    monkeypatch.setattr(celery_result, "AsyncResult", _FakeResult)

    with pytest.raises(HTTPException) as exc:
        registry.revoke_owned_task(tid, u2.id, db=session)
    assert exc.value.status_code == 404


def test_crawl_job_tenant_idor(db_env, monkeypatch):
    session, u1, u2, Session = db_env
    from app.models.crawl_job import DistributedCrawlJob
    from app.queue.crawl_queue import (
        fetch_crawl_bundle_for_job,
        get_crawl_job_for_user,
        job_owned_by_tenant,
    )

    # Avoid real Celery dispatch
    class _Ar:
        id = f"celery-{uuid.uuid4().hex}"

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            return _Ar()

    import app.workers.crawl_worker as crawl_worker

    monkeypatch.setattr(crawl_worker, "process_crawl_job", _Task)

    from app.queue.crawl_queue import enqueue_crawl

    out = enqueue_crawl(
        "https://example-tenant-a.test/",
        project_id=None,
        max_pages=1,
        user_id=u1.id,
    )
    job_id = out["job_id"]
    assert out["user_id"] == u1.id
    assert out["organization_id"] == personal_organization_id(u1.id)

    job = session.get(DistributedCrawlJob, job_id)
    assert job is not None
    job.status = "completed"
    session.commit()

    assert get_crawl_job_for_user(job_id, user_id=u1.id, db=session) is not None
    assert get_crawl_job_for_user(job_id, user_id=u2.id, db=session) is None
    assert not job_owned_by_tenant(job, user_id=u2.id)

    # Bundle readable by owner; cross-tenant blocked
    bundle = fetch_crawl_bundle_for_job(job_id, db=session, user_id=u1.id)
    assert bundle is not None
    assert fetch_crawl_bundle_for_job(job_id, db=session, user_id=u2.id) is None


def test_crawl_enqueue_rejects_foreign_org(db_env, monkeypatch):
    _session, u1, u2, _Session = db_env

    class _Ar:
        id = f"celery-{uuid.uuid4().hex}"

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            return _Ar()

    import app.workers.crawl_worker as crawl_worker
    from app.services.tenant_org import OrganizationForbiddenError
    from app.queue.crawl_queue import enqueue_crawl

    monkeypatch.setattr(crawl_worker, "process_crawl_job", _Task)

    with pytest.raises(OrganizationForbiddenError):
        enqueue_crawl(
            "https://hijack.test/",
            user_id=u1.id,
            organization_id=personal_organization_id(u2.id),
        )


def _patch_celery(monkeypatch):
    class _Ar:
        id = f"celery-{uuid.uuid4().hex}"

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            return _Ar()

    import app.workers.crawl_worker as crawl_worker

    monkeypatch.setattr(crawl_worker, "process_crawl_job", _Task)


def test_runtime_enqueue_requires_owner(db_env, monkeypatch):
    _session, u1, _u2, _Session = db_env
    from app.queue.crawl_queue import CrawlOwnerRequiredError, enqueue_crawl
    from app.models.crawl_job import DistributedCrawlJob

    _patch_celery(monkeypatch)

    with pytest.raises(CrawlOwnerRequiredError) as exc:
        enqueue_crawl("https://unowned-forbidden.test/")
    assert exc.value.code == "crawl_owner_required"

    out = enqueue_crawl("https://owned-required.test/", user_id=u1.id)
    assert out["user_id"] == u1.id
    assert out["organization_id"] == personal_organization_id(u1.id)
    job = _session.get(DistributedCrawlJob, out["job_id"])
    assert job is not None
    assert job.user_id == u1.id
    assert job.organization_id == personal_organization_id(u1.id)


def test_legacy_allow_unowned_still_works(db_env, monkeypatch):
    session, _u1, _u2, _Session = db_env
    from app.models.crawl_job import DistributedCrawlJob
    from app.queue.crawl_queue import enqueue_crawl

    _patch_celery(monkeypatch)
    out = enqueue_crawl("https://legacy-unowned.test/", allow_unowned=True)
    assert out["user_id"] is None
    assert out["organization_id"] is None
    job = session.get(DistributedCrawlJob, out["job_id"])
    assert job is not None
    assert job.user_id is None
    # Cross-tenant style access with a user id must not see unowned jobs
    from app.queue.crawl_queue import get_crawl_job_for_user

    assert get_crawl_job_for_user(out["job_id"], user_id=_u1.id, db=session) is None


def test_schedule_batch_and_technical_require_owner(db_env, monkeypatch):
    session, u1, u2, _Session = db_env
    from app.queue.crawl_queue import CrawlOwnerRequiredError
    from app.queue.crawl_scheduler import schedule_crawl_batch
    from app.seo_pipeline.crawler_layer import (
        run_technical_crawl_from_job,
        schedule_technical_crawl,
    )
    from app.models.crawl_job import DistributedCrawlJob

    _patch_celery(monkeypatch)
    monkeypatch.setattr(
        "app.queue.crawl_scheduler.filter_new_urls",
        lambda project_id, urls: list(urls),
    )
    monkeypatch.setattr("app.queue.crawl_scheduler.mark_urls_seen", lambda *a, **k: 0)

    with pytest.raises(CrawlOwnerRequiredError):
        schedule_crawl_batch(["https://batch-a.test/"], None)
    with pytest.raises(CrawlOwnerRequiredError):
        schedule_technical_crawl("https://tech-a.test/", max_pages=1)

    batch = schedule_crawl_batch(
        ["https://batch-owned.test/"],
        None,
        user_id=u1.id,
        organization_id=personal_organization_id(u1.id),
    )
    assert len(batch) == 1
    assert batch[0]["user_id"] == u1.id
    assert batch[0]["organization_id"] == personal_organization_id(u1.id)

    tech = schedule_technical_crawl(
        "https://tech-owned.test/",
        max_pages=1,
        user_id=u1.id,
        organization_id=personal_organization_id(u1.id),
    )
    job = session.get(DistributedCrawlJob, tech["job_id"])
    assert job is not None
    job.status = "completed"
    session.commit()

    from app.queue.crawl_queue import fetch_crawl_bundle_for_job

    assert fetch_crawl_bundle_for_job(tech["job_id"], db=session, user_id=u1.id) is not None
    assert fetch_crawl_bundle_for_job(tech["job_id"], db=session, user_id=u2.id) is None
    cross = run_technical_crawl_from_job(tech["job_id"], user_id=u2.id)
    assert cross == {"pages": [], "edges": [], "domain": "", "total": 0}
    with pytest.raises(CrawlOwnerRequiredError):
        run_technical_crawl_from_job(tech["job_id"])


def test_no_runtime_route_calls_distributed_crawl_unowned():
    """Guardrail: app routers must not call enqueue/schedule without tenant kwargs nearby."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "routers"
    offenders = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "enqueue_crawl(" in text or "schedule_crawl_batch(" in text or "schedule_technical_crawl(" in text:
            offenders.append(path.name)
    # Today no router calls distributed crawl; if added later they must pass owner (covered by API).
    assert offenders == []
