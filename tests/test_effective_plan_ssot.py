"""Regression: paid subscription always wins over expired trial banner."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.entitlement_service import (
    check_feature,
    resolve_effective_plan,
    resolve_effective_plan_state,
)
from app.services.saas_trial_service import (
    check_trial_feature_allowed,
    end_saas_trial_state,
    trial_status_payload,
)
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync
from app.migrations.ensure_saas_trial_3d import _ensure_trial_plan


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


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "0")


def _user(db, *, trial_used: bool = False, trial_expired: bool = False) -> User:
    now = datetime.now(timezone.utc)
    u = User(
        email=f"plan_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        has_password=True,
        trial_used=trial_used,
        trial_started_at=now - timedelta(days=10) if trial_used else None,
        trial_expires_at=(now - timedelta(days=1)) if trial_expired else (
            (now + timedelta(days=2)) if trial_used and not trial_expired else None
        ),
    )
    db.add(u)
    db.flush()
    return u


def _grant_plan(db, user: User, slug: str, *, days: int = 30, status: str = "active"):
    plan = plan_service.get_plan_by_slug(db, slug)
    assert plan is not None, f"missing plan {slug}"
    subscription_service.extend_or_create_subscription(
        db,
        user.id,
        plan.id,
        period_days=days,
        status=status,
        source="test_grant",
        notes="effective_plan_ssot",
    )
    db.flush()


def test_pro_active_trial_expired_no_banner(db):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, "pro")
    db.commit()

    payload = trial_status_payload(db, user)
    state = resolve_effective_plan_state(db, user)

    assert resolve_effective_plan(db, user) == "pro"
    assert state["has_paid_plan"] is True
    assert state["effective_plan_slug"] == "pro"
    assert state["show_trial_expired_banner"] is False
    assert state["show_upgrade_banner"] is False
    assert payload["has_paid_plan"] is True
    assert payload["banner"] is None
    assert payload["show_upgrade_banner"] is False
    assert "hết hạn" not in str(payload.get("banner") or "").lower()


def test_pro_active_no_upgrade_banner(db):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, "pro")
    db.commit()
    payload = trial_status_payload(db, user)
    assert payload["show_upgrade_banner"] is False
    assert payload["can_activate"] is False


def test_pro_active_feature_access(db):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, "pro")
    db.commit()
    trial_gate = check_trial_feature_allowed(db, user, "content_ai_article")
    assert trial_gate.get("allowed") is True
    ent = check_feature(db, user, "content_ai_article")
    assert ent.allowed is True
    assert ent.plan_slug == "pro"


def test_trial_expired_no_paid(db):
    user = _user(db, trial_used=True, trial_expired=True)
    db.commit()
    payload = trial_status_payload(db, user)
    state = resolve_effective_plan_state(db, user)
    assert state["has_paid_plan"] is False
    assert state["show_trial_expired_banner"] is True
    assert payload["banner"] and "hết hạn" in payload["banner"]
    assert payload["show_upgrade_banner"] is True
    gate = check_trial_feature_allowed(db, user, "seo_score")
    assert gate.get("allowed") is False
    assert gate.get("code") == "trial_expired"


def test_expired_pro_blocked_correctly(db):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, "pro", days=30)
    db.flush()
    from app.services.subscription_service import get_active_subscription, _expire_subscription_row
    from datetime import datetime, timezone

    sub = get_active_subscription(db, user.id)
    assert sub is not None
    now = datetime.now(timezone.utc)
    _expire_subscription_row(sub, now=now)
    db.flush()
    db.commit()

    state = resolve_effective_plan_state(db, user)
    assert state["has_paid_plan"] is False
    assert resolve_effective_plan(db, user) is None
    payload = trial_status_payload(db, user)
    assert payload["show_upgrade_banner"] is True
    assert payload["banner"] and "hết hạn" in payload["banner"]


@pytest.mark.parametrize("slug", ["starter", "agency", "business", "pro"])
def test_paid_plan_active_matrix(db, slug):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, slug)
    db.commit()
    state = resolve_effective_plan_state(db, user)
    payload = trial_status_payload(db, user)
    assert state["effective_plan_slug"] == slug
    assert state["has_paid_plan"] is True
    assert payload["banner"] is None
    assert payload["effective_plan_slug"] == slug


def test_plan_api_ui_same_fields(db):
    user = _user(db, trial_used=True, trial_expired=True)
    _grant_plan(db, user, "pro")
    db.commit()
    payload = trial_status_payload(db, user)
    state = resolve_effective_plan_state(db, user)
    assert payload["effective_plan_slug"] == state["effective_plan_slug"]
    assert payload["has_paid_plan"] == state["has_paid_plan"]
    assert payload["show_upgrade_banner"] == state["show_upgrade_banner"]


def test_cache_refresh_after_upgrade(db):
    """After trial→paid, status flips without relying on session/JWT plan cache."""
    user = _user(db, trial_used=True, trial_expired=False)
    user.trial_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.flush()
    before = trial_status_payload(db, user)
    # Simulate payment ending trial then granting pro
    end_saas_trial_state(db, user.id, reason="trial_to_paid")
    _grant_plan(db, user, "pro")
    db.commit()
    db.refresh(user)
    after = trial_status_payload(db, user)
    assert after["has_paid_plan"] is True
    assert after["banner"] is None
    assert after["effective_plan_slug"] == "pro"
    # Historical trial_used may remain; must not drive banner
    assert after["trial_used"] is True
    assert before.get("has_paid_plan") is False


def test_no_credit_inferred_as_plan(db):
    user = _user(db, trial_used=True, trial_expired=True)
    db.commit()
    # Credits alone must not create paid plan
    state = resolve_effective_plan_state(db, user)
    assert state["has_paid_plan"] is False
    assert state["effective_plan_slug"] is None
