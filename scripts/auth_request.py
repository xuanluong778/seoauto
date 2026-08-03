"""Resolve JWT user from HTTP request (Bearer header or seo_token cookie)."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth import user_from_token


def token_from_request(request: Request) -> str | None:
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        t = auth[7:].strip()
        if t:
            return t
    cookie = (request.cookies.get("seo_token") or "").strip()
    return cookie or None


def optional_user_from_request(request: Request, db: Session) -> User | None:
    token = token_from_request(request)
    if not token:
        return None
    try:
        return user_from_token(db, token)
    except HTTPException:
        return None
