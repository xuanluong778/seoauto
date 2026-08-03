"""HTTP API tests for affiliate endpoints (minimal app)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.admin_affiliate import router as admin_affiliate_router
from app.routers.affiliate import router as affiliate_router
from app.services.affiliate_service import approve_commission, get_settings, register_affiliate


@pytest.fixture()
def client():
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.affiliate  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    get_settings(db)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(affiliate_router)
    app.include_router(admin_affiliate_router, prefix="/admin")
    from app.services.safe_errors import global_exception_handler
    from fastapi import HTTPException

    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _user(db, email: str) -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user.id)}


def test_track_click_sets_signed_cookie(client):
    tc, db = client
    aff = _user(db, "aff_api@test.com")
    acc = register_affiliate(db, aff)
    acc.status = "active"
    db.commit()
    r = tc.post("/affiliate/track-click", json={"referral_code": acc.referral_code})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["referral_code"] == acc.referral_code
    assert "seo_aff_ref" in r.cookies
    from app.services.affiliate_service import verify_affiliate_cookie

    parsed = verify_affiliate_cookie(r.cookies.get("seo_aff_ref"))
    assert parsed is not None
    assert parsed["referral_code"] == acc.referral_code


def test_track_click_invalid_code(client):
    tc, _db = client
    r = tc.post("/affiliate/track-click", json={"referral_code": "NOTEXIST"})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "invalid_code"


def test_track_click_rate_limit_rule_configured():
    from app.services.rate_limiter import RATE_RULES

    assert "/affiliate/track-click" in RATE_RULES
    assert RATE_RULES["/affiliate/track-click"][0] > 0


def test_user_overview_requires_auth(client):
    tc, _db = client
    r = tc.get("/affiliate/overview")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "unauthorized"


def test_user_register_and_overview(client):
    tc, db = client
    u = _user(db, "user_api@test.com")
    db.commit()
    r = tc.post("/affiliate/register", headers=_auth(u), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["referral_code"]

    r2 = tc.get("/affiliate/overview", headers=_auth(u))
    assert r2.status_code == 200
    ov = r2.json()
    assert ov["success"] is True
    assert ov["data"]["registered"] is True


def test_payout_rejected_below_minimum(client):
    tc, db = client
    u = _user(db, "payout_api@test.com")
    acc = register_affiliate(db, u)
    acc.status = "active"
    acc.bank_name = "VCB"
    acc.bank_account_name = "Test"
    acc.bank_account_number = "1234567890"
    db.commit()
    r = tc.post("/affiliate/payout-request", headers=_auth(u), json={})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "bad_request"


def test_admin_accounts_forbidden_for_user(client):
    tc, db = client
    u = _user(db, "normal@test.com")
    db.commit()
    r = tc.get("/admin/affiliate/accounts", headers=_auth(u))
    assert r.status_code == 403
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "forbidden"


def test_admin_commission_approve_validation(client):
    tc, db = client
    admin = _user(db, "xuanluong778@gmail.com")
    aff_u = _user(db, "aff_admin@test.com")
    cust = _user(db, "cust_admin@test.com")
    acc = register_affiliate(db, aff_u)
    acc.status = "active"
    from app.models.affiliate import AffiliateReferral, AffiliateCommission

    db.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_amount=100_000,
        commission_rate=30,
        commission_amount=30_000,
        status="paid",
    )
    db.add(comm)
    db.commit()

    r = tc.post(f"/admin/affiliate/commissions/{comm.id}/approve", headers=_auth(admin))
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


def test_admin_approve_and_mark_payout_paid(client):
    tc, db = client
    admin = _user(db, "xuanluongmarketing@gmail.com")
    aff_u = _user(db, "aff_pay2@test.com")
    cust = _user(db, "cust_pay2@test.com")
    acc = register_affiliate(db, aff_u)
    acc.status = "active"
    acc.bank_name = "VCB"
    acc.bank_account_name = "Test User"
    acc.bank_account_number = "1234567890"
    from app.models.affiliate import AffiliateReferral, AffiliateCommission, AffiliatePayout
    from app.services.affiliate_service import approve_commission

    db.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_amount=500_000,
        commission_rate=30,
        commission_amount=150_000,
        status="pending",
    )
    db.add(comm)
    db.flush()
    approve_commission(db, comm.id)
    payout = AffiliatePayout(affiliate_id=acc.id, amount=150_000, status="requested", payout_method="bank")
    db.add(payout)
    db.commit()

    r = tc.post(f"/admin/affiliate/payouts/{payout.id}/approve", headers=_auth(admin), json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "processing"

    r2 = tc.post(
        f"/admin/affiliate/payouts/{payout.id}/mark-paid",
        headers=_auth(admin),
        json={"transaction_ref": "FT123", "note": "ok"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "paid"


def test_admin_mark_payout_paid_twice(client):
    tc, db = client
    admin = _user(db, "xuanluongmarketing@gmail.com")
    aff_u = _user(db, "aff_pay@test.com")
    cust = _user(db, "cust_pay@test.com")
    acc = register_affiliate(db, aff_u)
    acc.status = "active"
    from app.models.affiliate import AffiliateReferral, AffiliateCommission, AffiliatePayout

    db.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_amount=500_000,
        commission_rate=30,
        commission_amount=150_000,
        status="pending",
    )
    db.add(comm)
    db.flush()
    approve_commission(db, comm.id)
    payout = AffiliatePayout(affiliate_id=acc.id, amount=150_000, status="paid", payout_method="bank")
    db.add(payout)
    db.commit()

    r = tc.post(f"/admin/affiliate/payouts/{payout.id}/mark-paid", headers=_auth(admin), json={})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_approve_then_user_payout_flow(client):
    """Duyệt hoa hồng (kể cả đang hold) → withdrawable → user tạo payout requested → admin thấy bank info."""
    from datetime import datetime, timedelta, timezone

    from app.models.affiliate import AffiliateCommission, AffiliatePayout, AffiliateReferral

    tc, db = client
    admin = _user(db, "xuanluong778@gmail.com")
    aff_u = _user(db, "aff_flow_api@test.com")
    cust = _user(db, "cust_flow_api@test.com")
    settings = get_settings(db)
    settings.min_payout_amount = 200_000
    acc = register_affiliate(db, aff_u)
    acc.status = "active"
    acc.bank_name = "Vietcombank"
    acc.bank_account_name = "Nguyen Van Flow"
    acc.bank_account_number = "9988776655"
    db.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="6301",
        idempotency_key="ptx:6301",
        order_amount=1_000_000,
        commission_rate=30,
        commission_amount=300_000,
        status="pending",
        hold_until=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(comm)
    db.commit()

    r = tc.post(f"/admin/affiliate/commissions/{comm.id}/approve", headers=_auth(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "approved"
    assert body["data"]["balances"]["withdrawable"] == 300_000
    assert body["data"]["balances"]["pending"] == 0

    ov = tc.get("/affiliate/overview", headers=_auth(aff_u))
    assert ov.status_code == 200
    assert ov.json()["data"]["balances"]["withdrawable"] == 300_000
    assert ov.json()["data"]["payout_info"]["has_bank_info"] is True

    pr = tc.post("/affiliate/payout-request", headers=_auth(aff_u), json={})
    assert pr.status_code == 200, pr.text
    assert pr.json()["data"]["status"] == "requested"
    assert pr.json()["data"]["amount"] == 300_000

    # duplicate blocked
    pr2 = tc.post("/affiliate/payout-request", headers=_auth(aff_u), json={})
    assert pr2.status_code == 400

    admin_list = tc.get("/admin/affiliate/payouts?status=requested", headers=_auth(admin))
    assert admin_list.status_code == 200
    items = admin_list.json()["data"]["items"]
    assert len(items) >= 1
    hit = next(p for p in items if p["id"] == pr.json()["data"]["id"])
    assert hit["status"] == "requested"
    assert hit["bank_name"] == "Vietcombank"
    assert hit["bank_account_name"] == "Nguyen Van Flow"
    assert hit["bank_account_number"] == "9988776655"
    assert db.query(AffiliatePayout).filter(AffiliatePayout.id == hit["id"]).one().status == "requested"
