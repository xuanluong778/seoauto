"""Resend-first email sender with SMTP fallback."""

from __future__ import annotations

import pytest
import requests

from app.services.mail_smtp import send_email, send_otp_email


def _resend_cfg(**over):
    cfg = {
        "api_key": "re_test_key",
        "from_email": "SEOAuto <no-reply@mail.seoauto.vn>",
        "timeout_seconds": 15,
        "retry_count": 3,
    }
    cfg.update(over)
    return cfg


def _smtp_cfg(**over):
    cfg = {
        "host": "smtp.example.test",
        "port": 587,
        "use_tls": True,
        "user": "user@example.test",
        "password": "x",
        "from_email": "user@example.test",
        "from_name": "Seoauto",
        "otp_subject": "Mã OTP đăng nhập của bạn",
        "otp_length": 6,
        "otp_expire_seconds": 300,
    }
    cfg.update(over)
    return cfg


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}" if payload is None else b'{"id":"x"}'

    def json(self):
        return self._payload


def test_send_email_resend_returns_email_id(monkeypatch):
    monkeypatch.setattr("app.services.mail_smtp.get_resend_settings", lambda: _resend_cfg())
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        seen["auth"] = (headers or {}).get("Authorization", "").startswith("Bearer re_")
        return _FakeResp(200, {"id": "ae_prod_123"})

    monkeypatch.setattr("app.services.mail_smtp.requests.post", fake_post)
    out = send_email(to="user@gmail.com", subject="Mã OTP", text_body="code 123456")
    assert out["ok"] is True
    assert out["provider"] == "resend"
    assert out["email_id"] == "ae_prod_123"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["timeout"] == 15
    assert seen["auth"] is True
    assert seen["json"]["from"] == "SEOAuto <no-reply@mail.seoauto.vn>"
    assert seen["json"]["to"] == ["user@gmail.com"]


def test_send_email_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.services.mail_smtp.get_resend_settings", lambda: _resend_cfg(retry_count=3))
    monkeypatch.setattr("app.services.mail_smtp.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_post(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResp(503, {"message": "busy"})
        return _FakeResp(200, {"id": "ae_retry_ok"})

    monkeypatch.setattr("app.services.mail_smtp.requests.post", fake_post)
    out = send_email(to="user@gmail.com", subject="x", text_body="y")
    assert calls["n"] == 3
    assert out["email_id"] == "ae_retry_ok"


def test_send_email_falls_back_to_smtp(monkeypatch):
    monkeypatch.setattr("app.services.mail_smtp.get_resend_settings", lambda: _resend_cfg())
    monkeypatch.setattr("app.services.mail_smtp.get_smtp_settings", lambda: _smtp_cfg())

    def boom(*_a, **_k):
        raise requests.Timeout("slow")

    monkeypatch.setattr("app.services.mail_smtp.requests.post", boom)
    monkeypatch.setattr("app.services.mail_smtp.time.sleep", lambda _s: None)
    sent = {"ok": False}

    class _Smtp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            return None

        def login(self, *a):
            return None

        def sendmail(self, *a, **k):
            sent["ok"] = True

    monkeypatch.setattr("app.services.mail_smtp.smtplib.SMTP", _Smtp)
    out = send_email(to="user@gmail.com", subject="OTP", text_body="hi")
    assert sent["ok"] is True
    assert out["provider"] == "smtp"


def test_send_otp_email_uses_resend(monkeypatch):
    monkeypatch.setattr("app.services.mail_smtp.get_resend_settings", lambda: _resend_cfg())
    monkeypatch.setattr("app.services.mail_smtp.get_smtp_settings", lambda: _smtp_cfg())
    monkeypatch.setattr(
        "app.services.mail_smtp.requests.post",
        lambda *a, **k: _FakeResp(200, {"id": "ae_otp"}),
    )
    out = send_otp_email("user@gmail.com", "Mã OTP đăng nhập của bạn: 123456")
    assert out["email_id"] == "ae_otp"
