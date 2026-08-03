"""Tests for SaaS economics dashboard, thresholds, and expensive API guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.routers.admin_saas_economics import router as admin_saas_economics_router
from app.services.cost_control.types import ExternalApiProvider
from app.services.credits import consume_credits, grant_credits
from app.services.saas_economics_guard import assert_expensive_api_allowed, expensive_api_blocked
from app.services.saas_economics_service import (
    build_economics_dashboard,
    evaluate_thresholds_and_block,
    provider_for_ledger,
    save_economics_settings,
)
from app.services.safe_errors import global_exception_handler


@pytest.fixture()
def client():
    import app.models.affiliate  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.saas_economics  # noqa: F401
    import app.models.seo  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    import json

    from app.models.saas_economics import SaasEconomicsConfig, SaasEconomicsState
    from app.services.saas_economics_service import DEFAULT_ECONOMICS_SETTINGS

    db.add(
        SaasEconomicsConfig(
            key="settings",
            value_json=json.dumps(DEFAULT_ECONOMICS_SETTINGS, ensure_ascii=False),
        )
    )
    db.add(SaasEconomicsState(id=1, expensive_api_blocked=False))
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(admin_saas_economics_router, prefix="/api/admin")
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _user(db, email: str, *, role: str = "user") -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True, role=role)
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user.id)}


def _admin(db) -> User:
    return _user(db, "xuanluong778@gmail.com", role="admin")


def test_provider_for_ledger_mapping():
    assert provider_for_ledger(module="keyword", action="research_run", reason=None) == "dataforseo"
    assert provider_for_ledger(module="lead_scanner", action="basic_scan", reason=None) == "google_places"
    assert provider_for_ledger(module="content_ai", action="google_image", reason=None) == "google_cse"
    assert provider_for_ledger(module="audit", action="technical_deep", reason=None) == "crawl"
    assert provider_for_ledger(module=None, action=None, reason="keyword_research_run") == "dataforseo"


def test_dashboard_aggregates_burn_and_revenue(client):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "heavy@test.com")
    grant_credits(db, user_id=user.id, amount=5000, reason="test_grant", note="test")
    consume_credits(
        db,
        user_id=user.id,
        amount=120,
        reason="keyword_research_run",
        module="keyword",
        action="research_run",
    )
    now = datetime.now(timezone.utc)
    db.add(
        PaymentOrder(
            user_id=user.id,
            product_code="PRO_M",
            amount=878_900,
            status="paid",
            bank_code="MB",
            bank_account="123",
            bank_holder="SEOAuto",
            expired_at=now + timedelta(days=1),
            paid_at=now,
        )
    )
    db.add(
        PaymentOrder(
            user_id=user.id,
            product_code="CREDIT_100K",
            amount=110_000,
            status="paid",
            bank_code="MB",
            bank_account="123",
            bank_holder="SEOAuto",
            expired_at=now + timedelta(days=1),
            paid_at=now,
        )
    )
    db.commit()

    dash = build_economics_dashboard(db)
    assert dash["credit_burn"]["month"] >= 120
    assert dash["revenue"]["month"]["subscription_gross_vnd"] == 878_900
    assert dash["revenue"]["month"]["credit_pack_gross_vnd"] == 110_000
    assert any(p["provider"] == "dataforseo" for p in dash["by_provider"]["month"])

    res = tc.get("/api/admin/saas/economics/dashboard", headers=_auth(admin))
    assert res.status_code == 200
    body = res.json()
    assert body["credit_burn"]["month"] >= 120
    assert "alerts" in body


def test_threshold_auto_block_and_guard(client):
    tc, db = client
    admin = _admin(db)
    user = _user(db, "burner@test.com")
    save_economics_settings(
        db,
        {
            "daily_cost_threshold_vnd": 100,
            "monthly_cost_threshold_vnd": 1_000_000,
            "auto_block_expensive_api": True,
            "vnd_per_credit": {"dataforseo": 500, "openai": 500},
        },
    )
    grant_credits(db, user_id=user.id, amount=5000, reason="test_grant", note="test")
    consume_credits(
        db,
        user_id=user.id,
        amount=50,
        reason="keyword_research_run",
        module="keyword",
        action="research_run",
    )
    db.commit()

    result = evaluate_thresholds_and_block(db, trigger="test")
    db.commit()
    assert result["exceeded_daily"] is True
    assert expensive_api_blocked(db) is True

    with pytest.raises(HTTPException) as exc:
        assert_expensive_api_allowed(
            db,
            user=user,
            provider=ExternalApiProvider.DATAFORSEO,
        )
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "expensive_api_blocked"

    assert_expensive_api_allowed(db, user=admin, provider=ExternalApiProvider.OPENAI)

    res = tc.post("/api/admin/saas/economics/unblock", headers=_auth(admin))
    assert res.status_code == 200
    assert res.json()["expensive_api_blocked"] is False


def test_settings_patch_requires_admin(client):
    tc, db = client
    user = _user(db, "norm@test.com")
    res = tc.patch(
        "/api/admin/saas/economics/settings",
        headers=_auth(user),
        json={"daily_cost_threshold_vnd": 999},
    )
    assert res.status_code == 403
