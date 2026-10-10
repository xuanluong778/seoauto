"""Index Control overview API tests."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models.user import User
from app.services.index_control_history_store import save_check_history
from app.services.indexnow_log_store import save_indexnow_logs
from main import app

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture()
def auth_headers():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"ov-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user_id=user.id)
        yield {"Authorization": f"Bearer {token}"}, user.id
    finally:
        db.close()


def test_overview_requires_auth():
    r = client.get("/api/index-control/overview")
    assert r.status_code == 401


def test_overview_stats_and_urgent(auth_headers):
    headers, user_id = auth_headers
    db = SessionLocal()
    try:
        save_check_history(
            db,
            user_id=user_id,
            domain="example.com",
            url_type="website",
            items=[
                {
                    "url": "https://example.com/ok",
                    "indexability": "indexable",
                    "main_issue": "No issue",
                    "severity": "low",
                    "checks": {},
                },
                {
                    "url": "https://example.com/bad",
                    "indexability": "blocked",
                    "main_issue": "Meta noindex",
                    "severity": "critical",
                    "checks": {},
                },
                {
                    "url": "https://example.com/warn",
                    "indexability": "warning",
                    "main_issue": "Canonical",
                    "severity": "high",
                    "checks": {},
                },
            ],
        )
        save_indexnow_logs(
            db,
            user_id=user_id,
            domain="example.com",
            api_http_status=200,
            submit_status="success",
            batch_note="OK",
            items=[{"url": "https://example.com/sent", "send_status": "sent", "http_status": 200, "note": "OK"}],
        )
    finally:
        db.close()

    r = client.get("/api/index-control/overview", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    stats = data["stats"]
    assert stats["total_checked"] == 3
    assert stats["indexable"] == 1
    assert stats["warning"] == 1
    assert stats["blocked"] == 1
    assert stats["indexnow_sent"] == 1
    assert len(data["urgent_items"]) == 2
    assert data["urgent_items"][0]["severity"] == "critical"


def test_overview_isolation(auth_headers):
    headers_a, user_a = auth_headers
    db = SessionLocal()
    try:
        user_b = User(
            email=f"ovb-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user_b)
        db.commit()
        db.refresh(user_b)
        save_check_history(
            db,
            user_id=user_b.id,
            domain="other.com",
            url_type="website",
            items=[{
                "url": "https://other.com/x",
                "indexability": "blocked",
                "main_issue": "HTTP error",
                "severity": "high",
                "checks": {},
            }],
        )
    finally:
        db.close()

    r = client.get("/api/index-control/overview", headers=headers_a)
    data = r.json()
    assert data["stats"]["total_checked"] == 0
