"""Content Gap analysis for Content AI."""

from app.services.content_ai_content_gap import evaluate_content_gap

_RICH_HTML = """
<h1>Dịch vụ SEO tại Hà Nội</h1>
<p>Dịch vụ SEO tại Hà Nội giúp doanh nghiệp phát triển. Ví dụ: audit on-page cho shop online.</p>
<h2>Quy trình triển khai SEO</h2>
<p>""" + " ".join(["bước chi tiết"] * 90) + """</p>
<ul><li>Bước 1 audit</li><li>Bước 2 tối ưu</li></ul>
<h2>Bảng giá và yếu tố chi phí</h2>
<table><tr><th>Hạng mục</th><th>Ghi chú</th></tr><tr><td>On-page</td><td>Chi phí</td></tr></table>
<h2>Câu hỏi thường gặp</h2>
<p>SEO tại Hà Nội mất bao lâu? Tùy quy mô dự án.</p>
<p>Liên hệ hotline để nhận báo giá và tư vấn miễn phí.</p>
<a href="https://example.com/blog/seo-onpage">bài SEO on-page</a>
<a href="https://example.com/dich-vu-seo">dịch vụ SEO</a>
"""

_BRIEF = {
    "outline": "## Quy trình triển khai SEO\n## Bảng giá\n## FAQ\n## Liên hệ CTA",
    "required_entities": ["dịch vụ seo tại hà nội", "seo on-page", "audit seo"],
    "faq_questions": [
        "Chi phí dịch vụ SEO tại Hà Nội?",
        "Quy trình SEO gồm mấy bước?",
    ],
    "internal_link_plan": [
        {"url": "https://example.com/blog/seo-onpage", "anchor_suggestion": "SEO on-page"},
        {"url": "https://example.com/missing-page", "anchor_suggestion": "Trang thiếu"},
    ],
    "recommended_word_count": 800,
}


def test_empty_html_poor_gap():
    out = evaluate_content_gap(html_content="", primary_keyword="seo")
    assert out["gap_score"] <= 20
    assert out["severity"] == "poor"
    assert out["missing_sections"]


def test_rich_article_good_gap():
    out = evaluate_content_gap(
        html_content=_RICH_HTML,
        primary_keyword="dịch vụ seo tại hà nội",
        secondary_keywords="seo on-page",
        content_brief=_BRIEF,
        target_word_count=700,
        target_website="https://example.com",
        internal_links=[{"url": "https://example.com/blog/seo-onpage"}],
    )
    assert out["gap_score"] >= 45
    assert out["severity"] in {"good", "warning"}
    assert "https://example.com/missing-page" in " ".join(out["missing_internal_links"])


def test_missing_entities_reported():
    out = evaluate_content_gap(
        html_content="<h1>Test</h1><p>ngắn.</p>",
        primary_keyword="seo marketing",
        secondary_keywords="audit seo, content gap",
        content_brief={"required_entities": ["seo marketing", "audit seo", "content gap"]},
    )
    assert len(out["missing_entities"]) >= 2


def test_missing_faq_and_cta():
    html = "<h1>SEO test</h1><p>" + "word " * 120 + "</p><h2>Phần chính</h2><p>" + "chi tiết " * 80 + "</p>"
    out = evaluate_content_gap(
        html_content=html,
        primary_keyword="seo test",
        content_brief={"faq_questions": ["SEO test là gì?", "Giá bao nhiêu?"]},
    )
    assert out["missing_faq"]
    assert out["missing_cta"]
