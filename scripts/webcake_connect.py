"""Webcake / Storecake Open API: access + refresh tokens."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

DEFAULT_API_BASE = "https://api.storecake.io/api/v1/external"
TOKEN_TTL_SECONDS = 3600


def api_base_url() -> str:
    return str(os.getenv("WEBCAKE_API_BASE", DEFAULT_API_BASE)).rstrip("/")


def normalize_site_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = f"https://{s}"
    return s.rstrip("/")


def pack_webcake_secrets(
    *,
    access_token: str,
    refresh_token: str,
    expires_at: str = "",
) -> str:
    return json.dumps(
        {
            "v": 1,
            "access_token": str(access_token or ""),
            "refresh_token": str(refresh_token or ""),
            "expires_at": str(expires_at or ""),
        },
        ensure_ascii=False,
    )


def unpack_webcake_secrets(blob: str) -> dict[str, Any]:
    raw = str(blob or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {"v": 0, "access_token": raw, "refresh_token": "", "expires_at": ""}


def _expires_default() -> str:
    return datetime.fromtimestamp(time.time() + TOKEN_TTL_SECONDS, tz=timezone.utc).isoformat()


def refresh_access_token(refresh_token: str, *, timeout: float = 25) -> dict[str, Any]:
    rt = str(refresh_token or "").strip()
    if not rt:
        return {"ok": False, "message": "Thiếu Refresh Token."}
    url = f"{api_base_url()}/oauth/token"
    try:
        r = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Storecake-Refresh-Token": rt,
                "User-Agent": "digiseo-Tool/1.0",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "message": f"Không gọi được Webcake API: {exc}"}
    try:
        payload = r.json() if r.content else {}
    except ValueError:
        payload = {}
    if r.status_code >= 400 or not isinstance(payload, dict):
        snippet = (r.text or "")[:200]
        return {"ok": False, "message": f"Webcake token HTTP {r.status_code}. {snippet}".strip()}
    if not payload.get("success"):
        err = str(payload.get("error") or payload.get("message") or "Refresh failed.")
        return {"ok": False, "message": err}
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    access = str(data.get("access_token") or "").strip()
    new_refresh = str(data.get("refresh_token") or rt).strip()
    if not access:
        return {"ok": False, "message": "Webcake không trả access_token — kiểm tra Refresh Token."}
    return {
        "ok": True,
        "access_token": access,
        "refresh_token": new_refresh,
        "expires_at": _expires_default(),
    }


def ensure_access_token(secrets_blob: str, *, force_refresh: bool = False) -> tuple[str, str]:
    """Return (access_token, updated_secrets_blob)."""
    data = unpack_webcake_secrets(secrets_blob)
    access = str(data.get("access_token") or "").strip()
    refresh = str(data.get("refresh_token") or "").strip()
    expires_at = str(data.get("expires_at") or "")

    need_refresh = force_refresh or not access
    if not need_refresh and not expires_at and access:
        return access, secrets_blob
    if not need_refresh and expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            need_refresh = datetime.now(timezone.utc) >= exp
        except ValueError:
            need_refresh = True

    if not need_refresh and access:
        return access, secrets_blob

    if not refresh:
        if access:
            return access, secrets_blob
        raise ValueError("Thiếu Refresh Token để làm mới Access Token.")

    result = refresh_access_token(refresh)
    if not result.get("ok"):
        raise ValueError(str(result.get("message") or "Không làm mới được access token."))
    new_blob = pack_webcake_secrets(
        access_token=str(result["access_token"]),
        refresh_token=str(result.get("refresh_token") or refresh),
        expires_at=str(result.get("expires_at") or _expires_default()),
    )
    return str(result["access_token"]), new_blob


def _api_request(
    path: str,
    access_token: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    timeout: float = 25,
) -> requests.Response:
    p = path if path.startswith("/") else f"/{path}"
    url = f"{api_base_url()}{p}"
    headers = {
        "X-Storecake-Access-Token": str(access_token or "").strip(),
        "Accept": "application/json",
        "User-Agent": "digiseo-Tool/1.0",
    }
    return requests.request(method, url, headers=headers, params=params or {}, timeout=timeout)


def _extract_list(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        node = payload.get(key)
        if isinstance(node, list):
            return node
        if isinstance(node, dict):
            inner = node.get("data")
            if isinstance(inner, list):
                return inner
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            inner = data.get(key)
            if isinstance(inner, list):
                return inner
            if isinstance(inner, dict) and isinstance(inner.get("data"), list):
                return inner["data"]
    return []


def _count_categories(access_token: str, path: str) -> int:
    try:
        r = _api_request(path, access_token, params={"page": 1, "limit": 250})
    except requests.RequestException:
        return 0
    if r.status_code >= 400:
        return 0
    try:
        payload = r.json()
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("success") is False:
        return 0
    key = "categories" if "category" in path else "categories"
    items = _extract_list(payload, key, "data")
    total = 0
    for block_key in ("categories", "products"):
        block = payload.get(block_key)
        if isinstance(block, dict) and isinstance(block.get("total_entries"), int):
            total = max(total, int(block["total_entries"]))
    return total or len(items)


def test_webcake_connection(
    *,
    site_url: str = "",
    access_token: str = "",
    refresh_token: str = "",
    secrets_blob: str = "",
) -> dict[str, Any]:
    _ = normalize_site_url(site_url)
    access = str(access_token or "").strip()
    refresh = str(refresh_token or "").strip()
    blob = secrets_blob
    if not access and not refresh and blob:
        data = unpack_webcake_secrets(blob)
        access = str(data.get("access_token") or "").strip()
        refresh = str(data.get("refresh_token") or "").strip()
    if access and refresh and not blob:
        blob = pack_webcake_secrets(
            access_token=access,
            refresh_token=refresh,
            expires_at=_expires_default(),
        )
    try:
        token, blob = ensure_access_token(blob or pack_webcake_secrets(access_token=access, refresh_token=refresh))
    except ValueError as exc:
        if access and not refresh:
            token = access
            blob = pack_webcake_secrets(access_token=access, refresh_token="", expires_at="")
        else:
            return {"verified": False, "message": str(exc)}

    try:
        r = _api_request("/blog/category/all", token, params={"page": 1, "limit": 1})
    except requests.RequestException as exc:
        return {"verified": False, "message": f"Không gọi được Webcake API: {exc}"}
    if r.status_code == 401 and refresh:
        try:
            token, blob = ensure_access_token(blob, force_refresh=True)
            r = _api_request("/blog/category/all", token, params={"page": 1, "limit": 1})
        except ValueError as exc:
            return {"verified": False, "message": str(exc)}
    if r.status_code >= 400:
        return {
            "verified": False,
            "message": f"Webcake API HTTP {r.status_code}. {(r.text or '')[:180]}",
        }
    return {
        "verified": True,
        "message": "Kết nối Webcake thành công.",
        "secrets_blob": blob,
    }


def sync_webcake_categories(*, secrets_blob: str) -> tuple[int | None, str]:
    try:
        token, _ = ensure_access_token(secrets_blob)
    except ValueError as exc:
        return None, str(exc)
    blog_n = _count_categories(token, "/blog/category/all")
    prod_n = _count_categories(token, "/product/category/all")
    total = blog_n + prod_n
    return total, f"Đã đồng bộ: {blog_n} blog + {prod_n} product categories ({total} tổng)."
