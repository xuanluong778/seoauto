from datetime import datetime, timedelta, timezone
import os

import bcrypt
from jose import JWTError, jwt


SECRET_KEY = (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "change-this-in-production").strip()
ALGORITHM = "HS256"


def access_token_expire_hours() -> int:
    raw = (os.getenv("JWT_EXPIRE_HOURS") or os.getenv("ACCESS_TOKEN_EXPIRE_HOURS") or "720").strip()
    try:
        return max(1, min(8760, int(raw)))
    except ValueError:
        return 720


def access_token_max_age_seconds() -> int:
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
    if expires_hours is None:
        expires_hours = access_token_expire_hours()
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload = {"user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


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
