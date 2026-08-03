"""Tests for credit ledger v2 (buckets, FIFO, expiry, migration)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services.credits import (
    consume_credits,
    get_available_balance,
    grant_credits,
    purchased_expiry_months,
)


@pytest.fixture()
def db():
    import app.models.affiliate  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, balance: int = 0) -> User:
    u = User(
        email="credit@test.com",
        password_hash=hash_password("x"),
        has_password=True,
        credit_balance=balance,
    )
    db.add(u)
    db.flush()
    return u


def test_legacy_balance_migrated_to_bucket(db):
    user = _user(db, balance=500)
    db.commit()

    from app.migrations.ensure_credit_ledger_v2 import migrate_legacy_credit_balances

    migrate_legacy_credit_balances(db)
    db.commit()

    assert get_available_balance(db, user.id) == 500
    entry = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.user_id == user.id).one()
    assert entry.source_type == "admin_grant"
    assert entry.remaining_amount == 500
    assert entry.note == "legacy_balance_migration"


def test_consume_fifo_expiring_first(db):
    user = _user(db)
    now = datetime.now(timezone.utc)
    grant_credits(
        db,
        user_id=user.id,
        amount=100,
        reason="credit_pack_purchase",
        source_type="purchased",
        expired_at=now + timedelta(days=30),
        note="pack_soon",
    )
    grant_credits(
        db,
        user_id=user.id,
        amount=200,
        reason="credit_pack_purchase",
        source_type="purchased",
        expired_at=now + timedelta(days=365),
        note="pack_later",
    )
    db.commit()

    consume_credits(db, user_id=user.id, amount=50, reason="test_task", note="run")
    db.commit()

    rows = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == user.id)
        .order_by(CreditLedgerEntry.id)
        .all()
    )
    assert rows[0].remaining_amount == 50
    assert rows[1].remaining_amount == 200
    assert get_available_balance(db, user.id) == 250


def test_purchased_credit_has_expiry(db):
    user = _user(db)
    expiry = purchased_expiry_months(12)
    grant_credits(
        db,
        user_id=user.id,
        amount=1000,
        reason="credit_pack_purchase",
        source_type="purchased",
        expired_at=expiry,
        note="order=1",
    )
    db.commit()
    entry = db.query(CreditLedgerEntry).one()
    assert entry.source_type == "purchased"
    assert entry.expired_at is not None


def test_monthly_bonus_no_calendar_expiry(db):
    user = _user(db)
    from app.services.credits import plan_monthly_expiry_for_activation

    grant_credits(
        db,
        user_id=user.id,
        amount=1000,
        reason="plan_activation_bonus",
        source_type="plan_monthly",
        expired_at=plan_monthly_expiry_for_activation(),
        note="order_id=99 plan=starter",
    )
    db.commit()
    entry = db.query(CreditLedgerEntry).one()
    assert entry.source_type == "monthly_bonus"
    assert entry.expired_at is None


def test_expired_buckets_not_counted(db):
    user = _user(db)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    grant_credits(
        db,
        user_id=user.id,
        amount=100,
        reason="credit_pack_purchase",
        source_type="purchased",
        expired_at=past,
        note="expired",
    )
    db.commit()
    assert get_available_balance(db, user.id) == 0


def test_ensure_plan_monthly_syncs_locks_without_auto_grant(db):
    user = _user(db)
    plan = Plan(slug="pro", name="Pro", is_active=True)
    db.add(plan)
    db.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        started_at=datetime.now(timezone.utc),
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(sub)
    db.commit()

    from app.services.credits import ensure_plan_monthly_credits

    first = ensure_plan_monthly_credits(db, user.id)
    db.commit()
    second = ensure_plan_monthly_credits(db, user.id)
    db.commit()

    assert first is None
    assert second is None
    count = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.source_type == "monthly_bonus",
        )
        .count()
    )
    assert count == 0


def test_signup_bonus_idempotent(db, monkeypatch):
    monkeypatch.setenv("SIGNUP_CREDIT_BONUS", "200")
    user = _user(db)
    user.has_password = True
    db.commit()

    from app.services.credits import apply_signup_bonus_if_configured

    assert apply_signup_bonus_if_configured(db, user) is True
    db.commit()
    db.refresh(user)
    assert get_available_balance(db, user.id) == 200
    assert int(user.credit_balance or 0) == 200
    assert apply_signup_bonus_if_configured(db, user) is False
    db.commit()
    assert get_available_balance(db, user.id) == 200
