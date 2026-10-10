"""Tests for raw page evidence on SEO scoreboard issues/checks."""

from __future__ import annotations

from unittest.mock import patch

from app.schemas.url_scoreboard import UrlSeoScoreboardResponse
from app.services.parser import parse_page_seo_data
from app.services.url_seo_optimization_report import (
    EVIDENCE_FIELD_DEFAULTS,
    attach_evidence_to_scoreboard,
    build_page_field_evidence,
    enrich_item_with_evidence,
)
from app.services.url_seo_ten_group_scoring import analyze_page_links
from app.services.url_seo_scoreboard import build_url_seo_scoreboard

SAMPLE_HTML = """<!DOCTYPE html><html lang="vi"><head>
<title>SEO Title Example For Testing Purposes Only</title>
<meta name="description" content="Meta description ngắn.">
<link rel="canonical" href="https://example.com/test-page">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"Test"}</script>
</head><body>
<h1>Main Heading</h1>
<h2>Section A</h2><h2>Section B</h2>
<h3>Sub A</h3>
<p>SEO content body with enough words for testing parser and evidence attachment.</p>
<img src="/hero.jpg" alt="hero banner">
<img src="/chart.png">
<a href="/internal">Internal link</a>
<a href="https://google.com">External</a>
</body></html>"""


def _assert_evidence_fields(item: dict) -> None:
    for key in EVIDENCE_FIELD_DEFAULTS:
        assert key in item, f"missing {key} on {item.get('id') or item.get('type')}"
    if item.get("can_ai_fix"):
        assert item.get("page_field"), f"AI-fixable item missing page_field: {item.get('id')}"
        assert item.get("current_value") is not None or item.get("page_field") in ("heading", "image_alt"), (
            f"AI-fixable item missing current_value: {item.get('id')}"
        )


def test_parser_extracts_raw_page_data():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    assert pd["title"].startswith("SEO Title")
    assert pd["h1_count"] == 1
    assert pd["h2_count"] == 2
    assert len(pd["headings"]["h1"]) == 1
    assert len(pd["images"]) == 2
    assert pd["images_missing_alt"] == 1
    assert any(not row.get("is_internal") for row in pd["links"])


def test_build_page_field_evidence_title_meta_headings():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    link_profile = analyze_page_links(SAMPLE_HTML, "https://example.com/test-page", parsed_links=pd.get("links"))
    pd["link_profile"] = link_profile
    ev = build_page_field_evidence(page_data=pd, normalized_url="https://example.com/test-page")
    assert ev["title"]["current_length"] == len(pd["title"])
    assert ev["title"]["recommended_length"] == {"min": 50, "max": 60}
    assert "issues" in ev["title"]["evidence"]
    assert ev["meta_description"]["recommended_length"] == {"min": 140, "max": 160}
    assert "issues" in ev["meta_description"]["evidence"]
    assert ev["headings"]["current_value"]["h1"] == ["Main Heading"]
    assert ev["heading"]["page_field"] == "heading"
    assert "problematic_headings" in ev["heading"]["evidence"]
    assert ev["images"]["evidence"]["missing_alt_count"] == 1
    missing = ev["images"]["evidence"]["missing_alt"][0]
    assert missing.get("position") == 2
    assert "context" in missing
    assert ev["intro"]["current_value"]
    assert ev["content_section"]["evidence"]["sections"]
    assert ev["schema"]["current_value"]["status"] == "missing"  # no ld_blocks passed
    assert ev["links"]["evidence"]["internal_links_count"] >= 1
    assert ev["links"]["evidence"]["external_links_count"] >= 1
    assert "anchor_texts" in ev["links"]["evidence"]
    assert "weak_links" in ev["links"]["evidence"]


