"""Tests for plan_quota_registry."""

from __future__ import annotations

from app.services.plan_quota_registry import (
    PAID_PLAN_SLUGS,
    catalog_for_api,
    chatbot_monthly_reply_limit,
    feature_key_for,
    iter_usage_limits,
    lead_scanner_limits,
    monthly_quota,
    plan_feature,
)


def test_paid_plans_have_all_quota_keys():
    keys = (
        "projects",
        "ai_articles",
        "technical_audit",
        "seo_score",
        "keyword_research",
        "lead_scan",
        "lead_detail",
        "chatbot_reply",
        "google_map_location",
        "team_members",
    )
    for slug in PAID_PLAN_SLUGS:
        for k in keys:
            assert monthly_quota(slug, k) >= 0


def test_basic_blocks_google_map():
    assert plan_feature("starter", "google_map_seo") is False
    assert plan_feature("pro", "google_map_seo") is True
    assert monthly_quota("starter", "google_map_location") == 0
    assert monthly_quota("pro", "google_map_location") == 5


def test_basic_byok_preferred():
    assert plan_feature("starter", "byok_preferred") is False
    assert plan_feature("pro", "byok_preferred") is False
    assert plan_feature("agency", "byok_preferred") is False
    assert plan_feature("business", "byok_preferred") is False


def test_agency_whitelabel():
    assert plan_feature("agency", "white_label_report") is True
    assert plan_feature("starter", "white_label_report") is False


def test_feature_key_mapping():
    assert feature_key_for("projects") == "wordpress_site"
    assert feature_key_for("lead_detail") == "lead_map_place_detail"


def test_usage_limits_include_new_features():
    keys = {(slug, fk) for slug, fk, *_ in iter_usage_limits()}
    assert ("pro", "seo_score") in keys
    assert ("pro", "lead_map_scan") in keys
    assert ("pro", "google_map_location") in keys


def test_lead_scanner_synced_with_registry():
    pro = lead_scanner_limits("pro")
    assert pro["monthly_scans"] == monthly_quota("pro", "lead_scan")
    assert pro["daily_scans"] == 10


def test_chatbot_replies_match_registry():
    assert chatbot_monthly_reply_limit("pro") == 3000


def test_catalog_for_api_four_plans():
    items = catalog_for_api()
    assert len(items) == 4
    slugs = {x["plan_slug"] for x in items}
    assert slugs == set(PAID_PLAN_SLUGS)
