"""Tests for Monthly Bonus Credit — lock/unlock, cap, FIFO, idempotent SePay grants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.credit_policy_service import accumulation_cap_for_plan, monthly_grant_for_plan
from app.services.credit_policy_service import purchased_validity_months as policy_purchased_months
from app.services.credits import consume_credits, get_available_balance, grant_credits
from app.services.monthly_bonus_credit_service import (
    BUCKET_LOCKED,
    credit_wallet_breakdown,
    grant_monthly_bonus_for_order,
    lock_monthly_bonus_credits,
    sum_locked_monthly_bonus,
    sync_subscription_credit_locks,
    unlock_monthly_bonus_credits,
)
from app.services.payment_activation_service import activate_product
from app.services.payment_order_service import create_payment_order
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


def _user(db) -> User:
    u = User(email="mb@test.com", password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


def _active_sub(db, user: User, slug: str = "starter"):
    plan = plan_service.get_plan_by_slug(db, slug)
    assert plan is not None
    sub, _ = subscription_service.extend_or_create_subscription(
        db,
        user.id,
        plan.id,
        period_days=30,
        status="active",
        source="test",
    )
    return sub


def _expire_user_sub(db, user: User) -> None:
    subscription_service.expire_active_subscriptions_for_user(db, user.id)
    db.flush()


def test_renewal_grants_within_accumulation_cap(db):
    user = _user(db)
    _active_sub(db, user, "starter")
    db.commit()

    cap = accumulation_cap_for_plan("starter")
    monthly = monthly_grant_for_plan("starter")
    assert cap == 1000
    assert monthly == 500

    r1 = grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=101)
    r2 = grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=102)
    r3 = grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=103)
    db.commit()

    assert r1["granted"] == 500
    assert r2["granted"] == 500
    assert r3["granted"] == 0
    assert r3["reason"] == "at_accumulation_cap"
    assert get_available_balance(db, user.id) == cap

    buckets = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.source_type == "monthly_bonus",
        )
        .all()
    )
    assert len(buckets) == 2
    assert all(b.expired_at is None for b in buckets)
    assert all(b.status == "active" for b in buckets)


def test_expired_subscription_locks_monthly_bonus(db):
    user = _user(db)
    _active_sub(db, user, "pro")
    grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="pro", order_id=201)
    db.commit()

    assert get_available_balance(db, user.id) == 2500

    _expire_user_sub(db, user)
    sync_subscription_credit_locks(db, user.id)
    db.commit()

    assert get_available_balance(db, user.id) == 0
    assert sum_locked_monthly_bonus(db, user.id) == 2500

    locked_rows = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.status == BUCKET_LOCKED,
        )
        .all()
    )
    assert len(locked_rows) == 1
    assert locked_rows[0].locked_at is not None

    with pytest.raises(HTTPException) as exc:
        consume_credits(db, user_id=user.id, amount=1, reason="content_ai_article_medium")
    assert exc.value.status_code == 402
    detail = exc.value.detail
    assert detail["locked_credit"] == 2500


def test_renewal_unlocks_old_and_grants_new(db):
    user = _user(db)
    _active_sub(db, user, "starter")
    grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=301)
    db.commit()

    _expire_user_sub(db, user)
    sync_subscription_credit_locks(db, user.id)
    db.commit()
    assert sum_locked_monthly_bonus(db, user.id) == 500

    _active_sub(db, user, "starter")
    result = grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=302)
    db.commit()

    assert result["granted"] == 500
    assert sum_locked_monthly_bonus(db, user.id) == 0
    assert get_available_balance(db, user.id) == 1000

    ledger_events = (
        db.query(CreditLedger)
        .filter(
            CreditLedger.user_id == user.id,
            CreditLedger.reason.in_(("monthly_bonus_locked", "monthly_bonus_unlocked")),
        )
        .all()
    )
    reasons = {row.reason for row in ledger_events}
    assert "monthly_bonus_locked" in reasons
    assert "monthly_bonus_unlocked" in reasons


def test_sepay_activation_idempotent_no_duplicate_grant(db):
    user = _user(db)
    order = create_payment_order(db, user_id=user.id, product_code="STARTER_M")
    order.status = "paid"
    db.commit()

    r1 = activate_product(db, user_id=user.id, product_code="STARTER_M", order_id=order.id)
    db.commit()
    r2 = activate_product(db, user_id=user.id, product_code="STARTER_M", order_id=order.id)
    db.commit()

    assert r1["bonus_credits_granted"] == 500
    assert r2.get("idempotent") is True

    buckets = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.source_type == "monthly_bonus",
        )
        .all()
    )
    assert len(buckets) == 1
    assert f"order_id={order.id}" in (buckets[0].note or "")


def test_purchased_credit_validity_twelve_months(db):
    user = _user(db)
    now = datetime.now(timezone.utc)
    grant_credits(
        db,
        user_id=user.id,
        amount=1000,
        reason="credit_pack_purchase",
        source_type="purchased",
        note="pack_test",
    )
    db.commit()

    entry = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == user.id, CreditLedgerEntry.source_type == "purchased")
        .one()
    )
    assert entry.expired_at is not None
    months = policy_purchased_months()
    assert months == 12
    exp = entry.expired_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta = exp - now
    assert 350 <= delta.days <= 380


def test_consume_skips_locked_uses_purchased_fifo(db):
    user = _user(db)
    now = datetime.now(timezone.utc)

    grant_credits(
        db,
        user_id=user.id,
        amount=200,
        reason="monthly_bonus_grant",
        source_type="monthly_bonus",
        note="bonus_bucket",
        expired_at=None,
    )
    grant_credits(
        db,
        user_id=user.id,
        amount=80,
        reason="credit_pack_purchase",
        source_type="purchased",
        note="pack_a",
        expired_at=now + timedelta(days=10),
    )
    grant_credits(
        db,
        user_id=user.id,
        amount=120,
        reason="credit_pack_purchase",
        source_type="purchased",
        note="pack_b",
        expired_at=now + timedelta(days=90),
    )
    lock_monthly_bonus_credits(db, user.id)
    db.commit()

    assert get_available_balance(db, user.id) == 200

    consume_credits(db, user_id=user.id, amount=50, reason="keyword_research_run")
    db.commit()

    packs = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == user.id, CreditLedgerEntry.source_type == "purchased")
        .order_by(CreditLedgerEntry.id.asc())
        .all()
    )
    assert packs[0].remaining_amount == 30
    assert packs[1].remaining_amount == 120

    bonus = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == user.id, CreditLedgerEntry.source_type == "monthly_bonus")
        .one()
    )
    assert bonus.status == BUCKET_LOCKED
    assert bonus.remaining_amount == 200


def test_wallet_breakdown_locked_message(db):
    user = _user(db)
    _active_sub(db, user, "starter")
    grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=401)
    db.commit()

    _expire_user_sub(db, user)
    wallet = credit_wallet_breakdown(db, user.id, plan_slug="starter")
    db.commit()

    assert wallet["locked_credit"] == 500
    assert wallet["available_credit"] == 0
    assert wallet["locked_message"]
    assert "500" in wallet["locked_message"]
    assert wallet["renewal_grant_preview"]["amount"] == 500


def test_unlock_restores_spendable_balance(db):
    user = _user(db)
    grant_credits(
        db,
        user_id=user.id,
        amount=300,
        reason="monthly_bonus_grant",
        source_type="monthly_bonus",
    )
    lock_monthly_bonus_credits(db, user.id)
    db.commit()
    assert get_available_balance(db, user.id) == 0

    unlock_monthly_bonus_credits(db, user.id)
    db.commit()
    assert get_available_balance(db, user.id) == 300


def test_purchased_not_counted_in_monthly_cap(db):
    user = _user(db)
    _active_sub(db, user, "starter")
    grant_credits(
        db,
        user_id=user.id,
        amount=5000,
        reason="credit_pack_purchase",
        source_type="purchased",
    )
    grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=501)
    grant_monthly_bonus_for_order(db, user_id=user.id, plan_slug="starter", order_id=502)
    db.commit()

    assert get_available_balance(db, user.id) == 6000
    monthly_active = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.source_type == "monthly_bonus",
            CreditLedgerEntry.status == "active",
        )
        .all()
    )
    assert sum(r.remaining_amount for r in monthly_active) == 1000
