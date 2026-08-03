"""Shopify Admin API: client credentials token + connection test."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

SHOPIFY_API_VERSIONS = ("2025-01", "2024-10", "2024-07", "2024-04")
DEFAULT_API_VERSION = "2025-01"


def normalize_shop_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = f"https://{s}"
    try:
        u = urlparse(s)
        host = (u.netloc or u.path or "").lower().strip("/")
    except Exception:
        return ""
    if not host:
        return ""
    if not host.endswith(".myshopify.com"):
        if "." not in host:
            host = f"{host}.myshopify.com"
    return f"https://{host}".rstrip("/")


def pack_shopify_secrets(
    *,
    client_secret: str,
    api_version: str = DEFAULT_API_VERSION,
    access_token: str = "",
    expires_at: str = "",
) -> str:
    return json.dumps(
        {
            "v": 1,
            "client_secret": str(client_secret or ""),
            "api_version": str(api_version or DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION,
            "access_token": str(access_token or ""),
            "expires_at": str(expires_at or ""),
        },
        ensure_ascii=False,
    )


def unpack_shopify_secrets(blob: str) -> dict[str, Any]:
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
    # Legacy: plain Admin API access token (shpat_…)
    if raw.startswith("shpat_") or raw.startswith("shpua_"):
        return {"v": 0, "access_token": raw, "api_version": DEFAULT_API_VERSION, "client_secret": ""}
    return {"client_secret": raw, "api_version": DEFAULT_API_VERSION}


def mask_shopify_public(client_id: str, secrets_blob: str) -> dict[str, str]:
    data = unpack_shopify_secrets(secrets_blob)
    sec = str(data.get("client_secret") or "")
    tok = str(data.get("access_token") or "")
    if len(sec) <= 4:
        masked_sec = "•" * max(8, len(sec))
    else:
        masked_sec = sec[:3] + "•" * 12 + sec[-2:]
    if len(tok) <= 4:
        masked_tok = "•" * max(8, len(tok)) if tok else ""
    else:
        masked_tok = tok[:6] + "•" * 10 + tok[-3:]
    return {
        "client_id_masked": (client_id[:6] + "•" * 8) if len(client_id) > 6 else "•" * 8,
        "client_secret_masked": masked_sec,
        "access_token_masked": masked_tok,
        "api_version": str(data.get("api_version") or DEFAULT_API_VERSION),
    }


def fetch_client_credentials_token(
    *,
    shop_url: str,
    client_id: str,
    client_secret: str,
    timeout: float = 25,
) -> dict[str, Any]:
    base = normalize_shop_url(shop_url)
    cid = str(client_id or "").strip()
    secret = str(client_secret or "").strip()
    if not base:
        return {"ok": False, "message": "Store URL không hợp lệ."}
    if not cid or not secret:
        return {"ok": False, "message": "Thiếu Client ID hoặc Client Secret."}
    url = f"{base}/admin/oauth/access_token"
    try:
        r = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "digiseo-Tool/1.0",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "message": f"Không kết nối được Shopify: {exc}"}
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    if r.status_code >= 400 or not isinstance(data, dict):
        snippet = (r.text or "")[:200]
        return {
            "ok": False,
            "message": f"Shopify token HTTP {r.status_code}. {snippet}".strip(),
        }
    token = str(data.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "message": "Shopify không trả access_token — kiểm tra Client ID/Secret và quyền app."}
    expires_in = int(data.get("expires_in") or 86400)
    expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    return {
        "ok": True,
        "access_token": token,
        "expires_at": expires_at,
        "scope": str(data.get("scope") or ""),
    }


def ensure_access_token(
    *,
    shop_url: str,
    client_id: str,
    secrets_blob: str,
    force_refresh: bool = False,
) -> tuple[str, str, str]:
    """Return (access_token, api_version, updated_secrets_blob)."""
    data = unpack_shopify_secrets(secrets_blob)
    api_version = str(data.get("api_version") or DEFAULT_API_VERSION)
    token = str(data.get("access_token") or "").strip()
    expires_at = str(data.get("expires_at") or "")
    client_secret = str(data.get("client_secret") or secrets_blob or "").strip()

    need_refresh = force_refresh or not token
    if not need_refresh and expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            need_refresh = datetime.now(timezone.utc) >= exp
        except ValueError:
            need_refresh = True

    if not need_refresh and token:
        return token, api_version, secrets_blob

    if not client_secret and token:
        return token, api_version, secrets_blob

    result = fetch_client_credentials_token(
        shop_url=shop_url,
        client_id=client_id,
        client_secret=client_secret,
    )
    if not result.get("ok"):
        raise ValueError(str(result.get("message") or "Không lấy được access token."))
    new_blob = pack_shopify_secrets(
        client_secret=client_secret,
        api_version=api_version,
        access_token=str(result["access_token"]),
        expires_at=str(result.get("expires_at") or ""),
    )
    return str(result["access_token"]), api_version, new_blob


def _admin_request(
    *,
    shop_url: str,
    access_token: str,
    api_version: str,
    path: str,
    method: str = "GET",
    timeout: float = 25,
) -> requests.Response:
    base = normalize_shop_url(shop_url)
    ver = str(api_version or DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    p = path if path.startswith("/") else f"/{path}"
    url = f"{base}/admin/api/{ver}{p}"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Accept": "application/json",
        "User-Agent": "digiseo-Tool/1.0",
    }
    return requests.request(method, url, headers=headers, timeout=timeout)


def test_shopify_connection(
    *,
    shop_url: str,
    client_id: str,
    client_secret: str,
    api_version: str = DEFAULT_API_VERSION,
    secrets_blob: str = "",
) -> dict[str, Any]:
    ver = str(api_version or DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    token = ""
    expires_at = ""
    sec = str(client_secret or "").strip()
    if not sec:
        data = unpack_shopify_secrets(secrets_blob)
        sec = str(data.get("client_secret") or "").strip()
    try:
        if sec:
            tok_res = fetch_client_credentials_token(
                shop_url=shop_url,
                client_id=client_id,
                client_secret=sec,
            )
            if not tok_res.get("ok"):
                return {"verified": False, "message": str(tok_res.get("message") or "Token failed.")}
            token = str(tok_res["access_token"])
            expires_at = str(tok_res.get("expires_at") or "")
        else:
            data = unpack_shopify_secrets(secrets_blob)
            token = str(data.get("access_token") or "").strip()
            ver = str(data.get("api_version") or ver)
            if not token:
                return {"verified": False, "message": "Thiếu Client Secret để lấy access token."}
    except ValueError as exc:
        return {"verified": False, "message": str(exc)}

    try:
        r = _admin_request(
            shop_url=shop_url,
            access_token=token,
            api_version=ver,
            path="/shop.json",
        )
    except requests.RequestException as exc:
        return {"verified": False, "message": f"Không gọi được Shopify API: {exc}"}
    if r.status_code >= 400:
        return {
            "verified": False,
            "message": f"Shopify API HTTP {r.status_code}. {(r.text or '')[:180]}",
        }
    shop_name = ""
    try:
        payload = r.json()
        shop_name = str((payload.get("shop") or {}).get("name") or "")
    except ValueError:
        pass
    msg = "Kết nối Shopify thành công."
    if shop_name:
        msg += f" ({shop_name})"
    return {
        "verified": True,
        "message": msg,
        "access_token": token,
        "api_version": ver,
        "secrets_blob": pack_shopify_secrets(
            client_secret=sec,
            api_version=ver,
            access_token=token,
            expires_at=expires_at,
        ),
    }


def sync_shopify_blogs(
    *,
    shop_url: str,
    client_id: str,
    secrets_blob: str,
) -> tuple[int | None, str]:
    try:
        token, ver, _ = ensure_access_token(
            shop_url=shop_url,
            client_id=client_id,
            secrets_blob=secrets_blob,
        )
    except ValueError as exc:
        return None, str(exc)
    try:
        r = _admin_request(
            shop_url=shop_url,
            access_token=token,
            api_version=ver,
            path="/blogs.json?limit=250",
        )
    except requests.RequestException as exc:
        return None, f"Không gọi được Shopify: {exc}"
    if r.status_code >= 400:
        return None, f"Shopify blogs HTTP {r.status_code}. {(r.text or '')[:160]}"
    try:
        blogs = r.json().get("blogs") or []
    except (ValueError, AttributeError):
        blogs = []
    if not isinstance(blogs, list):
        blogs = []
    return len(blogs), f"Đã đồng bộ: {len(blogs)} blog trên Shopify."
