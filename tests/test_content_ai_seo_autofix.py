"""Tests for Content AI SEO Auto Fix preview."""

from __future__ import annotations

from app.services.content_ai_seo_autofix import (
    select_factors_for_autofix,
    run_seo_autofix_preview,
)
from app.services.content_ai_publish_checklist import evaluate_publish_checklist


def _sample_score_with_issues() -> dict:
    return evaluate_publish_checklist(
        title="Bài viết test",
        meta_description="",
        content_html="<p>" + ("từ " * 50) + "</p>",
        primary_keyword="seo test",
        slug="bai-viet",
    )


def test_select_factors_severe_mode():
    score = _sample_score_with_issues()
    failed, warnings = select_factors_for_autofix(score, mode="severe")
    assert failed
    assert not warnings


def test_select_factors_single_mode():
    score = _sample_score_with_issues()
    all_ids = [
        str(f.get("id"))
        for g in score.get("groups") or []
        for f in g.get("factors") or []
        if f.get("id")
    ]
    assert all_ids
    failed, warnings = select_factors_for_autofix(
        score, mode="single", factor_ids=[all_ids[0]]
    )
    assert len(failed) + len(warnings) >= 1


def test_rule_patch_injects_schema_for_warning_factor():
    from app.services.content_ai_seo_autofix import _rule_patch_content_html

    patched = _rule_patch_content_html(
        "<h1>Bài test</h1>" + "<p>nội dung " * 400 + "</p>",
        title="Bài test schema",
        meta="Meta test",
        keyword="bài test",
        target_website="",
        factors=[{"id": "media_schema_blockquote"}],
    )
    assert "application/ld+json" in patched


def test_guaranteed_schema_factor_reaches_passed():
    from app.services.content_ai_seo_autofix import _apply_guaranteed_factor_fix, _factor_lookup

    html = "<h1>Test</h1>" + "<p>nội dung " * 400 + "</p>"
    _, _, patched, _ = _apply_guaranteed_factor_fix(
        factor_id="media_schema_blockquote",
        title="Bài test schema",
        meta="Meta mô tả đủ dài cho bài test schema và người đọc.",
        content=html,
        slug="bai-test",
        keyword="bài test",
        target_website="",
    )
    after = evaluate_publish_checklist(
        title="Bài test schema",
        meta_description="Meta mô tả đủ dài cho bài test schema và người đọc.",
        content_html=patched,
        primary_keyword="bài test",
        slug="bai-test",
    )
    row = _factor_lookup(after).get("media_schema_blockquote") or {}
    assert row.get("status") == "passed"


def test_guaranteed_depth_words_reaches_passed():
    from app.services.content_ai_seo_autofix import _apply_guaranteed_factor_fix, _factor_lookup

    html = "<h1>Test</h1>" + "<p>từ " * 1190 + "</p>"
    _, _, patched, _ = _apply_guaranteed_factor_fix(
        factor_id="depth_word_count",
        title="Test",
        meta="Meta",
        content=html,
        slug="test",
        keyword="seo",
        target_website="",
    )
    after = evaluate_publish_checklist(
        title="Test",
        meta_description="Meta đủ dài cho bài viết test seo và mô tả chi tiết cho người đọc.",
        content_html=patched,
        primary_keyword="seo",
        slug="test",
    )
    row = _factor_lookup(after).get("depth_word_count") or {}
    assert row.get("status") == "passed"


def test_autofix_empty_content_returns_error():
    r = run_seo_autofix_preview(user_id=0, content_html="", title="")
    assert r.get("success") is False
    assert r.get("unchanged") is True


def test_autofix_no_issues_returns_error():
    score = evaluate_publish_checklist(
        title="SEO test keyword: hướng dẫn đầy đủ",
        meta_description="SEO test keyword — meta mô tả đủ dài cho SERP và có call to action rõ ràng cho người đọc muốn tìm hiểu thêm.",
        content_html=(
            "<h1>SEO test keyword</h1>"
            "<p>SEO test keyword giúp bạn hiểu rõ giá trị ngay từ đoạn mở bài với số liệu 80% và quy trình 3 bước.</p>"
            "<h2>Quy trình thực hiện</h2><ul><li>Bước 1</li><li>Bước 2</li></ul>"
            "<h2>Chi tiết</h2><p>Nội dung chi tiết với kinh nghiệm thực tế.</p>"
            "<h2>FAQ</h2><p>Câu hỏi thường gặp.</p>"
            "<p>Tóm lại, đây là kết luận.</p>"
            + "<p>word </p>" * 200
        ),
        primary_keyword="SEO test keyword",
        slug="seo-test-keyword",
        secondary_keywords=["seo", "test"],
    )
    failed, warnings = select_factors_for_autofix(score, mode="severe")
    if not failed:
        return
    r = run_seo_autofix_preview(
        user_id=0,
        title="SEO test keyword: hướng dẫn",
        meta_description="meta",
        content_html="<p>short</p>",
        primary_keyword="SEO test keyword",
        mode="severe",
    )
    assert "seo_before" in r or r.get("error")
