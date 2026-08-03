import os


def test_vi_intent_classifier_transactional_vs_info():
    from app.services.search_intent import classify_search_intent

    assert classify_search_intent("mua iphone 15")["intent"] == "transactional"
    assert classify_search_intent("iphone 15 giá bao nhiêu")["intent"] == "transactional"
    assert classify_search_intent("cách sửa laptop")["intent"] == "informational"
    assert classify_search_intent("hướng dẫn sửa laptop")["intent"] == "informational"
    assert classify_search_intent("iphone 15 review")["intent"] in ("commercial", "informational")


def test_vi_service_hire_intent_not_informational():
    from app.services.search_intent import classify_search_intent

    assert classify_search_intent("dịch vụ seo")["intent"] == "commercial"
    assert classify_search_intent("thuê seo")["intent"] == "commercial"
    assert classify_search_intent("giá dịch vụ seo")["intent"] == "transactional"


def test_intent_merge_blocked_without_high_serp():
    from app.services.search_intent import intent_merge_allowed

    assert intent_merge_allowed("informational", "commercial", serp_jaccard=0.0) is False
    assert intent_merge_allowed("informational", "transactional", serp_jaccard=0.5) is False
    assert intent_merge_allowed("informational", "commercial", serp_jaccard=0.84) is False
    assert intent_merge_allowed("informational", "commercial", serp_jaccard=0.90) is True
    assert intent_merge_allowed("informational", "informational", serp_jaccard=0.0) is True


def test_intent_gate_blocks_cross_intent_merge():
    os.environ["KEYWORD_CLUSTER_SCALABLE_N"] = "2"
    os.environ["KEYWORD_CLUSTER_INTENT_STRICT"] = "1"
    os.environ["SERP_FETCH_ENABLED"] = "0"

    from app.services.keyword_clusterer import cluster_keywords

    recs = [
        {"keyword": "mua iphone 15", "source": "t"},
        {"keyword": "iphone 15 giá bao nhiêu", "source": "t"},
        {"keyword": "cách sửa laptop", "source": "t"},
        {"keyword": "hướng dẫn sửa laptop", "source": "t"},
    ]
    clusters = cluster_keywords(recs, fetch_serp=False)

    for c in clusters:
        from app.services.search_intent import effective_intent_for_clustering

        intents = {effective_intent_for_clustering(r) for r in (c.get("keywords") or [])}
        assert len(intents) <= 1


def test_vi_synonym_merge_same_intent():
    os.environ["KEYWORD_CLUSTER_SCALABLE_N"] = "2"
    os.environ["KEYWORD_CLUSTER_INTENT_STRICT"] = "1"
    os.environ["SERP_FETCH_ENABLED"] = "0"

    from app.services.keyword_clusterer import cluster_keywords

    recs = [
        {"keyword": "cách sửa laptop", "source": "t"},
        {"keyword": "hướng dẫn sửa laptop", "source": "t"},
    ]
    clusters = cluster_keywords(recs, fetch_serp=False)
    assert len(clusters) == 1


def test_seo_info_must_not_cluster_with_service_keywords():
    """
    Bắt buộc: informational SEO queries không gom chung với dịch vụ/giá/thuê SEO.
    """
    os.environ["KEYWORD_CLUSTER_SCALABLE_N"] = "2"
    os.environ["KEYWORD_CLUSTER_INTENT_STRICT"] = "1"
    os.environ["SERP_FETCH_ENABLED"] = "0"

    from app.services.keyword_clusterer import cluster_keywords
    from app.services.search_intent import effective_intent_for_clustering

    info_kws = ["seo là gì", "cách học seo", "hướng dẫn seo"]
    money_kws = ["dịch vụ seo", "giá dịch vụ seo", "thuê seo"]
    recs = [{"keyword": k, "source": "t"} for k in info_kws + money_kws]
    clusters = cluster_keywords(recs, fetch_serp=False)

    info_set = {k.lower() for k in info_kws}
    money_set = {k.lower() for k in money_kws}

    for c in clusters:
        members = {str(r.get("keyword") or "").strip().lower() for r in (c.get("keywords") or [])}
        has_info = bool(members & info_set)
        has_money = bool(members & money_set)
        assert not (has_info and has_money), f"Mixed intent cluster: {members}"
        intents = {effective_intent_for_clustering(r) for r in (c.get("keywords") or [])}
        assert len(intents) <= 1

    # At least two distinct clusters (info group + money group)
    assert len(clusters) >= 2
