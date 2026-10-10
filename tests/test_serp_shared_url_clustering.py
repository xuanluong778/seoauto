"""SERP shared-URL clustering rules (>=3 merge, 1–2 weak, 0 separate)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app.services.cluster_serp_overlap import (
    build_serp_merge_edges,
    build_serp_pair_intersections,
    classify_serp_pair_strength,
    cluster_by_serp_shared_urls,
    compute_cluster_shared_url_metrics,
    post_merge_orphan_groups_by_serp,
    serp_merge_min_shared_urls,
)
from app.services.keyword_clusterer import cluster_keywords


def _urls(prefix: str, n: int = 10) -> list[str]:
    return [f"https://{prefix}.com/page{i}" for i in range(n)]


def test_classify_pair_strength():
    assert classify_serp_pair_strength(3) == "merge"
    assert classify_serp_pair_strength(5) == "merge"
    assert classify_serp_pair_strength(2) == "weak"
    assert classify_serp_pair_strength(1) == "weak"
    assert classify_serp_pair_strength(0) == "none"


def test_merge_when_at_least_3_shared_urls():
    shared = _urls("shared", 3)
    sets = [
        set(shared + _urls("a", 7)),
        set(shared + _urls("b", 7)),
    ]
    groups, weak, pair_inter, meta = cluster_by_serp_shared_urls(2, sets, min_merge=3)
    assert len(groups) == 1
    assert len(groups[0]) == 2
    assert len(weak) == 0
    assert meta["merge_edges"] == 1
    assert pair_inter[(0, 1)] == 3


def test_separate_when_zero_shared_urls():
    sets = [set(_urls("a")), set(_urls("b"))]
    groups, weak, _, _ = cluster_by_serp_shared_urls(2, sets, min_merge=3)
    assert len(groups) == 2
    assert all(len(g) == 1 for g in groups)
    assert len(weak) == 0


def test_weak_relation_when_1_or_2_shared_not_merged():
    shared = _urls("shared", 2)
    sets = [
        set(shared + _urls("a", 8)),
        set(shared + _urls("b", 8)),
    ]
    pair_inter, _ = build_serp_pair_intersections(sets, fanout_cap=60)
    edges, weak = build_serp_merge_edges(pair_inter, min_merge=3)
    assert edges == []
    assert len(weak) == 1
    assert weak[0]["shared_urls"] == 2
    groups, _, _, _ = cluster_by_serp_shared_urls(2, sets, min_merge=3)
    assert len(groups) == 2


def test_similar_text_high_confidence_skips_serp():
    """Similar phrases cluster locally; SERP is not fetched for every keyword."""
    os_environ = {"KEYWORD_CLUSTER_MERGE_SIMILAR": "0", "SERP_FETCH_ENABLED": "1", "BENCH_FAST": "1"}
    fake_fetch = MagicMock(return_value={"serp_urls": []})

    with patch.dict("os.environ", os_environ, clear=False):
        with patch("app.services.keyword_clusterer.fetch_serp_for_keyword", side_effect=fake_fetch):
            clusters = cluster_keywords(
                [
                    {"keyword": "dịch vụ seo", "source": "t"},
                    {"keyword": "dịch vụ seo uy tín", "source": "t"},
                ],
                fetch_serp=True,
            )
    assert len(clusters) >= 1
    fake_fetch.assert_not_called()


def test_merge_integration_with_mocked_serp():
    shared = [f"https://example.com/p{i}" for i in range(3)]
    urls_a = shared + [f"https://example.com/a{i}" for i in range(7)]
    urls_b = shared + [f"https://example.com/b{i}" for i in range(7)]

    def fake_fetch(q: str, **kwargs):
        if q == "kw a":
            return {"serp_urls": urls_a}
        if q == "kw b":
            return {"serp_urls": urls_b}
        return {"serp_urls": []}

    with patch.dict("os.environ", {"KEYWORD_CLUSTER_MERGE_SIMILAR": "0", "BENCH_FAST": "1"}, clear=False):
        with patch("app.services.keyword_clusterer.fetch_serp_for_keyword", side_effect=fake_fetch):
            clusters = cluster_keywords(
                [{"keyword": "kw a", "source": "t"}, {"keyword": "kw b", "source": "t"}],
                fetch_serp=True,
            )
    assert len(clusters) == 1
    assert clusters[0].get("shared_urls_count", 0) >= serp_merge_min_shared_urls()


def test_dao_tao_seo_training_keywords_merge_root():
    """Head term 'đào tạo seo' must not stand alone when SERP overlap >= 3 with variants."""
    shared = [f"https://shared-seo.vn/p{i}" for i in range(5)]
    training_kws = [
        "đào tạo seo",
        "đào tạo seo chuyên sâu",
        "đào tạo seo uy tín",
        "đào tạo seo chuyên nghiệp",
        "đào tạo seo thực chiến",
        "đào tạo seo online",
        "trung tâm đào tạo seo",
    ]
    other_kws = ["khóa học seo"]

    def _serp_for_kw(kw: str) -> list[str]:
        base = shared + [f"https://extra.vn/{abs(hash(kw)) % 97}/a", f"https://extra.vn/{abs(hash(kw)) % 97}/b"]
        if kw == "khóa học seo":
            return [f"https://khoahoc.vn/x{i}" for i in range(10)]
        return (base + [f"https://tail.vn/{i}" for i in range(10)])[:10]

    def fake_fetch(q: str, **kwargs):
        return {"serp_urls": _serp_for_kw(q), "source": "test"}

    all_kws = training_kws + other_kws
    with patch.dict("os.environ", {"KEYWORD_CLUSTER_MERGE_SIMILAR": "0", "BENCH_FAST": "1"}, clear=False):
        with patch("app.services.keyword_clusterer.fetch_serp_for_keyword", side_effect=fake_fetch):
            clusters = cluster_keywords([{"keyword": k, "source": "t"} for k in all_kws], fetch_serp=True)

    root_cluster = None
    for c in clusters:
        members = {str(r.get("keyword") or "").strip().lower() for r in (c.get("keywords") or [])}
        if "đào tạo seo" in members:
            root_cluster = c
            break

    assert root_cluster is not None, "đào tạo seo must be in a cluster"
    root_members = {str(r.get("keyword") or "").strip().lower() for r in (root_cluster.get("keywords") or [])}
    assert len(root_members) >= 4, f"expected training variants merged, got {root_members}"
    # High token overlap → local semantic cluster; SERP is optional (cost-first).
    if int(root_cluster.get("shared_urls_count") or 0) > 0:
        assert root_cluster.get("shared_urls_count", 0) >= 3
    assert "đào tạo seo chuyên sâu" in root_members

    khoa_clusters = [
        c for c in clusters
        if any(str(r.get("keyword") or "").strip().lower() == "khóa học seo" for r in (c.get("keywords") or []))
    ]
    assert len(khoa_clusters) == 1
    khoa_members = {str(r.get("keyword") or "").strip().lower() for r in (khoa_clusters[0].get("keywords") or [])}
    assert "đào tạo seo" not in khoa_members


def test_post_merge_orphan_attaches_head_term():
    from app.services.cluster_serp_overlap import post_merge_orphan_groups_by_serp

    shared = {f"https://x.com/p{i}" for i in range(5)}
    url_sets = [
        shared | {f"https://a.com/{i}" for i in range(5)},
        shared | {f"https://b.com/{i}" for i in range(5)},
        {f"https://solo.com/{i}" for i in range(10)},
    ]
    # solo shares 3 URLs with set 0 via manual overlap
    url_sets[2] = shared | {f"https://solo.com/x"}

    groups = [[0, 1], [2]]
    out = post_merge_orphan_groups_by_serp(groups, url_sets, min_merge=3)
    assert len(out) == 1
    assert len(out[0]) == 3


def test_singleton_shared_urls_count_is_zero():
    metrics = compute_cluster_shared_url_metrics([0], [{f"https://only.com/{i}" for i in range(10)}], {})
    assert metrics["shared_urls_count"] == 0


def test_semantic_fallback_only_without_serp():
    os.environ_patch = {
        "KEYWORD_CLUSTER_SCALABLE_N": "2",
        "KEYWORD_CLUSTER_INTENT_STRICT": "1",
        "SERP_FETCH_ENABLED": "0",
        "KEYWORD_CLUSTER_MERGE_SIMILAR": "0",
        "BENCH_FAST": "1",
    }
    with patch.dict("os.environ", os.environ_patch, clear=False):
        clusters = cluster_keywords(
            [
                {"keyword": "cách sửa laptop", "source": "t"},
                {"keyword": "hướng dẫn sửa laptop", "source": "t"},
            ],
            fetch_serp=False,
        )
    assert len(clusters) == 1
    ex = (clusters[0].get("explain") or {})
    assert "semantic" in str(ex.get("clustering_method") or "")
