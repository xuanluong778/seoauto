"""HTTP tests for SePay payment webhook."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.payments import router as payments_router
from app.services.payment_order_service import create_payment_order
from app.services.safe_errors import global_exception_handler
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SEPAY_WEBHOOK_SECRET", "test-sepay-secret")
    monkeypatch.setenv("BILLING_BANK_ACCOUNT", "7982468")

    import app.models.affiliate  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.sepay_payment_transaction  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.user_quota_addon  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    ensure_billing_catalog_sync(session)
    session.commit()

    app = FastAPI()
    app.include_router(payments_router, prefix="/api")
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, session
    app.dependency_overrides.clear()
    session.close()


def _auth_headers():
    return {"Authorization": "Bearer test-sepay-secret"}


def _user(db, email: str = "sepay@test.com") -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


def _payload(**overrides):
    base = {
        "id": "SEPAY-TX-100",
        "accountNumber": "7982468",
        "transferAmount": 399000,
        "transferType": "in",
        "content": "CK SEOA2025061799",
        "code": "SEOA2025061799",
    }
    base.update(overrides)
    return base


def test_webhook_requires_auth(client, monkeypatch):
    tc, _ = client
    # Default require_auth=True — forged/unsigned body must be rejected
    monkeypatch.delenv("SEPAY_WEBHOOK_REQUIRE_AUTH", raising=False)
    r = tc.post("/api/payments/sepay/webhook", json=_payload())
    assert r.status_code == 401


def test_webhook_rejects_invalid_unsigned_payload(client, monkeypatch):
    tc, _ = client
    monkeypatch.setenv("SEPAY_WEBHOOK_REQUIRE_AUTH", "0")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SEOAUTO_PRODUCTION", raising=False)
    r = tc.post("/api/payments/sepay/webhook", json={"foo": "bar"})
    assert r.status_code == 401


def test_webhook_rejects_missing_config_when_require_auth(client, monkeypatch):
    tc, _ = client
    monkeypatch.delenv("SEPAY_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("SEPAY_API_KEY", raising=False)
    monkeypatch.delenv("SEPAY_WEBHOOK_API_KEY", raising=False)
    monkeypatch.delenv("SEPAY_WEBHOOK_REQUIRE_AUTH", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(),
        headers={"Authorization": "Bearer any-token"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "payment_not_configured"


def test_webhook_accepts_unsigned_sepay_payload(client, monkeypatch):
    tc, db = client
    # Explicit non-production opt-out only
    monkeypatch.setenv("SEPAY_WEBHOOK_REQUIRE_AUTH", "0")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SEOAUTO_PRODUCTION", raising=False)
    user = _user(db, email="unsigned@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    order_code = order.order_code

    # No Authorization header — local unsigned mode
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(
            id="67216744",
            code=order_code,
            transferAmount=order.amount,
            content=f"CK {order_code}",
        ),
    )
    assert r.status_code == 200
    db.refresh(order)
    assert order.status == "paid"
    assert order.activation_status == "activated"


def test_webhook_health_get_head(client):
    tc, _ = client
    assert tc.get("/api/payments/sepay/webhook").status_code == 200
    assert tc.head("/api/payments/sepay/webhook").status_code == 200


def test_webhook_wrong_account_no_activation(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    order_code = order.order_code

    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-WRONG-ACC", accountNumber="1111111", code=order_code),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    db.refresh(order)
    assert order.status == "pending"


def test_webhook_full_payment_activates(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    order_code = order.order_code

    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-PAID-1", code=order_code, transferAmount=order.amount),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    db.refresh(order)
    assert order.status == "paid"
    assert order.paid_at is not None


def test_webhook_partial_payment(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    order_code = order.order_code

    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-PARTIAL-1", code=order_code, transferAmount=100000),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    db.refresh(order)
    assert order.status == "partial_paid"


def test_webhook_duplicate_transaction(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    order_code = order.order_code
    body = _payload(id="TX-DUP-1", code=order_code, transferAmount=order.amount)
    headers = _auth_headers()

    r1 = tc.post("/api/payments/sepay/webhook", json=body, headers=headers)
    assert r1.status_code == 200
    r2 = tc.post("/api/payments/sepay/webhook", json=body, headers=headers)
    assert r2.status_code == 200
    db.refresh(order)
    assert order.status == "paid"


def test_webhook_order_code_in_messy_content(client):
    tc, db = client
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    order_code = order.order_code
    # No explicit code field — extract from bank memo with junk separators.
    ymd = order_code[4:12]
    oid = order_code[12:]
    messy = f"NGUYEN VAN A chuyen SEOA {ymd[:4]}-{ymd[4:6]}-{ymd[6:]}-{oid} ACB"
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(
            id="TX-MESSY-1",
            code=None,
            content=messy,
            transferAmount=order.amount,
        ),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    db.refresh(order)
    assert order.status == "paid"
    assert order.activation_status == "activated"


def test_webhook_credit_pack_idempotent(client):
    tc, db = client
    user = _user(db, email="credit@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    from app.services.credits import get_available_balance

    before = get_available_balance(db, user.id)
    body = _payload(id="TX-CREDIT-1", code=order.order_code, transferAmount=order.amount)
    headers = _auth_headers()
    assert tc.post("/api/payments/sepay/webhook", json=body, headers=headers).status_code == 200
    mid = get_available_balance(db, user.id)
    assert mid > before
    assert tc.post("/api/payments/sepay/webhook", json=body, headers=headers).status_code == 200
    after = get_available_balance(db, user.id)
    assert after == mid


def test_webhook_accepts_apikey_auth_scheme(client, monkeypatch):
    tc, _ = client
    monkeypatch.setenv("SEPAY_API_KEY", "official-sepay-api-key")
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-APIKEY-SCHEME"),
        headers={"Authorization": "Apikey official-sepay-api-key"},
    )
    assert r.status_code == 200


def test_webhook_accepts_hmac_sha256(client, monkeypatch):
    import hashlib
    import hmac
    import json
    import time

    tc, _ = client
    secret = "hmac-test-secret"
    monkeypatch.setenv("SEPAY_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("SEPAY_API_KEY", raising=False)
    monkeypatch.delenv("SEPAY_WEBHOOK_API_KEY", raising=False)
    body = _payload(id="TX-HMAC-1")
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    r = tc.post(
        "/api/payments/sepay/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-SePay-Signature": f"sha256={digest}",
            "X-SePay-Timestamp": ts,
        },
    )
    assert r.status_code == 200


def test_webhook_late_after_expire_still_activates(client):
    from datetime import datetime, timedelta, timezone

    tc, db = client
    user = _user(db, email="late@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    order.expired_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-LATE-1", code=order.order_code, transferAmount=order.amount),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    db.refresh(order)
    assert order.status == "paid"


def test_webhook_order_not_found_still_success(client):
    tc, _ = client
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-NO-ORDER", code="SEOA209901011"),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_webhook_forged_payload_without_auth_rejected(client, monkeypatch):
    tc, db = client
    monkeypatch.delenv("SEPAY_WEBHOOK_REQUIRE_AUTH", raising=False)
    user = _user(db, email="forged@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    # Attacker sends valid-looking SePay JSON matching bank account + order code — no auth
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(
            id="TX-FORGED-1",
            code=order.order_code,
            transferAmount=order.amount,
            content=f"CK {order.order_code}",
        ),
    )
    assert r.status_code == 401
    db.refresh(order)
    assert order.status == "pending"


def test_webhook_wrong_hmac_signature_rejected(client, monkeypatch):
    import json
    import time

    tc, db = client
    secret = "hmac-test-secret"
    monkeypatch.setenv("SEPAY_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("SEPAY_API_KEY", raising=False)
    monkeypatch.delenv("SEPAY_WEBHOOK_API_KEY", raising=False)
    monkeypatch.delenv("SEPAY_WEBHOOK_REQUIRE_AUTH", raising=False)
    user = _user(db, email="badsig@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    body = _payload(id="TX-BAD-HMAC", code=order.order_code, transferAmount=order.amount)
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    r = tc.post(
        "/api/payments/sepay/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-SePay-Signature": "sha256=deadbeef" + ("0" * 56),
            "X-SePay-Timestamp": ts,
        },
    )
    assert r.status_code == 401
    db.refresh(order)
    assert order.status == "pending"


def test_webhook_missing_hmac_and_api_key_rejected(client, monkeypatch):
    tc, db = client
    monkeypatch.delenv("SEPAY_WEBHOOK_REQUIRE_AUTH", raising=False)
    user = _user(db, email="nosig@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    # HMAC headers incomplete (timestamp only) and no API key
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-NOSIG", code=order.order_code, transferAmount=order.amount),
        headers={"X-SePay-Timestamp": "1710000000"},
    )
    assert r.status_code == 401
    db.refresh(order)
    assert order.status == "pending"


def test_production_ignores_require_auth_off(client, monkeypatch):
    tc, db = client
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEPAY_WEBHOOK_REQUIRE_AUTH", "0")
    user = _user(db, email="prod-unsigned@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    db.commit()
    r = tc.post(
        "/api/payments/sepay/webhook",
        json=_payload(id="TX-PROD-UNSIGNED", code=order.order_code, transferAmount=order.amount),
    )
    assert r.status_code == 401
    db.refresh(order)
    assert order.status == "pending"


def test_webhook_replay_same_tx_idempotent_with_auth(client):
    tc, db = client
    user = _user(db, email="replay@test.com")
    order = create_payment_order(db, user_id=user.id, product_code="CREDIT_100K")
    db.commit()
    from app.services.credits import get_available_balance

    before = get_available_balance(db, user.id)
    body = _payload(id="TX-REPLAY-1", code=order.order_code, transferAmount=order.amount)
    headers = _auth_headers()
    assert tc.post("/api/payments/sepay/webhook", json=body, headers=headers).status_code == 200
    mid = get_available_balance(db, user.id)
    assert mid > before
    # Replay identical webhook — still 200, no double credit
    assert tc.post("/api/payments/sepay/webhook", json=body, headers=headers).status_code == 200
    assert get_available_balance(db, user.id) == mid
    db.refresh(order)
    assert order.status == "paid"
    assert order.activation_status == "activated"
