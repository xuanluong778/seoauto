"""Outbound email: Resend first (production), SMTP fallback."""

from __future__ import annotations

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from fastapi import HTTPException, status

from app.core.settings import get_resend_settings, get_smtp_settings

_LOG = logging.getLogger(__name__)
_RESEND_URL = "https://api.resend.com/emails"
_RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}


def _mask_email(value: str) -> str:
    raw = str(value or "").strip()
    if "@" not in raw:
        return "***"
    local, _, domain = raw.partition("@")
    if not local:
        return "***@" + domain
    return local[0] + "***@" + domain


def _safe_status(exc: BaseException) -> str:
    return type(exc).__name__


def _resend_from_header() -> str:
    cfg = get_resend_settings()
    if cfg.get("from_email"):
        return str(cfg["from_email"])
    smtp = get_smtp_settings()
    addr = str(smtp.get("from_email") or "").strip()
    name = str(smtp.get("from_name") or "").strip()
    if addr and name:
        return f"{name} <{addr}>"
    return addr


def _send_via_resend(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str,
    idempotency_key: str,
) -> dict[str, Any]:
    cfg = get_resend_settings()
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("missing_resend_api_key")
    from_header = _resend_from_header()
    if not from_header:
        raise RuntimeError("missing_resend_from")
    timeout = int(cfg.get("timeout_seconds") or 15)
    retries = int(cfg.get("retry_count") or 3)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = str(idempotency_key)[:256]
    payload: dict[str, Any] = {
        "from": from_header,
        "to": [to],
        "subject": subject,
    }
    if html_body:
        payload["html"] = html_body
    if text_body:
        payload["text"] = text_body
    if "html" not in payload and "text" not in payload:
        payload["text"] = subject or " "

    last_error = "resend_failed"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(_RESEND_URL, json=payload, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = _safe_status(exc)
            _LOG.warning(
                "resend network error to=%s attempt=%s/%s err=%s",
                _mask_email(to),
                attempt,
                retries,
                last_error,
            )
            if attempt < retries:
                time.sleep(0.4 * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(f"resend_{last_error.lower()}") from exc
        if resp.status_code in _RETRY_STATUSES and attempt < retries:
            _LOG.warning(
                "resend retry to=%s status=%s attempt=%s/%s",
                _mask_email(to),
                resp.status_code,
                attempt,
                retries,
            )
            time.sleep(0.4 * (2 ** (attempt - 1)))
            continue
        if resp.status_code >= 300:
            _LOG.warning(
                "resend rejected to=%s status=%s",
                _mask_email(to),
                resp.status_code,
            )
            raise RuntimeError(f"resend_http_{resp.status_code}")
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        email_id = str(data.get("id") or "").strip()
        _LOG.info("resend sent to=%s email_id=%s", _mask_email(to), email_id or "-")
        out = {"ok": True, "provider": "resend", "email_id": email_id, "id": email_id}
        out.update({k: v for k, v in data.items() if k in {"id", "from", "to", "created_at"}})
        return out
    raise RuntimeError(last_error)


def _send_via_smtp(*, to: str, subject: str, text_body: str, html_body: str) -> dict[str, Any]:
    cfg = get_smtp_settings()
    if not cfg["password"] or not cfg["user"]:
        raise RuntimeError("missing_smtp_config")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg["To"] = to
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    if not text_body and not html_body:
        msg.attach(MIMEText(subject or " ", "plain", "utf-8"))
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_email"], [to], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        _LOG.warning("smtp auth failed host=%s", cfg["host"])
        raise RuntimeError("smtp_auth_failed") from exc
    except (smtplib.SMTPException, OSError) as exc:
        _LOG.warning("smtp send failed to=%s err=%s", _mask_email(to), _safe_status(exc))
        raise RuntimeError("smtp_send_failed") from exc
    _LOG.info("smtp sent to=%s", _mask_email(to))
    return {"ok": True, "provider": "smtp", "email_id": ""}


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str = "",
    html_body: str = "",
    idempotency_key: str = "",
    meter: bool = True,
    user_id: int | None = None,
    organization_id: int | None = None,
    feature_key: str = "email_user_notify",
    request_id: str = "",
) -> dict[str, Any]:
    """Send via Resend when configured; fall back to SMTP."""
    recipient = str(to or "").strip()
    if not recipient:
        raise RuntimeError("missing_recipient")
    resend = get_resend_settings()
    result: dict[str, Any]
    if resend.get("api_key"):
        try:
            result = _send_via_resend(
                to=recipient,
                subject=str(subject or ""),
                text_body=str(text_body or ""),
                html_body=str(html_body or ""),
                idempotency_key=str(idempotency_key or ""),
            )
        except Exception as exc:
            _LOG.warning(
                "resend failed to=%s err=%s — trying SMTP fallback",
                _mask_email(recipient),
                _safe_status(exc),
            )
            result = _send_via_smtp(
                to=recipient,
                subject=str(subject or ""),
                text_body=str(text_body or ""),
                html_body=str(html_body or ""),
            )
    else:
        result = _send_via_smtp(
            to=recipient,
            subject=str(subject or ""),
            text_body=str(text_body or ""),
            html_body=str(html_body or ""),
        )

    if meter and result.get("ok"):
        try:
            from app.db import SessionLocal
            from app.services.cost_usage_logger import record_infra_cost_usage

            db = SessionLocal()
            try:
                record_infra_cost_usage(
                    db,
                    user_id=user_id,
                    organization_id=organization_id,
                    feature_key=str(feature_key or "email_user_notify"),
                    quantity=1,
                    provider=str(result.get("provider") or "email"),
                    request_id=str(request_id or idempotency_key or "")[:128] or None,
                    credits_used=0,
                )
                db.commit()
            except Exception:
                db.rollback()
                _LOG.exception("email cost usage log failed")
            finally:
                db.close()
        except Exception:
            _LOG.exception("email cost usage session failed")
    return result


def send_otp_email(to_email: str, plain_body: str) -> dict[str, Any]:
    cfg = get_smtp_settings()
    try:
        return send_email(
            to=to_email,
            subject=cfg["otp_subject"],
            text_body=plain_body,
            meter=False,
            feature_key="email_otp",
        )
    except RuntimeError as exc:
        code = str(exc)
        if code == "missing_smtp_config" and not get_resend_settings().get("api_key"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Email chưa cấu hình (RESEND_API_KEY hoặc SMTP_USER / SMTP_PASSWORD).",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gửi email OTP thất bại. Thử lại sau ít phút.",
        ) from exc
