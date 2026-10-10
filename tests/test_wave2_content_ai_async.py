"""WAVE 2 — Content AI async generation tests."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.content_ai_generation import ContentAiGeneration
from app.models.user import User


@pytest.fixture
def gen_db(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, ContentAiGeneration.__table__])
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.services.content_ai_generation_store.SessionLocal", Session)
    return Session


def test_stream_ordering_no_duplicate_seq():
    from app.services.content_ai_generation_stream import append_event, read_events, clear_stream

    gid = f"test-{uuid.uuid4().hex}"
    try:
        seqs = []
        for i in range(5):
            seqs.append(append_event(gid, "delta", f"chunk{i}"))
        rows = read_events(gid, after_seq=0)
        got_seqs = [int(r["seq"]) for r in rows]
        assert got_seqs == seqs
        assert len(got_seqs) == len(set(got_seqs))
        rows2 = read_events(gid, after_seq=3)
        assert [int(r["seq"]) for r in rows2] == [4, 5]
    finally:
        clear_stream(gid)


def test_generation_idempotency_same_key(gen_db):
    from app.services.content_ai_generation_store import create_generation

    db = gen_db()
    u = User(email="idem@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    g1 = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key="idem-key-1",
        request_payload={"field": "content"},
    )
    g2 = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key="idem-key-1",
        request_payload={"field": "content"},
    )
    assert g1.generation_id == g2.generation_id


def test_claim_generation_only_one_winner(gen_db):
    from app.services.content_ai_generation_store import claim_generation, create_generation, get_generation

    Session = gen_db
    db = Session()
    u = User(email="race-gen@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    gen = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key=f"race-{uuid.uuid4().hex}",
        request_payload={"field": "content"},
    )
    db.close()
    first = claim_generation(gen.generation_id)
    assert first is not None and first.state == "RUNNING"
    second = claim_generation(gen.generation_id)
    db = Session()
    row = get_generation(db, gen.generation_id)
    assert row is not None and row.state == "RUNNING"
    db.close()


def test_cancel_generation(gen_db):
    from app.services.content_ai_generation_store import cancel_generation, create_generation, get_generation

    db = gen_db()
    u = User(email="cancel@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    gen = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key=f"cancel-{uuid.uuid4().hex}",
        request_payload={"field": "content"},
    )
    cancelled = cancel_generation(db, gen.generation_id, user_id=u.id)
    assert cancelled is not None
    assert cancelled.state == "CANCELLED"
    row = get_generation(db, gen.generation_id)
    assert row.state == "CANCELLED"


def test_multi_tenant_isolation(gen_db):
    from app.services.content_ai_generation_store import create_generation, get_generation_for_user

    db = gen_db()
    u1 = User(email="t1@test.local", password_hash="x", has_password=True, role="user", status="active")
    u2 = User(email="t2@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add_all([u1, u2])
    db.commit()
    gen = create_generation(
        db,
        user_id=u1.id,
        organization_id=u1.id,
        idempotency_key=f"iso-{uuid.uuid4().hex}",
        request_payload={"field": "content"},
    )
    assert get_generation_for_user(db, gen.generation_id, user_id=u1.id) is not None
    assert get_generation_for_user(db, gen.generation_id, user_id=u2.id) is None


def test_async_rollout_flag_off(monkeypatch):
    monkeypatch.setenv("CONTENT_AI_ASYNC_GENERATION", "0")
    from app.services.content_ai_async_rollout import async_enabled_for_user

    class U:
        id = 42

    assert not async_enabled_for_user(U())


def test_async_rollout_canary(monkeypatch):
    monkeypatch.setenv("CONTENT_AI_ASYNC_GENERATION", "1")
    monkeypatch.setenv("CONTENT_AI_ASYNC_ROLLOUT_PERCENT", "50")
    from app.services.content_ai_async_rollout import async_enabled_for_user, _user_bucket

    enabled = sum(1 for uid in range(1, 200) if async_enabled_for_user(type("U", (), {"id": uid})()))
    assert 40 < enabled < 160


def test_sse_bridge_replays_events_in_order(gen_db, monkeypatch):
    from app.services.content_ai_generation_service import sse_bridge_generation
    from app.services.content_ai_generation_store import create_generation, complete_generation
    from app.services.content_ai_generation_stream import append_event, clear_stream

    db = gen_db()
    u = User(email="sse@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    gen = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key=f"sse-{uuid.uuid4().hex}",
        request_payload={"field": "content"},
    )
    gid = gen.generation_id
    append_event(gid, "ping", True)
    append_event(gid, "delta", "hello")
    append_event(gid, "replace_html", "<p>done</p>")
    append_event(gid, "word_count", {"word_count_ok": True, "word_count_actual": 10, "word_count_target": 10})
    append_event(gid, "done", True)
    complete_generation(gid, result={"html": "<p>done</p>", "word_count_meta": {}}, credits_charged=0)

    out = []
    for chunk in sse_bridge_generation(
        db,
        generation_id=gid,
        user=u,
        after_seq=0,
        emit_delta=lambda d: f"delta:{d}",
        emit_replace=lambda h: f"html:{h}",
        emit_wc=lambda m: "wc",
        emit_ping=lambda: "ping",
        emit_error=lambda **_: "err",
        emit_done=lambda: "DONE",
    ):
        out.append(chunk)
    assert out[0] == "ping"
    assert "delta:hello" in out
    assert any(x.startswith("html:") for x in out)
    assert "wc" in out
    assert "DONE" in out
    clear_stream(gid)


def test_credit_idempotency_reserve_once(gen_db, monkeypatch):
    from app.services.content_ai_generation_store import create_generation

    db = gen_db()
    u = User(email="credit@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    calls = {"n": 0}

    def fake_reserve(db, user, quote, **kw):
        calls["n"] += 1
        hold = MagicMock()
        hold._done = False
        hold.amount = 5
        hold.commit = MagicMock()
        hold.release = MagicMock()
        return hold

    monkeypatch.setattr(
        "app.services.content_ai_credit_service.reserve_content_ai_write",
        fake_reserve,
    )
    monkeypatch.setattr(
        "app.services.user_api_access.load_llm_config_for_request",
        lambda db, user: {"provider": "mock"},
    )
    monkeypatch.setattr(
        "app.services.cost_control.module_gates.content_ai_llm_gate",
        lambda *a, **k: MagicMock(__enter__=lambda s: None, __exit__=lambda s, *e: None),
    )
    monkeypatch.setattr(
        "app.services.llm_content_writer.iter_content_ai_content_stream_deltas",
        lambda **kw: iter(["<p>x</p>"]),
    )
    monkeypatch.setattr(
        "app.services.llm_content_writer.finalize_content_ai_stream_html",
        lambda raw, **kw: (raw, {}),
    )
    monkeypatch.setattr(
        "app.services.content_ai_entitlement.record_content_ai_usage",
        lambda *a, **k: None,
    )

    gen = create_generation(
        db,
        user_id=u.id,
        organization_id=u.id,
        idempotency_key=f"cr-{uuid.uuid4().hex}",
        request_payload={
            "field": "content",
            "user_id": u.id,
            "llm_gate": {"charge_credits": True, "quote": {"credit_cost": 5, "charge_credits": True}},
            "feature_key": "content_ai_article",
        },
    )
    from app.services.content_ai_generation_runner import run_content_ai_generation

    run_content_ai_generation(gen.generation_id, gen.request | {"user_id": u.id})
    assert calls["n"] == 1


def test_queue_fairness_generation_org_scope(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    from app.services.queue_fairness import try_acquire_slot, release_slot

    assert try_acquire_slot("generation", 1, "g1", org_id=10)
    release_slot("generation", 1, "g1", org_id=10)


def test_worker_crash_recovery_reenqueue(monkeypatch):
    from datetime import timedelta

    enqueued = []

    class Gen:
        generation_id = "gen-recover-1"
        created_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    monkeypatch.setenv("JOB_RECOVER_MIN_AGE_SECONDS", "1")

    with patch("app.services.celery_beat_lock.acquire_beat_tick_lock", return_value=True):
        with patch("app.services.job_store.list_jobs_by_states", return_value=[]):
            with patch("app.services.content_ai_generation_store.list_stale_generations", return_value=[Gen()]):
                with patch(
                    "app.workers.content_ai_generation_tasks.enqueue_content_ai_generation",
                    side_effect=lambda gid: enqueued.append(gid) or "t",
                ):
                    from app.workers.job_queue_recover import recover_queued_jobs_task

                    res = recover_queued_jobs_task()
    assert enqueued == ["gen-recover-1"]
    assert res.get("enqueued", 0) >= 1


def test_celery_route_generation_queue():
    from app.queue.celery_queues import TASK_ROUTES

    assert TASK_ROUTES["content_ai.run_generation"]["queue"] == "content_ai"
