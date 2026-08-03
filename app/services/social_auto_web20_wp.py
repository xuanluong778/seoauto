"""WordPress REST API cho site vệ tinh Web 2.0 — không dùng Content AI Publish."""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

from app.services.wp_connect import normalize_wp_base_url, wp_get_json


def _auth_headers(username: str, app_password: str) -> dict[str, str]:
    pwd = str(app_password or "").strip().replace(" ", "")
    cred = f"{username.strip()}:{pwd}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(cred).decode("ascii"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def test_wp_connection(*, site_url: str, username: str, app_password: str) -> dict[str, Any]:
    base = normalize_wp_base_url(site_url)
    if not base:
        return {"ok": False, "message": "URL WordPress không hợp lệ."}
    headers = _auth_headers(username, app_password)
    try:
        data, working = wp_get_json(url=f"{base}/wp-json/wp/v2/users/me", headers=headers, timeout=25)
    except Exception as exc:
        return {"ok": False, "message": f"Không kết nối được: {exc}"[:400]}
    if not isinstance(data, dict):
        return {"ok": False, "message": "WordPress REST API không phản hồi đúng định dạng."}
    name = str(data.get("name") or data.get("slug") or username)
    return {"ok": True, "message": f"Kết nối OK — {name}", "working_url": working}


def _resolve_category_id(base: str, headers: dict[str, str], category: str) -> int | None:
    cat = str(category or "").strip()
    if not cat:
        return None
    if cat.isdigit():
        return int(cat)
    try:
        r = requests.get(
            f"{base}/wp-json/wp/v2/categories",
            params={"search": cat, "per_page": 5},
            headers=headers,
            timeout=20,
        )
        if r.status_code >= 400:
            return None
        data = r.json()
        if isinstance(data, list) and data:
            return int(data[0].get("id") or 0) or None
    except Exception:
        return None
    return None


def _resolve_tag_ids(base: str, headers: dict[str, str], tags: list[str]) -> list[int]:
    ids: list[int] = []
    for tag in tags[:20]:
        name = str(tag).strip().lstrip("#")
        if not name:
            continue
        try:
            r = requests.get(
                f"{base}/wp-json/wp/v2/tags",
                params={"search": name, "per_page": 3},
                headers=headers,
                timeout=15,
            )
            if r.status_code < 400:
                data = r.json()
                if isinstance(data, list) and data:
                    tid = int(data[0].get("id") or 0)
                    if tid:
                        ids.append(tid)
                        continue
            cr = requests.post(
                f"{base}/wp-json/wp/v2/tags",
                json={"name": name},
                headers=headers,
                timeout=15,
            )
            if cr.status_code < 400:
                obj = cr.json()
                if isinstance(obj, dict) and obj.get("id"):
                    ids.append(int(obj["id"]))
        except Exception:
            continue
    return ids


def publish_post_to_wp(
    *,
    site_url: str,
    username: str,
    app_password: str,
    title: str,
    slug: str = "",
    excerpt: str = "",
    html_content: str = "",
    tags: list[str] | None = None,
    category: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    """Đăng bài lên WordPress vệ tinh qua REST API. Mặc định draft."""
    base = normalize_wp_base_url(site_url)
    if not base:
        raise HTTPException(status_code=400, detail="URL site không hợp lệ.")
    headers = _auth_headers(username, app_password)
    wp_status = str(status or "draft").lower()
    if wp_status not in {"draft", "publish", "pending", "private"}:
        wp_status = "draft"

    payload: dict[str, Any] = {
        "title": title or "Bài viết Web 2.0",
        "content": html_content or "",
        "excerpt": excerpt or "",
        "status": wp_status,
    }
    if slug:
        payload["slug"] = slug[:200]
    cat_id = _resolve_category_id(base, headers, category)
    if cat_id:
        payload["categories"] = [cat_id]
    tag_ids = _resolve_tag_ids(base, headers, tags or [])
    if tag_ids:
        payload["tags"] = tag_ids

    try:
        r = requests.post(f"{base}/wp-json/wp/v2/posts", json=payload, headers=headers, timeout=45)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"WordPress không phản hồi: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"WordPress lỗi ({r.status_code}): {(r.text or '')[:400]}")
    data = r.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="WordPress trả về dữ liệu không hợp lệ.")
    link = str(data.get("link") or "").strip()
    if not link and data.get("id"):
        link = f"{base}/?p={data.get('id')}"
    return {
        "wp_post_id": data.get("id"),
        "published_url": link,
        "status": data.get("status") or wp_status,
    }


def count_links_to_host(html: str, main_site_url: str) -> int:
    if not html or not main_site_url:
        return 0
    try:
        host = urlparse(main_site_url if "://" in main_site_url else f"https://{main_site_url}").netloc.lower()
        if host.startswith("www."):
            host = host[4:]
    except Exception:
        return 0
    if not host:
        return 0
    count = 0
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        try:
            h = urlparse(href).netloc.lower()
            if h.startswith("www."):
                h = h[4:]
            if host in h or h in host:
                count += 1
        except Exception:
            continue
    return count
