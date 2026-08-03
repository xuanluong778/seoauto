import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import HTTPException, status

from app.core.settings import get_smtp_settings


def send_otp_email(to_email: str, plain_body: str) -> None:
    cfg = get_smtp_settings()
    if not cfg["password"] or not cfg["user"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP chưa cấu hình (SMTP_USER / SMTP_PASSWORD trong env.local).",
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = cfg["otp_subject"]
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_email"], [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        hint = (
            " Gmail: bật xác minh 2 bước và dùng «Mật khẩu ứng dụng» 16 ký tự (không phải mật khẩu web). "
            "Sửa SMTP_PASSWORD trong env.local rồi khởi động lại run.bat."
        )
        err = exc.smtp_error.decode(errors="replace") if exc.smtp_error else str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SMTP từ chối đăng nhập ({exc.smtp_code}): {err}.{hint}",
        ) from exc
    except smtplib.SMTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gửi email thất bại: {exc}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Không kết nối được SMTP ({cfg['host']}:{cfg['port']}): {exc}. "
                "Kiểm tra mạng, tường lửa, antivirus chặn cổng 587."
            ),
        ) from exc
