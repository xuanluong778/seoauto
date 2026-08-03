"""Tests for admin billing APIs."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.admin_billing import router as admin_billing_router
from app.services.payment_order_service import create_payment_order
from app.services.safe_errors import global_exception_handler


@pytest.fixture()
def client():
    import app.models.affiliate  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.sepay_payment_transaction  # noqa: F401
    import app.models.subscription  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync

    ensure_billing_catalog_sync(db)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(admin_billing_router, prefix="/admin/api")
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _user(db, email: str, *, role: str = "user") -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True, role=role)
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user.id)}


def _admin(db) -> User:
    return _user(db, "xuanluong778@gmail.com", role="admin")


def test_admin_list_payment_orders(client):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "buyer@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()

    r = tc.get("/admin/api/billing/payment-orders", headers=_auth(admin))
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["items"][0]["order_code"] == order.order_code
    assert data["items"][0]["user_email"] == "buyer@test.com"


def test_admin_list_forbidden_non_admin(client):
    tc, db = client
    user = _user(db, "user@test.com")
    db.commit()
    r = tc.get("/admin/api/billing/payment-orders", headers=_auth(user))
    assert r.status_code == 403


def test_admin_mark_paid_and_cancel(client):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "buyer2@test.com")
    pending = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    to_cancel = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()

    r = tc.post(f"/admin/api/billing/payment-orders/{pending.id}/mark-paid", headers=_auth(admin))
    assert r.status_code == 200
    assert r.json()["order"]["status"] == "paid"

    r2 = tc.post(f"/admin/api/billing/payment-orders/{to_cancel.id}/cancel", headers=_auth(admin))
    assert r2.status_code == 200
    assert r2.json()["order"]["status"] == "cancelled"


def test_admin_list_filter_activation_failed(client, monkeypatch):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "buyer3@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="PRO_M")
    order.status = "paid"
    order.activation_status = "activation_failed"
    order.activation_error = "simulated"
    db.commit()

    r = tc.get(
        "/admin/api/billing/payment-orders?status=activation_failed",
        headers=_auth(admin),
    )
    assert r.status_code == 200
    codes = [x["order_code"] for x in r.json()["items"]]
    assert order.order_code in codes


def test_admin_actions_write_audit_log(client):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "buyer4@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()

    r = tc.post(f"/admin/api/billing/payment-orders/{order.id}/cancel", headers=_auth(admin))
    assert r.status_code == 200
    assert r.json()["order"]["status"] == "cancelled"
    db.refresh(order)
    assert order.status == "cancelled"
