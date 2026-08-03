"""
API route smoke tests — GET /api/audit/*, export CSV/PDF/GSheet (không đụng JWT/OAuth thật).
"""

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
from app.services.audit_store import save_technical_audit


@pytest.fixture()
def audit_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "technical_audits.json")
    Base.metadata.create_all(bind=engine)
    app = FastAPI()
    app.include_router(report_router)

    db = SessionLocal()
    try:
        user = User(
            email=f"qa-{uuid.uuid4().hex[:12]}@example.com",
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


def test_api_audit_get_legacy_shape(audit_client):
    client, user_id, token = audit_client
    legacy = {
        "domain": "legacy-api.com",
        "pages_scanned": 1,
        "issues": [{"type": "t1", "severity": "low", "message": "m"}],
        "technical_summary": {"health_score": 80},
    }
    aid = save_technical_audit(user_id=user_id, source_url="https://legacy-api.com", result=legacy)
    r = client.get(f"/api/audit/{aid}", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["audit_id"] == aid
    assert body["normalized_issues"] == []
    assert body["issues"][0]["type"] == "t1"


def test_api_audit_get_new_saas_shape(audit_client):
    client, user_id, token = audit_client
    from app.services.technical_output_normalizer import build_saas_api_extensions

    base = {
        "domain": "newsaas.com",
        "pages_scanned": 3,
        "issues": [{"type": "missing_title", "severity": "high", "message": "x", "checklist_group": "Onpage"}],
        "technical_summary": {"health_score": 70, "broken_internal_links": 0, "broken_internal_404": 0, "redirect_chains": 0, "internal_pages": 3, "total_technical_issues": 1},
        "robots": {"status": 200},
        "sitemap": {"status": 200, "urls": []},
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
    }
    result = {**base, **build_saas_api_extensions(base)}
    aid = save_technical_audit(user_id=user_id, source_url="https://newsaas.com", result=result)
    r = client.get(f"/api/audit/{aid}", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["saas_summary"] is not None
    assert isinstance(body["normalized_issues"], list)
    assert len(body["normalized_issues"]) >= 1


def test_api_audit_export_csv_pdf_gsheet(audit_client):
    client, user_id, token = audit_client
    from app.services.technical_output_normalizer import build_saas_api_extensions

    base = {
        "domain": "export.com",
        "pages_scanned": 2,
        "issues": [],
        "technical_summary": {"health_score": 88},
        "robots": {"status": 200},
        "sitemap": {"status": 200, "urls": []},
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
    }
    norm_issue = {
        "id": "missing_title_aabbccddeeff",
        "category": "onpage",
        "title": "Missing title",
        "description": "No title tag",
        "severity": "high",
        "affected_urls": ["https://export.com/"],
        "how_to_fix": "Add title",
    }
    result = {**base, **build_saas_api_extensions({**base, "issues": [{"type": "missing_title", "severity": "high", "checklist_group": "Onpage"}]})}
    result["normalized_issues"] = [norm_issue]
    aid = save_technical_audit(user_id=user_id, source_url="https://export.com", result=result)

    csv_r = client.get(f"/api/audit/{aid}/export.csv", headers=_auth(token))
    assert csv_r.status_code == 200
    assert "text/csv" in csv_r.headers.get("content-type", "")
    assert "missing_title" in csv_r.text

    pdf_r = client.get(f"/api/audit/{aid}/export.pdf", headers=_auth(token))
    assert pdf_r.status_code == 200
    assert pdf_r.headers.get("content-type", "").startswith("application/pdf")

    sheet_r = client.get(f"/api/audit/{aid}/export.gsheet", headers=_auth(token))
    assert sheet_r.status_code == 200
    assert "missing_title" in sheet_r.text


def test_api_audit_mine_recent(audit_client):
    client, user_id, token = audit_client
    save_technical_audit(
        user_id=user_id,
        source_url="https://mine.com",
        result={"domain": "mine.com", "pages_scanned": 1, "issues": [], "technical_summary": {}},
    )
    r = client.get("/api/audit/mine?limit=5", headers=_auth(token))
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert len(items) >= 1
    assert items[0]["domain"] == "mine.com"


def test_api_audit_404_without_auth_breaking_shape(audit_client):
    client, _user_id, token = audit_client
    r = client.get("/api/audit/nonexistent-id-xyz", headers=_auth(token))
    assert r.status_code == 404
