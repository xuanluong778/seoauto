"""WAVE 8 — server-side sessions, refresh rotation, revoke."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.core.security import decode_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.models.user_session import UserSession
from app.routers.admin import api_router as admin_api_router
from app.services.admin_service import update_user_role, update_user_status
from app.services.auth import issue_login_tokens, user_from_token
from app.services.oauth_cookie import SEO_REFRESH_COOKIE
from app.services.session_auth_rollout import jwt_access_expire_minutes
from app.services.user_session_service import (
    change_user_password_and_revoke_sessions,
    create_user_session,
    refresh_user_session,
    revoke_all_user_sessions,
    revoke_session,
)


@pytest.fixture()
def session_env(monkeypatch):
    monkeypatch.setenv("SERVER_SESSIONS_ENABLED", "1")
    monkeypatch.setenv("JWT_BLOCK_LEGACY_USER", "1")
    monkeypatch.setenv("JWT_SERVICE_TOKENS_ENABLED", "1")
    monkeypatch.setenv("REFRESH_TOKEN_HTTPONLY_ONLY", "1")
    monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "20")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")


@pytest.fixture()
def db_and_client(session_env, monkeypatch):
    import app.models.organization  # noqa: F401
    import app.models.security_audit_log  # noqa: F401

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
        email=f"sess-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role="user",
        status="active",
    )
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role="admin",
        status="active",
    )
    session.add_all([user, admin])
    session.commit()
    session.refresh(user)
    session.refresh(admin)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(admin_api_router, prefix="/api/admin")

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield {"client": client, "db": session, "user": user, "admin": admin}
    app.dependency_overrides.clear()
    session.close()


def _login(client: TestClient, email: str, password: str = "TestPass123!"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


def test_jwt_short_lived_access(db_and_client):
    ctx = db_and_client
    resp = _login(ctx["client"], ctx["user"].email)
    body = resp.json()
    payload = decode_access_token(body["access_token"])
    exp = payload["exp"]
    if isinstance(exp, datetime):
        exp_dt = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
    else:
        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    minutes = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 60
    assert 14 <= minutes <= 31
    assert "refresh_token" not in body
    assert SEO_REFRESH_COOKIE in resp.cookies
    assert body.get("expires_in") == jwt_access_expire_minutes() * 60


def test_login_then_refresh(db_and_client):
    ctx = db_and_client
    first = _login(ctx["client"], ctx["user"].email)
    r = ctx["client"].post("/auth/refresh")
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["access_token"] != first.json()["access_token"]
    assert "refresh_token" not in second
    me = ctx["client"].get(
        "/auth/me",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert me.status_code == 200


def test_logout_revokes_access_token(db_and_client):
    ctx = db_and_client
    resp = _login(ctx["client"], ctx["user"].email)
    token = resp.json()["access_token"]
    assert ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert ctx["client"].post("/auth/logout").status_code == 200
    blocked = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 401


def test_refresh_token_reuse_blocked(db_and_client, monkeypatch):
    """Immediate reuse = concurrent-tab race (allowed). Stale reuse after grace = blocked."""
    from datetime import timedelta

    from app.services import user_session_service as uss

    ctx = db_and_client
    _login(ctx["client"], ctx["user"].email)
    first_refresh = ctx["client"].cookies.get(SEO_REFRESH_COOKIE)
    rotated = ctx["client"].post("/auth/refresh")
    assert rotated.status_code == 200
    # Concurrent race (same second): must NOT kill the new session
    ctx["client"].cookies.set(SEO_REFRESH_COOKIE, first_refresh)
    race = ctx["client"].post("/auth/refresh")
    assert race.status_code == 200
    # After grace window: reuse of rotated refresh must fail + revoke family
    row = (
        ctx["db"]
        .query(UserSession)
        .filter(UserSession.refresh_token_hash.isnot(None))
        .order_by(UserSession.revoked_at.desc())
        .first()
    )
    # Simulate revoked_at in the past beyond grace
    for r in ctx["db"].query(UserSession).filter(UserSession.revoked_at.isnot(None)).all():
        if str(r.revoke_reason or "") == "rotated":
            r.revoked_at = uss._utcnow() - timedelta(seconds=120)
    ctx["db"].commit()
    ctx["client"].cookies.set(SEO_REFRESH_COOKIE, first_refresh)
    reuse = ctx["client"].post("/auth/refresh")
    assert reuse.status_code == 401
    # Active session of that family should be revoked after true reuse detection
    active = (
        ctx["db"]
        .query(UserSession)
        .filter(UserSession.user_id == ctx["user"].id, UserSession.revoked_at.is_(None))
        .count()
    )
    assert active == 0


def test_password_change_revokes_old_sessions(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    user = ctx["user"]
    body = _login(ctx["client"], user.email).json()
    old_token = body["access_token"]
    change_user_password_and_revoke_sessions(
        db,
        user=user,
        new_password="NewPass123!",
    )
    blocked = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert blocked.status_code == 401
    new_login = _login(ctx["client"], user.email, password="NewPass123!")
    assert new_login.json().get("access_token")


def test_role_downgrade_revokes_sessions(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    target = User(
        email=f"role-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role="admin",
        status="active",
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    token = _login(ctx["client"], target.email).json()["access_token"]
    update_user_role(db, target_user_id=target.id, new_role="user", actor=ctx["admin"])
    blocked = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 401


def test_account_disabled_revokes_sessions(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    target = ctx["user"]
    token = _login(ctx["client"], target.email).json()["access_token"]
    update_user_status(db, target_user_id=target.id, new_status="inactive", actor=ctx["admin"])
    blocked = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code in (401, 403)


def test_stolen_token_after_revoke_returns_401(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    user = ctx["user"]
    tokens = create_user_session(db, user=user)
    db.commit()
    stolen = tokens.access_token
    revoke_session(db, session_id=tokens.session_id, reason="stolen")
    db.commit()
    with pytest.raises(Exception):
        user_from_token(db, stolen)
    resp = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {stolen}"})
    assert resp.status_code == 401


def test_revoke_all_sessions_except_current(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    user = ctx["user"]
    t1 = create_user_session(db, user=user)
    t2 = create_user_session(db, user=user)
    db.commit()
    headers = {"Authorization": f"Bearer {t2.access_token}"}
    r = ctx["client"].post("/auth/sessions/revoke-all", headers=headers)
    assert r.status_code == 200
    assert ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {t1.access_token}"}).status_code == 401
    assert ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {t2.access_token}"}).status_code == 200


def test_server_session_row_created_on_login(db_and_client):
    ctx = db_and_client
    db = ctx["db"]
    user = ctx["user"]
    before = db.query(UserSession).filter(UserSession.user_id == user.id).count()
    _login(ctx["client"], user.email)
    after = db.query(UserSession).filter(UserSession.user_id == user.id).count()
    assert after == before + 1


def test_refresh_rotation_service(db_and_client):
    from datetime import timedelta

    from app.services import user_session_service as uss

    ctx = db_and_client
    db = ctx["db"]
    user = ctx["user"]
    first = create_user_session(db, user=user)
    db.commit()
    second = refresh_user_session(db, refresh_token=first.refresh_token)
    assert second.access_token != first.access_token
    # Concurrent race within grace: returns access for successor, empty refresh
    raced = refresh_user_session(db, refresh_token=first.refresh_token)
    assert raced.access_token
    assert raced.refresh_token == ""
    # After grace: true reuse blocked
    for r in db.query(UserSession).filter(UserSession.revoked_at.isnot(None)).all():
        if str(r.revoke_reason or "") == "rotated":
            r.revoked_at = uss._utcnow() - timedelta(seconds=120)
    db.commit()
    with pytest.raises(Exception):
        refresh_user_session(db, refresh_token=first.refresh_token)


def test_auth_regression_me_after_refresh(db_and_client):
    ctx = db_and_client
    _login(ctx["client"], ctx["user"].email)
    refreshed = ctx["client"].post("/auth/refresh")
    assert refreshed.status_code == 200
    token = refreshed.json()["access_token"]
    me = ctx["client"].get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == ctx["user"].id
