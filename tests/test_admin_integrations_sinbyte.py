"""Admin Sinbyte integration API tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.platform_integration import PlatformIntegration  # noqa: F401
from app.models.user import User
from app.routers.admin_integrations import router as admin_integrations_router
from app.services.safe_errors import global_exception_handler

PLATFORM_ADMIN_EMAIL = "xuanluong778@gmail.com"


@pytest.fixture()
def client():
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

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
    app.include_router(admin_integrations_router, prefix="/api/admin")
    app.add_exception_handler(HTTPException, global_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    yield tc, db
    app.dependency_overrides.clear()
    db.close()


def _admin(db) -> User:
    u = User(
        email=PLATFORM_ADMIN_EMAIL,
        password_hash=hash_password("x"),
        has_password=True,
        role="admin",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: User) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user.id)}


def test_sinbyte_status_requires_auth(client):
    tc, _ = client
    assert tc.get("/api/admin/integrations/sinbyte/status").status_code == 401


def test_sinbyte_save_mask_and_no_plaintext(client):
    tc, db = client
    headers = _auth(_admin(db))

    r = tc.post(
        "/api/admin/integrations/sinbyte/save",
        headers=headers,
        json={"api_key": "abcd1234secretkey"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["api_key_masked"].startswith("abcd")
    assert "secretkey" not in data["api_key_masked"]
    assert "abcd1234secretkey" not in r.text

    status = tc.get("/api/admin/integrations/sinbyte/status", headers=headers)
    assert status.status_code == 200
    st = status.json()
    assert st["configured"] is True
    assert st["source"] == "database"
    assert "secretkey" not in st["api_key_masked"]


@patch("app.services.sinbyte_service.requests.get")
def test_sinbyte_test_connection(mock_get, client):
    tc, db = client
    headers = _auth(_admin(db))
    tc.post(
        "/api/admin/integrations/sinbyte/save",
        headers=headers,
        json={"api_key": "abcd1234secretkey"},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_get.return_value = mock_resp

    r = tc.post("/api/admin/integrations/sinbyte/test", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["connected"] is True
    assert "abcd1234secretkey" not in r.text


def test_sinbyte_delete(client, monkeypatch):
    monkeypatch.delenv("SINBYTE_API_KEY", raising=False)
    tc, db = client
    headers = _auth(_admin(db))
    tc.post(
        "/api/admin/integrations/sinbyte/save",
        headers=headers,
        json={"api_key": "abcd1234secretkey"},
    )

    r = tc.delete("/api/admin/integrations/sinbyte", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    st = tc.get("/api/admin/integrations/sinbyte/status", headers=headers).json()
    assert st["configured"] is False
