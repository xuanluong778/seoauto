"""Shared WordPress connection: org isolation, auto-select, no leaked secrets."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
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
    import app.services.wordpress_site_links_pg as links_pg

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(pub_pg, "SessionLocal", Session)
    monkeypatch.setattr(links_pg, "SessionLocal", Session)

    u1 = User(email="wp-org1@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="wp-org2@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()

    yield session, u1, u2, Session
    session.close()


def _make_site(session, user_id: int, url: str, password: str = "secret-app-pass-aaaa"):
    from app.services.publishing_sites_pg import create_site_pg
    from app.services.tenant_org import ensure_personal_organization

    ensure_personal_organization(session, user_id)
    session.commit()
    item = create_site_pg(
        {
            "name": url.replace("https://", ""),
            "url": url,
            "username": "admin",
            "app_password": password,
            "platform": "wordpress",
        },
        user_id=user_id,
        db=session,
    )
    session.commit()
    return item


def test_list_has_no_password_and_auto_selects_single_site(db_session):
    session, u1, u2, _Session = db_session
    site = _make_site(session, u1.id, "https://only-one.test")

    from app.services.wordpress_connection import list_wordpress_connections, resolve_wordpress_connection

    listing = list_wordpress_connections(user_id=u1.id)
    assert len(listing["items"]) == 1
    assert listing["default_site_id"] == site["id"]
    assert listing["items"][0].get("app_password") in (None, "")
    assert "secret-app-pass-aaaa" not in str(listing)

    cred = resolve_wordpress_connection(user_id=u1.id)
    assert cred["site_id"] == site["id"]
    assert cred["url"].rstrip("/") == "https://only-one.test"
    assert cred["username"] == "admin"
    assert cred["app_password"] == "secret-app-pass-aaaa"


def test_other_org_cannot_list_or_resolve_site(db_session):
    session, u1, u2, _Session = db_session
    site = _make_site(session, u1.id, "https://private-a.test", password="owner-secret-zzzz")

    from app.services.wordpress_connection import list_wordpress_connections, resolve_wordpress_connection

    other_list = list_wordpress_connections(user_id=u2.id)
    assert other_list["items"] == []
    assert other_list["default_site_id"] == ""

    with pytest.raises(HTTPException) as exc:
        resolve_wordpress_connection(user_id=u2.id, site_id=site["id"])
    assert exc.value.status_code in (400, 404)

    with pytest.raises(HTTPException) as exc2:
        resolve_wordpress_connection(user_id=u2.id, site_url="https://private-a.test")
    assert exc2.value.status_code in (400, 404)


def test_client_password_is_ignored_saved_site_wins(db_session):
    session, u1, _u2, _Session = db_session
    site = _make_site(session, u1.id, "https://itsieuviet.test", password="stored-pass-1111")

    from app.services.wordpress_connection import resolve_wordpress_connection

    cred = resolve_wordpress_connection(
        user_id=u1.id,
        site_id=site["id"],
        site_url="https://itsieuviet.test",
    )
    assert cred["app_password"] == "stored-pass-1111"
    assert cred["site_id"] == site["id"]


def test_resolve_strips_unicode_whitespace_from_password(db_session):
    session, u1, _u2, _Session = db_session
    site = _make_site(session, u1.id, "https://spaced-pass.test", password="aaaa\u00a0bbbb cccc")

    from app.services.wordpress_connection import resolve_wordpress_connection

    cred = resolve_wordpress_connection(user_id=u1.id, site_id=site["id"])
    assert cred["username"] == "admin"
    assert cred["app_password"] == "aaaabbbbcccc"
    assert " " not in cred["app_password"]
    assert "\u00a0" not in cred["app_password"]
