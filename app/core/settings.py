import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# Cùng thư mục gốc project với main.py / env.local
_ENV_LOCAL = Path(__file__).resolve().parents[2] / "env.local"


def refresh_env_local() -> None:
    """Đọc lại env.local — thay đổi file có hiệu lực không cần restart (reload .py không đọc lại .env).

    Dùng override=True: nếu GOOGLE_* đã tồn tại trong os.environ nhưng rỗng/sai, load_dotenv mặc định
    sẽ không ghi đè và server vẫn báo «chưa cấu hình» dù env.local đã đúng.
    """
    if _ENV_LOCAL.is_file():
        load_dotenv(_ENV_LOCAL, override=True)


def _smtp_password_raw() -> str:
    raw = os.getenv("SMTP_PASSWORD", "") or ""
    return raw.replace(" ", "").strip()


def get_smtp_settings() -> dict:
    refresh_env_local()
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        "user": os.getenv("SMTP_USER", ""),
        "password": _smtp_password_raw(),
        "from_email": os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USER", "")),
        "from_name": os.getenv("SMTP_FROM_NAME", "Seoauto"),
        "otp_length": int(os.getenv("OTP_LENGTH", "6")),
        "otp_expire_seconds": int(os.getenv("OTP_EXPIRE_SECONDS", "300")),
        "otp_subject": os.getenv("OTP_EMAIL_SUBJECT", "Mã OTP đăng nhập"),
    }


def get_google_oauth_settings() -> dict | None:
    """Client OAuth web (Google Cloud Console). Trả None nếu chưa cấu hình."""
    refresh_env_local()
    file_vals = dotenv_values(_ENV_LOCAL) if _ENV_LOCAL.is_file() else {}

    def pick(key: str) -> str:
        """Ưu tiên giá trị trong env.local (nguồn user chỉnh), sau đó os.environ."""
        if file_vals:
            raw = file_vals.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return (os.getenv(key) or "").strip()

    cid = pick("GOOGLE_CLIENT_ID")
    csec = pick("GOOGLE_CLIENT_SECRET")
    if not cid or not csec:
        return None
    base = (pick("APP_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    default_redirect = f"{base}/integrations/google/callback"
    redirect = (pick("GOOGLE_OAUTH_REDIRECT_URI") or default_redirect).strip()
    return {
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": redirect,
    }


# Search Console + GA4 (Data API / Admin) — readonly
GOOGLE_OAUTH_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
)


def google_oauth_client_config(redirect_uri: str) -> dict:
    """Cấu hình JSON cho google_auth_oauthlib.flow.Flow.from_client_config."""
    s = get_google_oauth_settings()
    if not s:
        raise RuntimeError("Google OAuth chưa cấu hình (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).")
    return {
        "web": {
            "client_id": s["client_id"],
            "client_secret": s["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        },
    }
