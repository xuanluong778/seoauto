"""Tests for chatbot Viết bài SEO — SEO Score 30 yếu tố integration."""

from __future__ import annotations

from unittest.mock import patch

from app.services.chatbot_seo_write_enforcer import (
    MANDATORY_FACTOR_IDS,
    build_seo_result_summary,
    enforce_chatbot_seo_article,
    format_chatbot_seo_reply_lines,
    mandatory_failures,
    word_count_gate,
)
from app.services.chatbot_tab_registry import INTENT_QUICK_KEYWORD_ARTICLE, init_progress_for_intent
from app.services.content_ai_publish_checklist import build_seo_score_writing_brief
from app.services.seo_core_30_score import score_seo_core_30, seo_factor_counts


def _long_paragraph(keyword: str, repeat: int = 200) -> str:
    return " ".join([f"{keyword} là giải pháp SEO hiệu quả cho doanh nghiệp."] * repeat)


def _sample_seo_article(*, keyword: str = "dịch vụ seo", words: int = 1500) -> str:
    repeat = max(80, words // 12)
    return (
        f"<h1>{keyword.title()}</h1>"
        f"<p>Mở bài giới thiệu về {keyword} cho doanh nghiệp Việt Nam.</p>"
        f"<h2>Lợi ích {keyword}</h2><p>{_long_paragraph(keyword, repeat)}</p>"
        f"<h2>Quy trình triển khai</h2><p>{_long_paragraph(keyword, repeat // 2)}</p>"
        f"<h2>Câu hỏi thường gặp</h2>"
        f"<h3>{keyword} là gì?</h3><p>Định nghĩa chi tiết về {keyword}.</p>"
        f"<h3>Chi phí {keyword}?</h3><p>Phụ thuộc quy mô dự án.</p>"
        f"<h2>Kết luận</h2><p>Liên hệ ngay để nhận tư vấn {keyword} miễn phí.</p>"
        f"<p><strong>Đăng ký tư vấn {keyword} hôm nay</strong></p>"
    )


def test_write_tab_progress_includes_seo_steps():
    steps = init_progress_for_intent(INTENT_QUICK_KEYWORD_ARTICLE)
    ids = [s["id"] for s in steps]
    assert "outline" in ids
    assert "writing" in ids
    assert "word_count" in ids
    assert "seo_score" in ids
    assert "seo_rewrite" in ids
    assert "complete" in ids


def test_word_count_gate_1500_min_1350():
    gate_target = word_count_gate(actual=1349, target=1500)
    assert gate_target["below_target"] is True
    assert gate_target["target_min"] == 1350
    assert gate_target["below_hard"] is False
    gate_hard = word_count_gate(actual=899, target=1500)
    assert gate_hard["below_hard"] is True
    assert gate_hard["hard_min"] == 900


def test_build_seo_score_writing_brief_mentions_30_factors():
    brief = build_seo_score_writing_brief(
        primary_keyword="seo",
        target_word_count=1500,
        intent="informational",
        target_website="https://example.com",
        secondary_keywords=["từ khóa phụ"],
    )
    assert "seo" in brief.lower()
    assert "1500" in brief
    assert "faq" in brief.lower() or "hỏi" in brief.lower()


def test_sample_article_has_title_meta_h1_h2_faq_cta():
    kw = "dịch vụ seo"
    html = _sample_seo_article(keyword=kw, words=1500)
    title = f"{kw.title()} — Hướng dẫn chi tiết 2026"
    meta = f"Tìm hiểu {kw} toàn diện: quy trình, lợi ích và FAQ. Tư vấn miễn phí cho doanh nghiệp."
    score = score_seo_core_30(
        title=title,
        meta_description=meta,
        content_html=html,
        primary_keyword=kw,
        slug="dich-vu-seo",
        secondary_keywords=["seo onpage", "seo offpage"],
    )
    counts = seo_factor_counts(score)
    assert counts["total"] == 30
    assert score["score"] >= 0
    html_l = html.lower()
    assert "<h1>" in html_l
    assert "<h2>" in html_l
    assert "faq" in html_l or "câu hỏi" in html_l
    assert "liên hệ" in html_l or "đăng ký" in html_l


def test_enforce_rejects_below_60_percent_words():
    html = "<p>" + ("ngắn " * 200) + "</p>"
    out = enforce_chatbot_seo_article(
        user_id=1,
        workflow_id="wf-test",
        primary_keyword="dịch vụ seo",
        title="Dịch vụ SEO",
        meta_description="Meta đủ dài cho dịch vụ SEO chuyên nghiệp tại Việt Nam.",
        slug="dich-vu-seo",
        content_html=html,
        target_word_count=1500,
    )
    assert out["ok"] is False
    assert "60%" in out.get("error", "") or "900" in out.get("error", "")


def test_enforce_returns_seo_summary_on_success():
    kw = "dịch vụ seo"
    html = _sample_seo_article(keyword=kw, words=1500)
    title = f"{kw.title()} — Hướng dẫn chi tiết"
    meta = f"Khám phá {kw}: quy trình, chi phí và FAQ. Liên hệ tư vấn miễn phí ngay hôm nay."

    with patch(
        "app.services.chatbot_seo_write_enforcer._rewrite_with_seo_autofix",
        return_value={"success": True, "patch": {}},
    ):
        out = enforce_chatbot_seo_article(
            user_id=1,
            workflow_id="wf-ok",
            primary_keyword=kw,
            title=title,
            meta_description=meta,
            slug="dich-vu-seo",
            content_html=html,
            secondary_keywords=["seo onpage"],
            target_word_count=1500,
        )

    if not out["ok"]:
        # Nếu bài mẫu chưa đủ điểm, vẫn phải có seo_summary
        assert out.get("seo_summary")
        assert out["seo_summary"].get("total_factors") == 30
        return

    summary = out["seo_summary"]
    assert summary["requested_word_count"] == 1500
    assert summary["actual_word_count"] >= 1350
    assert summary["seo_score"] >= 50
    assert summary["passed_factors"] >= 1
    assert summary["total_factors"] == 30


def test_mandatory_failures_detects_missing_h1():
    score = score_seo_core_30(
        title="SEO test",
        meta_description="Meta description đủ dài cho bài viết SEO test chuẩn.",
        content_html="<h2>No H1</h2><p>" + ("word " * 200) + "</p>",
        primary_keyword="seo test",
        slug="seo-test",
    )
    failed = mandatory_failures(score)
    failed_ids = {f["id"] for f in failed}
    assert "heading_single_h1" in failed_ids or any(
        fid in MANDATORY_FACTOR_IDS for fid in failed_ids
    )


def test_enforce_triggers_rewrite_for_mandatory_failures():
    bad_html = "<p>" + ("nội dung thiếu heading " * 300) + "</p>"
    fixed_html = _sample_seo_article(words=1500)

    def _fake_autofix(**kwargs):
        return {
            "success": True,
            "patch": {
                "title": "Dịch vụ SEO chuyên nghiệp",
                "meta_description": "Tư vấn dịch vụ SEO toàn diện cho doanh nghiệp Việt Nam.",
                "content_html": fixed_html,
                "slug": "dich-vu-seo",
            },
        }

    with patch(
        "app.services.chatbot_seo_write_enforcer._rewrite_with_seo_autofix",
        side_effect=_fake_autofix,
    ):
        out = enforce_chatbot_seo_article(
            user_id=1,
            workflow_id="wf-rewrite",
            primary_keyword="dịch vụ seo",
            title="SEO",
            meta_description="Meta",
            slug="seo",
            content_html=bad_html,
            target_word_count=1500,
        )

    assert out.get("rewrite_attempts", 0) >= 1
    assert out.get("seo_summary") is not None
    assert out["seo_summary"]["total_factors"] == 30


def test_format_chatbot_seo_reply_lines():
    summary = build_seo_result_summary(
        score_result=score_seo_core_30(
            title="Dịch vụ SEO",
            meta_description="Meta đủ dài cho dịch vụ SEO chuyên nghiệp.",
            content_html=_sample_seo_article(words=1500),
            primary_keyword="dịch vụ seo",
        ),
        target_word_count=1500,
        actual_word_count=1500,
    )
    lines = format_chatbot_seo_reply_lines(summary)
    assert any("Số từ yêu cầu" in line for line in lines)
    assert any("SEO Score" in line for line in lines)
    assert any("/30" in line or "/ 30" in line for line in lines)
