"""Tests for credit preview API."""

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
from app.routers.credits_preview import router as credits_preview_router
from app.services.credit_preview_service import build_credit_preview


@pytest.fixture()
def client():
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
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
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(credits_preview_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _user(db, email: str = "u@test.com") -> User:
    u = User(email=email, password_hash=hash_password("x"), has_password=True, role="user")
    db.add(u)
    db.flush()
    return u


def test_build_credit_preview_keyword(client):
    _, db = client
    user = _user(db)
    data = build_credit_preview(
        db,
        user,
        module="keyword",
        action="research_run",
        quota_key="keyword_research",
        label="Keyword Research",
    )
    assert data["module"] == "keyword"
    assert data["action"] == "research_run"
    assert data["label"] == "Keyword Research"
    assert data["data_source"] == "api"


def test_preview_api_requires_auth(client):
    tc, _db = client
    res = tc.post("/api/credits/preview", json={"module": "keyword", "action": "research_run"})
    assert res.status_code == 401


def test_preview_api_authenticated(client):
    tc, db = client
    user = _user(db, "prev@test.com")
    db.commit()
    token = create_access_token(user.id)
    res = tc.post(
        "/api/credits/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={"module": "audit", "action": "technical_deep", "quota_key": "technical_audit"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["module"] == "audit"
    assert "credit_cost" in body
    assert "data_source_label" in body
