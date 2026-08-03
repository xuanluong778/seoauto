"""IndexNow submit API tests."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models.user import User
from app.services.indexnow_log_store import list_indexnow_logs
from app.services.indexnow_service import (
    validate_indexnow_domain,
    validate_indexnow_key,
    validate_indexnow_urls,
)
from main import app

client = TestClient(app)


@pytest.fixture()
def auth_headers():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"in-{uuid.uuid4().hex[:10]}@example.com",
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


def test_indexnow_requires_auth():
    r = client.post(
        "/api/index-control/indexnow-submit",
        json={"domain": "example.com", "key": "abcd1234", "urls": ["https://example.com/a"]},
    )
    assert r.status_code == 401


def test_validate_indexnow_key():
    assert validate_indexnow_key("")[1]
    assert validate_indexnow_key("short")[1]
    ok, err = validate_indexnow_key("abcd1234")
    assert ok == "abcd1234" and err is None


def test_validate_indexnow_domain():
    dom, err = validate_indexnow_domain("https://www.example.com")
    assert dom == "example.com" and err is None


def test_validate_indexnow_urls_domain_mismatch(monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    valid, invalid = validate_indexnow_urls(["https://other.com/page"], domain="example.com")
    assert not valid
    assert invalid


@patch("app.services.indexnow_service.requests.post")
def test_indexnow_submit_success(mock_post, auth_headers):
    headers, user_id = auth_headers
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_post.return_value = mock_resp

    r = client.post(
        "/api/index-control/indexnow-submit",
        headers=headers,
        json={
            "domain": "example.com",
            "key": "abcd1234",
            "urls": ["https://example.com/new-post"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("submit_id")
    assert mock_post.called
    payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert payload["key"] == "abcd1234"
    assert "https://example.com/new-post" in payload["urlList"]

    db = SessionLocal()
    try:
        logs = list_indexnow_logs(db, user_id=user_id, role="user")
        assert logs["count"] >= 1
        assert logs["items"][0]["send_status"] == "sent"
    finally:
        db.close()


@patch("app.services.indexnow_service.requests.post")
def test_indexnow_submit_rejected(mock_post, auth_headers):
    headers, _uid = auth_headers
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_post.return_value = mock_resp

    r = client.post(
        "/api/index-control/indexnow-submit",
        headers=headers,
        json={
            "domain": "example.com",
            "key": "abcd1234",
            "urls": ["https://example.com/page"],
        },
    )
    data = r.json()
    assert data["ok"] is False
    assert data["http_status"] == 403


def test_indexnow_too_many_urls(auth_headers):
    headers, _uid = auth_headers
    urls = [f"https://example.com/p{i}" for i in range(101)]
    r = client.post(
        "/api/index-control/indexnow-submit",
        headers=headers,
        json={"domain": "example.com", "key": "abcd1234", "urls": urls},
    )
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "too_many_urls"
