"""Blogger / Blogspot — Google OAuth + Blogger API v3."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests
from fastapi import HTTPException, Request

from app.core.security import create_web20_oauth_state, decode_web20_oauth_state

BLOGGER_API = "https://www.googleapis.com/blogger/v3"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
# Must match Authorized redirect URI in Google Cloud Console for this OAuth client.
DEFAULT_BLOGGER_CALLBACK_PATH = "/api/integrations/blogger/callback"


def is_mock_mode() -> bool:
    if str(os.getenv("WEB20_BLOGGER_MOCK", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    cid = str(os.getenv("GOOGLE_CLIENT_ID") or os.getenv("BLOGGER_GOOGLE_CLIENT_ID") or "").strip()
    return not cid


def _client_id() -> str:
    return str(os.getenv("BLOGGER_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return str(os.getenv("BLOGGER_GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def oauth_start_url(request: Request, user_id: int) -> dict[str, Any]:
    if is_mock_mode():
        state = create_web20_oauth_state(user_id, "blogger")
        return {
            "mode": "mock",
            "url": f"/api/social/web20/blogger/oauth/mock-callback?state={state}",
            "message": "Chế độ giả lập Blogger — không gọi Google thật.",
        }
    state = create_web20_oauth_state(user_id, "blogger")
    redirect_uri = _redirect_uri(request)
    params = {
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": BLOGGER_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"mode": "live", "url": url, "redirect_uri": redirect_uri}


def _redirect_uri(request: Request) -> str:
    """Public HTTPS callback — never use internal uvicorn host (redirect_uri_mismatch)."""
    explicit = str(os.getenv("BLOGGER_REDIRECT_URI", "")).strip()
    if explicit:
        return explicit.rstrip("/")
    base = (
        str(os.getenv("APP_BASE_URL") or "").strip()
        or str(os.getenv("PUBLIC_BASE_URL") or "").strip()
    ).rstrip("/")
    if not base:
        proto = str(request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
        host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        if host and "127.0.0.1" not in host and host.lower() != "localhost":
            base = f"{proto}://{host}".rstrip("/")
        else:
            base = str(request.base_url).rstrip("/")
    return f"{base}{DEFAULT_BLOGGER_CALLBACK_PATH}"


def _exchange_code(code: str, redirect_uri: str) -> dict[str, str]:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=45,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Google token error: {(r.text or '')[:300]}")
    data = r.json()
    return {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or ""),
    }


def mock_connect(user_id: int) -> dict[str, Any]:
    blogs = [
        {"id": f"mock_blog_{user_id}", "name": "Blogspot Demo (Mock)", "url": f"https://mock-{user_id}.blogspot.com"},
    ]
    return {
        "access_token": "mock_blogger_token",
        "refresh_token": "mock_blogger_refresh",
        "blogs": blogs,
        "active_blog_id": blogs[0]["id"],
    }


def handle_oauth_callback(request: Request, code: str, state: str) -> dict[str, Any]:
    user_id, platform = decode_web20_oauth_state(state)
    if platform != "blogger":
        raise HTTPException(status_code=400, detail="State OAuth không hợp lệ.")
    if is_mock_mode():
        return {**mock_connect(user_id), "user_id": user_id}
    tokens = _exchange_code(code, _redirect_uri(request))
    blogs = list_blogs_with_token(tokens["access_token"])
    active = str(blogs[0]["id"]) if blogs else ""
    return {**tokens, "blogs": blogs, "active_blog_id": active, "user_id": user_id}


def list_blogs_with_token(access_token: str) -> list[dict[str, Any]]:
    if access_token == "mock_blogger_token":
        return mock_connect(0)["blogs"]
    r = requests.get(
        f"{BLOGGER_API}/users/self/blogs",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Blogger list blogs: {(r.text or '')[:300]}")
    data = r.json()
    out: list[dict[str, Any]] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "url": str(item.get("url") or ""),
            }
        )
    return out


class BloggerProvider:
    platform = "blogger"

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        token = str(secrets.get("access_token") or "")
        if not token:
            return {"ok": False, "message": "Thiếu access token Blogger."}
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
            raise HTTPException(status_code=400, detail="Chưa chọn blog Blogger active.")
        title = str(post.get("title") or "Bài viết Web 2.0")
        content = str(post.get("html_content") or post.get("content") or "")
        is_draft = str(post.get("wp_status") or account.get("default_status") or "draft") != "publish"
        if token == "mock_blogger_token":
            return {
                "external_id": f"mock_post_{blog_id}",
                "published_url": f"https://mock.blogspot.com/{blog_id}/draft",
                "status": "draft" if is_draft else "live",
                "mode": "mock",
            }
        payload = {"title": title, "content": content, "isDraft": is_draft}
        r = requests.post(
            f"{BLOGGER_API}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Blogger API: {(r.text or '')[:400]}")
        data = r.json()
        return {
            "external_id": data.get("id"),
            "published_url": str(data.get("url") or ""),
            "status": "draft" if is_draft else "live",
            "mode": "api",
        }
