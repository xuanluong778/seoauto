"""Publish draft vs publish: DB credentials, ignore client secrets, no password in logs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.routers.pages import WordpressDraftPublishRequest, content_ai_publish_draft


class _FakeUser:
    id = 1


def _me_ok():
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}
    resp.json.return_value = {"id": 7, "slug": "quantri"}
    resp.text = "{}"
    return resp


def _run_publish(*, publish_mode: str, captured: dict):
    def fake_resolve(**kwargs):
        captured["resolve"] = kwargs
        return {
            "site_id": "site-db-1",
            "url": "https://itsieuviet.com",
            "username": "quantri",
            "app_password": "xxxx yyyy zzzz aaaa",
        }

    def fake_wp_get_json(path, **kwargs):
        captured["auth_url"] = kwargs.get("url")
        captured["auth_headers"] = dict(kwargs.get("headers") or {})
        return _me_ok(), "https://itsieuviet.com"

    def fake_wp_request(*, session, method, url, logs, step, **kwargs):
        body = kwargs.get("json") or {}
        captured.setdefault("posts", []).append({"step": step, "method": method, "url": url, "json": body})
        logs.append(f"[{step}] HTTP 201 json")
        resp = MagicMock()
        resp.status_code = 201
        resp.headers = {"Content-Type": "application/json"}
        resp.text = "{}"
        status = body.get("status") if "status" in body else publish_mode
        resp.json.return_value = {
            "id": 99,
            "status": status,
            "link": "https://itsieuviet.com/?p=99",
            "_links": {},
        }
        return resp

    payload = WordpressDraftPublishRequest(
        site_id="site-db-1",
        wp_url="https://itsieuviet.com",
        username="stale-local-user",
        app_password="STALE-LOCALSTORAGE-PASSWORD",
        publish_mode=publish_mode,
        seo_plugin="none",
        primary_keyword="test keyword",
        draft_payload={
            "title": "Bài kiểm tra SEOAuto",
            "content": "<p>Nội dung kiểm tra.</p>",
            "slug": "bai-kiem-tra-seoauto",
        },
    )
    user = _FakeUser()
    db = MagicMock()

    with (
        patch("app.routers.pages.assert_content_ai_feature"),
        patch(
            "app.services.wordpress_connection.resolve_wordpress_connection",
            side_effect=fake_resolve,
        ),
        patch("app.services.wp_connect.wp_get_json", side_effect=fake_wp_get_json),
        patch("app.routers.pages._wp_request", side_effect=fake_wp_request),
        patch("app.routers.pages._upload_featured_media", return_value=None),
        patch("app.routers.pages._ensure_wp_tag_ids", return_value=[]),
        patch("app.routers.pages._detect_wp_seo_plugin", return_value="none"),
        patch("app.routers.pages._rewrite_inline_images_for_wp", side_effect=lambda **kw: kw["content_html"]),
        patch("app.routers.pages._update_post_seo_meta"),
        patch("app.routers.pages._update_rankmath_via_plugin_endpoint"),
        patch("app.routers.pages.log_audit_event"),
        patch("app.routers.pages.record_content_ai_usage"),
    ):
        resp = content_ai_publish_draft(
            request=MagicMock(),
            payload=payload,
            current_user=user,
            db=db,
        )
    return resp


def test_publish_draft_uses_db_site_and_ignores_client_password():
    captured: dict = {}
    resp = _run_publish(publish_mode="draft", captured=captured)
    body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
    assert captured["resolve"]["site_id"] == "site-db-1"
    assert captured["resolve"]["user_id"] == 1
    assert captured["resolve"].get("site_url") == "https://itsieuviet.com"
    assert "Mozilla" in (captured["auth_headers"].get("User-Agent") or "")
    create = next(x for x in captured["posts"] if x["step"] == "create-draft")
    assert create["json"]["status"] == "draft"
    assert "STALE-LOCALSTORAGE-PASSWORD" not in body
    assert "xxxx yyyy" not in body
    data = resp.body
    import json

    parsed = json.loads(data)
    assert parsed["ok"] is True
    assert parsed["status"] == "draft"
    assert parsed["post_id"] == 99
    joined_logs = " ".join(parsed.get("logs") or [])
    assert "xxxx yyyy" not in joined_logs
    assert "STALE-LOCALSTORAGE-PASSWORD" not in joined_logs


def test_publish_live_sets_status_publish():
    captured: dict = {}
    resp = _run_publish(publish_mode="publish", captured=captured)
    import json

    parsed = json.loads(resp.body)
    assert parsed["ok"] is True
    create = next(x for x in captured["posts"] if x["step"] == "create-draft")
    assert create["json"]["status"] == "publish"
    assert parsed["status"] == "publish"
