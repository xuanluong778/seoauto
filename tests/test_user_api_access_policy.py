"""Tests for unified API key access policy (system vs custom)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.user_api_access import (
    CUSTOM_API_FORBIDDEN_MSG,
    SYSTEM_API_NOT_CONFIGURED_MSG,
    assert_user_may_manage_api_keys,
    build_system_ai_snapshot,
    can_see_api_keys_settings_tab,
    may_manage_custom_api_keys,
    resolve_ai_llm_gate,
)


def _user(**kw):
    defaults = dict(
        id=10,
        role="user",
        api_access_enabled=False,
        use_admin_api_pool=False,
        allow_custom_api_key=False,
        trial_used=False,
        trial_expires_at=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@patch("app.services.user_api_access.is_admin", return_value=False)
def test_regular_user_cannot_manage_api_keys(_admin):
    db = MagicMock()
    user = _user()
    assert may_manage_custom_api_keys(db, user) is False
    with pytest.raises(HTTPException) as exc:
        assert_user_may_manage_api_keys(db, user)
    assert exc.value.status_code == 403
    assert CUSTOM_API_FORBIDDEN_MSG in str(exc.value.detail)


@patch("app.services.user_api_access.is_admin", return_value=True)
def test_admin_can_manage_api_keys(_admin):
    db = MagicMock()
    user = _user(role="admin")
    assert may_manage_custom_api_keys(db, user) is True


def test_api_keys_settings_tab_only_for_admin_role():
    assert can_see_api_keys_settings_tab(None) is False
    assert can_see_api_keys_settings_tab(_user(role="user")) is False
    assert can_see_api_keys_settings_tab(_user(role="editor")) is False
    assert can_see_api_keys_settings_tab(_user(role="admin")) is True
    assert can_see_api_keys_settings_tab(_user(role="super_admin")) is True


@patch("app.services.user_api_access.is_admin", return_value=False)
def test_allow_custom_api_key_flag_legacy_disabled(_admin):
    db = MagicMock()
    user = _user(allow_custom_api_key=True)
    assert may_manage_custom_api_keys(db, user) is False


@patch("app.services.user_api_access.is_admin", return_value=False)
def test_legacy_api_access_does_not_open_ui(_admin):
    db = MagicMock()
    user = _user(api_access_enabled=True)
    assert may_manage_custom_api_keys(db, user) is False


@patch("app.services.user_api_access.admin_system_llm_available", return_value=False)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.user_api_access.is_admin", return_value=False)
def test_system_api_missing_message(_admin, mock_check, _sys):
    from app.schemas.saas import EntitlementResult

    db = MagicMock()
    user = _user()
    mock_check.return_value = EntitlementResult(
        allowed=True,
        reason_code="subscription",
        message="ok",
        plan_slug="starter",
        feature_key="content_ai_article",
    )
    snap = build_system_ai_snapshot(db, user, unit_cost=5)
    assert snap["allowed"] is False
    assert snap["code"] == "system_api_missing"
    assert snap["message"] == SYSTEM_API_NOT_CONFIGURED_MSG


@patch("app.services.user_api_access.admin_system_llm_available", return_value=True)
@patch("app.services.credits.get_available_balance", return_value=0)
@patch("app.services.credits.credits_enforced", return_value=True)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.user_api_access.is_admin", return_value=False)
def test_insufficient_credits_blocks_ai(_admin, mock_check, _ce, _bal, _sys):
    from app.schemas.saas import EntitlementResult

    db = MagicMock()
    user = _user()
    mock_check.return_value = EntitlementResult(
        allowed=True,
        reason_code="trial_3d",
        message="ok",
        plan_slug="trial_3d",
        feature_key="content_ai_article",
    )
    gate = resolve_ai_llm_gate(db, user, unit_cost=10)
    assert gate["allowed"] is False
    assert gate["code"] == "insufficient_credits"


@patch("app.services.user_api_access.admin_system_llm_available", return_value=True)
@patch("app.services.credits.get_available_balance", return_value=100)
@patch("app.services.credits.credits_enforced", return_value=True)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.user_api_access.is_admin", return_value=False)
def test_non_admin_always_uses_system_api_even_with_custom_key(_admin, mock_check, _ce, _bal, _sys):
    from app.schemas.saas import EntitlementResult

    db = MagicMock()
    user = _user(allow_custom_api_key=True, api_access_enabled=True)
    mock_check.return_value = EntitlementResult(
        allowed=True,
        reason_code="subscription",
        message="ok",
        plan_slug="agency",
        feature_key="content_ai_article",
    )
    gate = resolve_ai_llm_gate(db, user, unit_cost=10)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True
    assert gate["charge_credits"] is True


@patch("app.services.user_api_access.admin_system_llm_available", return_value=True)
@patch("app.services.credits.get_available_balance", return_value=100)
@patch("app.services.credits.credits_enforced", return_value=True)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.user_api_access.is_admin", return_value=False)
def test_trial_user_uses_system_api(_admin, mock_check, _ce, _bal, _sys):
    from app.schemas.saas import EntitlementResult

    db = MagicMock()
    user = _user()
    mock_check.return_value = EntitlementResult(
        allowed=True,
        reason_code="trial_3d",
        message="ok",
        plan_slug="trial_3d",
        feature_key="content_ai_article",
    )
    gate = resolve_ai_llm_gate(db, user, unit_cost=5)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True
    assert gate["charge_credits"] is True
