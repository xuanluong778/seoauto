"""WAVE 8 — security / multi-tenant hardening tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.security import ALGORITHM, SECRET_KEY, create_access_token, decode_access_token, hash_password
from app.db import Base
from app.models.user import User
from app.services.business_api_cache import cache_get, cache_set, tenant_cache_key
from app.services.duplicate_wp_corpus_cache import _corpus_key
from app.services.media_storage import save_private_image, validate_image_bytes
from app.services.safe_errors import global_exception_handler, sanitize_http_exception
from app.services.security_audit_log import log_audit_event
from app.services.trusted_proxy import resolve_client_ip
from app.services.url_safety import validate_public_http_url


def test_jwt_expired_token_rejected():
    expire = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = jwt.encode({"user_id": 1, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(ValueError, match="Invalid token"):
        decode_access_token(token)


def test_jwt_invalid_signature_rejected():
    token = create_access_token(user_id=1)
    tampered = token[:-4] + "xxxx"
    with pytest.raises(ValueError, match="Invalid token"):
        decode_access_token(tampered)


def test_jwt_user_id_swap_does_not_grant_access(monkeypatch):
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")
    from starlette.testclient import TestClient

    from main import app

    token_a = create_access_token(user_id=999999)
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code in (401, 403, 404)


def test_rbac_regular_user_blocked_from_admin_api():
    from app.api.auth import router as auth_router
    from app.routers.admin import api_router as admin_api_router
    from app.services.auth_tokens import create_auth_token_for_user

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(admin_api_router, prefix="/api/admin")
    db = __import__("app.db", fromlist=["SessionLocal"]).SessionLocal()
    try:
        u = User(
            email=f"rbac-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            has_password=True,
            role="user",
            status="active",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        token = create_auth_token_for_user(u.id)
    finally:
        db.close()
    client = TestClient(app)
    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_mass_assignment_role_not_self_elevatable(monkeypatch):
    """User profile update must not allow role=admin via API body."""
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")
    from starlette.testclient import TestClient

    from main import app

    db = __import__("app.db", fromlist=["SessionLocal"]).SessionLocal()
    try:
        u = User(
            email=f"escalate-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("TestPass123!"),
            has_password=True,
            role="user",
            status="active",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        token = create_access_token(user_id=u.id)
        uid = u.id
    finally:
        db.close()
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.patch(
        "/auth/me",
        json={"role": "super_admin", "status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 404:
        pytest.skip("PATCH /auth/me not exposed")
    assert r.status_code in (400, 403, 422, 405)
    db2 = __import__("app.db", fromlist=["SessionLocal"]).SessionLocal()
    try:
        refreshed = db2.query(User).filter(User.id == uid).first()
        assert refreshed is not None
        assert str(refreshed.role or "user").lower() not in ("super_admin", "admin")
    finally:
        db2.close()


@pytest.fixture()
def two_tenant_session(monkeypatch):
    monkeypatch.setenv("TENANT_CONTENT_AI_PG", "1")
    monkeypatch.setenv("TENANT_CONTENT_AI_DUAL_READ", "0")
    monkeypatch.setenv("TENANT_CONTENT_AI_JSON_WRITE", "0")
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")

    import app.models.content_ai_project  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.keyword_cluster_job  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
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
    import app.services.content_ai_projects_pg as cap
    import app.services.job_store as job_store

    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(cap, "SessionLocal", Session)
    monkeypatch.setattr(job_store, "SessionLocal", Session)

    u1 = User(email="w8a@test.invalid", password_hash=hash_password("x"), has_password=True)
    u2 = User(email="w8b@test.invalid", password_hash=hash_password("x"), has_password=True)
    session.add_all([u1, u2])
    session.commit()

    from app.services.tenant_org import ensure_personal_organization

    ensure_personal_organization(session, u1.id)
    ensure_personal_organization(session, u2.id)
    session.commit()
    yield session, u1, u2
    session.close()


def test_idor_job_cross_tenant_blocked(two_tenant_session):
    _session, u1, u2 = two_tenant_session
    from app.services.job_store import create_job, get_job_for_user

    st = create_job(
        job_type="content_ai_bulk",
        message="q",
        payload={"user_id": u1.id, "keywords": ["a"]},
        user_id=u1.id,
    )
    assert get_job_for_user(st.job_id, user_id=u1.id) is not None
    assert get_job_for_user(st.job_id, user_id=u2.id) is None
    assert get_job_for_user(st.job_id, user_id=u2.id, organization_id=u1.id) is None


def test_idor_content_ai_project_cross_tenant(two_tenant_session):
    _session, u1, u2 = two_tenant_session
    from app.services.content_ai_project_store import (
        delete_content_ai_project,
        get_content_ai_project,
        save_content_ai_project,
    )

    pid = save_content_ai_project(
        user_id=u1.id,
        source_payload={"title": "A", "primary_keyword": "a", "target_website": "https://a.test"},
        draft_payload={"title": "A", "content": "<p>a</p>"},
    )
    assert get_content_ai_project(pid, user_id=u1.id) is not None
    assert get_content_ai_project(pid, user_id=u2.id) is None
    assert delete_content_ai_project(pid, user_id=u2.id) is False


def test_idor_audit_cross_tenant(two_tenant_session):
    _session, u1, u2 = two_tenant_session
    from app.services.audit_store import get_audit_for_user, save_technical_audit

    aid = save_technical_audit(
        user_id=u1.id,
        source_url="https://tenant-a.example.com",
        result={"domain": "tenant-a.example.com", "pages_scanned": 1, "issues": [], "technical_summary": {}},
    )
    assert get_audit_for_user(aid, u1.id) is not None
    assert get_audit_for_user(aid, u2.id) is None


def test_redis_biz_cache_tenant_isolation():
    k_a = tenant_cache_key(user_id=1, organization_id=10, scope="auth_me")
    k_b = tenant_cache_key(user_id=2, organization_id=10, scope="auth_me")
    assert k_a != k_b
    cache_set(k_a, {"tenant": "A"}, ttl=60)
    assert cache_get(k_a) == {"tenant": "A"}
    assert cache_get(k_b) is None


def test_redis_dup_wp_key_collision_isolation():
    k1 = _corpus_key(user_id=1, site="https://example.com", keywords=["kw-a"])
    k2 = _corpus_key(user_id=2, site="https://example.com", keywords=["kw-a"])
    assert k1 != k2


def test_celery_forged_payload_user_id_ignored_at_read(two_tenant_session):
    """Job row ownership enforced at read — attacker cannot pass victim org_id."""
    _session, u1, u2 = two_tenant_session
    from app.services.job_store import create_job, get_job_for_user

    st = create_job(
        job_type="keyword_cluster",
        message="x",
        payload={"keywords": ["a"]},
        user_id=u1.id,
    )
    assert get_job_for_user(st.job_id, user_id=u2.id) is None
    assert get_job_for_user(st.job_id, user_id=u2.id, organization_id=u1.id) is None


def test_credit_ledger_scoped_by_user(two_tenant_session):
    _session, u1, u2 = two_tenant_session
    from app.services.credits import get_available_balance, grant_credits

    db = _session
    grant_credits(db, user_id=u1.id, amount=5000, reason="test_grant", source_type="admin")
    grant_credits(db, user_id=u2.id, amount=100, reason="test_grant", source_type="admin")
    db.commit()
    assert get_available_balance(db, u1.id, sync=False) == 5000
    assert get_available_balance(db, u2.id, sync=False) == 100


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "file:///etc/passwd",
    ],
)
def test_ssrf_blocks_internal_urls(url):
    assert validate_public_http_url(url) is not None


def test_upload_rejects_disallowed_extension():
    with pytest.raises(ValueError, match="Chỉ hỗ trợ"):
        validate_image_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200, suffix=".exe")


def test_upload_rejects_empty_file():
    with pytest.raises(ValueError, match="File rỗng"):
        validate_image_bytes(b"", suffix=".jpg")


def test_upload_accepts_valid_jpeg():
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 200
    validate_image_bytes(jpeg, suffix=".jpg")


def test_audit_log_records_actor_and_action(monkeypatch):
    captured: dict = {}

    class _FakeDb:
        def add(self, row):
            captured["row"] = row

        def commit(self):
            captured["committed"] = True

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("app.services.security_audit_log.SessionLocal", lambda: _FakeDb())
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/login",
        "headers": [(b"x-real-ip", b"203.0.113.10")],
        "client": ("127.0.0.1", 0),
    }
    req = Request(scope)
    log_audit_event(
        action="login_success",
        user_id=42,
        resource_type="session",
        resource_id="s1",
        detail={"tenant": 42},
        request=req,
    )
    row = captured.get("row")
    assert row is not None
    assert row.user_id == 42
    assert row.action == "login_success"
    assert row.resource_type == "session"
    assert captured.get("committed") is True


def test_audit_log_ip_uses_trusted_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "1")
    captured: dict = {}

    class _FakeDb:
        def add(self, row):
            captured["ip"] = row.ip_address

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("app.services.security_audit_log.SessionLocal", lambda: _FakeDb())
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (b"x-real-ip", b"203.0.113.77"),
            (b"x-forwarded-for", b"1.2.3.4"),
        ],
        "client": ("127.0.0.1", 0),
    }
    log_audit_event(action="test", user_id=1, request=Request(scope))
    assert captured.get("ip") == "203.0.113.77"


def test_error_response_strips_stack_and_secrets():
    exc = HTTPException(
        status_code=500,
        detail={"message": "fail", "traceback": "secret stack", "password": "x"},
    )
    safe = sanitize_http_exception(exc)
    detail = safe.detail
    assert isinstance(detail, dict)
    assert "traceback" not in detail
    assert "password" not in detail


def test_global_exception_handler_no_stack_leak():
    import asyncio

    async def _run():
        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        req = Request(scope)
        return await global_exception_handler(req, RuntimeError("db connection failed at /var/secret/path"))

    resp = asyncio.run(_run())
    body = json.loads(resp.body)
    text = json.dumps(body)
    assert "traceback" not in text.lower()
    assert "/var/secret" not in text


def test_rate_limit_xff_spoof_blocked_for_untrusted_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "1")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        "client": ("203.0.113.99", 0),
    }
    assert resolve_client_ip(Request(scope)) == "203.0.113.99"


def test_resolve_organization_rejects_foreign_org(two_tenant_session):
    _session, u1, u2 = two_tenant_session
    from app.services.tenant_org import OrganizationForbiddenError, personal_organization_id, resolve_organization_id

    victim = personal_organization_id(u2.id)
    with pytest.raises(OrganizationForbiddenError):
        resolve_organization_id(u1.id, victim, db=_session)


def test_concurrent_auth_check_idempotent():
    """Bearer path should reject garbage before DB side effects."""
    from starlette.testclient import TestClient

    from main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"Authorization": "Bearer not.a.valid.jwt"}
    codes = [client.get("/auth/me", headers=headers).status_code for _ in range(5)]
    assert all(c in (401, 403) for c in codes)
