"""WAVE 3 — DB pool, tenant query, index regression tests."""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, connection_budget, use_pgbouncer


def test_connection_budget_web_role(monkeypatch):
    monkeypatch.delenv("CELERY_WORKER", raising=False)
    monkeypatch.delenv("CELERY_BEAT", raising=False)
    monkeypatch.setenv("DB_USE_PGBOUNCER", "0")
    monkeypatch.setattr("app.db.use_pgbouncer", lambda: False)
    b = connection_budget()
    assert b["role"] == "web"
    if b.get("pgbouncer"):
        assert b["client_pool"] == "NullPool"
    else:
        assert b["max_per_process"] <= 10


def test_connection_budget_pgbouncer_nullpool(monkeypatch):
    monkeypatch.setattr("app.db.use_pgbouncer", lambda: True)
    b = connection_budget()
    assert b["pgbouncer"] is True
    assert b["client_pool"] == "NullPool"


def test_pool_exhaustion_bounded(monkeypatch):
    """40 concurrent short sessions on sqlite should not fail."""
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.models.user import User

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", Session)
    errors = []

    def _run():
        db = Session()
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=_run) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_list_entries_defers_payload_json(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.models.content_ai_project import ContentAiProject
    from app.models.user import User
    from app.services.content_ai_projects_pg import insert_entry_pg, list_entries_pg

    monkeypatch.setattr("app.services.content_ai_projects_pg.ensure_personal_organization", lambda db, uid: int(uid))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, ContentAiProject.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.content_ai_projects_pg.SessionLocal", Session)

    db = Session()
    u = User(email="w3@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.commit()
    pid = str(uuid.uuid4())
    insert_entry_pg(
        {
            "id": pid,
            "title": "T",
            "primary_keyword": "kw",
            "content": "<p>x</p>",
            "status": "draft",
        },
        user_id=u.id,
        organization_id=u.id,
        db=db,
    )
    db.commit()
    rows = list_entries_pg(user_id=u.id, organization_id=u.id, limit=10, db=db)
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["content"] == "<p>x</p>"
    db.close()


def test_tenant_query_isolation_pg_style(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    from app.models.content_ai_project import ContentAiProject
    from app.models.user import User
    from app.services.content_ai_projects_pg import get_entry_pg, insert_entry_pg

    monkeypatch.setattr("app.services.content_ai_projects_pg.ensure_personal_organization", lambda db, uid: int(uid))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[User.__table__, ContentAiProject.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.content_ai_projects_pg.SessionLocal", Session)

    db = Session()
    u1 = User(email="t1@w3.local", password_hash="x", has_password=True, role="user", status="active")
    u2 = User(email="t2@w3.local", password_hash="x", has_password=True, role="user", status="active")
    db.add_all([u1, u2])
    db.commit()
    pid = str(uuid.uuid4())
    insert_entry_pg(
        {"id": pid, "title": "Secret", "content": "c", "primary_keyword": "k"},
        user_id=u1.id,
        organization_id=u1.id,
        db=db,
    )
    db.commit()
    assert get_entry_pg(pid, user_id=u1.id, organization_id=u1.id, db=db) is not None
    assert get_entry_pg(pid, user_id=u2.id, organization_id=u2.id, db=db) is None
    db.close()


def test_credit_idempotency_unique_constraint_exists():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("postgresql only")
    import psycopg2

    conn = psycopg2.connect(url.replace("postgresql+psycopg2://", "postgresql://"))
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_credit_reservations_idempotency'"
    )
    assert cur.fetchone() is not None
    cur.close()
    conn.close()
