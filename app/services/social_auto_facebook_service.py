"""Facebook Graph API + OAuth (official). Mock mode when credentials missing."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests
from fastapi import HTTPException, Request

from app.core.security import create_facebook_oauth_state, decode_facebook_oauth_state
from app.services.social_auto_facebook_oauth_config import effective_login_config_id
from app.services.social_auto_facebook_store import (
    append_api_log,
    clear_facebook_oauth_meta,
    disconnect_page,
    get_facebook_oauth_meta,
    get_page_token,
    is_mock_mode,
    list_pages,
    save_facebook_oauth_meta,
    set_active_page,
    upsert_page,
)

GRAPH = "https://graph.facebook.com/v21.0"
FB_SCOPES_DEFAULT = "pages_show_list,pages_read_engagement,pages_manage_posts"
PAGE_SCOPES = frozenset({"pages_show_list", "pages_read_engagement", "pages_manage_posts"})
FB_CONNECTION_LABELS = {
    "not_connected": "Chưa kết nối",
    "fb_logged_in": "Đã đăng nhập Facebook",
    "no_pages_permission": "Chưa có quyền Fanpage",
    "connected": "Đã kết nối Fanpage",
}


def facebook_oauth_configured() -> bool:
    return not is_mock_mode()


def _facebook_oauth_scopes() -> str:
    custom = str(os.getenv("FACEBOOK_OAUTH_SCOPES", "")).strip()
    return custom or FB_SCOPES_DEFAULT


def _facebook_login_config_id() -> str:
    return effective_login_config_id()


def _facebook_app_id() -> str:
    return str(os.getenv("FACEBOOK_APP_ID", "")).strip()


def _get_app_access_token() -> str:
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    if not (app_id and app_secret):
        return ""
    r = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={"client_id": app_id, "client_secret": app_secret, "grant_type": "client_credentials"},
        timeout=20,
    )
    if r.status_code >= 400:
        return ""
    return str(r.json().get("access_token") or "").strip()


def _fetch_app_permissions() -> set[str]:
    app_id = _facebook_app_id()
    token = _get_app_access_token()
    if not (app_id and token):
        return set()
    r = requests.get(f"{GRAPH}/{app_id}/permissions", params={"access_token": token}, timeout=20)
    if r.status_code >= 400:
        return set()
    data = r.json()
    return {
        str(row.get("permission") or "").strip()
        for row in (data.get("data") or [])
        if isinstance(row, dict) and row.get("permission")
    }


def _oauth_preflight() -> dict[str, Any]:
    config_id = _facebook_login_config_id()
    app_perms = sorted(_fetch_app_permissions())
    has_pages = bool(set(app_perms) & PAGE_SCOPES)
    force_scope = str(os.getenv("FACEBOOK_FORCE_SCOPE_OAUTH", "")).strip().lower() in {"1", "true", "yes"}
    can_use_scope = has_pages or force_scope
    return {
        "has_config_id": bool(config_id),
        "app_permissions": app_perms,
        "app_has_pages_permissions": has_pages,
        "can_use_scope": can_use_scope,
        "scope_will_fail": not config_id and not can_use_scope,
    }


def facebook_oauth_setup_info() -> dict[str, Any]:
    """Hướng dẫn cấu hình Meta — hiển thị khi invalid_scope / chưa sẵn sàng."""
    app_id = _facebook_app_id()
    preflight = _oauth_preflight()
    business_url = (
        f"https://developers.facebook.com/apps/{app_id}/business-login/settings/"
        if app_id
        else "https://developers.facebook.com/apps/"
    )
    perms_url = (
        f"https://developers.facebook.com/apps/{app_id}/use_cases/"
        if app_id
        else "https://developers.facebook.com/apps/"
    )
    steps = [
        "App Meta hiện chưa có quyền Pages — OAuth scope sẽ báo Invalid Scopes.",
        "Cách A (Facebook Login for Business): Configurations → Create → User access token.",
        "Thêm pages_show_list, pages_read_engagement, pages_manage_posts → copy Configuration ID.",
        "Dán Configuration ID vào ô admin (KHÔNG dán App ID) hoặc FACEBOOK_LOGIN_CONFIG_ID trong env.",
        "Cách B: Use case «Quản lý Trang» → bật 3 quyền Pages → Ready for testing.",
        "Facebook Login → Valid OAuth Redirect URI = https://seoauto.vn/api/social/facebook/oauth/callback",
        "Bấm lại «Kết nối Fanpage».",
    ]
    return {
        "mock_mode": is_mock_mode(),
        "has_config_id": bool(_facebook_login_config_id()),
        "uses_scope_fallback": not bool(_facebook_login_config_id()),
        "scopes": _facebook_oauth_scopes(),
        "app_id": app_id or None,
        "redirect_uri": str(os.getenv("FACEBOOK_REDIRECT_URI", "")).strip() or None,
        "dashboard_url": business_url,
        "permissions_url": perms_url,
        "preflight": preflight,
        "steps": steps,
    }


def facebook_connection_status(user_id: int) -> dict[str, Any]:
    pages = [p for p in list_pages(user_id) if not p.get("is_mock") and p.get("status") == "connected"]
    if pages:
        return {
            "status": "connected",
            "label": FB_CONNECTION_LABELS["connected"],
            "page_count": len(pages),
            "message": None,
        }
    meta = get_facebook_oauth_meta(user_id)
    st = str(meta.get("status") or "").strip()
    if st in {"no_pages_permission", "fb_logged_in"}:
        return {
            "status": st,
            "label": FB_CONNECTION_LABELS.get(st, st),
            "page_count": 0,
            "message": meta.get("message"),
            "granted_permissions": meta.get("granted_permissions") or [],
        }
    return {
        "status": "not_connected",
        "label": FB_CONNECTION_LABELS["not_connected"],
        "page_count": 0,
        "message": None,
    }


def _redirect_uri(request: Request) -> str:
    explicit = str(os.getenv("FACEBOOK_REDIRECT_URI", "")).strip()
    if explicit:
        return explicit
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/social/facebook/oauth/callback"


def build_oauth_authorize_params(request: Request, user_id: int) -> dict[str, str]:
    """config_id nếu có; không thì scope Pages (OAuth thường)."""
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    if not app_id:
        raise HTTPException(status_code=503, detail="Chưa cấu hình FACEBOOK_APP_ID.")
    state = create_facebook_oauth_state(user_id)
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "response_type": "code",
    }
    config_id = _facebook_login_config_id()
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = _facebook_oauth_scopes()
    return params


def oauth_start_url(request: Request, user_id: int) -> dict[str, Any]:
    setup = facebook_oauth_setup_info()
    if is_mock_mode():
        return {
            "mode": "mock",
            "url": f"/api/social/facebook/oauth/mock-callback?state={create_facebook_oauth_state(user_id)}",
            "message": "Chế độ giả lập — không gọi Facebook thật.",
            "setup": setup,
            "connection": facebook_connection_status(user_id),
        }
    preflight = setup.get("preflight") or {}
    if preflight.get("scope_will_fail"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "facebook_oauth_not_ready",
                "message": (
                    "Meta App chưa có quyền Pages — OAuth scope sẽ báo Invalid Scopes. "
                    "Cần tạo Configuration ID (Facebook Login for Business) hoặc bật quyền Pages trong Meta App."
                ),
                "setup": setup,
            },
        )
    params = build_oauth_authorize_params(request, user_id)
    url = "https://www.facebook.com/v21.0/dialog/oauth?" + urllib.parse.urlencode(params)
    mode = "live_config" if params.get("config_id") else "live_scope"
    return {
        "mode": mode,
        "url": url,
        "uses_config_id": bool(params.get("config_id")),
        "scope": params.get("scope"),
        "app_id": params.get("client_id"),
        "config_id": params.get("config_id"),
        "redirect_uri": params.get("redirect_uri"),
        "setup": setup,
        "connection": facebook_connection_status(user_id),
    }


def _log_oauth_error(user_id: int, code: str, message: str, *, meta: dict[str, Any] | None = None) -> None:
    append_api_log(user_id, level="error", code=code, message=message[:1000], meta=meta or {})


def _exchange_code_for_token(code: str, redirect_uri: str, user_id: int) -> str:
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
        body = (r.text or "")[:500]
        missing = []
        if "invalid_scope" in body.lower() or "invalid scopes" in body.lower():
            missing = sorted(PAGE_SCOPES)
            _log_oauth_error(
                user_id,
                "invalid_scope",
                f"Facebook token error — thiếu quyền Pages: {', '.join(missing)}",
                meta={"response": body, "missing_scopes": missing},
            )
        raise HTTPException(status_code=502, detail=f"Facebook token error: {body[:300]}")
    data = r.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=502, detail="Facebook không trả access_token.")
    return token


def _fetch_granted_permissions(user_token: str) -> set[str]:
    r = requests.get(
        f"{GRAPH}/me/permissions",
        params={"access_token": user_token},
        timeout=30,
    )
    if r.status_code >= 400:
        return set()
    data = r.json()
    granted: set[str] = set()
    for row in data.get("data") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").lower() == "granted":
            perm = str(row.get("permission") or "").strip()
            if perm:
                granted.add(perm)
    return granted


def _fetch_user_pages(user_token: str, user_id: int) -> list[dict[str, Any]]:
    r = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
        timeout=30,
    )
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Facebook rate limit.")
    if r.status_code >= 400:
        body = (r.text or "")[:500]
        missing = sorted(PAGE_SCOPES)
        _log_oauth_error(
            user_id,
            "missing_pages_permission",
            f"Graph /me/accounts lỗi — có thể thiếu quyền: {', '.join(missing)}",
            meta={"response": body, "missing_scopes": missing},
        )
        raise HTTPException(status_code=502, detail=f"Không lấy được danh sách Fanpage: {body[:300]}")
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
    user_token = _exchange_code_for_token(code, redirect_uri, user_id)
    granted = _fetch_granted_permissions(user_token)
    missing_page_scopes = sorted(PAGE_SCOPES - granted)
    pages = _fetch_user_pages(user_token, user_id)

    if not pages:
        if missing_page_scopes:
            msg = (
                "Facebook mới cấp public_profile/email, chưa cấp quyền pages_show_list, "
                "pages_read_engagement, pages_manage_posts."
            )
            save_facebook_oauth_meta(
                user_id,
                status="no_pages_permission",
                granted_permissions=sorted(granted),
                message=msg,
            )
            _log_oauth_error(
                user_id,
                "missing_pages_scope",
                msg,
                meta={"granted": sorted(granted), "missing_scopes": missing_page_scopes},
            )
            return {
                "pages": [],
                "count": 0,
                "oauth_status": "no_pages_permission",
                "message": msg,
                "granted_permissions": sorted(granted),
                "missing_scopes": missing_page_scopes,
            }

        msg = "Đã đăng nhập Facebook nhưng không tìm thấy Fanpage nào bạn quản lý."
        save_facebook_oauth_meta(
            user_id,
            status="fb_logged_in",
            granted_permissions=sorted(granted),
            message=msg,
        )
        append_api_log(user_id, level="info", code="fb_logged_in_no_pages", message=msg)
        return {
            "pages": [],
            "count": 0,
            "oauth_status": "fb_logged_in",
            "message": msg,
            "granted_permissions": sorted(granted),
        }

    saved = []
    for pg in pages[:20]:
        pid = str(pg.get("id") or "")
        if not pid:
            continue
        page_token = str(pg.get("access_token") or "").strip()
        if not page_token:
            continue
        saved.append(
            upsert_page(
                user_id=user_id,
                page_id=pid,
                page_name=str(pg.get("name") or pid),
                page_access_token=page_token,
                status="connected",
                is_mock=False,
            )
        )
    if saved:
        set_active_page(user_id, str(saved[0].get("page_id")))
    save_facebook_oauth_meta(
        user_id,
        status="connected",
        granted_permissions=sorted(granted),
        message=f"Kết nối {len(saved)} Fanpage.",
    )
    append_api_log(user_id, level="info", code="oauth_connected", message=f"Kết nối {len(saved)} Fanpage.")
    return {"pages": saved, "count": len(saved), "oauth_status": "connected"}


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
    return {"pages": [page], "count": 1, "mode": "mock", "oauth_status": "connected"}


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
