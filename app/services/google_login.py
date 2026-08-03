"""Đăng nhập / đăng ký bằng Google OAuth (openid + email)."""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import Request
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.settings import get_google_oauth_settings, google_oauth_client_config
from app.models.user import User
from app.services.admin_auth import ensure_admin_user_fields, is_configured_admin_email
from app.services.auth import _raise_if_user_blocked
from app.services.credits import apply_signup_bonus_if_configured

_LOG = logging.getLogger(__name__)

GOOGLE_LOGIN_SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)

# Server → Google API có thể chậm (30–60s); timeout ngắn gây lỗi đăng nhập giả.
_GOOGLE_HTTP_TIMEOUT = (15, 90)


def oauth_redirect_uri() -> str:
    s = get_google_oauth_settings()
    if not s:
        raise RuntimeError("Google OAuth chưa cấu hình.")
    return s["redirect_uri"]


def build_google_login_flow(redirect_uri: str) -> Flow:
    client_cfg = google_oauth_client_config(redirect_uri)
    flow = Flow.from_client_config(
        client_cfg,
        scopes=list(GOOGLE_LOGIN_SCOPES),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    return flow


def _public_callback_url(request: Request) -> str:
    """URL callback công khai (https) — cần khớp redirect_uri đã đăng ký với Google."""
    url = str(request.url)
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip()
    if proto == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


def _parse_auth_code(request: Request) -> str:
    parsed = urlparse(_public_callback_url(request))
    code = (parse_qs(parsed.query).get("code") or [""])[0].strip()
    if not code:
        raise ValueError("Thiếu authorization code từ Google.")
    return code


def exchange_login_code(request: Request, redirect_uri: str) -> dict:
    """Đổi authorization code lấy token JSON từ Google (POST trực tiếp, timeout dài)."""
    settings = get_google_oauth_settings()
    if not settings:
        raise RuntimeError("Google OAuth chưa cấu hình.")
    code = _parse_auth_code(request)
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=_GOOGLE_HTTP_TIMEOUT,
    )
    if resp.status_code >= 400:
        _LOG.warning("Google token exchange HTTP %s: %s", resp.status_code, (resp.text or "")[:300])
        resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not data.get("access_token"):
        raise ValueError("Google không trả access_token.")
    return data


def _email_from_id_token(id_token: str, client_id: str) -> str | None:
    """Lấy email từ id_token — tránh gọi userinfo (thêm 1 round-trip chậm)."""
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport.requests import Request

        info = google_id_token.verify_oauth2_token(id_token, Request(), client_id)
        email = (info.get("email") or "").strip().lower()
        return email or None
    except Exception:
        pass
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return None
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(pad))
        email = (payload.get("email") or "").strip().lower()
        return email or None
    except Exception:
        return None


def email_from_login_tokens(token_data: dict) -> str:
    settings = get_google_oauth_settings()
    client_id = (settings or {}).get("client_id") or ""
    id_tok = str(token_data.get("id_token") or "").strip()
    if id_tok and client_id:
        email = _email_from_id_token(id_tok, client_id)
        if email:
            return email
    access = str(token_data.get("access_token") or "").strip()
    if access:
        return fetch_google_email(access)
    raise ValueError("Google không trả về email.")


def fetch_google_email(access_token: str) -> str:
    resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_GOOGLE_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google không trả về email.")
    if data.get("verified_email") is False:
        raise ValueError("Email Google chưa được xác minh.")
    return email


def login_or_register_google_user(email: str, db: Session) -> tuple[User, bool]:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        _raise_if_user_blocked(user)
        if is_configured_admin_email(email):
            ensure_admin_user_fields(user)
            db.commit()
            db.refresh(user)
        return user, False

    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        has_password=True,
        api_access_enabled=False,
        use_admin_api_pool=False,
    )
    if is_configured_admin_email(email):
        ensure_admin_user_fields(user)
    db.add(user)
    db.flush()
    apply_signup_bonus_if_configured(db, user)
    db.commit()
    db.refresh(user)
    return user, True


def issue_login_token(user: User) -> str:
    return create_access_token(user_id=user.id)
