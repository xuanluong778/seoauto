"""Index Control Social / Entity check tests."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models.user import User
from app.services.index_control_social_service import (
    ENTITY_DISCLAIMER,
    check_social_url,
    detect_social_platform,
)
from main import app

client = TestClient(app)


@pytest.fixture()
def auth_headers():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"soc-{uuid.uuid4().hex[:10]}@example.com",
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


def test_detect_social_platform():
    assert detect_social_platform("www.facebook.com") == "Facebook"
    assert detect_social_platform("www.youtube.com") == "YouTube"
    assert detect_social_platform("www.linkedin.com") == "LinkedIn"


@patch("app.services.index_control_social_service.requests.get")
@patch("app.services.index_control_social_service.parse_robots_txt")
def test_check_social_url_good(mock_robots, mock_get, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://www.facebook.com/examplebrand"
    mock_resp.text = (
        "<html><head>"
        '<meta property="og:title" content="Example Brand Page">'
        '<meta property="og:description" content="Official brand page">'
        "</head><body><h1>Example Brand</h1><p>Public content about the brand entity.</p></body></html>"
    )
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    from app.services.index_control_social_service import _SocialCache

    item = check_social_url("https://www.facebook.com/examplebrand", cache=_SocialCache())
    assert item["entity_status"] == "good"
    assert item["entity_status_label"] == "Tốt"
    assert item["checks"]["alive"] == "pass"
    assert item["checks"]["login_wall"] == "pass"
    assert ENTITY_DISCLAIMER in item["suggestion"]


@patch("app.services.index_control_social_service.requests.get")
@patch("app.services.index_control_social_service.parse_robots_txt")
def test_check_social_url_login_wall(mock_robots, mock_get, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://www.linkedin.com/company/private-co"
    mock_resp.text = "<html><head><title>Sign In | LinkedIn</title></head><body>Join LinkedIn</body></html>"
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    from app.services.index_control_social_service import _SocialCache

    item = check_social_url("https://www.linkedin.com/company/private-co", cache=_SocialCache())
    assert item["entity_status"] == "warning"
    assert item["checks"]["login_wall"] == "fail"
    assert item["login_wall"] is True


@patch("app.services.index_control_social_service.requests.get")
@patch("app.services.index_control_social_service.parse_robots_txt")
def test_api_social_check(mock_robots, mock_get, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_robots.return_value = {"status": 404, "body_preview": "", "sitemaps": []}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://www.pinterest.com/examplebrand/"
    mock_resp.text = (
        '<html><head><meta property="og:title" content="Brand"></head>'
        "<body>Public pinterest profile content here.</body></html>"
    )
    mock_resp.headers = {}
    mock_resp.history = []
    mock_get.return_value = mock_resp

    r = client.post(
        "/api/index-control/check",
        headers=auth_headers,
        json={
            "url_type": "social",
            "urls": ["https://www.pinterest.com/examplebrand/"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["demo"] is False
    assert data["items"][0]["url_type"] == "social_entity"
    assert data.get("disclaimer")
    assert data.get("history_check_id")
