"""Fetch WordPress post categories via REST API (shared by Content AI + Settings)."""

from __future__ import annotations

import base64
import re
from typing import Any

import requests

from app.services.wp_connect import normalize_wp_base_url, wp_get_json


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
    for label, strip_spaces in (("raw", False), ("strip-spaces", True)):
        candidate = _build_wp_session(user, pwd, strip_spaces=strip_spaces)
        try:
            resp, wp_base = wp_get_json(
                "/wp-json/wp/v2/users/me",
                url=url,
                headers=dict(candidate.headers),
                auth=candidate.auth,
                timeout=20,
            )
        except requests.RequestException as exc:
            logs.append(f"[auth:{label}] {exc}")
            continue
        logs.append(f"[auth:{label}@{wp_base}] HTTP {resp.status_code}")
        if resp.status_code < 400:
            session = candidate
            break

    if session is None or not wp_base:
        dns_hint = any("phân giải" in x for x in logs)
        return {
            "ok": False,
            "items": [],
            "message": (
                logs[-1].split("] ", 1)[-1]
                if dns_hint and logs
                else "Xác thực WordPress thất bại. Kiểm tra URL, username và Application password."
            ),
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
                timeout=25,
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
