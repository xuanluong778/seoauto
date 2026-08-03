import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import SECRET_KEY, create_access_token, hash_password
from app.core.settings import get_smtp_settings
from app.models.otp_login import OtpLogin
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services.mail_smtp import send_otp_email


def _hash_otp(email: str, code: str) -> str:
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{email.lower().strip()}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _random_digits(length: int) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _expires_at_utc(dt: datetime) -> datetime:
    """SQLite trả datetime timezone-naive; coi là UTC để so sánh an toàn với now(UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_gmail_for_otp(email_norm: str) -> None:
    """Chỉ Gmail thật (nhận được thư qua SMTP) — @gmail.com / @googlemail.com."""
    allowed = ("@gmail.com", "@googlemail.com")
    if not any(email_norm.endswith(s) for s in allowed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ Gmail (@gmail.com hoặc @googlemail.com) để nhận mã OTP.",
        )


def validate_otp_for_register(email_norm: str, raw_otp: str, db: Session) -> OtpLogin:
    """OTP còn hiệu lực, khớp mã, chưa dùng. Không đánh dấu used tại đây."""
    code = raw_otp.strip().replace(" ", "")
    if len(code) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã OTP không hợp lệ.",
        )
    row = (
        db.query(OtpLogin)
        .filter(
            OtpLogin.email == email_norm,
            OtpLogin.used.is_(False),
        )
        .order_by(OtpLogin.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chưa có mã OTP hợp lệ. Bấm «Nhận mã OTP» và kiểm tra Gmail (cả thư mục spam).",
        )
    if datetime.now(timezone.utc) > _expires_at_utc(row.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP đã hết hạn. Gửi lại mã.")
    if not hmac.compare_digest(row.code_hash, _hash_otp(email_norm, code)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mã OTP không đúng.")
    return row


def send_login_otp(email: str, db: Session) -> None:
    from app.services.admin_auth import skips_otp_for_user

    email_norm = email.lower().strip()
    user = db.query(User).filter(User.email == email_norm).first()
    if skips_otp_for_user(user, email_norm):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tài khoản admin chỉ cần email và mật khẩu — không dùng OTP.",
        )
    assert_gmail_for_otp(email_norm)
    cfg = get_smtp_settings()
    otp_len = max(4, min(cfg["otp_length"], 10))
    expire_sec = max(60, min(cfg["otp_expire_seconds"], 3600))

    user = db.query(User).filter(User.email == email_norm).first()
    if not user:
        user = User(
            email=email_norm,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            has_password=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    db.query(OtpLogin).filter(OtpLogin.email == email_norm).delete(synchronize_session=False)
    db.commit()

    code = _random_digits(otp_len)
    code_hash = _hash_otp(email_norm, code)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expire_sec)

    row = OtpLogin(email=email_norm, code_hash=code_hash, expires_at=expires_at, used=False)
    db.add(row)
    db.commit()

    body = (
        f"Mã OTP đăng nhập của bạn: {code}\n\n"
        f"Mã có hiệu lực trong {expire_sec // 60} phút.\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này."
    )
    send_otp_email(email_norm, body)


def verify_login_otp(email: str, code: str, db: Session) -> TokenResponse:
    email_norm = email.lower().strip()
    code = code.strip().replace(" ", "")

    row = (
        db.query(OtpLogin)
        .filter(
            OtpLogin.email == email_norm,
            OtpLogin.used.is_(False),
        )
        .order_by(OtpLogin.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không có OTP hợp lệ. Gửi lại mã.")

    if datetime.now(timezone.utc) > _expires_at_utc(row.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP đã hết hạn.")

    if not hmac.compare_digest(row.code_hash, _hash_otp(email_norm, code)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OTP không đúng.")

    user = db.query(User).filter(User.email == email_norm).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    row.used = True
    db.commit()

    token = create_access_token(user_id=user.id)
    return TokenResponse(access_token=token, token_type="bearer")
