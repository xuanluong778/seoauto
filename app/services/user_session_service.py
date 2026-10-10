"""Server-side user sessions: create, refresh rotation, revoke."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_session_access_token
from app.models.user import User
from app.models.user_session import UserSession
from app.services.rbac import normalize_role
from app.services.session_auth_rollout import jwt_access_expire_minutes, refresh_token_expire_days
from app.services.trusted_proxy import resolve_client_ip

_LOG = logging.getLogger(__name__)


@dataclass
class AuthSessionTokens:
    access_token: str
    refresh_token: str
    session_id: str
    expires_in: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _client_meta(request: Request | None) -> tuple[str, str]:
    if request is None:
        return "", ""
    ua = (request.headers.get("user-agent") or "")[:512]
    ip = resolve_client_ip(request)[:64]
    return ua, ip


def _session_active(row: UserSession | None) -> bool:
    if row is None:
        return False
    if row.revoked_at is not None:
        return False
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > _utcnow()


def create_user_session(
    db: Session,
    *,
    user: User,
    request: Request | None = None,
) -> AuthSessionTokens:
    session_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    refresh_plain = _new_refresh_token()
    ua, ip = _client_meta(request)
    expires_at = _utcnow() + timedelta(days=refresh_token_expire_days())
    row = UserSession(
        id=session_id,
        user_id=int(user.id),
        family_id=family_id,
        refresh_token_hash=_hash_refresh(refresh_plain),
        jti=jti,
        expires_at=expires_at,
        user_agent=ua or None,
        ip_address=ip or None,
        role_snapshot=normalize_role(getattr(user, "role", None)),
        last_used_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    minutes = jwt_access_expire_minutes()
    access = create_session_access_token(
        user_id=int(user.id),
        session_id=session_id,
        jti=jti,
        expires_minutes=minutes,
    )
    return AuthSessionTokens(
        access_token=access,
        refresh_token=refresh_plain,
        session_id=session_id,
        expires_in=minutes * 60,
    )


def validate_session_claims(db: Session, *, user_id: int, session_id: str, jti: str) -> None:
    row = (
        db.query(UserSession)
        .filter(
            UserSession.id == str(session_id),
            UserSession.user_id == int(user_id),
            UserSession.jti == str(jti),
        )
        .first()
    )
    if not _session_active(row):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    current_role = normalize_role(getattr(user, "role", None))
    snap = normalize_role(getattr(row, "role_snapshot", None) or current_role)
    if snap != current_role:
        revoke_session(db, session_id=str(session_id), reason="role_changed")
        db.flush()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    # Throttle last_used_at writes: parallel F5/API requests otherwise lock the
    # same session row and wait until statement_timeout (~30s) → page feels hung.
    now = _utcnow()
    prev = row.last_used_at
    if prev is not None:
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        if (now - prev).total_seconds() < 300:
            return
    try:
        with db.begin_nested():
            # Fail fast if another request holds the row — never block auth for 30s.
            db.execute(text("SET LOCAL lock_timeout = '50ms'"))
            row.last_used_at = now
            db.flush()
    except Exception:
        _LOG.warning("session last_used_at update skipped sid=%s", session_id, exc_info=True)


def refresh_user_session(
    db: Session,
    *,
    refresh_token: str,
    request: Request | None = None,
) -> AuthSessionTokens:
    token = (refresh_token or "").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    token_hash = _hash_refresh(token)
    row = db.query(UserSession).filter(UserSession.refresh_token_hash == token_hash).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if row.revoked_at is not None:
        # Concurrent refresh race: first request already rotated; do NOT revoke the
        # whole family (that forces sudden logout for the successful tab).
        revoked_at = row.revoked_at
        if revoked_at.tzinfo is None:
            revoked_at = revoked_at.replace(tzinfo=timezone.utc)
        grace = (_utcnow() - revoked_at).total_seconds()
        reason = str(row.revoke_reason or "")
        if reason == "rotated" and 0 <= grace <= 45:
            successor = (
                db.query(UserSession)
                .filter(
                    UserSession.family_id == str(row.family_id),
                    UserSession.user_id == int(row.user_id),
                    UserSession.revoked_at.is_(None),
                )
                .order_by(UserSession.last_used_at.desc())
                .first()
            )
            if successor is not None and _session_active(successor):
                user = db.query(User).filter(User.id == int(successor.user_id)).first()
                if user is not None:
                    from app.services.auth import _raise_if_user_blocked

                    _raise_if_user_blocked(user)
                    minutes = jwt_access_expire_minutes()
                    access = create_session_access_token(
                        user_id=int(user.id),
                        session_id=str(successor.id),
                        jti=str(successor.jti),
                        expires_minutes=minutes,
                    )
                    successor.last_used_at = _utcnow()
                    db.commit()
                    # refresh_token empty → caller must not overwrite seo_refresh cookie
                    return AuthSessionTokens(
                        access_token=access,
                        refresh_token="",
                        session_id=str(successor.id),
                        expires_in=minutes * 60,
                    )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        _revoke_family(db, family_id=str(row.family_id), reason="refresh_reuse")
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= _utcnow():
        revoke_session(db, session_id=str(row.id), reason="expired")
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.query(User).filter(User.id == int(row.user_id)).first()
    if not user:
        revoke_session(db, session_id=str(row.id), reason="user_missing")
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    from app.services.auth import _raise_if_user_blocked

    _raise_if_user_blocked(user)

    # Rotate: revoke current refresh, issue new session in same family
    revoke_session(db, session_id=str(row.id), reason="rotated")
    ua, ip = _client_meta(request)
    session_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    refresh_plain = _new_refresh_token()
    expires_at = _utcnow() + timedelta(days=refresh_token_expire_days())
    new_row = UserSession(
        id=session_id,
        user_id=int(user.id),
        family_id=str(row.family_id),
        refresh_token_hash=_hash_refresh(refresh_plain),
        jti=jti,
        expires_at=expires_at,
        user_agent=ua or row.user_agent,
        ip_address=ip or row.ip_address,
        role_snapshot=normalize_role(getattr(user, "role", None)),
        last_used_at=_utcnow(),
    )
    db.add(new_row)
    db.flush()
    minutes = jwt_access_expire_minutes()
    access = create_session_access_token(
        user_id=int(user.id),
        session_id=session_id,
        jti=jti,
        expires_minutes=minutes,
    )
    db.commit()
    return AuthSessionTokens(
        access_token=access,
        refresh_token=refresh_plain,
        session_id=session_id,
        expires_in=minutes * 60,
    )


def revoke_session(db: Session, *, session_id: str, reason: str = "logout") -> bool:
    row = db.query(UserSession).filter(UserSession.id == str(session_id)).first()
    if not row or row.revoked_at is not None:
        return False
    row.revoked_at = _utcnow()
    row.revoke_reason = str(reason or "logout")[:64]
    db.flush()
    return True


def revoke_session_by_access_token(db: Session, access_token: str, *, reason: str = "logout") -> bool:
    from app.core.security import decode_access_token

    try:
        payload = decode_access_token(access_token)
    except ValueError:
        return False
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        return False
    return revoke_session(db, session_id=sid, reason=reason)


def revoke_all_user_sessions(
    db: Session,
    *,
    user_id: int,
    except_session_id: str | None = None,
    reason: str = "revoke_all",
) -> int:
    now = _utcnow()
    q = db.query(UserSession).filter(
        UserSession.user_id == int(user_id),
        UserSession.revoked_at.is_(None),
    )
    if except_session_id:
        q = q.filter(UserSession.id != str(except_session_id))
    rows = q.all()
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = str(reason or "revoke_all")[:64]
    db.flush()
    return len(rows)


def _revoke_family(db: Session, *, family_id: str, reason: str) -> int:
    now = _utcnow()
    rows = (
        db.query(UserSession)
        .filter(
            UserSession.family_id == str(family_id),
            UserSession.revoked_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = str(reason)[:64]
    db.flush()
    return len(rows)


def change_user_password_and_revoke_sessions(
    db: Session,
    *,
    user: User,
    new_password: str,
    except_session_id: str | None = None,
) -> None:
    from app.core.security import hash_password

    user.password_hash = hash_password(new_password)
    user.has_password = True
    revoke_all_user_sessions(
        db,
        user_id=int(user.id),
        except_session_id=except_session_id,
        reason="password_change",
    )
    db.commit()
    db.refresh(user)


def tokens_to_response(tokens: AuthSessionTokens):
    from app.schemas.auth import TokenResponse

    return TokenResponse(
        access_token=tokens.access_token,
        token_type="bearer",
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )
