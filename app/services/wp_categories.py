"""Fetch WordPress post categories via REST API (shared by Content AI + Settings)."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from app.services.wp_connect import normalize_wp_base_url, wp_get_json, wp_http_status_note


def _build_wp_session(username: str, app_password: str, *, strip_spaces: bool) -> requests.Session:
    user = (username or "").strip()
    pwd = (app_password or "").strip()
    if strip_spaces:
        pwd = re.sub(r"\s+", "", pwd)
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    session = requests.Session()
    session.auth = (user, pwd)
    from app.services.wp_connect import DEFAULT_WP_HEADERS

    session.headers.update(
        {
            **DEFAULT_WP_HEADERS,
            "Authorization": f"Basic {token}",
        }
    )
    return session


def fetch_wordpress_categories(*, url: str, username: str, app_password: str) -> dict[str, Any]:
    """
    Return {ok, items, message, logs?}.
    items: [{id, name, parent}, ...]
    """
    if not normalize_wp_base_url(url):
        return {"ok": False, "items": [], "message": "URL WordPress không hợp lệ."}
    user = (username or "").strip()
    pwd = (app_password or "").strip()
    if not user or not pwd:
        return {"ok": False, "items": [], "message": "Thiếu username hoặc Application password."}

    logs: list[str] = []
    session: requests.Session | None = None
    wp_base = ""
    timed_out = False
    for label, strip_spaces in (("strip-spaces", True), ("raw", False)):
        candidate = _build_wp_session(user, pwd, strip_spaces=strip_spaces)
        try:
            resp, wp_base = wp_get_json(
                "/wp-json/wp/v2/users/me",
                url=url,
                headers=dict(candidate.headers),
                auth=candidate.auth,
                timeout=(3.5, 10),
            )
        except requests.RequestException as exc:
            logs.append(f"[auth:{label}] {exc.__class__.__name__}")
            blob = f"{exc.__class__.__name__} {exc}".lower()
            if "timeout" in blob or "timed out" in blob or "thời gian" in blob:
                timed_out = True
                break
            continue
        logs.append(f"[auth:{label}@{wp_base}] {wp_http_status_note(resp)}")
        if resp.status_code < 400:
            session = candidate
            break

    if timed_out and (session is None or not wp_base):
        return {
            "ok": False,
            "items": [],
            "message": (
                "Tải danh mục quá lâu (timeout). "
                "Server Seoauto không kết nối được WordPress REST — "
                "whitelist IP server trên hosting/Cloudflare rồi thử lại."
            ),
            "logs": logs[-8:],
        }

    if session is None or not wp_base:
        dns_hint = any("phân giải" in x for x in logs)
        last = logs[-1] if logs else ""
        http_hint = ""
        for token in ("HTTP 401", "HTTP 403", "HTTP 404", "timeout", "Timeout"):
            if token.lower() in last.lower() or any(token.lower() in x.lower() for x in logs):
                http_hint = token
                break
        if dns_hint and logs:
            message = logs[-1].split("] ", 1)[-1]
        elif http_hint.startswith("HTTP"):
            message = (
                f"Xác thực WordPress thất bại ({http_hint}). "
                "Kiểm tra Application Password tại Cài đặt → Xuất bản."
            )
        elif http_hint.lower().startswith("timeout"):
            message = (
                "Xác thực WordPress thất bại (timeout). "
                "Server không kết nối được WordPress REST — kiểm tra URL https://domain.com "
                "và whitelist IP máy chủ Seoauto trên hosting/Cloudflare."
            )
        else:
            message = (
                "Xác thực WordPress thất bại. "
                "Kiểm tra URL đã lưu và Application Password tại Cài đặt → Xuất bản."
            )
        return {
            "ok": False,
            "items": [],
            "message": message,
            "logs": logs[-8:],
        }

    items: list[dict[str, Any]] = []
    page = 1
    while page <= 50:
        try:
            r, wp_base = wp_get_json(
                "/wp-json/wp/v2/categories",
                url=wp_base,
                headers=dict(session.headers),
                auth=session.auth,
                timeout=(3.5, 10),
                params={
                    "per_page": 100,
                    "page": page,
                    "_fields": "id,name,parent",
                    "orderby": "name",
                    "order": "asc",
                },
            )
        except requests.RequestException as exc:
            return {
                "ok": False,
                "items": items,
                "message": str(exc),
                "logs": logs[-8:],
            }
        if r.status_code == 401:
            return {
                "ok": False,
                "items": [],
                "message": "WordPress từ chối đăng nhập (401). Kiểm tra Application password.",
                "logs": logs[-8:],
            }
        if r.status_code == 403:
            return {
                "ok": False,
                "items": [],
                "message": "Tài khoản không có quyền đọc danh mục (403).",
                "logs": logs[-8:],
            }
        if r.status_code >= 400:
            snippet = (r.text or "")[:200]
            return {
                "ok": False,
                "items": items,
                "message": f"Không đọc được danh mục (HTTP {r.status_code}). {snippet}".strip(),
                "logs": logs[-8:],
            }
        try:
            batch = r.json()
        except ValueError:
            batch = []
        if not isinstance(batch, list) or not batch:
            break
        for row in batch:
            if not isinstance(row, dict):
                continue
            try:
                cid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            name = re.sub(r"\s+", " ", str(row.get("name") or "").strip())
            if cid > 0 and name:
                try:
                    parent = int(row.get("parent") or 0)
                except (TypeError, ValueError):
                    parent = 0
                items.append({"id": cid, "name": name, "parent": parent})
        if len(batch) < 100:
            break
        page += 1

    items.sort(key=lambda x: (str(x.get("name") or "").lower(), int(x.get("id") or 0)))
    if not items:
        return {
            "ok": True,
            "items": [],
            "message": "Kết nối OK nhưng site chưa có danh mục nào — tạo category trên WordPress trước.",
        }
    return {"ok": True, "items": items, "message": f"Đã tải {len(items)} danh mục."}


def _wp_category_cache_path() -> Path:
    raw = (os.getenv("CONTENT_AI_CACHE_DIR") or "").strip()
    root = Path(raw) if raw else Path(__file__).resolve().parents[2] / "data" / "content_ai_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root / "wp_categories.json"


def _sanitize_cached_category_items(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        try:
            cid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        name = re.sub(r"\s+", " ", str(row.get("name") or "").strip())
        if cid <= 0 or not name:
            continue
        try:
            parent = int(row.get("parent") or 0)
        except (TypeError, ValueError):
            parent = 0
        out.append({"id": cid, "name": name, "parent": parent})
    return out


def _wp_category_cache_keys(*, user_id: int, site_id: str = "", url: str = "") -> list[str]:
    keys: list[str] = []
    sid = str(site_id or "").strip()
    if sid:
        keys.append(f"u{int(user_id)}:id:{sid}")
    norm = str(normalize_wp_base_url(url) or url or "").strip().lower().rstrip("/")
    if norm:
        keys.append(f"u{int(user_id)}:url:{norm}")
    return keys


def read_cached_wordpress_categories(*, user_id: int, site_id: str = "", url: str = "") -> dict[str, Any] | None:
    keys = _wp_category_cache_keys(user_id=user_id, site_id=site_id, url=url)
    if not keys:
        return None
    try:
        raw = json.loads(_wp_category_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    for key in keys:
        row = raw.get(key)
        if not isinstance(row, dict):
            continue
        items = _sanitize_cached_category_items(row.get("items"))
        if not items:
            continue
        return {
            "ok": True,
            "items": items,
            "message": str(row.get("message") or f"Đã tải {len(items)} danh mục."),
            "from_cache": True,
        }
    return None


def write_cached_wordpress_categories(
    *,
    user_id: int,
    site_id: str = "",
    url: str = "",
    items: list[dict[str, Any]] | None = None,
    message: str = "",
) -> None:
    clean = _sanitize_cached_category_items(items)
    keys = _wp_category_cache_keys(user_id=user_id, site_id=site_id, url=url)
    if not keys or not clean:
        return
    path = _wp_category_cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError, TypeError):
        raw = {}
    payload = {
        "items": clean,
        "message": str(message or f"Đã tải {len(clean)} danh mục."),
        "fetched_at": int(time.time()),
    }
    for key in keys:
        raw[key] = payload
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_wordpress_categories(
    *,
    user_id: int,
    site_id: str = "",
    url: str,
    username: str,
    app_password: str,
    refresh: bool = False,
) -> dict[str, Any]:
    """Prefer per-user/site cache; hit WordPress only when empty or refresh=True."""
    if not refresh:
        cached = read_cached_wordpress_categories(user_id=user_id, site_id=site_id, url=url)
        if cached:
            return cached
    result = fetch_wordpress_categories(url=url, username=username, app_password=app_password)
    if result.get("ok") and result.get("items"):
        write_cached_wordpress_categories(
            user_id=user_id,
            site_id=site_id,
            url=url,
            items=list(result.get("items") or []),
            message=str(result.get("message") or ""),
        )
    return result
