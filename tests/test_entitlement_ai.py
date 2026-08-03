"""Tests for unified AI entitlement (system API only)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.entitlement_service import can_use_ai, check_feature


def _user(**kw):
    defaults = dict(
        id=10,
        role="user",
        api_access_enabled=True,
        trial_used=False,
        trial_expires_at=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@patch("app.services.entitlement_service.has_active_free_usage", return_value=False)
@patch("app.services.entitlement_service.is_saas_enforcement_enabled", return_value=True)
@patch("app.services.entitlement_service.can_write", return_value=True)
@patch("app.services.entitlement_service.is_admin", return_value=False)
@patch("app.services.entitlement_service._has_paid_active_subscription", return_value=False)
@patch("app.services.entitlement_service._trial_3d_allows", return_value=None)
@patch("app.services.entitlement_service._free_usage_credit_allows", return_value=None)
def test_api_access_legacy_does_not_bypass(_fu, _trial, _paid, _admin, _write, _enforce, _free):
    db = MagicMock()
    user = _user(api_access_enabled=True)
    result = check_feature(db, user, "content_ai_article")
    assert result.allowed is False
    assert result.reason_code == "denied"


@patch("app.services.user_api_access.admin_system_llm_available", return_value=True)
@patch("app.services.credits.get_available_balance", return_value=100)
@patch("app.services.credits.credits_enforced", return_value=True)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.entitlement_service.is_admin", return_value=False)
def test_can_use_ai_always_system_llm(_admin, mock_check, _ce, _bal, _sys):
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
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is True
    assert gate["use_system_llm"] is True


@patch("app.services.user_api_access.admin_system_llm_available", return_value=False)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.entitlement_service.is_admin", return_value=False)
def test_can_use_ai_blocks_when_system_api_missing(_admin, mock_check, _sys):
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
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=5)
    assert gate["allowed"] is False
    assert gate["code"] == "system_api_missing"
    assert "liên hệ admin" in gate["message"].lower()


@patch("app.services.user_api_access.admin_system_llm_available", return_value=True)
@patch("app.services.credits.get_available_balance", return_value=0)
@patch("app.services.credits.credits_enforced", return_value=True)
@patch("app.services.entitlement_service.check_feature")
@patch("app.services.entitlement_service.is_admin", return_value=False)
def test_can_use_ai_requires_credit_gt_zero(_admin, mock_check, _ce, _bal, _sys):
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
    gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=0)
    assert gate["allowed"] is False
    assert gate["code"] == "insufficient_credits"
