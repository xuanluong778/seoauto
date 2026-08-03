"""Tests for credit purchase / admin grant auto-trial and gift usage days."""

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
from app.models.credit_ledger import CreditLedger
from app.models.user import User
from app.routers.admin import api_router as admin_router
from app.services import subscription_service
from app.services.admin_gift_service import admin_gift_usage_days
from app.services.admin_service import grant_credits_to_user_by_admin
from app.services.free_usage_service import free_usage_days_remaining
from app.services.payment_activation_service import activate_product
from app.services.payment_order_service import create_payment_order
from app.services.saas_trial_service import is_saas_trial_active, trial_days_remaining
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync


@pytest.fixture()
def db():
    import app.models.affiliate  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.saas_trial  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    from app.migrations.ensure_saas_trial_3d import _ensure_trial_plan

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    ensure_billing_catalog_sync(session)
    _ensure_trial_plan(session)
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/admin")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _user(db, *, role: str = "user") -> User:
    u = User(
        email=f"b_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        has_password=True,
        role=role,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setattr(
        "app.services.rbac.is_platform_admin",
        lambda u: u is not None and str(getattr(u, "role", "")).lower() == "admin",
    )


def _paid_order(db, user: User, product_code: str):
    order = create_payment_order(db, user_id=user.id, product_code=product_code)
    order.status = "paid"
    db.flush()
    return order


def test_credit_pack_auto_activates_trial_for_new_user(db):
    user = _user(db)
    order = _paid_order(db, user, "CREDIT_100K")
    db.commit()

    result = activate_product(db, user_id=user.id, product_code="CREDIT_100K", order_id=order.id)
    db.commit()
    db.refresh(user)

    assert result["trial_auto_activated"] is True
    assert is_saas_trial_active(user) is True
    assert trial_days_remaining(user) == 3
    assert subscription_service.get_active_subscription(db, user.id) is not None


def test_credit_pack_no_trial_reset_when_subscription_active(db):
    from app.services import plan_service

    user = _user(db)
    plan = plan_service.get_plan_by_slug(db, "starter")
    subscription_service.create_subscription(db, user.id, plan.id, months=1, status="active")
    order = _paid_order(db, user, "CREDIT_100K")
    db.commit()

    sub_before = subscription_service.get_active_subscription(db, user.id)
    end_before = sub_before.current_period_end

    result = activate_product(db, user_id=user.id, product_code="CREDIT_100K", order_id=order.id)
    db.commit()
    db.refresh(user)

    assert result["trial_auto_activated"] is False
    sub_after = subscription_service.get_active_subscription(db, user.id)
    assert sub_after.current_period_end == end_before


def test_admin_grant_credit_auto_trial(db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    _, balance, trial_auto = grant_credits_to_user_by_admin(
        db,
        target_user_id=target.id,
        credit_type="purchased",
        amount=200,
        reason="Test tặng credit",
        note="unit test",
        actor=admin,
    )
    db.refresh(target)

    assert trial_auto is True
    assert balance >= 200
    assert is_saas_trial_active(target) is True


def test_gift_usage_days_no_credit_granted(db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    before_ledgers = db.query(CreditLedger).filter(CreditLedger.user_id == target.id).count()
    admin_gift_usage_days(db, admin=admin, target=target, days=10, notes="gift days")
    db.commit()

    after_ledgers = db.query(CreditLedger).filter(CreditLedger.user_id == target.id).count()
    assert after_ledgers == before_ledgers
    assert free_usage_days_remaining(db, target.id) == 10


def test_admin_grant_credit_api_auto_trial(client, db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()

    r = client.post(
        f"/api/admin/users/{target.id}/grant-credits",
        headers=_auth(admin),
        json={
            "credit_type": "purchased",
            "amount": 100,
            "reason": "Tặng thử",
            "note": "test",
        },
    )
    assert r.status_code == 200, r.text
    db.refresh(target)
    assert is_saas_trial_active(target) is True
