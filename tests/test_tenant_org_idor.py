"""IDOR / cross-tenant tests for tenant_org.resolve_organization_id."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.services.tenant_org import (
    OrganizationForbiddenError,
    ensure_personal_organization,
    personal_organization_id,
    resolve_organization_id,
    user_belongs_to_organization,
)


@pytest.fixture()
def db_session(monkeypatch):
    monkeypatch.setenv("TENANT_CRED_SITES_PG", "1")
    monkeypatch.setenv("TENANT_CRED_SITES_DUAL_READ", "0")
    monkeypatch.setenv("TENANT_CRED_SITES_JSON_WRITE", "0")

    import app.models.affiliate  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.keyword_cluster_job  # noqa: F401
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
    import app.services.job_store as job_store
    import app.services.publishing_sites_pg as pub_pg

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(pub_pg, "SessionLocal", Session)
    monkeypatch.setattr(job_store, "SessionLocal", Session)

    u1 = User(email="tenant-a@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="tenant-b@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()

    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()

    yield session, u1, u2
    session.close()


def test_resolve_defaults_to_personal(db_session):
    session, u1, _u2 = db_session
    assert resolve_organization_id(u1.id, None, db=session) == personal_organization_id(u1.id)
    assert resolve_organization_id(u1.id, 0, db=session) == personal_organization_id(u1.id)
    assert resolve_organization_id(u1.id, -1, db=session) == personal_organization_id(u1.id)


def test_resolve_accepts_own_personal_org_id(db_session):
    session, u1, _u2 = db_session
    personal = personal_organization_id(u1.id)
    assert resolve_organization_id(u1.id, personal, db=session) == personal
    # Without db, personal still allowed
    assert resolve_organization_id(u1.id, personal) == personal


def test_resolve_rejects_foreign_personal_org_without_membership(db_session):
    session, u1, u2 = db_session
    victim_org = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError) as exc:
        resolve_organization_id(u1.id, victim_org, db=session)
    assert exc.value.code == "organization_forbidden"


def test_resolve_rejects_foreign_org_when_db_missing(db_session):
    _session, u1, u2 = db_session
    victim_org = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError):
        resolve_organization_id(u1.id, victim_org)


def test_resolve_allows_shared_org_only_for_member(db_session):
    session, u1, u2 = db_session
    shared_id = 900001
    session.add(
        Organization(
            id=shared_id,
            slug="shared-team-900001",
            name="Shared Team",
            status="active",
            kind="team",
        )
    )
    session.add(
        OrganizationMember(organization_id=shared_id, user_id=u1.id, role="owner")
    )
    session.commit()

    assert resolve_organization_id(u1.id, shared_id, db=session) == shared_id
    with pytest.raises(OrganizationForbiddenError):
        resolve_organization_id(u2.id, shared_id, db=session)
    assert user_belongs_to_organization(session, user_id=u1.id, organization_id=shared_id)
    assert not user_belongs_to_organization(session, user_id=u2.id, organization_id=shared_id)


def test_publishing_site_create_rejects_foreign_org_id(db_session):
    session, u1, u2 = db_session
    from app.services.publishing_sites_pg import create_site_pg, get_site_pg, list_sites_pg

    victim_org = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError):
        create_site_pg(
            {
                "name": "Hijack",
                "url": "https://hijack-example.test",
                "username": "admin",
                "app_password": "secret-app-pass-bbbb",
                "platform": "wordpress",
            },
            user_id=u1.id,
            organization_id=victim_org,
            db=session,
        )

    site = create_site_pg(
        {
            "name": "Own Site",
            "url": "https://own-example.test",
            "username": "admin",
            "app_password": "secret-app-pass-cccc",
            "platform": "wordpress",
        },
        user_id=u1.id,
        db=session,
    )
    session.commit()
    assert get_site_pg(site["id"], user_id=u2.id, db=session) is None
    with pytest.raises(OrganizationForbiddenError):
        list_sites_pg(user_id=u1.id, organization_id=victim_org, db=session)


def test_api_key_create_rejects_foreign_org_id(db_session):
    session, u1, u2 = db_session
    from app.services.user_api_keys_db import create_key_db, get_key_db, list_keys_db

    victim_org = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError):
        create_key_db(
            session,
            {"name": "k-hijack", "api_key": "sk-test-secret-value-hijack", "provider": "openai"},
            user_id=u1.id,
            organization_id=victim_org,
        )

    created = create_key_db(
        session,
        {"name": "k-own", "api_key": "sk-test-secret-value-own-key", "provider": "openai"},
        user_id=u1.id,
    )
    assert get_key_db(session, created["id"], user_id=u2.id, reveal_key=True) is None
    assert list_keys_db(session, user_id=u2.id) == []
    with pytest.raises(OrganizationForbiddenError):
        list_keys_db(session, user_id=u1.id, organization_id=victim_org)


def test_job_create_and_get_reject_cross_tenant_org(db_session):
    _session, u1, u2 = db_session
    import app.services.job_store as job_store

    victim_org = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError):
        job_store.create_job(
            job_type="test",
            user_id=u1.id,
            organization_id=victim_org,
            payload={"user_id": u1.id, "organization_id": victim_org},
        )

    st = job_store.create_job(job_type="test", user_id=u1.id, payload={"seed": "a"})
    assert st.organization_id == personal_organization_id(u1.id)
    assert job_store.get_job_for_user(st.job_id, user_id=u1.id) is not None
    assert job_store.get_job_for_user(st.job_id, user_id=u2.id) is None
    assert job_store.get_job_for_user(st.job_id, user_id=u1.id, organization_id=victim_org) is None


def test_assert_job_owned_does_not_trust_client_org_on_error():
    from fastapi import HTTPException

    from app.services.user_scope import assert_job_owned

    class _Job:
        user_id = 1
        organization_id = 1

    with pytest.raises(HTTPException) as exc:
        assert_job_owned(_Job(), user_id=1, organization_id=999999)
    assert exc.value.status_code == 404
