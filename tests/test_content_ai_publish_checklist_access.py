"""Content AI publish-checklist access for subscription trial users."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.content_ai_publish_checklist import evaluate_publish_checklist
from app.services.trial_access import require_active_trial


def test_require_active_trial_allows_active_subscription():
    user = SimpleNamespace(
        id=99,
        role="user",
        status="active",
        api_access_enabled=False,
    )
    db = MagicMock()
    sub = MagicMock()

    with patch("app.services.subscription_service.get_active_subscription", return_value=sub):
        with patch("app.services.subscription_service.is_subscription_active", return_value=True):
            with patch(
                "app.services.cau_ai_fix_entitlement.resolve_cau_ai_plan_slug",
                return_value=None,
            ):
                out = require_active_trial(current_user=user, db=db)
    assert out is user


def test_publish_checklist_returns_score_for_article_html():
    data = evaluate_publish_checklist(
        title="Cài win quận Thủ Đức",
        meta_description="Dịch vụ cài win tận nơi",
        content_html="<h1>Cài win quận Thủ Đức</h1><p>" + "nội dung " * 120 + "</p>",
        primary_keyword="cài win quận thủ đức",
        slug="cai-win-quan-thu-duc",
        secondary_keywords=[],
    )
    assert isinstance(data.get("score"), int)
    assert data["score"] >= 0
    assert len(data.get("groups") or []) == 10
