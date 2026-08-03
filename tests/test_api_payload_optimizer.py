"""Tests for API payload slimming / pagination helpers."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.user import User
from app.routers.report import router as report_router
from app.services.api_payload_optimizer import (
    find_audit_issue,
    paginate_list,
    shape_audit_response,
    slim_issue_urls,
)
from app.services.audit_store import save_technical_audit
from app.services.technical_output_normalizer import build_saas_api_extensions


def test_paginate_list_basic():
    items, total = paginate_list(list(range(120)), page=2, page_size=50)
    assert total == 120
    assert items[0] == 50
    assert len(items) == 50


def test_slim_issue_urls_truncates():
    issue = {"issue_id": "x", "affected_urls": [f"https://e.com/{i}" for i in range(10)]}
    slim = slim_issue_urls(issue, max_urls=3)
    assert slim["affected_urls_total"] == 10
    assert len(slim["affected_urls"]) == 3
    assert slim["_urls_truncated"] is True


def test_shape_audit_lite_strips_heavy_arrays():
    run = {
        "domain": "ex.com",
        "issues": [{"type": "t1", "url": "https://ex.com/a"}],
        "normalized_issues": [{"id": "t1", "affected_urls": ["https://ex.com/a"] * 8}],
        "gsc_enriched_pages": [{"url": "u"}],
        "technical_dashboard_v2": {
            "schema_version": 2,
            "issues": [{"issue_id": "t1", "affected_urls": ["https://ex.com/a"] * 8}],
        },
    }
    out = shape_audit_response(run, lite=True)
    assert out["gsc_enriched_pages"] == []
    assert out["issues"] == []
    assert out["_payload_mode"] == "lite"
    assert out["technical_dashboard_v2"]["issues"][0]["_urls_truncated"] is True


def test_shape_audit_issues_pagination():
    run = {
        "normalized_issues": [{"id": f"i{n}"} for n in range(75)],
    }
    out = shape_audit_response(run, issues_page=2, issues_page_size=30)
    assert len(out["normalized_issues"]) == 30
    assert out["issues_pagination"]["total"] == 75
    assert out["issues_pagination"]["has_more"] is True


def test_find_audit_issue_by_id():
    run = {"normalized_issues": [{"id": "abc", "title": "T"}]}
    assert find_audit_issue(run, "abc")["title"] == "T"


@pytest.fixture()
def audit_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "technical_audits.json")
    Base.metadata.create_all(bind=engine)
    app = FastAPI()
    app.include_router(report_router)

    db = SessionLocal()
    try:
        user = User(
            email=f"opt-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user_id=user.id)
        yield TestClient(app), user.id, token
    finally:
        db.close()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_api_audit_lite_backward_compat_full_default(audit_client):
    client, user_id, token = audit_client
    base = {
        "domain": "compat.com",
        "pages_scanned": 2,
        "issues": [{"type": "missing_title", "severity": "high", "message": "x"}],
        "technical_summary": {"health_score": 70},
        "gsc_enriched_pages": [{"url": "https://compat.com/"}],
    }
    ext = build_saas_api_extensions(base)
    result = {**base, **ext}
    aid = save_technical_audit(user_id=user_id, source_url="https://compat.com", result=result)

    full = client.get(f"/api/audit/{aid}", headers=_auth(token))
    assert full.status_code == 200
    body = full.json()
    assert isinstance(body.get("normalized_issues"), list)
    assert len(body.get("gsc_enriched_pages") or []) >= 1

    lite = client.get(f"/api/audit/{aid}?lite=1", headers=_auth(token))
    assert lite.status_code == 200
    lite_body = lite.json()
    assert lite_body.get("_payload_mode") == "lite"
    assert lite_body.get("gsc_enriched_pages") == []


def test_api_audit_issues_and_detail(audit_client):
    client, user_id, token = audit_client
    norm = {
        "id": "robots_block",
        "issue_id": "robots_block",
        "title": "Robots block",
        "severity": "critical",
        "affected_urls": ["https://detail.com/1", "https://detail.com/2"],
    }
    aid = save_technical_audit(
        user_id=user_id,
        source_url="https://detail.com",
        result={
            "domain": "detail.com",
            "pages_scanned": 1,
            "issues": [],
            "normalized_issues": [norm],
            "technical_summary": {},
        },
    )
    page = client.get(f"/api/audit/{aid}/issues?page=1&page_size=10", headers=_auth(token))
    assert page.status_code == 200
    pdata = page.json()
    assert pdata["total"] == 1
    assert pdata["items"][0]["issue_id"] == "robots_block"

    detail = client.get(
        f"/api/audit/{aid}/issue-detail?issue_id=robots_block",
        headers=_auth(token),
    )
    assert detail.status_code == 200
    assert len(detail.json()["issue"]["affected_urls"]) == 2
