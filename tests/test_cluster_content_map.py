"""Tests for cluster Content Map enrichment."""

from app.services.cluster_content_map import (
    build_keyword_item,
    compute_confidence_score,
    enrich_cluster_for_content_map,
)


def test_enrich_cluster_has_saas_fields():
    raw = {
        "cluster_name": "SEO training",
        "main_keyword": "đào tạo seo",
        "intent": "informational",
        "intent_confidence": 0.8,
        "serp_similarity_avg": 0.62,
        "cohesion_score": 0.62,
        "suggested_content_type": "long_form_article_or_guide",
        "keywords": [
            {
                "keyword": "đào tạo seo",
                "search_volume": 14800,
                "volume_source": "dataforseo",
                "intent": "informational",
            },
            {
                "keyword": "khóa học seo",
                "search_volume": 1200,
                "volume_source": "dataforseo",
                "intent": "informational",
            },
            {
                "keyword": "seo là gì",
                "search_volume": 500,
                "volume_source": "estimated",
                "intent": "informational",
            },
        ],
        "explain": {"serp_data_available": True, "strong_pairs": []},
    }
    out = enrich_cluster_for_content_map(raw, idx=0, input_keyword_count=5)
    assert out["topic"]
    assert out["main_keyword"] == "đào tạo seo"
    assert out["total_keyword"] == 3
    assert out["confidence_score"] > 0
    assert out["content_priority"] in ("high", "medium", "low")
    assert len(out["keyword_items"]) == 3
    assert out["keyword_items"][0]["content_role"] == "primary"
    assert out["keyword_items"][0]["volume"] == 14800
    assert out["keyword_items"][2]["volume"] is None
    assert out["total_volume"] == 16000
    plan = out.get("content_plan") or {}
    assert plan.get("primary_keyword") == "đào tạo seo"
    assert plan.get("priority_score", 0) > 0
    assert plan.get("outline")


def test_compute_confidence_score_bounds():
    s = compute_confidence_score(
        serp_overlap=0.7,
        intent_confidence=0.9,
        semantic_score=0.6,
        volume_coverage=0.8,
        dedupe_ratio=1.0,
    )
    assert 0 <= s <= 100


def test_build_content_plan_fields():
    from app.services.cluster_content_map import build_content_plan

    items = [
        {"keyword": "đào tạo seo", "content_role": "primary", "volume": 1200},
        {"keyword": "khóa học seo", "content_role": "secondary", "volume": 400},
        {"keyword": "seo là gì", "content_role": "faq", "volume": None},
        {"keyword": "học seo online", "content_role": "semantic", "volume": 200},
    ]
    plan = build_content_plan(
        cluster_id="c0",
        topic="Đào tạo SEO",
        main_kw="đào tạo seo",
        keyword_items=items,
        cluster_intent="informational",
        suggested_content_type="long_form_article_or_guide",
        content_angle="Giải đáp & hướng dẫn chi tiết",
        total_volume=1600,
        confidence_score=78.0,
    )
    assert plan["primary_keyword"] == "đào tạo seo"
    assert "khóa học seo" in plan["secondary_keywords"]
    assert "seo là gì" in plan["faq_keywords"]
    assert plan["priority_score"] >= 40
    assert plan["target_word_count"] >= 800
    assert plan["recommended_title"]
    assert plan["outline"]


def test_build_keyword_item_matching_point():
    row = {"keyword": "khóa học seo", "search_volume": 1000, "volume_source": "dataforseo", "intent": "informational"}
    item = build_keyword_item(
        row,
        main_kw="đào tạo seo",
        cluster_intent="informational",
        rank=1,
        cluster_size=3,
        serp_pair_map={},
        cluster_serp_avg=0.5,
    )
    assert item["matching_point"] >= 0
    assert item["content_role"] in ("primary", "secondary", "semantic", "faq", "supporting")
