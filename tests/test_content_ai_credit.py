"""Tests for Content AI variable credit pricing."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.content_ai_credit_service import (
    ContentAiBillingFlags,
    billing_flags_from_request,
    charge_content_ai_write,
    quote_content_ai_write,
    resolve_billing_policy,
)


def _user(*, admin: bool = False, byok: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=42, is_admin=admin, api_access_enabled=byok)


@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=500)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_quote_word_tiers(_admin, _bal, _enf):
    user = _user()
    db = MagicMock()
    q_short = quote_content_ai_write(db, user, field="content", word_count=900, use_system_llm=True)
    q_med = quote_content_ai_write(db, user, field="content", word_count=1500, use_system_llm=True)
    q_long = quote_content_ai_write(db, user, field="content", word_count=2000, use_system_llm=True)
    assert q_short["tier_action"] == "article_short"
    assert q_med["tier_action"] == "article_medium"
    assert q_long["tier_action"] == "article_long"
    assert q_short["credit_cost"] == 12
    assert q_med["credit_cost"] == 25
    assert q_long["credit_cost"] == 45
    assert q_short["credit_cost"] < q_med["credit_cost"] < q_long["credit_cost"]


@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=500)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_quote_addons_sum(_admin, _bal, _enf):
    user = _user()
    db = MagicMock()
    flags = ContentAiBillingFlags(
        include_research=True,
        include_outline=True,
        include_internal_links=True,
        include_rewrite=True,
        image_source="google",
    )
    quote = quote_content_ai_write(db, user, field="content", word_count=1500, flags=flags, use_system_llm=True)
    # base 25 + research 15 + outline 3 + internal 5 + rewrite 20 + images (slots * 8)
    assert quote["credit_subtotal"] > quote["lines"][0]["credit_cost"]
    assert quote["credit_cost"] == quote["credit_subtotal"]


@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_system_api_always_charges_credits(_admin):
    user = _user(byok=True)
    policy = resolve_billing_policy(user=user, use_system_llm=True)
    assert policy["mode"] == "system_api"
    assert policy["charge_credits"] is True


@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=500)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_system_api_full_credit_not_reduced(_admin, _bal, _enf):
    user = _user(byok=True)
    db = MagicMock()
    quote = quote_content_ai_write(db, user, field="content", word_count=1000, use_system_llm=True)
    assert quote["billing_mode"] == "system_api"
    assert quote["credit_cost"] == 12


def test_billing_flags_infer_outline_and_rewrite():
    flags = billing_flags_from_request(
        field="content",
        outline_content="",
        content="<p>" + ("word " * 100) + "</p>",
    )
    assert flags.include_outline is True
    assert flags.include_rewrite is True


@patch("app.services.content_ai_credit_service.consume_credits")
@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_charge_skips_fallback(_admin, _enf, consume):
    user = _user()
    db = MagicMock()
    quote = {"charge_credits": True, "credit_cost": 25, "tier_action": "article_medium", "request_id": "abc", "lines": [], "flags": {}}
    assert charge_content_ai_write(db, user, quote, field="content", llm_used=True, used_fallback=True) is None
    consume.assert_not_called()


@patch("app.services.content_ai_credit_service.consume_credits")
@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
def test_charge_writes_ledger(_admin, _enf, consume):
    user = _user()
    db = MagicMock()
    quote = {
        "charge_credits": True,
        "credit_cost": 25,
        "tier_action": "article_medium",
        "request_id": "req1",
        "word_count": 1500,
        "lines": [{"key": "base", "action": "article_medium", "credit_cost": 25}],
        "flags": {"project_id": "p1"},
        "billing_mode": "system_api",
    }
    meta = charge_content_ai_write(db, user, quote, field="content", llm_used=True, used_fallback=False)
    assert meta and meta["charged"] == 25
    consume.assert_called_once()
    kw = consume.call_args.kwargs
    assert kw["module"] == "content_ai"
    assert kw["action"] == "article_medium"
    assert kw["request_id"] == "req1"
