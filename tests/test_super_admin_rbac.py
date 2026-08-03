"""RBAC super_admin: unlimited access + no credit charge; normal users still gated."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.user import User
from app.services.auth import hash_password
from app.services.rbac import (
    has_unlimited_access,
    is_admin,
    is_super_admin,
    normalize_role,
)


def _ns_user(role: str, email: str = "user@example.com"):
    return SimpleNamespace(role=role, email=email, id=1, status="active")


def test_normalize_role_accepts_super_admin():
    assert normalize_role("super_admin") == "super_admin"
    assert normalize_role("SUPER_ADMIN") == "super_admin"


def test_super_admin_is_admin_and_unlimited():
    u = _ns_user("super_admin", "anyone@example.com")
    assert is_super_admin(u) is True
    assert is_admin(u) is True
    assert has_unlimited_access(u) is True


def test_normal_user_not_admin():
    u = _ns_user("user", "normal@example.com")
    assert is_super_admin(u) is False
    assert is_admin(u) is False
    assert has_unlimited_access(u) is False


def test_admin_role_still_admin():
    u = _ns_user("admin")
    assert is_admin(u) is True
    assert is_super_admin(u) is False


@pytest.fixture()
def db_session():
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.user_quota_addon  # noqa: F401
    import app.models.wordpress_plugin  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _db_user(db, email: str, *, role: str = "user") -> User:
    u = User(
        email=email,
        password_hash=hash_password("x"),
        has_password=True,
        role=role,
        status="active",
    )
    db.add(u)
    db.flush()
    return u


def test_entitlement_admin_bypass(db_session):
    from app.services.entitlement_service import check_feature

    admin = _db_user(db_session, "sa_test_admin@example.com", role="super_admin")
    normal = _db_user(db_session, "sa_test_user@example.com", role="user")

    ok = check_feature(db_session, admin, "content_ai_article", quantity=1)
    assert ok.allowed is True
    assert ok.reason_code in ("admin", "legacy_enforcement_off")

    denied = check_feature(db_session, normal, "content_ai_article", quantity=1)
    assert denied.reason_code != "admin"


def test_consume_credits_skips_super_admin(db_session):
    from app.services.credits import consume_credits, get_available_balance, grant_credits

    admin = _db_user(db_session, "sa_credit_admin@example.com", role="super_admin")
    grant_credits(db_session, user_id=admin.id, amount=10, reason="test_seed", note="seed")
    db_session.commit()
    before = get_available_balance(db_session, admin.id)
    after = consume_credits(
        db_session,
        user_id=admin.id,
        amount=5,
        reason="test_charge",
        note="should skip",
    )
    db_session.commit()
    assert after == before
    assert get_available_balance(db_session, admin.id) == before


def test_consume_credits_still_charges_normal_user(db_session):
    from app.services.credits import consume_credits, get_available_balance, grant_credits

    user = _db_user(db_session, "sa_credit_user@example.com", role="user")
    grant_credits(db_session, user_id=user.id, amount=10, reason="test_seed", note="seed")
    db_session.commit()
    before = get_available_balance(db_session, user.id)
    after = consume_credits(
        db_session,
        user_id=user.id,
        amount=3,
        reason="test_charge",
        note="should charge",
    )
    db_session.commit()
    assert after == before - 3


def test_plugin_entitlement_admin_unlimited_sites(db_session):
    from app.services.plugin_entitlement_service import PluginEntitlementService

    admin = _db_user(db_session, "sa_plugin_admin@example.com", role="super_admin")
    svc = PluginEntitlementService()
    ent = svc.check(db_session, admin, current_site_count=999)
    assert ent.allowed is True
    assert int(ent.max_sites) < 0 or int(ent.max_sites) >= 999
