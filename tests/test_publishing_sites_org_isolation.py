"""Cross-organization isolation for publishing sites and API keys."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User


@pytest.fixture()
def db_session(monkeypatch):
    monkeypatch.setenv("TENANT_CRED_SITES_PG", "1")
    monkeypatch.setenv("TENANT_CRED_SITES_DUAL_READ", "0")
    monkeypatch.setenv("TENANT_CRED_SITES_JSON_WRITE", "0")

    import app.models.affiliate  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.user_quota_addon  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.user_api_key  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    import app.db as dbmod
    import app.services.publishing_sites_pg as pub_pg

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(pub_pg, "SessionLocal", Session)

    u1 = User(email="org1@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="org2@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()

    yield session, u1, u2, Session
    session.close()


def test_publishing_site_not_readable_cross_org(db_session):
    session, u1, u2, Session = db_session
    from app.services.publishing_sites_pg import create_site_pg, get_site_pg, list_sites_pg
    from app.services.tenant_org import ensure_personal_organization

    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()

    site = create_site_pg(
        {
            "name": "A Site",
            "url": "https://a-example.test",
            "username": "admin",
            "app_password": "secret-app-pass-aaaa",
            "platform": "wordpress",
        },
        user_id=u1.id,
        db=session,
    )
    session.commit()
    site_id = site["id"]
    assert not (site.get("app_password") or "").strip()
    assert site.get("app_password_masked")

    own = get_site_pg(site_id, user_id=u1.id, db=session)
    assert own is not None
    assert own["id"] == site_id

    other = get_site_pg(site_id, user_id=u2.id, db=session)
    assert other is None
    assert list_sites_pg(user_id=u2.id, db=session) == []

    secret = get_site_pg(site_id, user_id=u1.id, reveal_password=True, db=session)
    assert secret and secret.get("app_password") == "secret-app-pass-aaaa"
    assert get_site_pg(site_id, user_id=u2.id, reveal_password=True, db=session) is None


def test_api_key_not_readable_cross_org(db_session):
    session, u1, u2, Session = db_session
    from app.services.tenant_org import ensure_personal_organization
    from app.services.user_api_keys_db import create_key_db, get_key_db, list_keys_db

    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()

    created = create_key_db(
        session,
        {"name": "k1", "api_key": "sk-test-secret-value-123456", "provider": "openai"},
        user_id=u1.id,
    )
    assert not created.get("api_key")
    assert created.get("api_key_masked")
    kid = created["id"]

    assert get_key_db(session, kid, user_id=u1.id, reveal_key=False) is not None
    assert get_key_db(session, kid, user_id=u2.id, reveal_key=True) is None
    assert list_keys_db(session, user_id=u2.id) == []


def test_migrate_idempotent_and_quarantine(db_session):
    session, u1, u2, Session = db_session
    from app.models.publishing_site import LegacyDataQuarantine, PublishingSite
    from app.services.publishing_sites_pg import upsert_from_migrate
    from app.services.tenant_org import ensure_personal_organization

    org = ensure_personal_organization(session, u1.id)
    session.commit()
    payload = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "user_id": u1.id,
        "name": "Site",
        "url": "https://migrate-example.test",
        "username": "u",
        "app_password": "plain-pass-xyz",
        "platform": "wordpress",
    }
    a1 = upsert_from_migrate(
        session, record_id=payload["id"], organization_id=org, user_id=u1.id, payload=payload
    )
    a2 = upsert_from_migrate(
        session, record_id=payload["id"], organization_id=org, user_id=u1.id, payload=payload
    )
    session.commit()
    assert a1 == "inserted"
    assert a2 == "updated"
    assert session.query(PublishingSite).count() == 1

    from scripts.migrate_credentials_publishing_sites import quarantine

    quarantine(
        session,
        store="publishing_sites",
        record_id="orphan-1",
        reason="missing_user_id",
        payload={"id": "orphan-1", "url": "https://x.test", "app_password": "secret"},
    )
    session.commit()
    assert session.query(LegacyDataQuarantine).filter_by(source_record_id="orphan-1").count() == 1
    quarantine(
        session,
        store="publishing_sites",
        record_id="orphan-1",
        reason="missing_user_id",
        payload={"id": "orphan-1", "url": "https://x.test", "app_password": "secret"},
    )
    session.commit()
    assert session.query(LegacyDataQuarantine).filter_by(source_record_id="orphan-1").count() == 1
    # redacted payload has no full secret plaintext
    q = session.query(LegacyDataQuarantine).filter_by(source_record_id="orphan-1").one()
    assert "secret" not in q.payload_json or "***REDACTED***" in q.payload_json
