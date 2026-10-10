"""Tests for payment order service and API."""

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
from app.routers.saas import router as saas_router
from app.services.payment_order_service import (
    PaymentCheckoutError,
    build_order_code,
    create_payment_order,
    create_payment_order_checkout,
    expire_stale_pending_orders,
    payment_order_status_payload,
    resolve_product_amount,
)
from app.services.billing_vat import payment_amount_breakdown, price_with_vat as _vat_price
from app.services.safe_errors import global_exception_handler


@pytest.fixture()
def client():
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.plan  # noqa: F401

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
    app.include_router(saas_router, prefix="/api")
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _user(db, email: str = "pay@test.com") -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user.id)}


def test_resolve_product_amount_from_catalog(client):
    _, db = client
    row = resolve_product_amount("PRO_M", db)
    assert row["base_amount"] == 799_000
    assert row["vat_amount"] == 79_900
    assert row["amount"] == _vat_price(799_000)
    assert row["product_code"] == "PRO_M"
    assert "Pro" in row["product_name"]


def test_resolve_rejects_contact_sales(client):
    _, db = client
    with pytest.raises(PaymentCheckoutError, match="liên hệ"):
        resolve_product_amount("ARTICLE_ADDON_1000", db)


def test_build_order_code_format():
    from datetime import datetime, timezone

    code = build_order_code(42, datetime(2025, 6, 17, tzinfo=timezone.utc))
    assert code == "SEOA2025061742"


def test_create_payment_order_sets_bank_and_amount(client):
    _, db = client
    user = _user(db)
    db.commit()
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    assert order.amount == _vat_price(499_000)
    assert order.bank_code == "ACB"
    assert order.bank_account == "7982468"
    assert order.bank_holder == "Cong ty TNHH The Gioi Digi"
    assert order.status == "pending"
    assert order.order_code.startswith("SEOA")
    assert order.order_code.endswith(str(order.id))


def test_create_payment_order_api(client):
    tc, db = client
    user = _user(db)
    db.commit()
    r = tc.post(
        "/api/saas/payment-orders",
        json={"product_code": "CREDIT_100K"},
        headers=_auth(user),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["amount"] == _vat_price(100_000)
    assert data["product_code"] == "CREDIT_100K"
    assert data["status"] == "pending"
    assert data["order_code"].startswith("SEOA")


def test_create_payment_order_checkout_api(client):
    tc, db = client
    user = _user(db)
    db.commit()
    r = tc.post(
        "/api/saas/create-payment-order",
        json={"product_code": "PRO_M"},
        headers=_auth(user),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["contact_sales"] is False
    assert data["product_code"] == "PRO_M"
    assert data["product_name"]
    assert data["base_amount"] == 799_000
    assert data["vat_amount"] == 79_900
    assert data["vat_percent"] == 10
    assert data["amount"] == _vat_price(799_000)
    assert data["bank_code"] == "ACB"
    assert data["bank_account"] == "7982468"
    assert data["bank_holder"] == "Cong ty TNHH The Gioi Digi"
    assert data["transfer_content"] == data["order_code"]
    assert data["order_code"].startswith("SEOA")
    assert data["qr_url"] and "vietqr.io" in data["qr_url"]


def test_create_payment_order_contact_sales(client):
    tc, db = client
    user = _user(db)
    db.commit()
    r = tc.post(
        "/api/saas/create-payment-order",
        json={"product_code": "ARTICLE_ADDON_1000"},
        headers=_auth(user),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["contact_sales"] is True
    assert data["success"] is False
    assert data["product_code"] == "ARTICLE_ADDON_1000"
    assert data.get("order_code") is None


def test_create_rejects_extra_amount_from_frontend(client):
    tc, db = client
    user = _user(db)
    db.commit()
    r = tc.post(
        "/api/saas/create-payment-order",
        json={"product_code": "PRO_M", "amount": 1},
        headers=_auth(user),
    )
    assert r.status_code == 422


def test_create_rejects_unknown_product(client):
    tc, db = client
    user = _user(db)
    db.commit()
    r = tc.post(
        "/api/saas/payment-orders",
        json={"product_code": "NOPE_X"},
        headers=_auth(user),
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "unknown_product"


def test_expire_stale_pending_orders(client):
    _, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="PRO_M")
    from datetime import datetime, timedelta, timezone

    order.expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    n = expire_stale_pending_orders(db, user_id=user.id)
    db.commit()
    assert n == 1
    db.refresh(order)
    assert order.status == "expired"


def test_payment_order_status_api_owner(client):
    tc, db = client
    user = _user(db)
    db.commit()
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    r = tc.get(
        f"/api/saas/payment-orders/{order.order_code}/status",
        headers=_auth(user),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["order_code"] == order.order_code
    assert data["product_code"] == "CREDIT_100K"
    assert data["product_name"]
    assert data["amount"] == _vat_price(100_000)
    assert data["status"] == "pending"
    assert "activation_status" not in data or data.get("activation_status") is None


def test_payment_order_status_api_forbidden_other_user(client):
    tc, db = client
    owner = _user(db, "owner@test.com")
    other = _user(db, "other@test.com")
    order = create_payment_order(db, user_id=owner.id, product_code="PRO_M")
    db.commit()
    r = tc.get(
        f"/api/saas/payment-orders/{order.order_code}/status",
        headers=_auth(other),
    )
    assert r.status_code == 403


def test_payment_order_status_api_admin(client):
    tc, db = client
    owner = _user(db, "owner2@test.com")
    admin = _user(db, "admin@test.com")
    admin.role = "admin"
    order = create_payment_order(db, user_id=owner.id, product_code="STARTER_M")
    db.commit()
    r = tc.get(
        f"/api/saas/payment-orders/{order.order_code}/status",
        headers=_auth(admin),
    )
    assert r.status_code == 200
    assert r.json()["order_code"] == order.order_code


def test_payment_order_status_auto_expires(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="PRO_M")
    from datetime import datetime, timedelta, timezone

    order.expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    r = tc.get(
        f"/api/saas/payment-orders/{order.order_code}/status",
        headers=_auth(user),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "expired"
    db.refresh(order)
    assert order.status == "expired"


def test_payment_order_poll_status_pending(client):
    _, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    payload = payment_order_status_payload(order)
    assert payload["status"] == "pending"
    assert payload["poll_status"] == "pending"


def test_payment_order_poll_status_success_when_paid_and_activated(client):
    _, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    order.status = "paid"
    order.activation_status = "activated"
    db.commit()
    payload = payment_order_status_payload(order)
    assert payload["status"] == "paid"
    assert payload["poll_status"] == "success"
    assert payload["activation_status"] == "activated"


def test_payment_order_poll_status_failed_when_expired(client):
    _, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="PRO_M")
    order.status = "expired"
    db.commit()
    payload = payment_order_status_payload(order)
    assert payload["poll_status"] == "failed"


def test_payment_order_poll_status_api_returns_success(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    order.status = "paid"
    order.activation_status = "activated"
    db.commit()
    r = tc.get(
        f"/api/saas/payment-orders/{order.order_code}/status",
        headers=_auth(user),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["poll_status"] == "success"
    assert data["status"] == "paid"
