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
@patch("app.services.volume_providers.google_ads.google_ads_configured", return_value=False)
@patch("app.services.keyword_ads_expand.peek_ads_ideas_cache_status", return_value={"hits": 0, "misses": 1, "total": 1, "hit_seeds": [], "miss_keywords": ["seo"]})
@patch("app.services.keyword_dataforseo_expand.peek_k4k_cache_status", return_value={"hits": 0, "misses": 1, "total": 1})
def test_pro_live_cost(_k4k, _ads, _gads, _feat, _slug, _admin):
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


def test_maybe_log_skips_when_no_dfs() -> None:
    from app.services.dataforseo_billing_service import maybe_log_dataforseo_usage

    with patch("app.services.dataforseo_billing_service.log_dataforseo_usage") as log_fn:
        maybe_log_dataforseo_usage(
            MagicMock(),
            stats={"dataforseo_calls": 0, "google_ads_calls": 2},
            user_id=1,
            action="keyword_research",
            endpoint="keywords_for_keywords/live",
        )
        log_fn.assert_not_called()


def test_maybe_log_writes_when_dfs_called() -> None:
    from app.services.dataforseo_billing_service import maybe_log_dataforseo_usage

    with patch("app.services.dataforseo_billing_service.log_dataforseo_usage") as log_fn:
        maybe_log_dataforseo_usage(
            MagicMock(),
            stats={"dataforseo_calls": 1, "cache_hits": 2},
            user_id=1,
            action="keyword_research",
            endpoint="keywords_for_keywords/live",
            api_mode="live",
        )
        log_fn.assert_called_once()
        kwargs = log_fn.call_args.kwargs
        assert kwargs["tasks_count"] == 1
        assert kwargs["api_called"] == 1


@patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
@patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
@patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
@patch("app.services.volume_providers.google_ads.google_ads_configured", return_value=True)
@patch(
    "app.services.keyword_ads_expand.peek_ads_ideas_cache_status",
    return_value={"hits": 0, "misses": 1, "total": 1, "hit_seeds": [], "miss_keywords": ["seo"]},
)
@patch(
    "app.services.keyword_dataforseo_expand.peek_k4k_cache_status",
    return_value={"hits": 0, "misses": 1, "total": 1, "hit_seeds": [], "miss_keywords": ["seo"]},
)
def test_ads_primary_does_not_charge_dfs_live(_k4k, _ads, _gads, _feat, _slug, _admin, monkeypatch):
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    preview = preview_research_billing(
        MagicMock(), _user(), seeds=["seo"], country="vn", language="vi",
    )
    assert preview.allow_live is True
    assert preview.cache_hit is False
    assert preview.api_mode == "cache"
    assert preview.credit_cost == 5


@patch("app.services.dataforseo_billing_service.is_admin", return_value=False)
@patch("app.services.dataforseo_billing_service.resolve_cau_ai_plan_slug", return_value="pro")
@patch("app.services.dataforseo_billing_service.plan_feature", return_value=True)
@patch(
    "app.services.keyword_ads_expand.peek_ads_ideas_cache_status",
    return_value={"hits": 1, "misses": 0, "total": 1, "hit_seeds": ["seo"], "miss_keywords": []},
)
@patch(
    "app.services.keyword_dataforseo_expand.peek_k4k_cache_status",
    return_value={"hits": 0, "misses": 1, "total": 1, "hit_seeds": [], "miss_keywords": ["seo"]},
)
def test_kideas_cache_is_not_live_paid(_k4k, _ads, _feat, _slug, _admin):
    preview = preview_research_billing(
        MagicMock(), _user(), seeds=["seo"], country="vn", language="vi",
    )
    assert preview.cache_hit is True
    assert preview.api_mode == "cache"
    assert preview.credit_cost <= 5
