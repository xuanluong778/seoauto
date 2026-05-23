"""Content AI SEO score (rule-based, read-only)."""

from app.services.content_ai_score import evaluate_content_score

_SAMPLE_HTML = """
<h1>Dịch vụ SEO tại Hà Nội — tư vấn chuyên sâu</h1>
<p>Dịch vụ SEO tại Hà Nội giúp doanh nghiệp tăng trưởng bền vững. Theo kinh nghiệm triển khai,
bạn cần lộ trình rõ từng bước và ví dụ thực tế.</p>
<h2>Lợi ích khi thuê dịch vụ SEO</h2>
<p>""" + " ".join(["nội dung"] * 80) + """</p>
<ul><li>Bước 1: audit</li><li>Bước 2: tối ưu</li></ul>
<h2>Quy trình triển khai</h2>
<p>""" + " ".join(["chi tiết"] * 90) + """</p>
<table><tr><th>Hạng mục</th><th>Ghi chú</th></tr><tr><td>On-page</td><td>Title meta</td></tr></table>
<h2>Câu hỏi thường gặp</h2>
<p>Giá dịch vụ phụ thuộc quy mô — liên hệ để nhận báo giá chi tiết.</p>
<p>Liên hệ tư vấn ngay hôm nay qua hotline.</p>
<img src="/a.jpg" alt="Dịch vụ SEO tại Hà Nội minh họa quy trình" />
<a href="https://example.com/blog/seo-onpage">SEO on-page</a>
<a href="https://wikipedia.org/wiki/Search_engine_optimization">Wikipedia</a>
<script type="application/ld+json">{"@type":"Article","headline":"SEO"}</script>
"""


def test_empty_html_low_score_and_missing():
    out = evaluate_content_score(
        title="Test",
        primary_keyword="seo",
        html_content="",
    )
    assert out["total_score"] <= 15
    assert out["grade"] == "F"
    assert any("HTML" in m or "nội dung" in m.lower() for m in out["missing_items"])


def test_rich_article_scores_reasonably():
    out = evaluate_content_score(
        title="Dịch vụ SEO tại Hà Nội — tư vấn chuyên sâu",
        slug="dich-vu-seo-tai-ha-noi",
        meta_description="Dịch vụ SEO tại Hà Nội " + "x" * 120,
        primary_keyword="dịch vụ seo tại hà nội",
        secondary_keywords="seo on-page, audit seo",
        html_content=_SAMPLE_HTML,
        target_word_count=800,
        target_website="https://example.com",
    )
    assert out["total_score"] >= 45
    assert out["grade"] in {"A", "B", "C", "D", "F"}
    assert "detail_scores" in out
    assert set(out["detail_scores"].keys()) >= {
        "search_intent",
        "title_meta_slug",
        "heading_structure",
        "keyword_semantic",
        "content_depth",
        "eeat_helpful",
        "internal_link",
        "image_alt",
        "readability",
        "cta",
    }
    assert out["scoring_mode"] == "rule_based"


def test_malformed_html_does_not_crash():
    out = evaluate_content_score(
        title="T",
        html_content="<p>open <<<< unclosed",
        primary_keyword="test",
    )
    assert isinstance(out["total_score"], int)
    assert 0 <= out["total_score"] <= 100


def test_internal_links_planned_without_html():
    out = evaluate_content_score(
        title="Tiêu đề đủ dài cho seo test keyword",
        meta_description="Mô tả meta " * 10,
        primary_keyword="seo test",
        html_content="<h1>SEO test</h1><p>" + "word " * 200 + "</p>",
        internal_links=[{"url": "https://example.com/a", "anchor_text": "bài liên quan"}],
    )
    warns = " ".join(out["warning_items"]).lower()
    assert "kế hoạch" in warns or out["detail_scores"]["internal_link"]["score"] >= 20
