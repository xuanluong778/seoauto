from __future__ import annotations

import pytest

from app.services.keyword_intent_rules import classify_intent_detail, classify_intent_rules, majority_intent
from app.services.keyword_research_metrics import (
    build_search_volume_package,
    competition_label_from_index,
    compute_trend,
    parse_monthly_search_values,
)


@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("đào tạo seo", "education"),
        ("khóa học seo", "education"),
        ("dịch vụ seo", "commercial"),
        ("báo giá seo", "transactional"),
        ("seo là gì", "informational"),
        ("cách seo website", "informational"),
        ("phần mềm seo", "transactional"),
        ("công ty seo tphcm", "local"),
    ],
)
def test_intent_rules_keywords(keyword: str, expected: str) -> None:
    detail = classify_intent_detail(keyword)
    assert detail["intent"] == expected
    assert classify_intent_rules(keyword) == expected


def test_intent_unknown_no_signal() -> None:
    detail = classify_intent_detail("xyzabc generic term")
    assert detail["intent"] == "unknown"
    assert detail["source"] == "N/A"


def test_majority_intent_unknown_empty() -> None:
    assert majority_intent([]) == "unknown"


@pytest.mark.parametrize(
    "idx,label,source",
    [
        (None, "Unknown", "N/A"),
        (0.1, "Low", "dataforseo"),
        (0.5, "Medium", "dataforseo"),
        (0.9, "High", "dataforseo"),
        ("LOW", "Low", "dataforseo"),
        ("1", "High", "dataforseo"),
    ],
)
def test_competition_from_index(idx, label, source) -> None:
    got_label, got_src = competition_label_from_index(idx)
    assert got_label == label
    assert got_src == source


def test_google_ads_competition_index_one_is_low() -> None:
    label, src = competition_label_from_index(1, provider="google_ads")
    assert label == "Low"
    assert src == "google_ads"
    unknown, na = competition_label_from_index(0, provider="google_ads")
    assert unknown == "Unknown"
    assert na == "N/A"


def test_parse_monthly_searches() -> None:
    raw = [
        {"year": 2024, "month": 1, "search_volume": 100},
        {"year": 2024, "month": 2, "search_volume": 120},
        {"year": 2024, "month": 3, "search_volume": 140},
        {"year": 2024, "month": 4, "search_volume": 160},
    ]
    vals = parse_monthly_search_values(raw)
    assert vals == [100, 120, 140, 160]
    named = parse_monthly_search_values(
        [
            {"year": 2024, "month": "JANUARY", "search_volume": 10},
            {"year": 2024, "month": "FEBRUARY", "monthly_searches": 20},
        ]
    )
    assert named == [10, 20]


def test_trend_up() -> None:
    t = compute_trend([100, 100, 100, 100, 200, 200, 200, 200])
    assert t["direction"] == "up"
    assert t["pct_change"] is not None
    assert t["data_source"] == "dataforseo"


def test_trend_google_ads_source() -> None:
    t = compute_trend([100, 100, 100, 100, 200, 200, 200, 200], data_source="google_ads")
    assert t["direction"] == "up"
    assert t["data_source"] == "google_ads"


def test_trend_unknown_short_series() -> None:
    t = compute_trend([100, 110])
    assert t["direction"] == "unknown"
    assert t["data_source"] == "N/A"


def test_build_search_volume_real_monthly() -> None:
    monthly = [
        {"year": 2024, "month": i, "search_volume": 1000 + i * 50}
        for i in range(1, 13)
    ]
    pkg = build_search_volume_package(
        "test kw",
        raw_volume=1200,
        volume_source="dataforseo",
        monthly_searches=monthly,
    )
    assert pkg["has_monthly_data"] is True
    assert pkg["data_source"] == "dataforseo"
    assert pkg["raw_volume"] == 1200
    assert pkg["display_volume"] == 1200
    assert pkg["avg_monthly"] == 1200
    assert isinstance(pkg["avg_monthly"], int)
    assert len(pkg["chart_series"]) == 12
    assert pkg["jan"] > 0


def test_build_search_volume_raw_equals_display() -> None:
    """Monthly chart data must not change displayed volume."""
    monthly = [
        {"year": 2024, "month": 10, "search_volume": 100},
        {"year": 2024, "month": 11, "search_volume": 120},
        {"year": 2024, "month": 12, "search_volume": 140},
    ]
    pkg = build_search_volume_package(
        "dao tao seo",
        raw_volume=14800,
        volume_source="dataforseo",
        monthly_searches=monthly,
    )
    assert pkg["display_volume"] == 14800
    assert pkg["raw_volume"] == 14800
    assert pkg["avg_monthly"] == 14800


def test_build_search_volume_cache_source() -> None:
    pkg = build_search_volume_package(
        "cached kw",
        raw_volume=5000,
        volume_source="api_cache",
        from_cache=True,
    )
    assert pkg["data_source"] == "cache"


def test_build_search_volume_missing_is_na() -> None:
    pkg = build_search_volume_package("missing", raw_volume=None, volume_source="N/A")
    assert pkg["avg_monthly"] is None
    assert pkg["display_volume"] is None
    assert pkg["data_source"] == "N/A"
    assert pkg["chart_series"] == []
