"""WordPress REST probe — host fallback and browser User-Agent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from app.routers.pages import _build_wp_session
from app.services.wp_connect import wp_get_json, wp_http_status_note


def test_build_wp_session_uses_browser_user_agent():
    session = _build_wp_session("quantri", "abcd efgh", strip_spaces=True)
    ua = session.headers.get("User-Agent") or ""
    assert "Mozilla" in ua
    assert "python-requests" not in ua.lower()
    assert session.headers.get("Authorization", "").startswith("Basic ")
    assert session.auth == ("quantri", "abcdefgh")


def test_basic_auth_header_keeps_all_password_chars():
    import base64

    pwd = "xxxx yyyy zzzz aaaa"
    session = _build_wp_session("quantri", pwd, strip_spaces=True)
    expected = base64.b64encode(b"quantri:xxxxyyyyzzzzaaaa").decode("ascii")
    assert session.headers.get("Authorization") == f"Basic {expected}"
    assert session.auth == ("quantri", "xxxxyyyyzzzzaaaa")


def test_wp_http_status_note_has_no_secret():
    resp = MagicMock()
    resp.status_code = 401
    resp.headers = {"Content-Type": "application/json"}
    resp.json.return_value = {"code": "rest_not_logged_in", "message": "not logged in"}
    resp.text = "password=super-secret"
    note = wp_http_status_note(resp)
    assert "401" in note
    assert "rest_not_logged_in" in note
    assert "super-secret" not in note
    assert "password=" not in note


def test_wp_get_json_retries_www_after_401():
    apex = MagicMock()
    apex.status_code = 401
    apex.headers = {"Content-Type": "application/json"}
    apex.json.return_value = {"code": "rest_not_logged_in"}
    apex.text = "{}"

    www = MagicMock()
    www.status_code = 200
    www.headers = {"Content-Type": "application/json"}
    www.json.return_value = {"id": 1}
    www.text = '{"id":1}'

    with patch("app.services.wp_connect._build_retry_session") as build:
        sess = MagicMock()
        sess.get.side_effect = [
            apex,
            apex,  # http apex
            www,  # https www
        ]
        build.return_value = sess
        with patch("app.services.url_safety.validate_public_http_url", return_value=None):
            resp, base = wp_get_json("/wp-json/wp/v2/users/me", url="https://itsieuviet.com")
    assert resp.status_code == 200
    assert "www.itsieuviet.com" in base
    assert "https://" in base


def test_wp_get_json_stops_after_connect_timeout():
    with patch("app.services.wp_connect._build_retry_session") as build:
        sess = MagicMock()
        sess.get.side_effect = requests.exceptions.ConnectTimeout("connect timed out")
        build.return_value = sess
        with patch("app.services.url_safety.validate_public_http_url", return_value=None):
            try:
                wp_get_json("/wp-json/wp/v2/users/me", url="https://itsieuviet.com", timeout=(1, 2))
                raise AssertionError("expected timeout")
            except requests.RequestException as exc:
                assert "timeout" in str(exc).lower() or "thời gian" in str(exc)
        assert sess.get.call_count == 1


def test_timeout_error_includes_egress_ip_and_whitelist():
    from app.services.wp_connect import format_wp_request_error, wp_server_egress_ip

    msg = format_wp_request_error(TimeoutError("timed out"), host="itsieuviet.com")
    assert "itsieuviet.com" in msg
    assert "whitelist" in msg.lower() or "Whitelist" in msg
    ip = wp_server_egress_ip()
    if ip:
        assert ip in msg
