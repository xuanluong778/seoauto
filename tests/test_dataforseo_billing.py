"""Tests for DataForSEO billing / cache-first keyword research."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.dataforseo_billing_service import (
    preview_research_billing,
    preview_volume_batch_billing,
    user_may_use_dataforseo_live,
)
from app.services.search_volume import peek_volume_cache_status


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=7)


@patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
@patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="starter")
@patch("app.services.dataforseo_billing_service.plan_feature", return_value=False)
def test_basic_plan_no_live(_feat, _slug, _admin):
    db = MagicMock()
    assert user_may_use_dataforseo_live(db, _user()) is False
    preview = preview_research_billing(
        db, _user(), seeds=["seo"], country="vn", language="vi",
    )
    assert preview.allow_live is False
    assert preview.api_mode == "basic"
    assert preview.credit_cost == 5


@patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
@patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
@patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
@patch("app.services.keyword_dataforseo_expand.peek_k4k_cache_status", return_value={"hits": 0, "misses": 1, "total": 1})
def test_pro_live_cost(_k4k, _feat, _slug, _admin):
    db = MagicMock()
    preview = preview_research_billing(
        db, _user(), seeds=["seo"], country="vn", language="vi",
    )
    assert preview.allow_live is True
    assert preview.api_mode == "live"
    assert preview.credit_cost == 30


@patch("app.services.search_volume._redis_get", return_value=None)
@patch("app.services.search_volume._db_get", return_value=None)
def test_peek_volume_all_miss(_db, _redis):
    out = peek_volume_cache_status(["a", "b"], country="vn", language="vi")
    assert out["total"] == 2
    assert out["misses"] == 2


@patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
@patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
@patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
@patch(
    "app.services.search_volume.peek_volume_cache_status",
    return_value={"total": 50, "hits": 50, "misses": 0, "miss_keywords": []},
)
def test_volume_batch_all_cache(_peek, _feat, _slug, _admin):
    db = MagicMock()
    preview = preview_volume_batch_billing(
        db, _user(), keywords=["k"] * 50, country="vn", language="vi",
    )
    assert preview.api_keywords == 0
    assert preview.from_cache is True
    assert preview.credit_cost < 35