def test_enrich_item_maps_check_id_to_page_field():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    ev = build_page_field_evidence(page_data=pd)
    check = enrich_item_with_evidence(
        {"id": "title_missing", "title": "Có thẻ Title", "status": "failed"},
        ev,
        group_key="title_meta_slug",
    )
    assert check["page_field"] == "title"
    assert check["issue_id"] == "title_missing"
    assert check["current_value"] == pd["title"]
    assert check["current_length"] == len(pd["title"])
    assert check["can_ai_fix"] is True
    assert "issues" in check["evidence"]


def test_enrich_title_length_check_has_issue_codes():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    ev = build_page_field_evidence(page_data=pd, primary_keyword="seo test")
    check = enrich_item_with_evidence(
        {"id": "title_length", "title": "Độ dài Title", "status": "warning"},
        ev,
        group_key="title_meta_slug",
        primary_keyword="seo test",
    )
    assert check["page_field"] == "title"
    assert check["evidence"].get("issues") is not None
    assert check["current_value"] == pd["title"]


def test_enrich_heading_check_lists_problematic():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    ev = build_page_field_evidence(page_data=pd)
    check = enrich_item_with_evidence(
        {"id": "h2_structure", "title": "Cấu trúc H2", "status": "passed"},
        ev,
        group_key="heading",
    )
    assert check["page_field"] == "heading"
    assert "h1" in check["evidence"]
    assert check["evidence"]["h1"] == ["Main Heading"]


def test_enrich_image_check_has_missing_alt_details():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    ev = build_page_field_evidence(page_data=pd)
    check = enrich_item_with_evidence(
        {"id": "alt_text", "title": "Alt", "status": "failed"},
        ev,
        group_key="image_seo",
    )
    assert check["page_field"] == "image_alt"
    assert check["evidence"]["missing_alt_count"] == 1
    target = check["evidence"].get("target_images") or check["current_value"]
    assert isinstance(target, list) and target
    assert target[0].get("src") == "/chart.png"
    assert target[0].get("position") == 2


def test_enrich_links_check_has_weak_links():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    link_profile = analyze_page_links(SAMPLE_HTML, "https://example.com/test-page", parsed_links=pd.get("links"))
    pd["link_profile"] = link_profile
    ev = build_page_field_evidence(page_data=pd)
    check = enrich_item_with_evidence(
        {"id": "internal_links", "title": "Internal links", "status": "warning"},
        ev,
        group_key="links",
    )
    assert check["page_field"] == "links"
    assert check["evidence"].get("featured_links") or check["evidence"].get("internal")


def test_attach_evidence_to_scoreboard_shape():
    pd = parse_page_seo_data(SAMPLE_HTML, base_url="https://example.com/test-page")
    sb = {
        "url": "https://example.com/test-page",
        "normalized_url": "https://example.com/test-page",
        "page_snapshot": pd,
        "issues": [{"pillar": "structure", "type": "missing_meta", "severity": "medium", "message": "x", "fix": "y"}],
        "ten_group_scoreboard": {
            "groups": [
                {
                    "id": "image_seo",
                    "checks": [{"id": "alt_text", "title": "Alt", "status": "failed"}],
                }
            ],
            "priority_fixes": [{"group": "heading", "check_id": "h1_missing", "title": "H1"}],
        },
    }
    attach_evidence_to_scoreboard(sb)
    assert "page_evidence" in sb
    _assert_evidence_fields(sb["issues"][0])
    assert sb["issues"][0]["page_field"] == "meta_description"
    assert sb["issues"][0]["issue_id"] == "missing_meta"
    check = sb["ten_group_scoreboard"]["groups"][0]["checks"][0]
    assert check["page_field"] == "image_alt"
    assert check["group_key"] == "image_seo"
    assert check["evidence"]["missing_alt_count"] == 1


def _mock_fetch_ok(*_a, **_k):
    return {
        "ok": True,
        "normalized_url": "https://example.com/test-page",
        "status": 200,
        "final_url": "https://example.com/test-page",
        "html": SAMPLE_HTML,
        "headers": {},
        "error": None,
        "notes": [],
    }


def _mock_serp(*_a, **_k):
    return {"keyword": "seo test", "rows": [], "source": "test", "cache_hit": False, "provider_called": False, "snap": {}}


