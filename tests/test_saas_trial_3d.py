"""Tests for SEOAuto 3-day SaaS trial."""

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
from app.routers.trial_api import router as trial_router
from app.services import credits as credits_svc
from app.services.entitlement_service import check_feature
from app.services.saas_trial_service import (
    TRIAL_CREDIT_LIMIT,
    activate_saas_trial,
    check_trial_feature_allowed,
    record_daily_usage,
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


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(trial_router, prefix="/api")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _user(db) -> User:
    u = User(
        email=f"trial_{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        has_password=True,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "1")


def test_activate_trial_success(client, db):
    user = _user(db)
    db.commit()
    r = client.post("/api/trial/activate", headers=_auth(user), json={"device_fingerprint": "dev1"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["trial_active"] is True
    assert data["trial_days_remaining"] == 3
    assert data["trial_credit_limit"] == TRIAL_CREDIT_LIMIT

    r2 = client.post("/api/trial/activate", headers=_auth(user), json={})
    assert r2.status_code == 400


def test_trial_status_before_activate(client, db):
    user = _user(db)
    db.commit()
    r = client.get("/api/trial/status", headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["can_activate"] is True


def test_trial_status_hidden_when_free_usage_active(client, db):
    from app.services.free_usage_service import extend_free_usage_days

    user = _user(db)
    extend_free_usage_days(db, user.id, 5)
    db.commit()
    r = client.get("/api/trial/status", headers=_auth(user))
    assert r.status_code == 200
    data = r.json()
    assert data["can_activate"] is False
    assert data["free_usage_active"] is True


def test_activate_trial_blocked_when_free_usage_active(client, db):
    from app.services.free_usage_service import extend_free_usage_days

    user = _user(db)
    extend_free_usage_days(db, user.id, 5)
    db.commit()
    r = client.post("/api/trial/activate", headers=_auth(user), json={"device_fingerprint": "dev1"})
    assert r.status_code == 400
    assert "tặng" in r.json()["detail"].lower()


def test_trial_status_blocked_when_ip_claimed(db):
    user1 = _user(db)
    user2 = _user(db)
    db.commit()
    activate_saas_trial(db, user1, device_fingerprint="d1", ip_address="1.2.3.4")
    db.commit()

    data = trial_status_payload(db, user2, ip_address="1.2.3.4")
    assert data["can_activate"] is False
    assert data["trial_claim_blocked"] is True
    assert data["trial_used"] is False


def test_trial_status_blocked_when_device_claimed(db):
    user1 = _user(db)
    user2 = _user(db)
    db.commit()
    activate_saas_trial(db, user1, device_fingerprint="shared-device", ip_address="9.9.9.9")
    db.commit()

    data = trial_status_payload(db, user2, device_fingerprint="shared-device", ip_address="8.8.8.8")
    assert data["can_activate"] is False
    assert data["trial_claim_blocked"] is True


def test_trial_need_credit_when_zero(db):
    user = _user(db)
    db.commit()
    activate_saas_trial(db, user, device_fingerprint="d1", ip_address="1.2.3.4")
    db.commit()
    db.refresh(user)

    result = check_trial_feature_allowed(db, user, "content_ai_article")
    assert result["allowed"] is False
    assert "mua credit" in result["message"].lower()


def test_trial_content_ai_daily_limit(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.entitlement_service._credit_cost_for_feature",
        lambda _fk, _q=1: 5,
    )
    user = _user(db)
    db.commit()
    activate_saas_trial(db, user)
    credits_svc.grant_credits(
        db, user_id=user.id, amount=500, reason="buy", source_type="purchased", note="t"
    )
    db.commit()
    db.refresh(user)

    for _ in range(5):
        record_daily_usage(db, user.id, "content_ai_article", 1)
    db.commit()

    blocked = check_trial_feature_allowed(db, user, "content_ai_article")
    assert blocked["allowed"] is False
    assert "5" in blocked["message"]


def test_keyword_research_blocked_in_trial(db):
    user = _user(db)
    db.commit()
    activate_saas_trial(db, user)
    credits_svc.grant_credits(
        db, user_id=user.id, amount=100, reason="buy", source_type="purchased", note="t"
    )
    db.commit()
    db.refresh(user)

    result = check_feature(db, user, "keyword_research")
    assert result.allowed is False
    assert "nâng cấp" in result.message.lower() or "dùng thử" in result.message.lower()


def test_trial_credit_cap(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.entitlement_service._credit_cost_for_feature",
        lambda _fk, _q=1: 10,
    )
    user = _user(db)
    db.commit()
    activate_saas_trial(db, user)
    credits_svc.grant_credits(
        db, user_id=user.id, amount=5000, reason="buy", source_type="purchased", note="t"
    )
    user.trial_credit_used = TRIAL_CREDIT_LIMIT
    db.commit()
    db.refresh(user)

    result = check_trial_feature_allowed(db, user, "content_ai_article")
    assert result["allowed"] is False
    assert result["code"] == "trial_credit_cap"


def test_trial_expired_requires_upgrade(db):
    user = _user(db)
    db.commit()
    activate_saas_trial(db, user)
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    db.refresh(user)

    result = check_feature(db, user, "content_ai_article")
    assert result.allowed is False
    assert "nâng cấp" in result.message.lower() or "hết hạn" in result.message.lower()
