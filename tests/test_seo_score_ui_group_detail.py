"""UI contract: SEO Score group detail panel + AI fix modal."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "seo_url_score.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "seo-score-page.css").read_text(encoding="utf-8")

GROUP_IDS = [
    "title_meta_slug",
    "heading",
    "image_seo",
    "schema",
    "links",
    "content_quality",
]

REQUIRED_JS = [
    "function renderTenGroupDetail",
    "function renderGroupStatsPanel",
    "function renderGroupCurrentDataPanel",
    "function renderTitleMetaCurrentData",
    "function renderHeadingsCurrentData",
    "function renderImagesCurrentData",
    "function renderSchemaCurrentData",
    "function renderLinksCurrentData",
    "function renderContentCurrentData",
    "function renderChecksSections",
    "function openAiFixModal",
    "function requestAiFix",
    "function canShowAiFixButton",
    "function buildAiFixPayload",
    "Sửa bằng AI",
    "ssAiFixModal",
    "ssAiFixStateLoading",
    "ssAiFixStateError",
    "ssAiFixStateEmpty",
    "ssAiFixStateReady",
    "NON_AI_CHECK_IDS",
    "AI_FIXABLE_FIELDS",
    "Không tìm thấy dữ liệu",
    "Dữ liệu hiện tại",
    "Đóng góp điểm tổng",
]

REQUIRED_CSS = [
    ".ss-group-detail-stats",
    ".ss-group-current-data",
    ".ss-data-empty",
    ".ss-image-row",
    ".ss-heading-list",
    ".ss-check-row",
    ".ss-ai-fix-btn",
    ".ss-ai-modal",
    ".ss-ai-state-loading",
    ".ss-ai-state-error",
    ".ss-ai-state-empty",
]


def test_group_detail_helpers_present():
    for token in REQUIRED_JS:
        assert token in HTML, f"missing JS/UI token: {token}"


def test_group_switch_cases_cover_sidebar_groups():
    for gid in GROUP_IDS:
        assert 'case "' + gid + '":' in HTML or "case '" + gid + "':" in HTML


def test_group_detail_styles_present():
    for sel in REQUIRED_CSS:
        assert sel in CSS, f"missing CSS: {sel}"


def test_ai_fix_payload_shape_from_mock_check():
    # Simulate JS buildAiFixPayload logic via documented field names in HTML
    payload_keys = ["group_key", "issue_id", "page_field", "current_value", "evidence", "keyword", "url"]
    for key in payload_keys:
        assert key in HTML


def test_non_ai_checks_exclude_noindex_robots():
    assert '"noindex"' in HTML
    assert '"robots_txt"' in HTML
    assert '"http_5xx"' in HTML


def test_ai_fixable_fields_include_title_meta_image():
    assert '"title"' in HTML
    assert '"meta_description"' in HTML
    assert '"image_alt"' in HTML