@patch("app.services.url_seo_scoreboard.fetch_seo_score_serp", side_effect=_mock_serp)
@patch("app.services.url_seo_scoreboard._safe_fetch", side_effect=_mock_fetch_ok)
def test_build_url_seo_scoreboard_includes_evidence(_fetch, _serp):
    raw = build_url_seo_scoreboard("https://example.com/test-page", keyword="seo test")
    UrlSeoScoreboardResponse.model_validate(raw)

    assert "page_evidence" in raw
    assert raw["page_evidence"]["title"]["recommended_length"]["min"] == 50
    assert raw["page_snapshot"]["headings"]["h1"] == ["Main Heading"]

    title_checks = []
    links_group = None
    for g in raw["ten_group_scoreboard"]["groups"]:
        if g["id"] == "title_meta_slug":
            title_checks = g["checks"]
        if g["id"] == "links":
            links_group = g
    assert title_checks
    assert links_group is not None
    assert links_group["label"] == "Internal / External Link"
    assert links_group.get("link_data")
    for c in title_checks:
        _assert_evidence_fields(c)
        if c["id"] in ("title_length", "title_missing", "kw_in_title"):
            assert c["page_field"] == "title"
            assert c["issue_id"] == c["id"]
            assert c["group_key"] == "title_meta_slug"
            assert c["current_value"]
            assert "issues" in c["evidence"] or "issue_details" in c["evidence"]

    intro_ev = raw["page_evidence"].get("intro") or {}
    assert intro_ev.get("current_value")
    assert raw["page_evidence"].get("content_section")

    if raw["issues"]:
        for issue in raw["issues"]:
            _assert_evidence_fields(issue)

    top = raw["optimization_report"]["top_problems"]
    if top:
        _assert_evidence_fields(top[0])


@patch("app.routers.analyze.record_quota_usage")
@patch("app.routers.analyze.credits_enforced", return_value=False)
@patch("app.routers.analyze.assert_public_http_url")
@patch("app.services.url_seo_scoreboard.fetch_seo_score_serp", side_effect=_mock_serp)
@patch("app.services.url_seo_scoreboard._safe_fetch", side_effect=_mock_fetch_ok)
def test_analyze_url_seo_scoreboard_api(_fetch, _serp, _assert_url, _credits, _quota):
    """POST /analyze/url-seo-scoreboard trả page_evidence đủ field cho AI fix."""
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.security import create_access_token, hash_password
    from app.db import Base, get_db
    from app.models.user import User
    from app.routers.analyze import router as analyze_router
    from app.services.trial_access import require_active_trial

    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    user = User(email="score@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)

    @contextmanager
    def _noop_gate(*_a, **_k):
        class _S:
            committed = False

            def commit(self):
                self.committed = True

            def record_usage(self, **_kw):
                return None

            def release(self, **_kw):
                return None

        yield _S()

    app = FastAPI()
    app.include_router(analyze_router)

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[require_active_trial] = lambda: user
    token = create_access_token({"sub": str(user.id)})
    tc = TestClient(app)

    with patch("app.routers.analyze.cost_gate_session", _noop_gate), patch(
        "app.routers.analyze.saas_action_gate", _noop_gate
    ):
        r = tc.post(
            "/analyze/url-seo-scoreboard",
            json={"url": "https://example.com/test-page", "keyword": "seo test"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200, r.text
    data = r.json()
    UrlSeoScoreboardResponse.model_validate(data)
    assert data["page_evidence"]["title"]["current_value"]
    assert data["page_evidence"]["intro"]["current_value"]
    assert data["page_evidence"]["image_alt"]["evidence"]["missing_alt_count"] == 1
    title_checks = next(g for g in data["ten_group_scoreboard"]["groups"] if g["id"] == "title_meta_slug")["checks"]
    assert title_checks[0]["issue_id"]
    assert title_checks[0]["group_key"] == "title_meta_slug"
    db.close()
