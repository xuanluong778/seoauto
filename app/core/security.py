from datetime import datetime, timedelta, timezone
import logging
import os
import re

import bcrypt
from jose import JWTError, jwt

_LOG = logging.getLogger(__name__)

_DEFAULT_DEV_SECRET = "change-this-in-production"
_WEAK_SECRET_MARKERS = frozenset(
    {
        "change-this-in-production",
        "changeme",
        "secret",
        "jwt-secret",
        "your-secret-key",
        "dev-secret",
    }
)


def _resolve_secret_key() -> str:
    return (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or _DEFAULT_DEV_SECRET).strip()


SECRET_KEY = _resolve_secret_key()
ALGORITHM = "HS256"


def validate_jwt_secret_at_startup(*, production: bool) -> None:
    """Reject weak/default JWT secrets in production; never log secret values."""
    secret = _resolve_secret_key()
    if not secret:
        raise RuntimeError("JWT_SECRET is required in production.")
    lowered = secret.lower()
    if len(secret) < 32:
        msg = "JWT_SECRET is too short for production (minimum 32 characters)."
        if production:
            raise RuntimeError(msg)
        _LOG.warning("%s Set JWT_SECRET in env.local before deploy.", msg)
        return
    if lowered in _WEAK_SECRET_MARKERS or lowered.startswith("change-this"):
        msg = "JWT_SECRET uses a known weak/default value."
        if production:
            raise RuntimeError(msg)
        _LOG.warning("%s Set a strong random JWT_SECRET before deploy.", msg)
        return
    if production and not re.search(r"[A-Za-z]", secret):
        raise RuntimeError("JWT_SECRET must include letters and be cryptographically random.")


def access_token_expire_hours() -> int:
    from app.services.session_auth_rollout import server_sessions_enabled

    if server_sessions_enabled():
        return max(1, (access_token_expire_minutes() + 59) // 60)
    raw = (os.getenv("JWT_EXPIRE_HOURS") or os.getenv("ACCESS_TOKEN_EXPIRE_HOURS") or "720").strip()
    try:
        return max(1, min(8760, int(raw)))
    except ValueError:
        return 720


def access_token_expire_minutes() -> int:
    from app.services.session_auth_rollout import jwt_access_expire_minutes, server_sessions_enabled

    if server_sessions_enabled():
        return jwt_access_expire_minutes()
    return access_token_expire_hours() * 60


def access_token_max_age_seconds() -> int:
    from app.services.session_auth_rollout import server_sessions_enabled

    if server_sessions_enabled():
        return access_token_expire_minutes() * 60
    return access_token_expire_hours() * 3600


ACCESS_TOKEN_EXPIRE_HOURS = access_token_expire_hours()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, expires_hours: int | None = None) -> str:
    """Legacy long-lived user JWT — blocked when SERVER_SESSIONS + JWT_BLOCK_LEGACY_USER."""
    if expires_hours is None:
        expires_hours = access_token_expire_hours()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=expires_hours)
    payload = {
        "user_id": user_id,
        "exp": expire,
        "iat": now,
        "typ": "legacy_user",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_service_access_token(user_id: int, *, expires_hours: int | None = None) -> str:
    """Internal load-test / cron user impersonation — typ=service, no session row."""
    if expires_hours is None:
        raw = (os.getenv("JWT_SERVICE_TOKEN_HOURS") or "24").strip()
        try:
            expires_hours = max(1, min(168, int(raw)))
        except ValueError:
            expires_hours = 24
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=int(expires_hours))
    payload = {
        "user_id": int(user_id),
        "typ": "service",
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def is_service_token_payload(payload: dict) -> bool:
    return str(payload.get("typ") or "").strip().lower() == "service"


def is_session_token_payload(payload: dict) -> bool:
    sid = str(payload.get("sid") or "").strip()
    jti = str(payload.get("jti") or "").strip()
    return bool(sid and jti)


def create_session_access_token(
    *,
    user_id: int,
    session_id: str,
    jti: str,
    expires_minutes: int | None = None,
) -> str:
    if expires_minutes is None:
        expires_minutes = access_token_expire_minutes()
    expire = datetime.now(timezone.utc) + timedelta(minutes=int(expires_minutes))
    payload = {
        "user_id": int(user_id),
        "sid": str(session_id),
        "jti": str(jti),
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    secrets: list[str] = []
    primary = (SECRET_KEY or "").strip()
    if primary:
        secrets.append(primary)
    prev = (os.getenv("JWT_SECRET_PREVIOUS") or "").strip()
    if prev and prev not in secrets:
        secrets.append(prev)
    last_exc: Exception | None = None
    for secret in secrets:
        try:
            return jwt.decode(token, secret, algorithms=[ALGORITHM])
        except JWTError as exc:
            last_exc = exc
            continue
    raise ValueError("Invalid token") from last_exc


def create_google_oauth_state(user_id: int) -> str:
    """State chống CSRF cho luồng OAuth Google (GSC + GA)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"google_oauth": True, "user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_google_oauth_state(state: str) -> int:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid oauth state") from exc
    if not data.get("google_oauth"):
        raise ValueError("Invalid oauth state")
    return int(data["user_id"])


def create_facebook_oauth_state(user_id: int) -> str:
    """State chống CSRF cho luồng OAuth Facebook Fanpage."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"facebook_oauth": True, "user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_facebook_oauth_state(state: str) -> int:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid oauth state") from exc
    if not data.get("facebook_oauth"):
        raise ValueError("Invalid oauth state")
    return int(data["user_id"])


def create_cskh_facebook_oauth_state(user_id: int, bot_id: int) -> str:
    """State CSRF cho OAuth Facebook Fanpage (Chatbot CSKH) — gắn bot_id."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"cskh_facebook_oauth": True, "user_id": user_id, "bot_id": bot_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_cskh_facebook_oauth_state(state: str) -> tuple[int, int]:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid oauth state") from exc
    if not data.get("cskh_facebook_oauth"):
        raise ValueError("Invalid oauth state")
    return int(data["user_id"]), int(data["bot_id"])


def create_web20_oauth_state(user_id: int, platform: str) -> str:
    """State CSRF cho OAuth Web 2.0 (Blogger, Tumblr, …)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"web20_oauth": True, "user_id": user_id, "platform": str(platform or "").strip().lower(), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_web20_oauth_state(state: str) -> tuple[int, str]:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid oauth state") from exc
    if not data.get("web20_oauth"):
        raise ValueError("Invalid oauth state")
    return int(data["user_id"]), str(data.get("platform") or "")


def create_google_login_state() -> str:
    """State chống CSRF cho luồng đăng nhập Google."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"google_login": True, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def is_google_login_state(state: str) -> bool:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return False
    return bool(data.get("google_login"))


def create_gbp_oauth_state(user_id: int) -> str:
    """State CSRF cho OAuth Google Business Profile (Google Map SEO)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"gbp_oauth": True, "user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_gbp_oauth_state(state: str) -> int:
    try:
        data = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid oauth state") from exc
    if not data.get("gbp_oauth"):
        raise ValueError("Invalid oauth state")
    return int(data["user_id"])
