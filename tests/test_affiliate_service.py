"""Tests for affiliate program backend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.affiliate import (
    AffiliateAccount,
    AffiliateAdjustment,
    AffiliateClick,
    AffiliateCommission,
    AffiliatePayout,
    AffiliateReferral,
    AffiliateSettings,
)
from app.models.user import User
from app.services.affiliate_service import (
    AFFILIATE_COOKIE,
    _hash_value,
    approve_commission,
    attach_referral_from_cookie,
    cancel_commission_for_refund,
    compute_balances,
    get_settings,
    mark_payout_paid,
    record_commission_for_payment,
    register_affiliate,
    release_held_commissions,
    request_payout,
    sign_affiliate_cookie,
    track_click,
    try_attach_referral_from_request,
    verify_affiliate_cookie,
)
from app.services.auth import hash_password


@pytest.fixture()
def db_session():
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.payment_transaction  # noqa: F401
    import app.models.affiliate  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        get_settings(db)
        db.commit()
        yield db
    finally:
        db.close()


def _user(db, email: str) -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


class _FakeRequest:
    def __init__(self, ip: str = "1.2.3.4", url: str = "https://seoauto.vn/?ref=ABC"):
        self.client = type("C", (), {"host": ip})()
        self.headers = {"user-agent": "pytest"}
        self.url = url
        self.query_params = {}


def test_register_affiliate_creates_active_account(db_session):
    u = _user(db_session, "aff@test.com")
    acc = register_affiliate(db_session, u)
    db_session.commit()
    assert acc.referral_code
    assert acc.status == "active"
    assert acc.commission_rate == 30
    assert acc.cookie_days == 60


def test_migrate_legacy_pending_to_active(db_session):
    u = _user(db_session, "legacy@test.com")
    acc = AffiliateAccount(
        user_id=u.id,
        referral_code="LEGACY01",
        status="pending",
        commission_rate=30,
        cookie_days=60,
    )
    db_session.add(acc)
    db_session.commit()
    from app.services.affiliate_service import migrate_legacy_affiliate_accounts

    n = migrate_legacy_affiliate_accounts(db_session)
    db_session.commit()
    db_session.refresh(acc)
    assert n == 1
    assert acc.status == "active"


def test_self_referral_blocked(db_session):
    aff_user = _user(db_session, "aff2@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    ref_user = aff_user
    got = attach_referral_from_cookie(
        db_session,
        user=ref_user,
        referral_code=acc.referral_code,
        click_id=None,
    )
    assert got is None


def test_referral_and_commission_30_percent(db_session):
    aff_user = _user(db_session, "aff3@test.com")
    cust = _user(db_session, "cust@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(
        AffiliateReferral(
            affiliate_id=acc.id,
            referred_user_id=cust.id,
            status="registered",
        )
    )
    db_session.flush()
    comm = record_commission_for_payment(
        db_session,
        user_id=cust.id,
        order_amount=1_000_000,
        payment_transaction_id=99,
    )
    assert comm is not None
    assert comm.commission_rate == 30
    assert comm.commission_amount == 300_000
    assert comm.status == "pending"
    assert comm.idempotency_key == "ptx:99"


def test_commission_cancelled_on_refund(db_session):
    aff_user = _user(db_session, "aff4@test.com")
    cust = _user(db_session, "cust4@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(
        AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid")
    )
    db_session.flush()
    comm = record_commission_for_payment(
        db_session,
        user_id=cust.id,
        order_amount=500_000,
        payment_transaction_id=42,
    )
    assert comm.status == "pending"
    n = cancel_commission_for_refund(db_session, payment_transaction_id=42)
    assert n == 1
    db_session.refresh(comm)
    assert comm.status == "cancelled"


def test_ip_hash_not_stored_raw(db_session):
    aff_user = _user(db_session, "aff5@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.flush()
    result = track_click(
        db_session,
        referral_code=acc.referral_code,
        request=_FakeRequest(ip="9.9.9.9"),
    )
    assert result
    click = db_session.query(AffiliateClick).filter(AffiliateClick.id == result["click_id"]).one()
    assert click.ip_hash == _hash_value("9.9.9.9")
    assert "9.9.9.9" not in (click.ip_hash or "")


def test_balances_pending_until_approved(db_session):
    aff_user = _user(db_session, "aff6@test.com")
    cust = _user(db_session, "cust6@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(
        AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid")
    )
    db_session.flush()
    record_commission_for_payment(
        db_session,
        user_id=cust.id,
        order_amount=100_000,
        payment_transaction_id=7,
    )
    bal = compute_balances(db_session, acc.id)
    assert bal["pending"] == 30_000
    assert bal["withdrawable"] == 0


def test_referral_not_overwritten(db_session):
    aff1 = _user(db_session, "aff7a@test.com")
    aff2 = _user(db_session, "aff7b@test.com")
    acc1 = register_affiliate(db_session, aff1)
    acc2 = register_affiliate(db_session, aff2)
    acc1.status = "active"
    acc2.status = "active"
    cust = _user(db_session, "cust7@test.com")
    db_session.flush()
    db_session.add(
        AffiliateReferral(affiliate_id=acc1.id, referred_user_id=cust.id, status="registered")
    )
    db_session.commit()
    token = sign_affiliate_cookie(referral_code=acc2.referral_code, click_id=None, cookie_days=60)
    req = type("R", (), {"cookies": {AFFILIATE_COOKIE: token}})()
    ref = try_attach_referral_from_request(req, cust, db_session)
    assert ref is not None
    assert ref.affiliate_id == acc1.id


def test_try_attach_self_referral_blocked(db_session):
    aff_user = _user(db_session, "aff8@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.commit()
    token = sign_affiliate_cookie(referral_code=acc.referral_code, click_id=None, cookie_days=60)
    req = type("R", (), {"cookies": {AFFILIATE_COOKIE: token}})()
    ref = try_attach_referral_from_request(req, aff_user, db_session)
    assert ref is None


def test_forged_cookie_rejected(db_session):
    aff_user = _user(db_session, "aff_forge@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    cust = _user(db_session, "cust_forge@test.com")
    db_session.commit()
    # Plain unsigned referral code must not attribute
    req = type("R", (), {"cookies": {AFFILIATE_COOKIE: acc.referral_code}})()
    assert try_attach_referral_from_request(req, cust, db_session) is None
    assert verify_affiliate_cookie("not-a-jwt") is None


def test_signed_cookie_and_click_binding(db_session):
    aff_user = _user(db_session, "aff_bind@test.com")
    other = _user(db_session, "aff_other@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc2 = register_affiliate(db_session, other)
    acc.status = "active"
    acc2.status = "active"
    cust = _user(db_session, "cust_bind@test.com")
    db_session.flush()
    click = track_click(db_session, referral_code=acc.referral_code, request=_FakeRequest())
    db_session.commit()
    # Mismatched click_id / code rejected
    bad = attach_referral_from_cookie(
        db_session,
        user=cust,
        referral_code=acc2.referral_code,
        click_id=click["click_id"],
    )
    assert bad is None
    token = sign_affiliate_cookie(
        referral_code=acc.referral_code,
        click_id=click["click_id"],
        cookie_days=60,
    )
    req = type("R", (), {"cookies": {AFFILIATE_COOKIE: token}})()
    ref = try_attach_referral_from_request(req, cust, db_session)
    assert ref is not None
    assert ref.affiliate_id == acc.id


def test_commission_idempotent_on_repeat(db_session):
    aff_user = _user(db_session, "aff_idem@test.com")
    cust = _user(db_session, "cust_idem@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    c1 = record_commission_for_payment(
        db_session, user_id=cust.id, order_amount=200_000, payment_transaction_id=555
    )
    c2 = record_commission_for_payment(
        db_session, user_id=cust.id, order_amount=200_000, payment_transaction_id=555
    )
    assert c1 is not None and c2 is not None
    assert c1.id == c2.id
    assert db_session.query(AffiliateCommission).count() == 1


def test_partial_payout_keeps_remaining_commission(db_session):
    settings = get_settings(db_session)
    settings.min_payout_amount = 50_000
    aff_user = _user(db_session, "aff_partial@test.com")
    cust = _user(db_session, "cust_partial@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    acc.bank_name = "VCB"
    acc.bank_account_name = "A"
    acc.bank_account_number = "123"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="9001",
        idempotency_key="ptx:9001",
        order_amount=1_000_000,
        commission_rate=30,
        commission_amount=300_000,
        paid_amount=0,
        status="pending",
    )
    db_session.add(comm)
    db_session.flush()
    approve_commission(db_session, comm.id)
    payout = request_payout(db_session, aff_user, amount=100_000)
    payout.status = "processing"
    db_session.flush()
    mark_payout_paid(db_session, payout.id, "FT1", None)
    db_session.refresh(comm)
    assert comm.status == "approved"
    assert int(comm.paid_amount) == 100_000
    bal = compute_balances(db_session, acc.id)
    assert bal["withdrawable"] == 200_000


def test_release_held_commissions(db_session):
    aff_user = _user(db_session, "aff_hold@test.com")
    cust = _user(db_session, "cust_hold@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="8001",
        idempotency_key="ptx:8001",
        order_amount=100_000,
        commission_rate=30,
        commission_amount=30_000,
        status="pending",
        hold_until=past,
    )
    db_session.add(comm)
    db_session.flush()
    n = release_held_commissions(db_session)
    db_session.refresh(comm)
    assert n == 1
    assert comm.status == "approved"
    bal = compute_balances(db_session, acc.id)
    assert bal["withdrawable"] == 30_000


def test_refund_after_paid_creates_debt(db_session):
    aff_user = _user(db_session, "aff_debt@test.com")
    cust = _user(db_session, "cust_debt@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="7001",
        idempotency_key="ptx:7001",
        order_amount=500_000,
        commission_rate=30,
        commission_amount=150_000,
        paid_amount=150_000,
        status="paid",
    )
    db_session.add(comm)
    db_session.flush()
    n = cancel_commission_for_refund(db_session, payment_transaction_id=7001)
    assert n == 1
    debt_rows = db_session.query(AffiliateAdjustment).filter(AffiliateAdjustment.affiliate_id == acc.id).all()
    assert len(debt_rows) == 1
    assert debt_rows[0].amount == 150_000
    assert debt_rows[0].status == "open"
    # Future approved commission is reduced by debt
    comm2 = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="7002",
        idempotency_key="ptx:7002",
        order_amount=1_000_000,
        commission_rate=30,
        commission_amount=300_000,
        status="approved",
    )
    db_session.add(comm2)
    db_session.flush()
    bal = compute_balances(db_session, acc.id)
    assert bal["debt"] == 150_000
    assert bal["withdrawable"] == 150_000


def test_admin_approve_clears_hold_and_adds_withdrawable(db_session):
    """Admin Duyệt phải bỏ hold và cộng ngay vào số dư có thể rút."""
    settings = get_settings(db_session)
    settings.min_payout_amount = 200_000
    aff_user = _user(db_session, "aff_flow@test.com")
    cust = _user(db_session, "cust_flow@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    acc.bank_name = "VCB"
    acc.bank_account_name = "Nguyen Van A"
    acc.bank_account_number = "0123456789"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    future = datetime.now(timezone.utc) + timedelta(days=7)
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="6101",
        idempotency_key="ptx:6101",
        order_amount=1_000_000,
        commission_rate=30,
        commission_amount=300_000,
        status="pending",
        hold_until=future,
    )
    db_session.add(comm)
    db_session.flush()

    before = compute_balances(db_session, acc.id)
    assert before["pending"] == 300_000
    assert before["withdrawable"] == 0

    approved = approve_commission(db_session, comm.id)
    db_session.refresh(comm)
    assert approved.status == "approved"
    assert comm.status == "approved"
    assert comm.hold_until is None

    after = compute_balances(db_session, acc.id)
    assert after["pending"] == 0
    assert after["withdrawable"] == 300_000

    payout = request_payout(db_session, aff_user)
    assert payout.status == "requested"
    assert payout.amount == 300_000

    # Duplicate open payout blocked
    try:
        request_payout(db_session, aff_user)
        assert False, "expected duplicate payout to fail"
    except Exception as exc:
        assert "chờ xử lý" in str(getattr(exc, "detail", exc))

    reserved = compute_balances(db_session, acc.id)
    assert reserved["withdrawable"] == 0
    assert reserved["reserved"] == 300_000


def test_request_payout_requires_bank_and_min_balance(db_session):
    settings = get_settings(db_session)
    settings.min_payout_amount = 200_000
    aff_user = _user(db_session, "aff_min@test.com")
    cust = _user(db_session, "cust_min@test.com")
    acc = register_affiliate(db_session, aff_user)
    acc.status = "active"
    db_session.add(AffiliateReferral(affiliate_id=acc.id, referred_user_id=cust.id, status="paid"))
    db_session.flush()
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=cust.id,
        order_id="6201",
        idempotency_key="ptx:6201",
        order_amount=500_000,
        commission_rate=30,
        commission_amount=150_000,
        status="approved",
    )
    db_session.add(comm)
    db_session.flush()

    try:
        request_payout(db_session, aff_user)
        assert False, "expected bank info required"
    except Exception as exc:
        assert "ngân hàng" in str(getattr(exc, "detail", exc)).lower()

    acc.bank_name = "VCB"
    acc.bank_account_name = "A"
    acc.bank_account_number = "1"
    db_session.flush()
    try:
        request_payout(db_session, aff_user)
        assert False, "expected min payout rejection"
    except Exception as exc:
        assert "tối thiểu" in str(getattr(exc, "detail", exc)).lower()
