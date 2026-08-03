"""Index Control Web 2.0 check tests."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models.user import User
from app.services.index_control_web20_service import (
    check_web20_url,
    detect_platform,
    validate_web20_url,
)
from main import app

client = TestClient(app)


@pytest.fixture()
def auth_headers():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"w20-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("test-pass"),
            role="user",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user_id=user.id)
        yield {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def test_detect_platform():
    assert detect_platform("myblog.wordpress.com") == "WordPress.com"
    assert detect_platform("example.blogspot.com") == "Blogger"
    assert detect_platform("user.medium.com") == "Medium"


def test_validate_web20_url_localhost(monkeypatch):
    def fake_getaddrinfo(host, port):
        if host == "127.0.0.1":
            raise OSError("blocked")
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake_getaddrinfo)
    _, err = validate_web20_url("http://127.0.0.1/page")
    assert err is not None


@patch("app.services.index_control_web20_service.requests.get")
@patch("app.services.index_control_web20_service.parse_robots_txt")
def test_check_web20_url_live(mock_robots, mock_get, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://myblog.wordpress.com/post"
    mock_resp.text = (
        "<html><head>"
        '<link rel="canonical" href="https://myblog.wordpress.com/post">'
        '<meta name="robots" content="index,follow">'
        "</head><body><p>Hello world content here for crawl test.</p></body></html>"
    )
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    from app.services.index_control_web20_service import _PlatformCache

    item = check_web20_url("https://myblog.wordpress.com/post", cache=_PlatformCache())
    assert item["status"] == "Live"
    assert item["indexability"] == "indexable"
    assert item["checks"]["http"] == "pass"
    assert item["checks"]["noindex"] == "pass"
    assert item["checks"]["crawl"] == "pass"
    assert item["platform"] == "WordPress.com"


@patch("app.services.index_control_web20_service.requests.get")
@patch("app.services.index_control_web20_service.parse_robots_txt")
def test_check_web20_url_noindex(mock_robots, mock_get, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.blogspot.com/hidden"
    mock_resp.text = '<html><head><meta name="robots" content="noindex"></head><body>x</body></html>'
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    from app.services.index_control_web20_service import _PlatformCache

    item = check_web20_url("https://example.blogspot.com/hidden", cache=_PlatformCache())
    assert item["indexability"] == "blocked"
    assert item["checks"]["noindex"] == "fail"


@patch("app.services.index_control_web20_service.requests.get")
@patch("app.services.index_control_web20_service.parse_robots_txt")
def test_api_web20_check(mock_robots, mock_get, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://brand.tumblr.com/post/1"
    mock_resp.text = "<html><head></head><body>Public post content</body></html>"
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    r = client.post(
        "/api/index-control/check",
        headers=auth_headers,
        json={
            "url_type": "web2",
            "urls": ["https://brand.tumblr.com/post/1"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["demo"] is False
    assert data["items"][0]["url_type"] == "web20"
    assert data.get("history_check_id")
