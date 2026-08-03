"""Tests for cluster SERP overlap accuracy helpers."""

from app.services.cluster_serp_overlap import (
    apply_intent_gate_to_serp_pairs,
    build_url_sets_from_snapshots,
    filter_serp_url_for_overlap,
    jaccard_sets,
    select_main_keyword,
    split_over_clustered_groups,
)


def test_filter_serp_url_strips_tracking_and_normalizes():
    u = filter_serp_url_for_overlap("http://WWW.Example.com/path/?utm_source=x&gclid=1")
    assert u == "https://example.com/path"


def test_filter_serp_url_rejects_ads():
    assert filter_serp_url_for_overlap("https://googleadservices.com/pagead/aclk?adurl=1") is None


def test_intent_gate_blocks_cross_intent_low_serp():
    pairs = [(0, 1, 0.42)]
    intent_labels = ["transactional", "informational"]
    kept, meta = apply_intent_gate_to_serp_pairs(
        pairs,
        intent_labels=intent_labels,
        strictness="normal",
        gate_floor=None,
    )
    assert len(kept) == 0
    assert meta["blocked_by_intent"] >= 1


def test_intent_gate_allows_high_serp_override():
    pairs = [(0, 1, 0.88)]
    intent_labels = ["transactional", "informational"]
    kept, _ = apply_intent_gate_to_serp_pairs(
        pairs,
        intent_labels=intent_labels,
        strictness="normal",
        gate_floor=None,
    )
    assert len(kept) == 1


def test_split_over_clustered_by_mixed_intent():
    url_sets = [
        {"https://a.com/1", "https://b.com/2"},
        {"https://a.com/1", "https://c.com/3"},
        {"https://x.com/9"},
        {"https://y.com/8"},
    ]
    groups = [[0, 1, 2, 3]]
    intent_labels = ["informational", "informational", "transactional", "transactional"]
    out = split_over_clustered_groups(
        groups,
        url_sets=url_sets,
        intent_labels=intent_labels,
        strictness="strict",
    )
    assert len(out) >= 2


def test_select_main_keyword_prefers_short_high_intent():
    rows = [
        {"keyword": "đào tạo seo chuyên sâu tại tphcm", "search_volume": 900, "volume_source": "dataforseo", "intent": "informational"},
        {"keyword": "đào tạo seo", "search_volume": 1200, "volume_source": "dataforseo", "intent": "informational"},
    ]
    assert select_main_keyword(rows, cluster_intent="informational") == "đào tạo seo"


def test_build_url_sets_filters_noise():
    snaps = {
        "kw": {
            "serp_urls": [
                "https://example.com/a",
                "https://googleadservices.com/pagead/aclk",
                "http://www.example.com/a/",
            ]
        }
    }
    sets = build_url_sets_from_snapshots(snaps, ["kw"])
    assert len(sets[0]) == 1
    assert "https://example.com/a" in sets[0]


def test_jaccard_sets():
    assert jaccard_sets({"a", "b"}, {"b", "c"}) == 1 / 3
