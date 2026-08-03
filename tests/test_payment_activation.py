"""Tests for activate_product billing fulfillment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.models.user_quota_addon import UserQuotaAddon
from app.services.credits import get_available_balance
from app.services.monthly_bonus_credit_service import grant_admin_plan_cycle_credits
from app.services.payment_activation_service import ProductActivationError, activate_product
from app.services.payment_order_service import create_payment_order
from app.services.saas_hybrid_pricing import plan_cycle_credit_breakdown
from app.services import subscription_service
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync, get_billing_product_by_code


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


def _user(db, email: str | None = None) -> User:
    addr = email or "activate@test.com"
    u = User(email=addr, password_hash=hash_password("x"), has_password=True)
    db.add(u)
    db.flush()
    return u


def _paid_order(db, user: User, product_code: str) -> PaymentOrder:
    order = create_payment_order(db, user_id=user.id, product_code=product_code)
    order.status = "paid"
    db.flush()
    return order


def test_activate_plan_grants_subscription_and_credits(db):
    user = _user(db)
    order = _paid_order(db, user, "STARTER_M")
    db.commit()

    result = activate_product(db, user_id=user.id, product_code="STARTER_M", order_id=order.id)
    db.commit()

    assert result["product_type"] == "plan"
    assert result["plan_slug"] == "starter"
    assert result["billing_cycle"] == "monthly"
    assert result["bonus_credits_granted"] == 500
    sub = subscription_service.get_active_subscription(db, user.id)
    assert sub is not None
    db.refresh(order)
    assert order.activation_status == "activated"


def test_activate_product_idempotent(db):
    user = _user(db)
    order = _paid_order(db, user, "PRO_M")
    db.commit()

    r1 = activate_product(db, user_id=user.id, product_code="PRO_M", order_id=order.id)
    db.commit()
    r2 = activate_product(db, user_id=user.id, product_code="PRO_M", order_id=order.id)
    db.commit()

    assert r1["bonus_credits_granted"] == 2500
    assert r2.get("idempotent") is True
    ledgers = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == user.id,
            CreditLedgerEntry.source_type == "monthly_bonus",
        )
        .all()
    )
    assert len(ledgers) == 1


def test_activate_credit_pack_with_expiry(db):
    user = _user(db)
    order = _paid_order(db, user, "CREDIT_100K")
    db.commit()

    result = activate_product(db, user_id=user.id, product_code="CREDIT_100K", order_id=order.id)
    db.commit()

    assert result["product_type"] == "credit_pack"
    assert result["credits"] == 1000
    ledger = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == user.id, CreditLedgerEntry.source_type == "purchased")
        .one()
    )
    assert ledger.expired_at is not None


def test_activate_article_addon(db):
    user = _user(db)
    order = _paid_order(db, user, "ARTICLE_ADDON_50")
    db.commit()

    result = activate_product(db, user_id=user.id, product_code="ARTICLE_ADDON_50", order_id=order.id)
    db.commit()

    assert result["product_type"] == "article_addon"
    assert result["articles"] == 50
    addon = db.query(UserQuotaAddon).filter(UserQuotaAddon.payment_order_id == order.id).one()
    assert addon.bonus_limit == 50


def test_activate_failure_marks_order(db, monkeypatch):
    user = _user(db)
    order = _paid_order(db, user, "STARTER_M")
    db.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        "app.services.payment_activation_service.subscription_service.extend_or_create_subscription",
        boom,
    )

    with pytest.raises(ProductActivationError):
        activate_product(db, user_id=user.id, product_code="STARTER_M", order_id=order.id)
    db.commit()
    db.refresh(order)
    assert order.status == "paid"
    assert order.activation_status == "activation_failed"
    assert "simulated failure" in (order.activation_error or "")


SEMI_ANNUAL_CASES = [
    ("STARTER_6M", "starter", 1_995_000, 3_500),
    ("PRO_6M", "pro", 3_995_000, 17_500),
    ("AGENCY_6M", "agency", 8_450_000, 49_000),
    ("BUSINESS_6M", "business", 17_450_000, 126_000),
]


@pytest.mark.parametrize("product_code,slug,price_vnd,total_credit", SEMI_ANNUAL_CASES)
def test_activate_semi_annual_plan(db, product_code, slug, price_vnd, total_credit):
    product = get_billing_product_by_code(product_code)
    assert product is not None
    assert product["billing_cycle"] == "semi_annual"
    assert int(product["duration_months"]) == 6
    assert int(product["price"]) == price_vnd
    assert int(product["total_credit"]) == total_credit

    breakdown = plan_cycle_credit_breakdown(slug, "semi_annual")
    assert breakdown["total_credit"] == total_credit
    assert breakdown["base_credit"] + breakdown["bonus_credit"] == total_credit

    user = _user(db)
    order = _paid_order(db, user, product_code)
    db.commit()

    before = datetime.now(timezone.utc)
    result = activate_product(db, user_id=user.id, product_code=product_code, order_id=order.id)
    db.commit()
    after = datetime.now(timezone.utc)

    assert result["product_type"] == "plan"
    assert result["plan_slug"] == slug
    assert result["billing_cycle"] == "semi_annual"
    assert result["duration_months"] == 6
    assert result["bonus_credits_granted"] == total_credit
    assert result["base_credit"] == breakdown["base_credit"]
    assert result["bonus_credit"] == breakdown["bonus_credit"]
    assert result["total_credit"] == total_credit

    sub = subscription_service.get_active_subscription(db, user.id)
    assert sub is not None
    end = sub.current_period_end
    assert end is not None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    min_end = before + timedelta(days=175)
    max_end = after + timedelta(days=190)
    assert min_end <= end <= max_end

    assert get_available_balance(db, user.id) == total_credit


@pytest.mark.parametrize("product_code,slug,price_vnd,total_credit", SEMI_ANNUAL_CASES)
def test_activate_semi_annual_preserves_existing_credit(db, product_code, slug, price_vnd, total_credit):
    user = _user(db)
    from app.services.credits import grant_credits

    grant_credits(db, user_id=user.id, amount=1200, reason="existing", source_type="purchased")
    order = _paid_order(db, user, product_code)
    db.commit()

    result = activate_product(db, user_id=user.id, product_code=product_code, order_id=order.id)
    db.commit()

    assert result["bonus_credits_granted"] == total_credit
    assert get_available_balance(db, user.id) == 1200 + total_credit


def test_monthly_and_semi_annual_unaffected_by_yearly(db):
    user = _user(db)
    order_m = _paid_order(db, user, "STARTER_M")
    db.commit()
    result_m = activate_product(db, user_id=user.id, product_code="STARTER_M", order_id=order_m.id)
    db.commit()
    assert result_m["billing_cycle"] == "monthly"
    assert result_m["bonus_credits_granted"] == 500

    user2 = _user(db, email="activate2@test.com")
    order_6m = _paid_order(db, user2, "STARTER_6M")
    db.commit()
    result_6m = activate_product(db, user_id=user2.id, product_code="STARTER_6M", order_id=order_6m.id)
    db.commit()
    assert result_6m["billing_cycle"] == "semi_annual"
    assert result_6m["bonus_credits_granted"] == 3500


YEARLY_CASES = [
    ("STARTER_Y", "starter", 3_990_000, 7_000),
    ("PRO_Y", "pro", 7_990_000, 35_000),
    ("AGENCY_Y", "agency", 16_900_000, 98_000),
    ("BUSINESS_Y", "business", 34_900_000, 252_000),
]


@pytest.mark.parametrize("product_code,slug,price_vnd,total_credit", YEARLY_CASES)
def test_activate_yearly_plan(db, product_code, slug, price_vnd, total_credit):
    product = get_billing_product_by_code(product_code)
    assert product is not None
    assert product["billing_cycle"] == "yearly"
    assert int(product["duration_months"]) == 14
    assert int(product["price"]) == price_vnd
    assert int(product["total_credit"]) == total_credit

    breakdown = plan_cycle_credit_breakdown(slug, "yearly")
    assert breakdown["total_credit"] == total_credit
    assert breakdown["base_credit"] + breakdown["bonus_credit"] == total_credit
    assert breakdown["total_duration_months"] == 14

    user = _user(db, email=f"yearly_{slug}@test.com")
    order = _paid_order(db, user, product_code)
    db.commit()

    before = datetime.now(timezone.utc)
    result = activate_product(db, user_id=user.id, product_code=product_code, order_id=order.id)
    db.commit()
    after = datetime.now(timezone.utc)

    assert result["product_type"] == "plan"
    assert result["plan_slug"] == slug
    assert result["billing_cycle"] == "yearly"
    assert result["duration_months"] == 14
    assert result["bonus_credits_granted"] == total_credit
    assert result["base_credit"] == breakdown["base_credit"]
    assert result["bonus_credit"] == breakdown["bonus_credit"]
    assert result["total_credit"] == total_credit

    sub = subscription_service.get_active_subscription(db, user.id)
    assert sub is not None
    end = sub.current_period_end
    assert end is not None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    min_end = before + timedelta(days=420)
    max_end = after + timedelta(days=435)
    assert min_end <= end <= max_end

    assert get_available_balance(db, user.id) == total_credit


@pytest.mark.parametrize("product_code,slug,price_vnd,total_credit", YEARLY_CASES)
def test_activate_yearly_preserves_existing_credit(db, product_code, slug, price_vnd, total_credit):
    user = _user(db, email=f"yearly_keep_{slug}@test.com")
    from app.services.credits import grant_credits

    grant_credits(db, user_id=user.id, amount=800, reason="existing", source_type="purchased")
    order = _paid_order(db, user, product_code)
    db.commit()

    result = activate_product(db, user_id=user.id, product_code=product_code, order_id=order.id)
    db.commit()

    assert result["bonus_credits_granted"] == total_credit
    assert get_available_balance(db, user.id) == 800 + total_credit


@pytest.mark.parametrize("slug,total_credit", [(s, c) for _, s, _, c in YEARLY_CASES])
def test_admin_grant_yearly_credits(db, slug, total_credit):
    from app.services import plan_service

    user = _user(db, email=f"admin_yearly_{slug}@test.com")
    plan = plan_service.get_plan_by_slug(db, slug)
    assert plan is not None

    sub = subscription_service.create_subscription(db, user.id, plan.id, months=14, status="active", source="manual")
    db.flush()

    result = grant_admin_plan_cycle_credits(
        db,
        user_id=user.id,
        plan_slug=slug,
        billing_cycle="yearly",
        note=f"admin_grant subscription_id={sub.id}",
    )
    db.commit()

    breakdown = plan_cycle_credit_breakdown(slug, "yearly")
    assert result["granted"] == total_credit
    assert result["base_credit"] == breakdown["base_credit"]
    assert result["bonus_credit"] == breakdown["bonus_credit"]
    assert result["billing_cycle"] == "yearly"
    assert result["total_duration_months"] == 14
    assert get_available_balance(db, user.id) == total_credit

    end = sub.current_period_end
    assert end is not None
    delta = end - sub.current_period_start
    assert 420 <= delta.days <= 435


@pytest.mark.parametrize("slug,total_credit", [(s, c) for _, s, _, c in SEMI_ANNUAL_CASES])
def test_admin_grant_semi_annual_credits(db, slug, total_credit):
    from app.services import plan_service

    user = _user(db)
    plan = plan_service.get_plan_by_slug(db, slug)
    assert plan is not None

    sub = subscription_service.create_subscription(db, user.id, plan.id, months=6, status="active", source="manual")
    db.flush()

    result = grant_admin_plan_cycle_credits(
        db,
        user_id=user.id,
        plan_slug=slug,
        billing_cycle="semi_annual",
        note=f"admin_grant subscription_id={sub.id}",
    )
    db.commit()

    breakdown = plan_cycle_credit_breakdown(slug, "semi_annual")
    assert result["granted"] == total_credit
    assert result["base_credit"] == breakdown["base_credit"]
    assert result["bonus_credit"] == breakdown["bonus_credit"]
    assert result["billing_cycle"] == "semi_annual"
    assert get_available_balance(db, user.id) == total_credit

    end = sub.current_period_end
    assert end is not None
    delta = end - sub.current_period_start
    assert 175 <= delta.days <= 190

