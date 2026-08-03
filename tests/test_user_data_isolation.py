"""Cross-user data isolation — P0 security tests + regression suite."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.keyword_cluster_project import KeywordClusterProject
from app.models.user import User
from app.routers.admin import api_router as admin_api_router
from app.routers.keywords import router as keywords_router
from app.routers.report import router as report_router
from app.routers.settings_api import router as settings_api_router
from app.services.audit_store import save_technical_audit
from app.services.api_keys_store import create_key, get_key
from app.services.content_ai_project_store import (
    get_content_ai_project,
    list_content_ai_projects,
    save_content_ai_project,
)
import app.services.content_ai_project_store as content_ai_project_store
from app.services.json_atomic import read_json_list
from app.services.publishing_sites_store import create_site, get_site, list_sites


@pytest.fixture()
def two_users_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user_a = User(
            email=f"user-a-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pass-a"),
            role="user",
            status="active",
        )
        user_b = User(
            email=f"user-b-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pass-b"),
            role="user",
            status="active",
        )
        db.add(user_a)
        db.add(user_b)
        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)
        yield {
            "db": db,
            "user_a": user_a,
            "user_b": user_b,
            "token_a": create_access_token(user_id=user_a.id),
            "token_b": create_access_token(user_id=user_b.id),
        }
    finally:
        db.close()


@pytest.fixture()
def isolation_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_users_db):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "technical_audits.json")
    user_a = two_users_db["user_a"]
    user_b = two_users_db["user_b"]

    aid = save_technical_audit(
        user_id=user_a.id,
        source_url="https://user-a-secret.example.com",
        result={
            "domain": "user-a-secret.example.com",
            "pages_scanned": 5,
            "issues": [{"type": "missing_title", "severity": "high", "message": "secret"}],
            "technical_summary": {"health_score": 42},
        },
    )

    app = FastAPI()
    app.include_router(report_router)
    client = TestClient(app)
    yield {
        "client": client,
        "user_a_id": user_a.id,
        "user_b_id": user_b.id,
        "token_a": two_users_db["token_a"],
        "token_b": two_users_db["token_b"],
        "audit_id": aid,
        "secret_domain": "user-a-secret.example.com",
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_b_cannot_read_user_a_audit_api(isolation_clients):
    ctx = isolation_clients
    r = ctx["client"].get(f"/api/audit/{ctx['audit_id']}", headers=_auth(ctx["token_b"]))
    assert r.status_code == 404


def test_user_b_mine_list_empty(isolation_clients):
    ctx = isolation_clients
    r = ctx["client"].get("/api/audit/mine?limit=8", headers=_auth(ctx["token_b"]))
    assert r.status_code == 200
    assert r.json().get("items") == []


def test_user_a_sees_own_audit(isolation_clients):
    ctx = isolation_clients
    r = ctx["client"].get(f"/api/audit/{ctx['audit_id']}", headers=_auth(ctx["token_a"]))
    assert r.status_code == 200
    assert r.json().get("domain") == ctx["secret_domain"]


def test_report_page_never_ssr_user_audit(monkeypatch):
    from unittest.mock import MagicMock

    from app.routers.report import report_page

    captured: dict = {}

    def fake_template_response(request, name, context):
        captured.update(context)
        from starlette.responses import HTMLResponse

        return HTMLResponse("ok", headers={"Cache-Control": "no-store"})

    monkeypatch.setattr("app.routers.report.templates.TemplateResponse", fake_template_response)

    req = MagicMock()
    resp = report_page(request=req, group=None, status=None, audit_id="foreign-audit-id")
    assert captured.get("latest_audit") is None
    assert captured.get("report_from_audit") is False
    assert captured.get("dashboard", {}).get("logged_in") is False
    assert "no-store" in (resp.headers.get("cache-control") or "").lower()


def test_orphan_audit_not_visible_to_any_user(isolation_clients, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "orphan.json")
    from app.services.audit_store import get_latest_audit, save_technical_audit

    orphan_id = save_technical_audit(
        user_id=isolation_clients["user_a_id"],
        source_url="https://orphan.example.com",
        result={"domain": "orphan.example.com", "pages_scanned": 1, "issues": [], "technical_summary": {}},
    )
    # Simulate legacy row without user_id
    import json
    from app.services.audit_store import AUDIT_FILE

    runs = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
    for row in runs:
        if str(row.get("id")) == orphan_id:
            row.pop("user_id", None)
    AUDIT_FILE.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")

    assert get_latest_audit(isolation_clients["user_a_id"]) is None
    ctx = isolation_clients
    r = ctx["client"].get(f"/api/audit/{orphan_id}", headers=_auth(ctx["token_a"]))
    assert r.status_code == 404


# --- Content AI projects (JSON store) ---


def test_content_ai_user_b_cannot_read_user_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_users_db):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.services.content_ai_project_store.PROJECT_FILE", tmp_path / "content_ai_projects.json")
    user_a = two_users_db["user_a"]
    user_b = two_users_db["user_b"]
    pid = save_content_ai_project(
        user_id=user_a.id,
        source_payload={
            "target_website": "https://a-secret.test",
            "primary_keyword": "secret kw",
            "title": "Secret Title",
        },
        draft_payload={"title": "Secret Title", "content": "<p>secret body</p>"},
    )
    assert get_content_ai_project(pid, user_id=user_a.id) is not None
    assert get_content_ai_project(pid, user_id=user_b.id) is None
    assert list_content_ai_projects(user_id=user_b.id) == []


def test_content_ai_retention_does_not_evict_other_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_users_db):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.services.content_ai_project_store.PROJECT_FILE", tmp_path / "content_ai_projects.json")
    user_a = two_users_db["user_a"].id
    user_b = two_users_db["user_b"].id
    pid_b = save_content_ai_project(
        user_id=user_b,
        source_payload={"primary_keyword": "kw-b-only", "title": "B-only"},
        draft_payload={"title": "B-only", "content": "<p>b</p>"},
    )
    for i in range(125):
        save_content_ai_project(
            user_id=user_a,
            source_payload={"primary_keyword": f"kw-a-{i}", "title": f"A{i}"},
            draft_payload={"title": f"A{i}", "content": f"<p>{i}</p>"},
        )
    rows = read_json_list(content_ai_project_store.PROJECT_FILE)
    b_rows = [r for r in rows if int(r.get("user_id") or 0) == user_b]
    assert len(b_rows) == 1
    assert get_content_ai_project(pid_b, user_id=user_b) is not None


# --- Keyword cluster history (SQL) ---


def test_user_b_cannot_read_user_a_cluster_history(two_users_db):
    db = two_users_db["db"]
    user_a = two_users_db["user_a"]
    row = KeywordClusterProject(
        user_id=user_a.id,
        keywords_label="secret cluster",
        keywords_json='["secret kw"]',
        language="vi",
        country="vn",
        device="desktop",
        cluster_strictness="normal",
        fetch_serp=0,
        brand_url="",
        result_json='{"clusters":[]}',
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    app = FastAPI()
    app.include_router(keywords_router)
    client = TestClient(app)
    r = client.get(f"/keywords/cluster/history/{row.id}", headers=_auth(two_users_db["token_b"]))
    assert r.status_code == 404


# --- Settings API keys (SQL) ---


def test_user_b_cannot_read_user_a_api_key(two_users_db):
    user_a = two_users_db["user_a"]
    created = create_key(
        {"name": "A-secret", "provider": "openai", "api_key": "sk-user-a-secret-key"},
        user_id=user_a.id,
    )
    key_id = created["id"]
    assert get_key(key_id, user_id=user_a.id, reveal_key=True) is not None
    assert get_key(key_id, user_id=two_users_db["user_b"].id, reveal_key=True) is None

    app = FastAPI()
    app.include_router(settings_api_router)
    client = TestClient(app)
    r = client.get(f"/api/settings/api-keys/{key_id}", headers=_auth(two_users_db["token_b"]))
    assert r.status_code == 404


# --- Publishing sites (JSON) ---


def test_user_b_cannot_read_user_a_publishing_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_users_db):
    monkeypatch.chdir(tmp_path)
    user_a = two_users_db["user_a"]
    user_b = two_users_db["user_b"]
    site = create_site(
        {
            "platform": "wordpress",
            "name": "Secret WP",
            "url": "https://secret-wp.test",
            "username": "wpuser",
            "app_password": "app-pass",
        },
        user_id=user_a.id,
    )
    sid = site["id"]
    assert get_site(sid, user_id=user_a.id) is not None
    assert get_site(sid, user_id=user_b.id) is None
    assert list_sites(user_id=user_b.id) == []


# --- Admin API ---


def test_regular_user_cannot_call_admin_api_check(two_users_db):
    app = FastAPI()
    app.include_router(admin_api_router, prefix="/admin/api")
    app.include_router(admin_api_router, prefix="/api/admin")
    client = TestClient(app)
    r = client.get("/admin/api/check", headers=_auth(two_users_db["token_a"]))
    assert r.status_code == 403
    r_legacy = client.get("/api/admin/check", headers=_auth(two_users_db["token_b"]))
    assert r_legacy.status_code == 403
