"""Facebook Graph API + OAuth (official). Mock mode when credentials missing."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests
from fastapi import HTTPException, Request

from app.core.security import create_facebook_oauth_state, decode_facebook_oauth_state
from app.services.social_auto_facebook_store import (
    append_api_log,
    disconnect_page,
    get_page_token,
    is_mock_mode,
    list_pages,
    set_active_page,
    upsert_page,
)

GRAPH = "https://graph.facebook.com/v21.0"
FB_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts,public_profile"


def facebook_oauth_configured() -> bool:
    return not is_mock_mode()


def _redirect_uri(request: Request) -> str:
    explicit = str(os.getenv("FACEBOOK_REDIRECT_URI", "")).strip()
    if explicit:
        return explicit
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/social/facebook/oauth/callback"


def oauth_start_url(request: Request, user_id: int) -> dict[str, Any]:
    if is_mock_mode():
        return {
            "mode": "mock",
            "url": f"/api/social/facebook/oauth/mock-callback?state={create_facebook_oauth_state(user_id)}",
            "message": "Chế độ giả lập — không gọi Facebook thật.",
        }
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    state = create_facebook_oauth_state(user_id)
    params = {
        "client_id": app_id,
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "scope": FB_SCOPES,
        "response_type": "code",
    }
    url = "https://www.facebook.com/v21.0/dialog/oauth?" + urllib.parse.urlencode(params)
    return {"mode": "live", "url": url}


def _exchange_code_for_token(code: str, redirect_uri: str) -> str:
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    r = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Facebook token error: {(r.text or '')[:300]}")
    data = r.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=502, detail="Facebook không trả access_token.")
    return token


def _fetch_user_pages(user_token: str) -> list[dict[str, Any]]:
    r = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
        timeout=30,
    )
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Facebook rate limit.")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Không lấy được danh sách Fanpage: {(r.text or '')[:300]}")
    data = r.json()
    return [x for x in (data.get("data") or []) if isinstance(x, dict)]


def handle_oauth_callback(request: Request, code: str, state: str) -> dict[str, Any]:
    try:
        user_id = decode_facebook_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="State OAuth không hợp lệ.") from exc

    if is_mock_mode():
        return mock_connect(user_id)

    redirect_uri = _redirect_uri(request)
    user_token = _exchange_code_for_token(code, redirect_uri)
    pages = _fetch_user_pages(user_token)
    saved = []
    for pg in pages[:20]:
        pid = str(pg.get("id") or "")
        if not pid:
            continue
        saved.append(
            upsert_page(
                user_id=user_id,
                page_id=pid,
                page_name=str(pg.get("name") or pid),
                page_access_token=str(pg.get("access_token") or user_token),
                status="connected",
                is_mock=False,
            )
        )
    if saved:
        set_active_page(user_id, str(saved[0].get("page_id")))
    append_api_log(user_id, level="info", code="oauth_connected", message=f"Kết nối {len(saved)} Fanpage.")
    return {"pages": saved, "count": len(saved)}


def mock_connect(user_id: int) -> dict[str, Any]:
    page = upsert_page(
        user_id=user_id,
        page_id=f"mock_page_{user_id}",
        page_name="Fanpage Demo (Mock)",
        page_access_token="mock_token",
        status="connected",
        is_mock=True,
    )
    set_active_page(user_id, str(page.get("page_id")))
    append_api_log(user_id, level="info", code="mock_connected", message="Kết nối Fanpage giả lập.")
    return {"pages": [page], "count": 1, "mode": "mock"}


def publish_post_mock(user_id: int, page_id: str, message: str) -> dict[str, Any]:
    """Giả lập đăng bài — không gọi Graph API."""
    append_api_log(
        user_id,
        level="info",
        code="mock_publish",
        message="Giả lập đăng bài Fanpage thành công.",
        page_id=page_id,
        meta={"chars": len(message)},
    )
    return {
        "id": f"mock_post_{page_id}",
        "permalink_url": f"https://www.facebook.com/{page_id}/posts/mock",
    }


def publish_post_live(user_id: int, page_id: str, message: str) -> dict[str, Any]:
    token = get_page_token(page_id, user_id)
    if not token:
        append_api_log(
            user_id, level="error", code="permission_denied",
            message="Thiếu token Fanpage.", page_id=page_id,
        )
        raise HTTPException(status_code=403, detail="Chưa có quyền đăng Fanpage này.")
    r = requests.post(
        f"{GRAPH}/{page_id}/feed",
        data={"message": message, "access_token": token},
        timeout=45,
    )
    if r.status_code == 429:
        append_api_log(user_id, level="error", code="rate_limit", message="Facebook rate limit.", page_id=page_id)
        raise HTTPException(status_code=429, detail="Facebook rate limit — đã tạm dừng theo cài đặt an toàn.")
    if r.status_code >= 400:
        body = (r.text or "")[:400]
        code = "permission_denied" if r.status_code in {400, 403} else "api_error"
        append_api_log(user_id, level="error", code=code, message=body, page_id=page_id)
        raise HTTPException(status_code=502, detail=f"Facebook API lỗi: {body}")
    data = r.json()
    post_id = str(data.get("id") or "")
    append_api_log(user_id, level="info", code="published", message="Đăng Fanpage thành công.", page_id=page_id)
    return {"id": post_id, "permalink_url": f"https://www.facebook.com/{post_id}"}


def publish_to_fanpage(user_id: int, page_id: str, message: str) -> dict[str, Any]:
    pages = list_pages(user_id)
    page = next((p for p in pages if str(p.get("page_id")) == str(page_id)), None)
    if not page:
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage.")
    if page.get("is_mock") or is_mock_mode():
        return publish_post_mock(user_id, page_id, message)
    return publish_post_live(user_id, page_id, message)


def build_preview(message: str, *, page_name: str = "Fanpage") -> dict[str, Any]:
    return {
        "platform": "facebook",
        "page_name": page_name,
        "message": message,
        "char_count": len(message),
        "link_preview": False,
    }
