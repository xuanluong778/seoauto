"""Production checklist — SaaS UI messages, API lock, entitlement gates."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.saas import router as saas_router
from app.services import credits as credits_svc
from app.services import plan_service, subscription_service
from app.services.admin_gift_service import admin_gift_usage_days
from app.services.admin_service import grant_credits_to_user_by_admin
from app.services.entitlement_service import can_use_ai, check_feature
from app.services.free_usage_service import extend_free_usage_days
from app.services.payment_activation_service import activate_product
from app.services.payment_order_service import create_payment_order
from app.services.saas_trial_service import activate_saas_trial, is_saas_trial_active
from app.services.saas_ui_messages import (
    FORBIDDEN_UI_PHRASES,
    MSG_EXPIRED,
    MSG_NEED_CREDIT,
    MSG_NO_TRIAL,
    MSG_SYSTEM_API_MISSING,
    MSG_SYSTEM_OK,
    resolve_ai_access_state,
)
from app.services.saas_user_service import build_saas_me_response
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync
from app.services.user_api_access import assert_user_may_manage_api_keys, may_manage_custom_api_keys
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


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(saas_router, prefix="/api")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _user(db, *, role: str = "user", email: str | None = None) -> User:
    u = User(
        email=email or f"u_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        has_password=True,
        role=role,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}


def _grant(db, user: User, amount: int = 500) -> None:
    credits_svc.grant_credits(
        db, user_id=user.id, amount=amount, reason="test", source_type="purchased", note="t"
    )


def _paid_order(db, user: User, code: str = "CREDIT_100K"):
    order = create_payment_order(db, user_id=user.id, product_code=code)
    order.status = "paid"
    db.flush()
    return order


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setenv("COST_CONTROL_ENABLED", "1")

    def _system_api_ok(_db):
        return True

    monkeypatch.setattr(
        "app.services.user_api_access.admin_system_llm_available",
        _system_api_ok,
    )
    monkeypatch.setattr(
        "app.services.entitlement_service.admin_system_llm_available",
        _system_api_ok,
        raising=False,
    )


def test_01_trial_active_no_credit_blocks_ai(db):
    user = _user(db)
    activate_saas_trial(db, user)
    db.commit()
    db.refresh(user)
    assert is_saas_trial_active(user)
    ui = resolve_ai_access_state(db, user)
    assert ui["state"] == "need_credit"
    assert ui["message"] == MSG_NEED_CREDIT
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is False
    assert gate["code"] in {"insufficient_credits", "trial_need_credit"}


def test_02_credit_pack_auto_trial_and_system_api(db):
    user = _user(db)
    order = _paid_order(db, user)
    db.commit()
    result = activate_product(db, user_id=user.id, product_code="CREDIT_100K", order_id=order.id)
    db.commit()
    db.refresh(user)
    assert result["trial_auto_activated"] is True
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True


def test_03_admin_grant_credit_auto_trial(db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    _, _, trial_auto = grant_credits_to_user_by_admin(
        db,
        target_user_id=target.id,
        credit_type="purchased",
        amount=200,
        reason="gift",
        note="t",
        actor=admin,
    )
    db.refresh(target)
    assert trial_auto is True
    assert is_saas_trial_active(target)


def test_04_gift_days_no_credit_blocks_ai(db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    admin_gift_usage_days(db, admin=admin, target=target, days=10)
    db.commit()
    ui = resolve_ai_access_state(db, target)
    assert ui["state"] == "need_credit"
    gate = can_use_ai(db, target, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is False


def test_05_free_usage_plus_credit_uses_system_api(db):
    admin = _user(db, role="admin")
    target = _user(db)
    db.commit()
    extend_free_usage_days(db, target.id, 5)
    _grant(db, target, 100)
    db.commit()
    ui = resolve_ai_access_state(db, target)
    assert ui["state"] == "ready"
    assert ui["message"] == MSG_SYSTEM_OK
    gate = can_use_ai(db, target, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True


@pytest.mark.parametrize("slug", ["starter", "pro", "agency", "business"])
def test_06_08_plans_use_system_api_no_custom_keys(db, slug):
    user = _user(db)
    plan = plan_service.get_plan_by_slug(db, slug)
    subscription_service.create_subscription(db, user.id, plan.id, months=1, status="active")
    _grant(db, user, 200)
    db.commit()
    assert may_manage_custom_api_keys(db, user) is False
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True


def test_09_user_cannot_post_api_key(db):
    from fastapi import HTTPException

    user = _user(db)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        assert_user_may_manage_api_keys(db, user)
    assert exc.value.status_code == 403


def test_10_subscription_wins_over_trial(db, monkeypatch):
    monkeypatch.setattr("app.services.entitlement_service._credit_cost_for_feature", lambda _fk, _q=1: 5)
    user = _user(db)
    activate_saas_trial(db, user)
    starter = plan_service.get_plan_by_slug(db, "starter")
    subscription_service.create_subscription(db, user.id, starter.id, months=1, status="active")
    _grant(db, user, 100)
    db.commit()
    result = check_feature(db, user, "content_ai_article")
    assert result.allowed is True
    assert result.reason_code == "subscription"


def test_11_expired_trial_with_credit_blocked(db, monkeypatch):
    monkeypatch.setattr("app.services.entitlement_service._credit_cost_for_feature", lambda _fk, _q=1: 5)
    user = _user(db)
    activate_saas_trial(db, user)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    _grant(db, user, 500)
    db.commit()
    db.refresh(user)
    result = check_feature(db, user, "content_ai_article")
    assert result.allowed is False
    ui = resolve_ai_access_state(db, user)
    assert ui["state"] == "expired"
    assert ui["message"] == MSG_EXPIRED


def test_12_system_api_missing_message(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.user_api_access.admin_system_llm_available",
        lambda _db: False,
    )
    user = _user(db)
    activate_saas_trial(db, user)
    _grant(db, user, 100)
    db.commit()
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is False
    assert gate["code"] == "system_api_missing"
    assert gate["message"] == MSG_SYSTEM_API_MISSING


def test_13_user_isolation_saas_me(client, db):
    user_a = _user(db, email="a@test.com")
    user_b = _user(db, email="b@test.com")
    _grant(db, user_a, 100)
    db.commit()
    ra = client.get("/api/saas/me", headers=_auth(user_a))
    rb = client.get("/api/saas/me", headers=_auth(user_b))
    assert ra.status_code == 200
    assert rb.status_code == 200
    assert ra.json()["user_id"] == user_a.id
    assert rb.json()["user_id"] == user_b.id
    assert ra.json()["credit_balance"] >= 100
    assert rb.json()["credit_balance"] == 0


def test_14_saas_me_no_api_key_flag_for_regular_user(db):
    user = _user(db)
    _grant(db, user, 50)
    activate_saas_trial(db, user)
    db.commit()
    me = build_saas_me_response(db, user)
    assert me.can_manage_api_keys is False
    assert me.llm_source == "system"


def test_15_no_forbidden_ui_phrases_in_saas_me(db):
    user = _user(db)
    db.commit()
    me = build_saas_me_response(db, user)
    blob = " ".join(
        str(x or "")
        for x in (
            me.message,
            me.trial_message,
            me.ai_access_message,
            me.byok_note,
            me.saas_trial_banner,
        )
    ).lower()
    for phrase in FORBIDDEN_UI_PHRASES:
        assert phrase not in blob, f"found forbidden phrase: {phrase}"


def test_no_trial_message_for_new_user(db):
    user = _user(db)
    db.commit()
    ui = resolve_ai_access_state(db, user)
    assert ui["state"] == "no_trial"
    assert ui["message"] == MSG_NO_TRIAL
