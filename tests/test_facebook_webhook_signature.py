"""Facebook Messenger webhook must verify X-Hub-Signature-256 (fail-closed)."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def fb_secret(monkeypatch):
    secret = "test_facebook_app_secret_32chars!!"
    monkeypatch.setenv("FACEBOOK_APP_SECRET", secret)
    monkeypatch.setenv("CSKH_FB_WEBHOOK_VERIFY_TOKEN", "unit_verify_token")
    monkeypatch.delenv("SEOAUTO_PRODUCTION", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    return secret


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_facebook_webhook_signature_ok(fb_secret):
    from app.services.chatbot_cskh_facebook_service import verify_facebook_webhook_signature

    body = b'{"object":"page"}'
    assert verify_facebook_webhook_signature(
        raw_body=body,
        signature_header=_sign(fb_secret, body),
    )


def test_verify_facebook_webhook_signature_rejects_bad(fb_secret):
    from app.services.chatbot_cskh_facebook_service import verify_facebook_webhook_signature

    body = b'{"object":"page"}'
    assert not verify_facebook_webhook_signature(
        raw_body=body,
        signature_header="sha256=deadbeef",
    )


def test_verify_facebook_webhook_signature_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("FACEBOOK_APP_SECRET", raising=False)
    from app.services.chatbot_cskh_facebook_service import verify_facebook_webhook_signature

    assert not verify_facebook_webhook_signature(
        raw_body=b"{}",
        signature_header="sha256=abc",
    )


def test_webhook_verify_token_empty_in_production(monkeypatch):
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "1")
    monkeypatch.delenv("CSKH_FB_WEBHOOK_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN", raising=False)
    from app.services.chatbot_cskh_facebook_service import webhook_verify_token

    assert webhook_verify_token() == ""


def test_facebook_webhook_post_requires_signature(fb_secret, monkeypatch):
    """Mount only the Facebook router — avoid full main.py migration boot."""
    monkeypatch.setattr(
        "app.services.chatbot_cskh_facebook_service.process_messenger_webhook",
        lambda db, payload: None,
    )
    from app.db import get_db
    from app.routers.chatbot_cskh_facebook import router

    def _fake_db():
        yield None

    app = FastAPI()
    app.dependency_overrides[get_db] = _fake_db
    app.include_router(router, prefix="/api/chatbot")
    client = TestClient(app)
    body = json.dumps({"object": "page", "entry": []}).encode("utf-8")

    r = client.post(
        "/api/chatbot/facebook/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 403

    r2 = client.post(
        "/api/chatbot/facebook/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(fb_secret, body),
        },
    )
    assert r2.status_code == 200
    assert r2.json().get("ok") is True
