"""UI contract: SEO Score AI fix modal wired to /api/seo-score/ai-fix."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "seo_url_score.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "seo-score-page.css").read_text(encoding="utf-8")

AI_FIX_FIELDS = ["title", "meta_description", "heading", "image_alt"]

REQUIRED_HTML = [
    'fetch("/api/seo-score/ai-fix"',
    "function requestAiFix",
    "function runAiFixRequest",
    "function regenerateAiFix",
    "function copyAiFixAfter",
    "function formatAiFixDisplayValue",
    "function formatAiFixCopyText",
    "ssAiFixBeforeText",
    "ssAiFixAfterText",
    "ssAiFixRegenBtn",
    "ssAiFixCopyBtn",
    "ssAiFixApplyBtn",
    "Tạo lại bằng AI",
    "Copy bản sau",
    "Bản trước",
    "Bản sau (AI)",
    "ssAiFixConfidence",
    "ssAiFixReason",
    "ssAiFixWarnings",
    "function applyAiFix",
    "function patchScoreboardAfterApply",
    "/api/seo-score/apply-fix",
    "ssAiFixAppliedBadge",
    "ssAiFixRescoreBtn",
    "Chấm điểm lại",
    "Bạn có chắc muốn áp dụng thay đổi này lên website không?",
    "Chưa thể áp dụng tự động",
    "AI_FIX_FIELD_LABELS",
]

REQUIRED_CSS = [
    ".ss-ai-compare-grid",
    ".ss-ai-compare-col",
    ".ss-ai-compare-content-after",
    ".ss-ai-btn-regen",
    ".ss-ai-btn-copy",
    ".ss-ai-meta-bar",
    ".ss-ai-applied-badge",
    ".ss-ai-btn-rescore",
]


def test_ai_fix_api_and_helpers_present():
    for token in REQUIRED_HTML:
        assert token in HTML, f"missing HTML/JS: {token}"


def test_ai_fix_modal_styles_two_column():
    for sel in REQUIRED_CSS:
        assert sel in CSS, f"missing CSS: {sel}"
    assert "@media (max-width: 640px)" in CSS
    assert "grid-template-columns: 1fr" in CSS


def test_ai_fix_field_labels_cover_title_meta_heading_image_alt():
    for field in AI_FIX_FIELDS:
        assert field in HTML, f"missing field label key: {field}"
    assert "title: \"Title\"" in HTML or 'title: "Title"' in HTML
    assert "meta_description" in HTML
    assert "image_alt" in HTML


def test_check_id_maps_to_ai_fix_fields():
    mapping = {
        "title_missing": "title",
        "title_length": "title",
        "meta_missing": "meta_description",
        "meta_length": "meta_description",
        "h1_missing": "heading",
        "alt_text": "image_alt",
    }
    for check_id, page_field in mapping.items():
        assert check_id + ': "' + page_field + '"' in HTML or check_id + ": '" + page_field + "'" in HTML


def test_ai_fix_payload_sent_to_api():
    for key in [
        "url",
        "keyword",
        "group_key",
        "issue_id",
        "page_field",
        "current_value",
        "evidence",
    ]:
        assert key in HTML
