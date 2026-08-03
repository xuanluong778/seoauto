"""Tumblr — OAuth 2 + REST API v2."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests
from fastapi import HTTPException, Request

from app.core.security import create_web20_oauth_state, decode_web20_oauth_state

TUMBLR_API = "https://api.tumblr.com/v2"


def is_mock_mode() -> bool:
    if str(os.getenv("WEB20_TUMBLR_MOCK", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    cid = str(os.getenv("TUMBLR_CONSUMER_KEY") or os.getenv("TUMBLR_CLIENT_ID") or "").strip()
    return not cid


def _client_id() -> str:
    return str(os.getenv("TUMBLR_CLIENT_ID") or os.getenv("TUMBLR_CONSUMER_KEY") or "").strip()


def _client_secret() -> str:
    return str(os.getenv("TUMBLR_CLIENT_SECRET") or os.getenv("TUMBLR_CONSUMER_SECRET") or "").strip()


def _redirect_uri(request: Request) -> str:
    explicit = str(os.getenv("TUMBLR_REDIRECT_URI", "")).strip()
    if explicit:
        return explicit
    return f"{str(request.base_url).rstrip('/')}/api/social/web20/tumblr/oauth/callback"


def oauth_start_url(request: Request, user_id: int) -> dict[str, Any]:
    if is_mock_mode():
        state = create_web20_oauth_state(user_id, "tumblr")
        return {
            "mode": "mock",
            "url": f"/api/social/web20/tumblr/oauth/mock-callback?state={state}",
            "message": "Chế độ giả lập Tumblr.",
        }
    state = create_web20_oauth_state(user_id, "tumblr")
    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "scope": "basic write offline_access",
        "state": state,
        "redirect_uri": _redirect_uri(request),
    }
    url = "https://www.tumblr.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    return {"mode": "live", "url": url}


def _exchange_code(code: str, redirect_uri: str) -> dict[str, str]:
    r = requests.post(
        "https://api.tumblr.com/v2/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": redirect_uri,
        },
        timeout=45,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Tumblr token error: {(r.text or '')[:300]}")
    data = r.json()
    return {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or ""),
    }


def mock_connect(user_id: int) -> dict[str, Any]:
    blogs = [
        {
            "id": f"mock.tumblr.com",
            "name": f"Tumblr Demo (Mock {user_id})",
            "url": f"https://mock-{user_id}.tumblr.com",
        }
    ]
    return {
        "access_token": "mock_tumblr_token",
        "refresh_token": "mock_tumblr_refresh",
        "blogs": blogs,
        "active_blog_id": blogs[0]["id"],
    }


def handle_oauth_callback(request: Request, code: str, state: str) -> dict[str, Any]:
    user_id, platform = decode_web20_oauth_state(state)
    if platform != "tumblr":
        raise HTTPException(status_code=400, detail="State OAuth không hợp lệ.")
    if is_mock_mode():
        return {**mock_connect(user_id), "user_id": user_id}
    tokens = _exchange_code(code, _redirect_uri(request))
    blogs = list_blogs_with_token(tokens["access_token"])
    active = str(blogs[0]["id"]) if blogs else ""
    return {**tokens, "blogs": blogs, "active_blog_id": active, "user_id": user_id}


def list_blogs_with_token(access_token: str) -> list[dict[str, Any]]:
    if access_token == "mock_tumblr_token":
        return mock_connect(0)["blogs"]
    r = requests.get(
        f"{TUMBLR_API}/user/info",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Tumblr user info: {(r.text or '')[:300]}")
    data = r.json()
    out: list[dict[str, Any]] = []
    user = (data.get("response") or {}).get("user") or {}
    for blog in user.get("blogs") or []:
        if not isinstance(blog, dict):
            continue
        out.append(
            {
                "id": str(blog.get("name") or blog.get("uuid") or ""),
                "name": str(blog.get("title") or blog.get("name") or ""),
                "url": str(blog.get("url") or ""),
            }
        )
    return out


class TumblrProvider:
    platform = "tumblr"

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        token = str(secrets.get("access_token") or "")
        if not token:
            return {"ok": False, "message": "Thiếu access token Tumblr."}
        try:
            blogs = list_blogs_with_token(token)
        except HTTPException as exc:
            return {"ok": False, "message": str(exc.detail)}
        return {"ok": True, "message": f"Kết nối OK — {len(blogs)} blog.", "blogs": blogs}

    def list_destinations(self, account: dict[str, Any], secrets: dict[str, Any]) -> list[dict[str, Any]]:
        cached = account.get("blogs")
        if isinstance(cached, list) and cached:
            return cached
        return list_blogs_with_token(str(secrets.get("access_token") or ""))

    def publish_post(self, account: dict[str, Any], secrets: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        token = str(secrets.get("access_token") or "")
        blog_id = str(account.get("external_id") or secrets.get("blog_id") or "")
        if not blog_id:
            raise HTTPException(status_code=400, detail="Chưa chọn blog Tumblr active.")
        title = str(post.get("title") or "Bài viết Web 2.0")
        body = str(post.get("html_content") or post.get("content") or "")
        desired = str(post.get("wp_status") or account.get("default_status") or "draft")
        # Tumblr: draft | queue | publish
        if desired == "publish":
            state = "published"
        elif desired == "queue":
            state = "queue"
        else:
            state = "draft"
        if token == "mock_tumblr_token":
            return {
                "external_id": f"mock_tumblr_{blog_id}",
                "published_url": f"https://{blog_id}/post/mock",
                "status": state,
                "mode": "mock",
            }
        payload = {
            "type": "text",
            "title": title,
            "body": body,
            "state": state,
            "format": "html",
        }
        r = requests.post(
            f"{TUMBLR_API}/blog/{blog_id}/post",
            headers={"Authorization": f"Bearer {token}"},
            data=payload,
            timeout=45,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Tumblr API: {(r.text or '')[:400]}")
        resp = r.json().get("response") or {}
        return {
            "external_id": resp.get("id") or resp.get("id_string"),
            "published_url": str(resp.get("post_url") or ""),
            "status": state,
            "mode": "api",
        }
