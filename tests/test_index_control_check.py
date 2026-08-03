"""Index Control — website check API + service."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models.user import User
from app.services.index_control_history_store import list_history_items, save_check_history
from app.services.index_control_service import (
    check_website_url,
    check_website_urls,
    validate_check_url,
)
from main import app

client = TestClient(app)


@pytest.fixture()
def auth_headers():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"ic-{uuid.uuid4().hex[:10]}@example.com",
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


def test_check_requires_auth():
    r = client.post(
        "/api/index-control/check",
        json={"domain": "example.com", "url_type": "website", "urls": ["https://example.com/a"]},
    )
    assert r.status_code == 401


def test_validate_blocks_localhost(monkeypatch):
    def fake_getaddrinfo(host, port):
        if host == "127.0.0.1":
            raise OSError("blocked")
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake_getaddrinfo)
    _, err = validate_check_url("http://127.0.0.1/page", domain="127.0.0.1")
    assert err is not None


def test_validate_domain_mismatch(monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    _, err = validate_check_url("https://other.com/page", domain="example.com")
    assert err is not None


@patch("app.services.index_control_service.requests.get")
@patch("app.services.index_control_service.parse_sitemap_xml")
@patch("app.services.index_control_service.parse_robots_txt")
def test_check_website_url_indexable(mock_robots, mock_sitemap, mock_get, auth_headers):
    mock_robots.return_value = {
        "status": 200,
        "body_preview": "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml",
        "sitemaps": ["https://example.com/sitemap.xml"],
        "disallow": [],
    }
    mock_sitemap.return_value = {
        "status": 200,
        "urls": ["https://example.com/page"],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/page"
    mock_resp.text = (
        "<html><head>"
        '<link rel="canonical" href="https://example.com/page">'
        '<meta name="robots" content="index,follow">'
        "</head><body>ok</body></html>"
    )
    mock_resp.headers = {}
    mock_get.return_value = mock_resp

    r = client.post(
        "/api/index-control/check",
        headers=auth_headers[0],
        json={
            "domain": "example.com",
            "url_type": "website",
            "urls": ["https://example.com/page"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["demo"] is False
    item = data["items"][0]
    assert item["indexability"] == "indexable"
    assert item["checks"]["http_status"] == "pass"
    assert item["checks"]["meta_noindex"] == "pass"
    assert item["main_issue"] == "No issue"


@patch("app.services.index_control_service.requests.get")
@patch("app.services.index_control_service.parse_robots_txt")
def test_check_website_url_meta_noindex(mock_robots, mock_get, auth_headers):
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/hidden"
    mock_resp.text = '<html><head><meta name="robots" content="noindex,follow"></head></html>'
    mock_resp.headers = {}
    mock_get.return_value = mock_resp

    from app.services.index_control_service import _DomainCache

    item = check_website_url("https://example.com/hidden", domain="example.com", cache=_DomainCache())
    assert item["indexability"] == "blocked"
    assert item["main_issue"] == "Meta noindex"
    assert item["checks"]["meta_noindex"] == "fail"


@patch("app.services.index_control_service.requests.get")
def test_check_batch_one_url_error_does_not_crash(mock_get, auth_headers):
    mock_get.side_effect = [
        Exception("network"),
    ]
    data = check_website_urls(
        domain="example.com",
        urls=["https://example.com/a"],
    )
    assert data["ok"] is True
    assert len(data["items"]) == 1
    assert data["items"][0]["indexability"] == "error"


def test_domain_required(auth_headers):
    r = client.post(
        "/api/index-control/check",
        headers=auth_headers[0],
        json={"url_type": "website", "urls": ["https://example.com/a"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "domain_required"


def test_history_isolation(auth_headers):
    headers_a, user_a = auth_headers
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user_b = User(
            email=f"icb-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user_b)
        db.commit()
        db.refresh(user_b)

        save_check_history(
            db,
            user_id=user_a,
            domain="example.com",
            url_type="website",
            items=[{
                "url": "https://example.com/a",
                "final_url": "https://example.com/a",
                "status_code": 200,
                "indexability": "indexable",
                "main_issue": "No issue",
                "severity": "low",
                "checks": {"http_status": "pass"},
                "suggestion": "OK",
            }],
        )

        listed_a = list_history_items(db, user_id=user_a, role="user")
        listed_b = list_history_items(db, user_id=user_b.id, role="user")
        assert listed_a["count"] == 1
        assert listed_b["count"] == 0
    finally:
        db.close()

    r = client.get("/api/index-control/history", headers=headers_a)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] >= 1


@patch("app.services.index_control_service.requests.get")
@patch("app.services.index_control_service.parse_sitemap_xml")
@patch("app.services.index_control_service.parse_robots_txt")
def test_check_saves_history(mock_robots, mock_sitemap, mock_get, auth_headers):
    headers, user_id = auth_headers
    mock_robots.return_value = {
        "status": 200,
        "body_preview": "User-agent: *\nAllow: /",
        "sitemaps": [],
        "disallow": [],
    }
    mock_sitemap.return_value = {"status": 0, "urls": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/page"
    mock_resp.text = "<html><head></head><body>ok</body></html>"
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    r = client.post(
        "/api/index-control/check",
        headers=headers,
        json={
            "domain": "example.com",
            "url_type": "website",
            "urls": ["https://example.com/page"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("history_check_id")

    hr = client.get("/api/index-control/history", headers=headers)
    assert hr.json()["count"] >= 1


def test_delete_history_item(auth_headers):
    headers, user_id = auth_headers
    db = SessionLocal()
    try:
        save_check_history(
            db,
            user_id=user_id,
            domain="example.com",
            url_type="website",
            items=[{
                "url": "https://example.com/del",
                "indexability": "warning",
                "main_issue": "Not found in sitemap",
                "severity": "medium",
                "checks": {},
            }],
        )
        items = list_history_items(db, user_id=user_id, role="user")
        item_id = items["items"][0]["id"]
    finally:
        db.close()

    dr = client.delete(f"/api/index-control/history/{item_id}", headers=headers)
    assert dr.status_code == 200
    assert dr.json()["ok"] is True
