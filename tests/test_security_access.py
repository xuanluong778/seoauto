"""Production security: admin isolation, docs lockdown, IDOR."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.core.runtime import is_production
from app.core.security import hash_password
from app.services.auth_tokens import create_auth_token_for_user
from app.db import Base, SessionLocal, engine
from app.middleware.security import SecurityMiddleware
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.user import User
from app.routers.admin import api_router as admin_api_router
from app.core.secrets_crypto import encrypt_secret
from app.services.wp_site_connector import get_site

Base.metadata.create_all(bind=engine)


def _create_user(db: Session, email: str, *, role: str = "user") -> User:
    local, _, domain = email.strip().lower().partition("@")
    unique = f"{local}+{uuid.uuid4().hex[:8]}@{domain or 'example.com'}"
    u = User(
        email=unique,
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role=role,
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def api_client():
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(admin_api_router, prefix="/api/admin")
    with TestClient(app) as c:
        yield c


def test_regular_user_cannot_list_admin_users(api_client: TestClient):
    db = SessionLocal()
    try:
        user = _create_user(db, "sec_regular@example.com", role="user")
        token = create_auth_token_for_user(user.id)
    finally:
        db.close()
    r = api_client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_user_cannot_read_other_users_wp_site(monkeypatch, tmp_path):
    import json

    sites_file = tmp_path / "sites.json"
    monkeypatch.setattr("app.services.wp_site_connector.SITES_FILE", sites_file)
    site_id = "site-owner-only"
    sites_file.write_text(
        json.dumps(
            [
                {
                    "id": site_id,
                    "user_id": 101,
                    "url": "https://example.com",
                    "username": "editor",
                    "app_password": encrypt_secret("abcd-efgh"),
                }
            ]
        ),
        encoding="utf-8",
    )
    assert get_site(site_id, 101) is not None
    assert get_site(site_id, 202) is None


def test_docs_blocked_when_production_flag(monkeypatch):
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "1")
    monkeypatch.delenv("APP_ENV", raising=False)
    assert is_production() is True

    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            r = client.get(path)
            assert r.status_code == 404, path
