"""Free usage days (admin gift) — entitlement and user snapshot."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.saas import router as saas_router
from app.routers.saas_admin import router as saas_admin_router
from app.services import credits as credits_svc
from app.services.admin_gift_service import admin_gift_usage_days
from app.services.entitlement_service import check_feature
from app.services.free_usage_service import free_usage_days_remaining
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync


@pytest.fixture()
def db():
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    ensure_billing_catalog_sync(session)
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(saas_admin_router, prefix="/api/admin")
    app.include_router(saas_router, prefix="/api")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _user(db, *, role: str = "user") -> User:
    email = f"u_{uuid.uuid4().hex[:8]}@test.com"
    u = User(email=email, password_hash=hash_password("x"), has_password=True, role=role)
    db.add(u)
    db.flush()
    return u


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _admin_platform_check(monkeypatch):
    monkeypatch.setattr(
        "app.services.rbac.is_platform_admin",
        lambda u: u is not None and str(getattr(u, "role", "")).lower() == "admin",
    )


@pytest.fixture()
def enforcement_on(monkeypatch):
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "1")


@pytest.mark.parametrize("days", [5, 10, 15, 20, 25])
def test_admin_gift_usage_days_sets_free_usage_expires_at(client, db, days):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-usage-days",
        headers=_auth_header(admin),
        json={"days": days, "notes": f"Gift {days}d"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["days_granted"] == days
    assert data["free_usage_days_remaining"] == days
    assert data["free_usage_expires_at"]

    db.refresh(target)
    assert target.free_usage_expires_at is not None
    assert free_usage_days_remaining(db, target.id) == days


def test_admin_can_gift_without_credit_or_plan(client, db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-usage-days",
        headers=_auth_header(admin),
        json={"days": 10},
    )
    assert r.status_code == 200


def test_user_saas_me_shows_free_usage_banner(client, db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    client.post(
        f"/api/admin/saas/users/{target.id}/gift-usage-days",
        headers=_auth_header(admin),
        json={"days": 5},
    )

    r = client.get("/api/saas/me", headers=_auth_header(target))
    assert r.status_code == 200
    data = r.json()
    assert data["free_usage_active"] is True
    assert data["free_usage_days_remaining"] == 5
    assert "Còn 5 ngày dùng phần mềm" in (data["free_usage_banner"] or "")
    assert data.get("plan_name") == "Còn 5 ngày dùng phần mềm"
    assert data["needs_credit_for_features"] is True


def test_entitlement_blocks_without_credit_during_free_usage(db, enforcement_on):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    admin_gift_usage_days(db, admin=admin, target=target, days=10, notes="test")
    db.commit()

    result = check_feature(db, target, "content_ai_article")
    assert result.allowed is False
    assert "Còn 10 ngày dùng phần mềm" in result.message
    assert "mua credit" in result.message.lower()


def test_entitlement_allows_with_credit_during_free_usage(db, enforcement_on, monkeypatch):
    monkeypatch.setattr(
        "app.services.entitlement_service._credit_cost_for_feature",
        lambda _fk, _q=1: 10,
    )
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    admin_gift_usage_days(db, admin=admin, target=target, days=10, notes="test")
    credits_svc.grant_credits(
        db,
        user_id=target.id,
        amount=100,
        reason="test",
        source_type="purchased",
        note="test",
    )
    db.commit()
    db.refresh(target)

    result = check_feature(db, target, "content_ai_article")
    assert result.allowed is True
    assert result.reason_code in ("free_usage_credits", "credits")


def test_entitlement_requires_upgrade_when_free_usage_expired(db, enforcement_on):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    admin_gift_usage_days(db, admin=admin, target=target, days=1, notes="test")
    target.free_usage_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    db.refresh(target)

    result = check_feature(db, target, "content_ai_article")
    assert result.allowed is False
    assert "nâng cấp" in result.message.lower() or "gia hạn" in result.message.lower()
