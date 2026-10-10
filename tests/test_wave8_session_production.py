"""WAVE 8 production hardening — legacy JWT block, migration, HttpOnly refresh."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.core.security import create_access_token, create_service_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.models.user_session import UserSession
from app.services.auth import user_from_token
from app.services.oauth_cookie import SEO_REFRESH_COOKIE


@pytest.fixture()
def prod_session_env(monkeypatch):
    monkeypatch.setenv("SERVER_SESSIONS_ENABLED", "1")
    monkeypatch.setenv("JWT_BLOCK_LEGACY_USER", "1")
    monkeypatch.setenv("JWT_SERVICE_TOKENS_ENABLED", "1")
    monkeypatch.setenv("REFRESH_TOKEN_HTTPONLY_ONLY", "1")
    monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "20")
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")


@pytest.fixture()
def client_ctx(prod_session_env, monkeypatch):
    import app.models.plan  # noqa: F401
    import app.models.security_audit_log  # noqa: F401
    import app.models.usage_limit  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "SessionLocal", Session)

    user = User(
        email=f"prod-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role="user",
        status="active",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    app = FastAPI()
    app.include_router(auth_router)

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield {"client": client, "db": session, "user": user}
    app.dependency_overrides.clear()
    session.close()


def test_legacy_user_jwt_blocked(client_ctx):
    ctx = client_ctx
    legacy = create_access_token(user_id=ctx["user"].id, expires_hours=720)
    resp = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401


def test_old_720h_token_after_cutoff(client_ctx):
    ctx = client_ctx
    legacy = create_access_token(user_id=ctx["user"].id, expires_hours=720)
    blocked = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert blocked.status_code == 401


def test_service_token_compatibility(client_ctx):
    ctx = client_ctx
    svc = create_service_access_token(ctx["user"].id)
    resp = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {svc}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == ctx["user"].id


def test_refresh_token_not_in_login_json(client_ctx):
    ctx = client_ctx
    r = ctx["client"].post(
        "/auth/login",
        json={"email": ctx["user"].email, "password": "TestPass123!"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "refresh_token" not in body
    assert body.get("access_token")
    assert SEO_REFRESH_COOKIE in r.cookies


def test_refresh_via_cookie_only(client_ctx):
    ctx = client_ctx
    login = ctx["client"].post(
        "/auth/login",
        json={"email": ctx["user"].email, "password": "TestPass123!"},
    )
    assert login.status_code == 200
    refreshed = ctx["client"].post("/auth/refresh")
    assert refreshed.status_code == 200
    assert "refresh_token" not in refreshed.json()
    assert refreshed.json().get("access_token")


def test_session_db_migration_schema():
    from app.migrations.ensure_user_sessions import apply_user_sessions_migration, schema_status

    result = apply_user_sessions_migration()
    st = schema_status()
    assert st["ok"] is True
    assert result["status"]["user_sessions"] is True


def test_main_does_not_boot_create_user_sessions():
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    src = main_path.read_text(encoding="utf-8")
    assert "_ensure_user_sessions_table()" not in src
