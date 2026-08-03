"""Facebook OAuth URL builder — config_id vs scope."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import social_auto_facebook_service as fb_svc
from app.services.social_auto_facebook_oauth_config import (
    CONFIG_FILE,
    effective_login_config_id,
    save_runtime_config_id,
)


class _Req:
    base_url = "https://seoauto.vn/"


def test_build_oauth_uses_scope_by_default(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.delenv("FACEBOOK_LOGIN_CONFIG_ID", raising=False)
    params = fb_svc.build_oauth_authorize_params(_Req(), 7)
    assert params["scope"] == "pages_show_list,pages_read_engagement,pages_manage_posts"
    assert "public_profile" not in params["scope"]
    assert "config_id" not in params


def test_build_oauth_uses_config_id_when_set(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_LOGIN_CONFIG_ID", "9876543210123456")
    params = fb_svc.build_oauth_authorize_params(_Req(), 7)
    assert params.get("config_id") == "9876543210123456"
    assert "scope" not in params


def test_oauth_start_scope_fallback_without_config_id(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FACEBOOK_REDIRECT_URI", "https://seoauto.vn/api/social/facebook/oauth/callback")
    monkeypatch.delenv("FACEBOOK_LOGIN_CONFIG_ID", raising=False)
    with patch.object(fb_svc, "_fetch_app_permissions", return_value={"pages_show_list"}):
        out = fb_svc.oauth_start_url(_Req(), 1)
    assert out["mode"] == "live_scope"
    assert "scope=pages_show_list" in out["url"]
    assert "facebook.com" in out["url"]


def test_handle_oauth_callback_no_pages_permission(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    with patch.object(fb_svc, "is_mock_mode", return_value=False):
        with patch.object(fb_svc, "decode_facebook_oauth_state", return_value=1):
            with patch.object(fb_svc, "_exchange_code_for_token", return_value="user_tok"):
                with patch.object(fb_svc, "_fetch_granted_permissions", return_value={"public_profile"}):
                    with patch.object(fb_svc, "_fetch_user_pages", return_value=[]):
                        with patch.object(fb_svc, "save_facebook_oauth_meta") as save_meta:
                            out = fb_svc.handle_oauth_callback(_Req(), "code", "state")
    assert out["oauth_status"] == "no_pages_permission"
    assert "pages_show_list" in out["message"]
    save_meta.assert_called_once()


def test_handle_oauth_callback_saves_pages(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    page_row = {"id": "pg1", "name": "My Page", "access_token": "page_tok"}
    with patch.object(fb_svc, "is_mock_mode", return_value=False):
        with patch.object(fb_svc, "decode_facebook_oauth_state", return_value=1):
            with patch.object(fb_svc, "_exchange_code_for_token", return_value="user_tok"):
                with patch.object(fb_svc, "_fetch_granted_permissions", return_value=fb_svc.PAGE_SCOPES):
                    with patch.object(fb_svc, "_fetch_user_pages", return_value=[page_row]):
                        with patch.object(fb_svc, "upsert_page", return_value={"page_id": "pg1"}) as up:
                            with patch.object(fb_svc, "set_active_page"):
                                with patch.object(fb_svc, "save_facebook_oauth_meta"):
                                    out = fb_svc.handle_oauth_callback(_Req(), "code", "state")
    assert out["count"] == 1
    up.assert_called_once()
    assert up.call_args.kwargs["page_access_token"] == "page_tok"


def test_oauth_start_blocks_when_scope_will_fail(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.delenv("FACEBOOK_LOGIN_CONFIG_ID", raising=False)
    with patch.object(fb_svc, "_fetch_app_permissions", return_value={"user_payment_tokens"}):
        with pytest.raises(HTTPException) as exc:
            fb_svc.oauth_start_url(_Req(), 1)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "facebook_oauth_not_ready"


def test_oauth_start_scope_when_app_has_pages(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.delenv("FACEBOOK_LOGIN_CONFIG_ID", raising=False)
    with patch.object(fb_svc, "_fetch_app_permissions", return_value={"pages_show_list"}):
        out = fb_svc.oauth_start_url(_Req(), 1)
    assert out["mode"] == "live_scope"
    assert "pages_show_list" in out["url"]


def test_runtime_config_id_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.social_auto_facebook_oauth_config.CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.delenv("FACEBOOK_LOGIN_CONFIG_ID", raising=False)
    save_runtime_config_id("9876543210123456")
    assert effective_login_config_id() == "9876543210123456"
