"""Tests for user billing overview API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.routers.saas import router as saas_router
from app.services.account_billing_overview_service import build_billing_overview
from app.services.safe_errors import global_exception_handler
from app.services.seoauto_pricing_catalog import ensure_billing_catalog_sync


@pytest.fixture()
def client():
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.payment_order  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    ensure_billing_catalog_sync(db)
    user = User(
        email="billing@test.local",
        password_hash=hash_password("secret"),
        has_password=True,
        credit_balance=250,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.add_exception_handler(Exception, global_exception_handler)
    app.include_router(saas_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(user.id)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        c.user_id = user.id
        c.db = db
        c.auth_headers = {"Authorization": f"Bearer {token}"}
        yield c
    db.close()


def test_billing_overview_service_credit_and_history(client):
    db = client.db
    user_id = client.user_id
    now = datetime.now(timezone.utc)
    db.add(
        CreditLedgerEntry(
            user_id=user_id,
            source_type="purchased",
            amount=300,
            remaining_amount=120,
            expired_at=now + timedelta(days=5),
        )
    )
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=-25,
            balance_after=225,
            reason="content_ai_article_medium",
            module="content_ai",
            action="article_medium",
            credit_used=25,
        )
    )
    db.add(
        PaymentOrder(
            user_id=user_id,
            order_code="SEO-TEST-001",
            product_code="CREDIT_500",
            amount=500000,
            status="paid",
            bank_code="MB",
            bank_account="123",
            bank_holder="SEOAuto",
            expired_at=now + timedelta(hours=1),
            paid_at=now,
        )
    )
    db.commit()

    user = db.query(User).filter(User.id == user_id).one()
    payload = build_billing_overview(db, user, history_limit=10)

    assert payload["credit_balance"] == 120
    assert len(payload["credit_expiring_soon"]) == 1
    assert payload["credit_expiring_soon"][0]["amount"] == 120
    assert len(payload["credit_history"]) == 1
    assert payload["credit_history"][0]["credit_used"] == 25
    assert payload["credit_history"][0]["label"]
    assert len(payload["payment_history"]) == 1
    assert payload["payment_history"][0]["order_code"] == "SEO-TEST-001"
    assert any(a["code"] == "top_module" for a in payload["alerts"]) or payload["top_credit_module"]


def test_billing_overview_api(client):
    res = client.get("/api/saas/billing-overview")
    assert res.status_code == 200
    data = res.json()
    assert "credit_balance" in data
    assert "quotas" in data
    assert "credit_history" in data
    assert "payment_history" in data
    assert "alerts" in data
    assert "low_credit_threshold" in data


def test_billing_overview_hides_admin_grant_note(client):
    db = client.db
    user_id = client.user_id
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=100,
            balance_after=350,
            reason="admin_grant",
            note="internal admin secret note",
            grant_reason="Khuyến mãi tháng 6",
        )
    )
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=-10,
            balance_after=340,
            reason="keyword_research_run",
            module="keyword",
            action="research_run",
            credit_used=10,
        )
    )
    db.commit()
    user = db.query(User).filter(User.id == user_id).one()
    payload = build_billing_overview(db, user, history_limit=20)
    history = payload["credit_history"]
    assert all(h["delta"] < 0 for h in history)
    assert all("internal admin" not in str(h.get("note") or "").lower() for h in history)
