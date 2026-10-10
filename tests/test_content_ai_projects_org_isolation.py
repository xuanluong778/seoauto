"""Content AI projects: org isolation, CRUD, pagination, concurrent writes."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User


@pytest.fixture()
def db_session(monkeypatch):
    monkeypatch.setenv("TENANT_CONTENT_AI_PG", "1")
    monkeypatch.setenv("TENANT_CONTENT_AI_DUAL_READ", "0")
    monkeypatch.setenv("TENANT_CONTENT_AI_JSON_WRITE", "0")

    import app.models.affiliate  # noqa: F401
    import app.models.content_ai_project  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.user_api_key  # noqa: F401
    import app.models.user_quota_addon  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    import app.db as dbmod
    import app.services.content_ai_projects_pg as cap_pg

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(cap_pg, "SessionLocal", Session)

    u1 = User(email="cai-org1@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="cai-org2@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()

    from app.services.tenant_org import ensure_personal_organization

    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()

    yield session, u1, u2, Session
    session.close()


def test_crud_and_pagination(db_session):
    session, u1, u2, Session = db_session
    from app.services.content_ai_project_store import (
        delete_content_ai_project,
        get_content_ai_project,
        list_content_ai_projects,
        save_content_ai_project,
        update_content_ai_project_fields,
    )

    ids = []
    for i in range(5):
        pid = save_content_ai_project(
            user_id=u1.id,
            source_payload={
                "title": f"T{i}",
                "primary_keyword": f"kw{i}",
                "target_website": "https://a.example.com",
                "outline_content": "## H2",
            },
            draft_payload={"title": f"T{i}", "content": f"<p>body {i} extra words here for count</p>"},
        )
        ids.append(pid)

    page = list_content_ai_projects(user_id=u1.id, limit=2, offset=0)
    assert len(page) == 2
    page2 = list_content_ai_projects(user_id=u1.id, limit=2, offset=2)
    assert len(page2) == 2
    assert {p["id"] for p in page}.isdisjoint({p["id"] for p in page2})

    row = get_content_ai_project(ids[0], user_id=u1.id)
    assert row is not None
    assert row["organization_id"] == u1.id
    assert "api_key" not in row

    updated = update_content_ai_project_fields(
        ids[0], {"title": "Renamed", "content": "<p>new content</p>"}, user_id=u1.id
    )
    assert updated is not None
    again = get_content_ai_project(ids[0], user_id=u1.id)
    assert again and again["title"] == "Renamed"

    assert delete_content_ai_project(ids[0], user_id=u1.id) is True
    assert get_content_ai_project(ids[0], user_id=u1.id) is None


def test_tenant_isolation_two_orgs(db_session):
    session, u1, u2, Session = db_session
    from app.services.content_ai_project_store import (
        delete_content_ai_project,
        get_content_ai_project,
        list_content_ai_projects,
        save_content_ai_project,
        update_content_ai_project_fields,
    )

    a_id = save_content_ai_project(
        user_id=u1.id,
        source_payload={"title": "OrgA secret", "primary_keyword": "a", "target_website": "https://a.test"},
        draft_payload={"title": "OrgA secret", "content": "<p>alpha private</p>"},
    )
    b_id = save_content_ai_project(
        user_id=u2.id,
        source_payload={"title": "OrgB secret", "primary_keyword": "b", "target_website": "https://b.test"},
        draft_payload={"title": "OrgB secret", "content": "<p>beta private</p>"},
    )

    assert get_content_ai_project(a_id, user_id=u2.id) is None
    assert get_content_ai_project(b_id, user_id=u1.id) is None
    assert get_content_ai_project(a_id, user_id=0) is None
    assert update_content_ai_project_fields(a_id, {"title": "hack"}, user_id=u2.id) is None
    assert delete_content_ai_project(a_id, user_id=u2.id) is False
    assert get_content_ai_project(a_id, user_id=u1.id) is not None

    a_list = list_content_ai_projects(user_id=u1.id, limit=50)
    assert all(x["id"] != b_id for x in a_list)
    assert any(x["id"] == a_id for x in a_list)


def test_secrets_stripped_on_write(db_session):
    session, u1, u2, Session = db_session
    from app.services.content_ai_project_store import get_content_ai_project, save_content_ai_project
    from app.services.content_ai_projects_pg import sanitize_entry

    raw = sanitize_entry(
        {
            "title": "x",
            "api_key": "sk-should-never-store",
            "nested": {"password": "pw", "ok": 1},
            "content": "hello",
        }
    )
    assert "api_key" not in raw
    assert "password" not in raw.get("nested", {})

    pid = save_content_ai_project(
        user_id=u1.id,
        source_payload={
            "title": "sec",
            "primary_keyword": "s",
            "target_website": "https://s.test",
            "api_key": "sk-leak",
        },
        draft_payload={"title": "sec", "content": "<p>c</p>", "secret_token": "t"},
    )
    row = get_content_ai_project(pid, user_id=u1.id)
    assert row
    blob = str(row)
    assert "sk-leak" not in blob
    assert "secret_token" not in row
    assert "api_key" not in row


def test_concurrent_updates(db_session):
    session, u1, u2, Session = db_session
    from app.services.content_ai_project_store import (
        get_content_ai_project,
        save_content_ai_project,
        update_content_ai_project_fields,
    )

    pid = save_content_ai_project(
        user_id=u1.id,
        source_payload={"title": "C", "primary_keyword": "c", "target_website": "https://c.test"},
        draft_payload={"title": "C", "content": "<p>base</p>"},
    )
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            update_content_ai_project_fields(
                pid, {"content": f"<p>w{n}</p>", "title": f"T{n}"}, user_id=u1.id
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    final = get_content_ai_project(pid, user_id=u1.id)
    assert final is not None
    assert final.get("title", "").startswith("T")


def test_migrate_upsert_idempotent_and_quarantine(db_session):
    session, u1, u2, Session = db_session
    from app.models.publishing_site import LegacyDataQuarantine
    from app.services.content_ai_projects_pg import count_entries_pg, upsert_from_migrate
    from app.services.tenant_org import ensure_personal_organization

    org = ensure_personal_organization(session, u1.id)
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": u1.id,
        "title": "M",
        "content": "body",
        "primary_keyword": "m",
        "target_website": "https://m.test",
        "api_key": "strip-me",
    }
    assert upsert_from_migrate(session, record_id=payload["id"], organization_id=org, user_id=u1.id, payload=payload) == "inserted"
    assert upsert_from_migrate(session, record_id=payload["id"], organization_id=org, user_id=u1.id, payload=payload) == "skipped"
    payload["title"] = "M2"
    assert upsert_from_migrate(session, record_id=payload["id"], organization_id=org, user_id=u1.id, payload=payload) == "updated"
    session.commit()
    assert count_entries_pg(user_id=u1.id, organization_id=org, db=session) == 1

    from scripts.migrate_content_ai_projects import quarantine

    quarantine(
        session,
        store="content_ai_projects",
        record_id="orphan-1",
        reason="missing_or_invalid_user_id",
        payload={"id": "orphan-1", "title": "no user"},
    )
    session.commit()
    q = (
        session.query(LegacyDataQuarantine)
        .filter(LegacyDataQuarantine.source_store == "content_ai_projects")
        .count()
    )
    assert q == 1
