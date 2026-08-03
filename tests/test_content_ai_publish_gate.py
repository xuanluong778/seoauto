"""Publish quality gate (soft) for Content AI."""

from app.services.content_ai_publish_gate import evaluate_publish_gate

_GOOD_HTML = """
<h1>Dịch vụ SEO tại Hà Nội chuyên nghiệp</h1>
<p>Dịch vụ SEO tại Hà Nội giúp doanh nghiệp tăng trưởng. Theo kinh nghiệm, bạn cần lộ trình rõ.</p>
<h2>Lợi ích dịch vụ SEO</h2>
<p>""" + " ".join(["chi tiết"] * 120) + """</p>
<h2>Quy trình triển khai</h2>
<p>""" + " ".join(["bước"] * 120) + """</p>
<h2>Câu hỏi thường gặp</h2>
<p>Giá phụ thuộc quy mô.</p>
<p>Liên hệ tư vấn ngay để nhận báo giá qua hotline.</p>
<img src="/a.jpg" alt="Dịch vụ SEO tại Hà Nội minh họa quy trình on-page" />
<a href="https://example.com/blog/seo">SEO on-page</a>
<a href="https://example.com/dich-vu">Dịch vụ SEO</a>
<script type="application/ld+json">{"@type":"Article","headline":"SEO"}</script>
"""


def test_blocker_when_missing_required_fields():
    out = evaluate_publish_gate(
        title="",
        meta_description="",
        slug="",
        html_content="",
        primary_keyword="",
    )
    assert out["severity"] == "blocker"
    assert out["can_publish"] is False
    assert len(out["blockers"]) >= 3


def test_blocker_empty_html():
    out = evaluate_publish_gate(
        title="Tiêu đề đủ dài cho bài viết SEO test",
        meta_description="Mô tả meta " * 12,
        slug="seo-test",
        primary_keyword="seo test",
        html_content="",
    )
    assert out["severity"] == "blocker"
    assert any("html" in b.lower() or "rỗng" in b.lower() for b in out["blockers"])


def test_warning_low_score_with_content():
    out = evaluate_publish_gate(
        title="SEO",
        meta_description="x",
        slug="seo",
        primary_keyword="seo",
        html_content="<h1>SEO</h1><p>ngắn.</p>",
        target_word_count=2000,
    )
    assert out["severity"] in {"warning", "blocker"}
    assert out["can_publish"] is False
    assert out["total_score"] < 75


def test_pass_or_warning_with_rich_article():
    out = evaluate_publish_gate(
        title="Dịch vụ SEO tại Hà Nội — tư vấn chuyên sâu",
        slug="dich-vu-seo-tai-ha-noi",
        meta_description="Dịch vụ SEO tại Hà Nội " + "mô tả " * 25,
        primary_keyword="dịch vụ seo tại hà nội",
        secondary_keywords="seo on-page",
        html_content=_GOOD_HTML,
        target_word_count=600,
        target_website="https://example.com",
        publish_target="wordpress",
        featured_image_url="https://example.com/img.jpg",
    )
    assert out["severity"] in {"pass", "warning"}
    assert "total_score" in out
    assert "blockers" in out
    assert "required_fixes" in out
    assert out["publish_target"] == "wordpress"


def test_invalid_json_ld_warning():
    out = evaluate_publish_gate(
        title="Tiêu đề bài viết SEO test keyword đủ dài",
        meta_description="Meta description " * 10,
        slug="seo-test-kw",
        primary_keyword="seo test",
        html_content=(
            "<h1>SEO test keyword</h1><p>"
            + "word " * 200
            + "</p><a href=\"https://example.com/a\">link</a>"
            + '<script type="application/ld+json">{ broken</script>'
            + "<p>Liên hệ hotline để tư vấn.</p>"
        ),
        target_website="https://example.com",
    )
    assert any("JSON-LD" in w for w in out["warnings"]) or out["severity"] != "pass"
