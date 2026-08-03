"""Google Business Profile OAuth — cấu hình tách khỏi GSC / đăng nhập Google."""

from __future__ import annotations

import os

from app.core.settings import _ENV_LOCAL, refresh_env_local
from dotenv import dotenv_values

# Quản lý hồ sơ Google Business (Business Profile API)
GBP_OAUTH_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/business.manage",
)

# APIs bắt buộc trên Google Cloud Console (cùng project với OAuth Client ID)
GBP_REQUIRED_APIS: tuple[dict[str, str], ...] = (
    {
        "id": "mybusinessaccountmanagement.googleapis.com",
        "label": "My Business Account Management API",
        "url": "https://console.cloud.google.com/apis/library/mybusinessaccountmanagement.googleapis.com",
    },
    {
        "id": "mybusinessbusinessinformation.googleapis.com",
        "label": "My Business Business Information API",
        "url": "https://console.cloud.google.com/apis/library/mybusinessbusinessinformation.googleapis.com",
    },
    {
        "id": "mybusiness.googleapis.com",
        "label": "Google My Business API (Reviews)",
        "url": "https://console.cloud.google.com/apis/library/mybusiness.googleapis.com",
    },
)


def gbp_api_setup_links() -> list[dict[str, str]]:
    return [{"id": x["id"], "label": x["label"], "url": x["url"]} for x in GBP_REQUIRED_APIS]


def get_gbp_oauth_settings() -> dict | None:
    """Dùng chung GOOGLE_CLIENT_ID/SECRET; redirect URI riêng cho GBP."""
    refresh_env_local()
    file_vals = dotenv_values(_ENV_LOCAL) if _ENV_LOCAL.is_file() else {}

    def pick(key: str) -> str:
        if file_vals:
            raw = file_vals.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return (os.getenv(key) or "").strip()

    cid = pick("GBP_GOOGLE_CLIENT_ID") or pick("GOOGLE_CLIENT_ID")
    csec = pick("GBP_GOOGLE_CLIENT_SECRET") or pick("GOOGLE_CLIENT_SECRET")
    if not cid or not csec:
        return None
    base = (pick("APP_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    default_redirect = f"{base}/api/google-map-seo/oauth/callback"
    redirect = (pick("GBP_OAUTH_REDIRECT_URI") or default_redirect).strip()
    return {
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": redirect,
    }


def gbp_oauth_client_config(redirect_uri: str) -> dict:
    s = get_gbp_oauth_settings()
    if not s:
        raise RuntimeError("Google Business Profile OAuth chưa cấu hình.")
    return {
        "web": {
            "client_id": s["client_id"],
            "client_secret": s["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        },
    }
