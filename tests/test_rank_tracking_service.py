"""Rank tracking service tests."""

from __future__ import annotations

from app.services.rank_tracking_service import domain_matches, find_domain_rank, normalize_domain


def test_normalize_domain():
    assert normalize_domain("https://www.SEOAuto.vn/path") == "seoauto.vn"
    assert normalize_domain("seoauto.vn") == "seoauto.vn"


def test_domain_matches():
    assert domain_matches("www.seoauto.vn", "seoauto.vn")
    assert domain_matches("blog.seoauto.vn", "seoauto.vn")
    assert not domain_matches("example.com", "seoauto.vn")


def test_find_domain_rank():
    items = [
        {"type": "organic", "rank_absolute": 1, "rank_group": 1, "domain": "example.com", "url": "https://example.com", "title": "A"},
        {"type": "organic", "rank_absolute": 5, "rank_group": 5, "domain": "www.seoauto.vn", "url": "https://www.seoauto.vn/x", "title": "SEOAuto"},
        {"type": "paid", "rank_absolute": 2, "domain": "ads.com", "url": "https://ads.com"},
    ]
    match = find_domain_rank(items, "seoauto.vn")
    assert match is not None
    assert match["rank_absolute"] == 5
    assert match["url"] == "https://www.seoauto.vn/x"
    assert find_domain_rank(items, "missing.com") is None
