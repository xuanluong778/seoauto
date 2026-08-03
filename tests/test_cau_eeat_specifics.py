"""Tests nhận diện loại bài + context_guard cho eeat_specifics."""

from app.services.cau_seo_fix_engine import (
    _detect_article_type,
    _validate_eeat_specifics_context_guard,
)


def test_detect_knowledge_blog_from_keyword_research_title():
    atype, reason = _detect_article_type(
        title="Nghiên cứu từ khóa hiệu quả trong SEO",
        keyword="nghiên cứu từ khóa",
        slug="nghien-cuu-tu-khoa",
        post_url="https://example.com/nghien-cuu-tu-khoa/",
        category="SEO",
        content_html=(
            "<h2>Cách nghiên cứu từ khóa</h2><p>Hướng dẫn quy trình 5 bước.</p>"
            "<h2>Phân loại intent</h2><p>3 nhóm intent chính.</p>"
        ),
    )
    assert atype == "knowledge_blog"
    assert reason


def test_context_guard_rejects_service_stats_on_knowledge_blog():
    article = (
        "<h2>Cách nghiên cứu từ khóa</h2>"
        "<p>Quy trình gồm 5 bước nghiên cứu từ khóa cơ bản.</p>"
    )
    block = (
        '<section class="eeat-specifics">'
        "<p>Thời gian triển khai trung bình <strong>14 ngày</strong>.</p>"
        "<p>Chi phí từ <strong>8 triệu</strong> VNĐ.</p>"
        "</section>"
    )
    terms = {"nghien", "cuu", "khoa", "quy", "trinh"}
    ok, msg = _validate_eeat_specifics_context_guard(
        block_html=block,
        article_type="knowledge_blog",
        article_terms=terms,
        article_text=article,
        title="Nghiên cứu từ khóa hiệu quả trong SEO",
        keyword="nghiên cứu từ khóa",
        category="SEO",
        post_url="https://example.com/nghien-cuu-tu-khoa/",
    )
    assert not ok
    assert "triển khai" in msg.lower() or "blog kiến thức" in msg.lower() or "giá" in msg.lower()


def test_context_guard_accepts_sourced_stats_from_article():
    article = (
        "<h2>Search volume</h2>"
        "<p>Từ khóa có volume khoảng <strong>1.200</strong> lượt/tháng và độ cạnh tranh <strong>45%</strong>.</p>"
        "<p>Quy trình gồm <strong>5 bước</strong> trong <strong>3 ngày</strong> thực hành.</p>"
    )
    block = (
        '<section class="eeat-specifics">'
        "<p>Trong nghiên cứu từ khóa, volume có <strong>45%</strong> độ cạnh tranh và <strong>3 ngày</strong> thực hành.</p>"
        "</section>"
    )
    terms = {"nghien", "cuu", "khoa", "volume", "quy", "trinh"}
    ok, msg = _validate_eeat_specifics_context_guard(
        block_html=block,
        article_type="knowledge_blog",
        article_terms=terms,
        article_text=article,
        title="Nghiên cứu từ khóa",
        keyword="nghiên cứu từ khóa",
        category="SEO",
        post_url="https://example.com/nghien-cuu-tu-khoa/",
    )
    assert ok, msg
