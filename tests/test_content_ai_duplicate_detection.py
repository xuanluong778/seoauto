"""Content AI duplicate / same-intent detection."""

from __future__ import annotations

from app.services.content_ai_duplicate_detection import (
    MSG_EXACT,
    MSG_SAME_INTENT,
    ExistingArticleRef,
    check_keywords_for_duplicates,
    classify_content_purpose,
    extract_location_key,
    extract_service_core,
    find_duplicate_for_keyword,
    locations_compatible,
    normalize_keyword,
)


def _ref(keyword: str, *, title: str = "", url: str = "", project_id: str = "p1") -> ExistingArticleRef:
    return ExistingArticleRef(
        keyword=keyword,
        title=title or keyword,
        url=url,
        source="published" if url else "content_ai",
        project_id=project_id,
    )


def test_exact_primary_keyword_match():
    existing = [_ref("sửa máy tính quận 9", title="Sửa máy tính Quận 9", url="https://ex.com/a")]
    match = find_duplicate_for_keyword("Sửa Máy Tính Quận 9", existing)
    assert match is not None
    assert match.match_type == "exact"
    assert match.message == MSG_EXACT
    assert match.existing.url == "https://ex.com/a"


def test_exact_match_on_published_title():
    """WP corpus often stores full title as keyword; query may be the same title."""
    title = "Sửa lỗi máy tính không nhận chuột nhanh chóng và hiệu quả"
    existing = [_ref(title, title=title, url="https://ex.com/wp")]
    match = find_duplicate_for_keyword(title, existing)
    assert match is not None
    assert match.match_type == "exact"
    assert match.message == MSG_EXACT


def test_short_keyword_contained_in_long_wp_title():
    """Primary keyword that is a substantial substring of a published title → same intent."""
    title = "Sửa lỗi máy tính không nhận chuột nhanh chóng và hiệu quả"
    existing = [_ref(title, title=title, url="https://ex.com/wp")]
    match = find_duplicate_for_keyword("sửa lỗi máy tính không nhận chuột", existing)
    assert match is not None
    assert match.match_type == "same_intent"
    assert match.message == MSG_SAME_INTENT


def test_same_intent_english_district_9_example():
    existing = [_ref("home computer repair in District 9", title="Home Computer Repair D9")]
    match = find_duplicate_for_keyword("trusted computer repair in District 9", existing)
    assert match is not None
    assert match.match_type == "same_intent"
    assert match.message == MSG_SAME_INTENT


def test_same_intent_vietnamese_local_service():
    existing = [_ref("sửa máy tính quận 9", title="Sửa máy tính Q9")]
    match = find_duplicate_for_keyword("sửa máy tính uy tín quận 9", existing)
    assert match is not None
    assert match.match_type == "same_intent"


def test_different_location_not_duplicate():
    existing = [_ref("sửa máy tính quận 9")]
    match = find_duplicate_for_keyword("sửa máy tính quận 7", existing)
    assert match is None


def test_different_purpose_pricing_vs_service():
    existing = [_ref("sửa máy tính quận 9")]
    match = find_duplicate_for_keyword("bảng giá sửa máy tính quận 9", existing)
    assert match is None


def test_different_purpose_guide_vs_service():
    existing = [_ref("computer repair in District 9")]
    match = find_duplicate_for_keyword("how to repair computer in District 9", existing)
    assert match is None


def test_different_purpose_faq_vs_service():
    existing = [_ref("sửa máy tính quận 9")]
    match = find_duplicate_for_keyword("faq sửa máy tính quận 9", existing)
    assert match is None


def test_cross_user_isolation_via_corpus_only():
    """Detector only sees the corpus passed in — callers must scope by user_id."""
    user_a = [_ref("sửa máy tính quận 9", project_id="a1")]
    match_b = find_duplicate_for_keyword("sửa máy tính quận 9", [])
    assert match_b is None
    match_a = find_duplicate_for_keyword("sửa máy tính quận 9", user_a)
    assert match_a is not None
    assert match_a.match_type == "exact"


def test_check_keywords_batch_with_mocked_corpus(monkeypatch):
    corpus = [
        _ref("home computer repair in District 9", title="Home repair D9"),
        _ref("seo training online", title="SEO course"),
    ]
    embed_calls: list[list[str]] = []

    def _fake_collect(**kwargs):
        return corpus

    def _fake_embed(keywords, *, use_cache=True):
        embed_calls.append(list(keywords))
        return {}

    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.collect_existing_articles",
        _fake_collect,
    )
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.embed_keywords",
        _fake_embed,
    )
    rows = check_keywords_for_duplicates(
        [
            "home computer repair in District 9",
            "trusted computer repair in District 9",
            "seo pricing guide",
            "computer repair in District 1",
        ],
        user_id=42,
        db=None,
    )
    assert rows[0]["is_duplicate"] is True
    assert rows[0]["match_type"] == "exact"
    assert rows[1]["is_duplicate"] is True
    assert rows[1]["match_type"] == "same_intent"
    assert rows[2]["is_duplicate"] is False
    assert rows[3]["is_duplicate"] is False
    # Exact + strong structural same-intent must not call embedding.
    assert embed_calls == []


def test_exact_match_skips_embedding(monkeypatch):
    corpus = [_ref("sửa máy tính quận 9", title="Sửa máy tính Quận 9")]
    embed_calls: list[list[str]] = []

    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.collect_existing_articles",
        lambda **kwargs: corpus,
    )
    monkeypatch.setattr(
        "app.services.content_ai_duplicate_detection.embed_keywords",
        lambda keywords, *, use_cache=True: embed_calls.append(list(keywords)) or {},
    )
    rows = check_keywords_for_duplicates(
        ["Sửa Máy Tính Quận 9"],
        user_id=7,
        db=None,
        include_connected_sites=False,
    )
    assert rows[0]["match_type"] == "exact"
    assert embed_calls == []


