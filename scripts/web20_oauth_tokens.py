"""OAuth token refresh for Web 2.0 Blogger / Tumblr."""

from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import HTTPException

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.social_auto_web20_store import update_account


def _blogger_client_id() -> str:
    return str(os.getenv("BLOGGER_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _blogger_client_secret() -> str:
    return str(os.getenv("BLOGGER_GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def _tumblr_client_id() -> str:
    return str(os.getenv("TUMBLR_CLIENT_ID") or os.getenv("TUMBLR_CONSUMER_KEY") or "").strip()


def _tumblr_client_secret() -> str:
    return str(os.getenv("TUMBLR_CLIENT_SECRET") or os.getenv("TUMBLR_CONSUMER_SECRET") or "").strip()


def refresh_blogger_token(refresh_token: str) -> dict[str, str]:
    if not refresh_token or refresh_token == "mock_blogger_refresh":
        return {"access_token": "mock_blogger_token", "refresh_token": refresh_token}
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": _blogger_client_id(),
            "client_secret": _blogger_client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=45,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Blogger refresh token: {(r.text or '')[:300]}")
    data = r.json()
    out = {"access_token": str(data.get("access_token") or "")}
    if data.get("refresh_token"):
        out["refresh_token"] = str(data["refresh_token"])
    return out


def refresh_tumblr_token(refresh_token: str) -> dict[str, str]:
    if not refresh_token or refresh_token == "mock_tumblr_refresh":
        return {"access_token": "mock_tumblr_token", "refresh_token": refresh_token}
    r = requests.post(
        "https://api.tumblr.com/v2/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _tumblr_client_id(),
            "client_secret": _tumblr_client_secret(),
        },
        timeout=45,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Tumblr refresh token: {(r.text or '')[:300]}")
    data = r.json()
    out = {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or refresh_token),
    }
    return out


def ensure_fresh_oauth_secrets(
    account: dict[str, Any],
    secrets: dict[str, Any],
    *,
    user_id: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Refresh OAuth access token if needed; persist encrypted tokens to store."""
    platform = str(account.get("platform") or secrets.get("platform") or "")
    if platform not in {"blogger", "tumblr"}:
        return secrets
    access = str(secrets.get("access_token") or "")
    refresh = str(secrets.get("refresh_token") or "")
    if access.startswith("mock_") and not force_refresh:
        return secrets
    if not refresh and not force_refresh:
        return secrets
    try:
        if platform == "blogger":
            tokens = refresh_blogger_token(refresh)
        else:
            tokens = refresh_tumblr_token(refresh)
    except HTTPException:
        if not force_refresh:
            raise
        return secrets
    new_access = tokens.get("access_token") or access
    new_refresh = tokens.get("refresh_token") or refresh
    patch: dict[str, Any] = {"access_token": new_access}
    if new_refresh != refresh:
        patch["refresh_token"] = new_refresh
    update_account(str(account.get("id") or ""), user_id, patch)
    updated = dict(secrets)
    updated["access_token"] = new_access
    updated["refresh_token"] = new_refresh
    return updated
