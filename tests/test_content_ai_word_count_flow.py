"""Content AI + chatbot word count policy flow tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.content_ai_word_count_policy import (
    assess_word_count_meta,
    build_word_count_response,
    chatbot_validated_word_count,
    needs_word_count_repair,
    needs_word_count_trim,
    resolve_word_counts,
    validate_target_word_count,
    word_count_bounds,
)


def _user(*, plan: str = "starter") -> SimpleNamespace:
    return SimpleNamespace(id=11, plan_slug=plan, plan=plan, is_admin=False, api_access_enabled=False)


def test_resolve_word_counts_preset_1000():
    user = _user(plan="pro")
    counts = resolve_word_counts(1000, user, None)
    assert counts["requested_word_count"] == 1000
    assert counts["validated_word_count"] == 1000


def test_starter_custom_above_plan_clamped_to_1500():
    user = _user(plan="starter")
    assert validate_target_word_count(5000, user, None) == 1500
    counts = resolve_word_counts(5000, user, None)
    assert counts["requested_word_count"] == 5000
    assert counts["validated_word_count"] == 1500


def test_assess_status_ok_short_long():
    lo, hi = word_count_bounds(1000)
    ok = assess_word_count_meta("<p>" + "word " * lo + "</p>", 1000)
    assert ok["word_count_status"] == "ok"
    short = assess_word_count_meta("<p>one two three</p>", 1000)
    assert short["word_count_status"] == "short"
    long_html = "<p>" + "word " * (hi + 50) + "</p>"
    long_meta = assess_word_count_meta(long_html, 1000)
    assert long_meta["word_count_status"] == "long"


def test_repair_trigger_at_15_percent_below_target():
    validated = 1000
    assert needs_word_count_repair(840, validated) is True
    assert needs_word_count_repair(860, validated) is False


def test_trim_trigger_at_15_percent_above_target():
    validated = 1000
    assert needs_word_count_trim(1160, validated) is True
    assert needs_word_count_trim(1140, validated) is False


@patch("app.services.content_ai_credit_service.consume_credits")
@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=5000)
@patch("app.services.content_ai_credit_service.api_access_enabled_for", return_value=False)
def test_billing_uses_actual_not_client_low_target(_a, _b, _c, _d, consume):
    from app.services.content_ai_credit_service import charge_content_ai_from_html

    user = _user(plan="pro")
    db = MagicMock()
    html = "<h1>T</h1>" + ("<p>seo " * 1480 + "</p>")
    charge_content_ai_from_html(db, user, html, field="content", use_system_llm=True, llm_used=True)
    assert consume.call_args.kwargs["action"] == "article_medium"


def test_policy_flags_repair_for_15_percent_short():
    html = "<p>" + "word " * 800 + "</p>"
    meta = assess_word_count_meta(html, 1000)
    assert meta["needs_repair"] is True
    assert meta["word_count_status"] == "short"


def test_chatbot_validated_word_count_uses_policy():
    with patch("app.db.SessionLocal") as mock_sl:
        mock_db = MagicMock()
        mock_sl.return_value = mock_db
        stub = SimpleNamespace(id=99, plan_slug="starter", plan="starter")
        mock_db.get.return_value = stub
        wc = chatbot_validated_word_count(99, 3000)
    assert wc == 1500


def test_build_word_count_response_fields():
    user = _user(plan="pro")
    html = "<p>" + "word " * 1000 + "</p>"
    resp = build_word_count_response(client_value=1000, user=user, db=None, html=html)
    assert resp["requested_word_count"] == 1000
    assert resp["validated_word_count"] == 1000
    assert resp["actual_word_count"] == 1000
    assert resp["word_count_status"] == "ok"
    assert resp["word_count_target"] == 1000
    assert resp["word_count_actual"] == 1000