def test_location_and_purpose_helpers():
    assert extract_location_key("computer repair in District 9") == "district 9"
    assert extract_location_key("sửa máy tính quận 9") == "district 9"
    assert locations_compatible("district 9", "district 7") is False
    assert classify_content_purpose("bảng giá sửa máy tính") == "pricing"
    assert classify_content_purpose("hướng dẫn sửa máy tính") == "guide"
    assert classify_content_purpose("faq sửa máy tính") == "faq"
    assert "computer" in extract_service_core("trusted home computer repair in District 9")
    assert "repair" in extract_service_core("trusted home computer repair in District 9")
    assert normalize_keyword("  Sửa  Máy  ") == "sửa máy"


def test_wp_title_text_strips_html():
    from app.services.content_ai_duplicate_detection import _wp_title_text

    assert _wp_title_text({"rendered": "<b>Sửa máy tính</b> Q9"}) == "Sửa máy tính Q9"
    assert _wp_title_text("plain") == "plain"


def test_wp_rest_fetch_posts_maps_title_and_slug(monkeypatch):
    from app.services import content_ai_duplicate_detection as mod

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return [
                {
                    "id": 1,
                    "link": "https://ex.com/sua-loi-may-tinh-khong-nhan-chuot/",
                    "slug": "sua-loi-may-tinh-khong-nhan-chuot",
                    "title": {"rendered": "Sửa lỗi máy tính không nhận chuột"},
                }
            ]

    # Public REST path (no credentials) must still work.
    monkeypatch.setattr(mod, "_resolve_wp_site_credentials", lambda user_id, site_base: None)

    def _fake_wp_get_json(path, **kwargs):
        return _Resp(), "https://ex.com"

    import sys
    import types

    fake_wp = types.ModuleType("app.services.wp_connect")
    fake_wp.normalize_wp_base_url = lambda u: str(u or "").rstrip("/")
    fake_wp.wp_get_json = _fake_wp_get_json
    monkeypatch.setitem(sys.modules, "app.services.wp_connect", fake_wp)

    refs = mod._wp_rest_fetch_posts(user_id=1, site_base="https://ex.com", max_pages=1)
    titles = {r.title for r in refs}
    keywords = {normalize_keyword(r.keyword) for r in refs}
    assert "Sửa lỗi máy tính không nhận chuột" in titles
    assert normalize_keyword("Sửa lỗi máy tính không nhận chuột") in keywords
    assert normalize_keyword("sua loi may tinh khong nhan chuot") in keywords
    assert all(r.source == "published" for r in refs)


def test_collect_connected_uses_wp_when_il_empty(monkeypatch):
    from app.services import content_ai_duplicate_detection as mod

    monkeypatch.setattr(mod, "_owned_site_bases", lambda user_id, **kwargs: ["https://ex.com"])
    monkeypatch.setattr(mod, "_collect_il_published_articles", lambda **kwargs: [])
    monkeypatch.setattr(
        mod,
        "_wp_rest_fetch_posts",
        lambda **kwargs: [
            _ref(
                "Sửa lỗi máy tính không nhận chuột",
                title="Sửa lỗi máy tính không nhận chuột",
                url="https://ex.com/a/",
            )
        ],
    )
    refs = mod._collect_connected_site_articles(user_id=1, db=None, target_website="https://ex.com")
    assert len(refs) == 1
    assert refs[0].url == "https://ex.com/a/"


def test_wp_search_enrichment_adds_older_post(monkeypatch):
    from app.services import content_ai_duplicate_detection as mod

    monkeypatch.setattr(mod, "_owned_site_bases", lambda user_id, **kwargs: ["https://ex.com"])
    monkeypatch.setattr(
        mod,
        "_wp_rest_fetch_posts",
        lambda **kwargs: [
            _ref(
                "Sửa lỗi máy tính không nhận chuột",
                title="Sửa lỗi máy tính không nhận chuột",
                url="https://ex.com/old/",
            )
        ],
    )
    enriched = mod._enrich_corpus_with_wp_keyword_search(
        [],
        ["sửa lỗi máy tính không nhận chuột"],
        user_id=1,
        target_website="https://ex.com",
    )
    assert len(enriched) == 1
    match = find_duplicate_for_keyword("sửa lỗi máy tính không nhận chuột", enriched)
    assert match is not None
    assert match.match_type == "exact"
    assert match.message == MSG_EXACT


def test_check_keywords_uses_wp_search_when_connected(monkeypatch):
    from app.services import content_ai_duplicate_detection as mod

    monkeypatch.setattr(mod, "collect_existing_articles", lambda **kwargs: [])
    monkeypatch.setattr(mod, "embed_keywords", lambda keywords, *, use_cache=True: {})
    monkeypatch.setattr(
        mod,
        "_enrich_corpus_with_wp_keyword_search",
        lambda existing, keywords, **kwargs: [
            _ref(
                "sửa lỗi máy tính không nhận chuột",
                title="Sửa lỗi máy tính không nhận chuột",
                url="https://itsieuviet.com/x/",
            )
        ],
    )
    rows = check_keywords_for_duplicates(
        ["sửa lỗi máy tính không nhận chuột"],
        user_id=1,
        db=None,
        target_website="https://itsieuviet.com",
        include_connected_sites=True,
    )
    assert rows[0]["is_duplicate"] is True
    assert rows[0]["match_type"] == "exact"
    assert rows[0]["message"] == MSG_EXACT

