"""Tests for admin gift plan and usage days."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.saas_admin import router as saas_admin_router
from app.services import subscription_service
from app.services.credits import grant_credits
from app.services.free_usage_service import free_usage_days_remaining
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync


@pytest.fixture()
def db():
    import app.models.affiliate  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.seo  # noqa: F401
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
    """Tests: role=admin is enough for SaaS admin routes."""
    monkeypatch.setattr(
        "app.services.rbac.is_platform_admin",
        lambda u: u is not None and str(getattr(u, "role", "")).lower() == "admin",
    )


def _grant_purchased_credit(db, user: User, amount: int = 500) -> None:
    grant_credits(
        db,
        user_id=user.id,
        amount=amount,
        reason="test_purchase",
        source_type="purchased",
        note="test",
    )


def _activate_plan(db, user: User, plan_slug: str = "starter", months: int = 1) -> None:
    from app.services import plan_service

    plan = plan_service.get_plan_by_slug(db, plan_slug)
    assert plan is not None
    subscription_service.create_subscription(db, user.id, plan.id, months=months, status="active")
    db.commit()


@pytest.mark.parametrize("plan_slug,credit", [
    ("starter", 500),
    ("pro", 2500),
    ("agency", 7000),
    ("business", 18000),
])
def test_gift_plan_all_tiers(client, db, plan_slug, credit):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-plan",
        headers=_auth_header(admin),
        json={"plan_slug": plan_slug, "duration_days": 30, "include_credit": True, "notes": "Test gift"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plan_slug"] == plan_slug
    assert data["credits_granted"] == credit
    sub = subscription_service.get_active_subscription(db, target.id)
    assert sub is not None


def test_gift_plan_without_credit(client, db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-plan",
        headers=_auth_header(admin),
        json={"plan_slug": "pro", "duration_months": 2, "include_credit": False},
    )
    assert r.status_code == 200
    assert r.json()["credits_granted"] == 0


@pytest.mark.parametrize("days", [5, 10, 15, 20, 25, 37])
def test_gift_usage_days(client, db, days):
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

    db.refresh(target)
    assert free_usage_days_remaining(db, target.id) == days


def test_gift_days_does_not_extend_subscription(client, db):
    admin = _user(db, role="admin")
    target = _user(db)
    _activate_plan(db, target, "starter", months=1)
    db.commit()

    sub_before = subscription_service.get_active_subscription(db, target.id)
    end_before = sub_before.current_period_end

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-usage-days",
        headers=_auth_header(admin),
        json={"days": 10},
    )
    assert r.status_code == 200

    sub_after = subscription_service.get_active_subscription(db, target.id)
    assert sub_after.current_period_end == end_before


def test_gift_history_and_eligibility(client, db):
    from app.models.security_audit_log import SecurityAuditLog
    from app.services.admin_gift_service import GIFT_PLAN_ACTION, list_user_gift_history

    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    elig = client.get(
        f"/api/admin/saas/users/{target.id}/gift-eligibility",
        headers=_auth_header(admin),
    )
    assert elig.status_code == 200
    assert elig.json()["can_gift_days"] is True

    client.post(
        f"/api/admin/saas/users/{target.id}/gift-plan",
        headers=_auth_header(admin),
        json={"plan_slug": "starter", "duration_days": 14, "include_credit": True},
    )

    db.add(
        SecurityAuditLog(
            user_id=admin.id,
            action=GIFT_PLAN_ACTION,
            resource_type="user",
            resource_id=str(target.id),
            detail_json='{"plan_slug":"starter","credits_granted":500,"reason":"test"}',
            ip_address="127.0.0.1",
        )
    )
    db.commit()

    items = list_user_gift_history(db, target.id)
    assert len(items) >= 1
    assert items[0]["badge"] == "Gói được tặng"

    hist = client.get(
        f"/api/admin/saas/users/{target.id}/gifts",
        headers=_auth_header(admin),
    )
    assert hist.status_code == 200
    assert len(hist.json()["items"]) >= 1


def test_non_admin_forbidden(client, db):
    user = _user(db, role="user")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/saas/users/{target.id}/gift-plan",
        headers=_auth_header(user),
        json={"plan_slug": "starter", "duration_days": 7},
    )
    assert r.status_code in (401, 403)
