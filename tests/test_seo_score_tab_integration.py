"""
Tổng hợp test tab SEO Score (/tool/seo-score) sau Link score, AI Fix, Apply WP.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.seo import Project
from app.models.user import User
from app.routers.seo_score import router as seo_score_router
from app.schemas.url_scoreboard import UrlSeoScoreboardResponse
from app.services.seo_score_ai_fix import finalize_seo_score_ai_fix_credit, run_seo_score_ai_fix
from app.services.seo_score_wp_apply import MANUAL_APPLY_MESSAGE, apply_seo_score_fix_to_wordpress
from app.services.trial_access import require_active_trial
from app.services.url_seo_scoreboard import build_url_seo_scoreboard
from app.services.url_seo_ten_group_scoring import GROUP_WEIGHTS, ensure_ten_groups_complete

SAMPLE_HTML = """<!DOCTYPE html><html lang="vi"><head>
<title>SEO Title Example For Testing Purposes Only Here</title>
<meta name="description" content="Meta description ngắn cho bài test SEO score integration.">
<link rel="canonical" href="https://example.com/test-page">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"Test"}</script>
</head><body>
<h1>Main Heading</h1>
<h2>Section A</h2><h2>Section B</h2>
<h3>Sub A</h3>
<p>SEO content body with enough words for testing parser and evidence attachment on page.</p>
<img src="/hero.jpg" alt="hero banner">
<img src="/chart.png">
<a href="/internal">Internal link</a>
<a href="https://google.com">External</a>
</body></html>"""


def _mock_fetch(*_a, **_k):
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
    return {"serp_results": [], "keyword": "seo test"}


def _scoreboard(keyword: str = "seo test") -> dict:
    with patch("app.services.url_seo_scoreboard.fetch_serp", side_effect=_mock_serp), patch(
        "app.services.url_seo_scoreboard._safe_fetch", side_effect=_mock_fetch
    ):
        return build_url_seo_scoreboard("https://example.com/test-page", keyword=keyword)


@pytest.fixture()
def api_client():
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
    user_a = User(email="tab-a@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    user_b = User(email="tab-b@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    db.add_all([user_a, user_b])
    db.flush()
    db.add_all([Project(user_id=user_a.id, domain="example.com"), Project(user_id=user_b.id, domain="other.com")])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(seo_score_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_trial] = lambda: user_a
    tc = TestClient(app)
    yield tc, db, user_a, user_b
    app.dependency_overrides.clear()
    db.close()


def test_01_valid_url_scoreboard_with_keyword():
    raw = _scoreboard("seo test")
    UrlSeoScoreboardResponse.model_validate(raw)
    assert raw["fetch"]["ok"] is True
    assert raw.get("page_evidence")


def test_02_ten_groups_include_links():
    raw = _scoreboard()
    groups = raw["ten_group_scoreboard"]["groups"]
    assert len(groups) == 10
    ids = {g["id"] for g in groups}
    assert "links" in ids
    links = next(g for g in groups if g["id"] == "links")
    assert links["label"] == "Internal / External Link"
    assert links.get("link_data")


def test_03_contribution_sum_matches_total_without_penalty():
    raw = _scoreboard()
    tb = raw["ten_group_scoreboard"]
    weighted = round(sum(float(g.get("weighted_points") or 0) for g in tb["groups"]), 1)
    total = float(tb["total_score"])
    penalties = tb.get("penalties_applied") or []
    if not penalties:
        assert abs(weighted - total) <= 0.2


def test_04_links_evidence_internal_external():
    raw = _scoreboard()
    ev = raw["page_evidence"]["links"]["evidence"]
    assert ev.get("internal_links_count", 0) >= 1
    assert ev.get("external_links_count", 0) >= 1


def test_05_title_evidence_with_length():
    raw = _scoreboard()
    t = raw["page_evidence"]["title"]
    assert t["current_value"]
    assert t["current_length"] == len(str(t["current_value"]))
    assert t["recommended_length"]["min"] == 50


def test_06_meta_evidence_with_length():
    raw = _scoreboard()
    m = raw["page_evidence"]["meta_description"]
    assert m["current_value"]
    assert m["current_length"] == len(str(m["current_value"]))


def test_07_heading_evidence_lists_h1_h2_h3():
    raw = _scoreboard()
    h = raw["page_evidence"]["headings"]["current_value"]
    assert h["h1"] == ["Main Heading"]
    assert len(h["h2"]) >= 2
    assert len(h["h3"]) >= 1


def test_08_image_missing_alt_evidence():
    raw = _scoreboard()
    img = raw["page_evidence"]["images"]["evidence"]
    assert img.get("missing_alt_count", 0) >= 1
    assert any(row.get("missing_alt") for row in img.get("missing_alt") or [])


def test_09_ai_fix_title_meta_heading_image_alt_rule():
    cases = [
        ("title", "Short title", "seo test"),
        ("meta_description", "Meta ngắn.", "seo test"),
        (
            "heading",
            {"h1": ["Main Heading"], "h2": ["Section A"], "h3": []},
            "seo test",
        ),
        (
            "image_alt",
            [{"src": "/chart.png", "alt": "", "missing_alt": True}],
            "seo test",
        ),
    ]
    for pf, cur, kw in cases:
        out = run_seo_score_ai_fix(
            user_id=1,
            url="https://example.com/test-page",
            keyword=kw,
            page_field=pf,
            current_value=cur,
            evidence={},
            force_rule_fallback=True,
        )
        assert out["before"] is not None
        assert out["after"] is not None
        assert "reason" in out
        assert "confidence" in out


def test_10_ui_copy_after_helper_present():
    from pathlib import Path

    html = Path(__file__).resolve().parents[1].joinpath("templates/seo_url_score.html").read_text(encoding="utf-8")
    assert "function copyAiFixAfter" in html
    assert "function formatAiFixCopyText" in html
    assert "Copy bản sau" in html


def test_11_apply_without_wp_manual_message(api_client):
    tc, db, user_a, _ = api_client
    project = db.query(Project).filter(Project.user_id == user_a.id).first()
    token = create_access_token(user_id=user_a.id)
    with patch("app.routers.seo_score.assert_public_http_url"), patch(
        "app.services.seo_score_wp_apply.list_sites", return_value=[]
    ):
        res = tc.post(
            "/api/seo-score/apply-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": project.id,
                "url": "https://example.com/test-page",
                "page_field": "title",
                "before": "Old",
                "after": "New title",
            },
        )
    assert res.status_code == 200
    data = res.json()
    assert data["applied"] is False
    assert data["manual_only"] is True
    assert MANUAL_APPLY_MESSAGE in data["message"]


def test_12_apply_title_with_wp_connection(api_client):
    _, db, user_a, _ = api_client
    project = db.query(Project).filter(Project.user_id == user_a.id).first()
    site = {"id": "s1", "url": "https://example.com", "user_id": user_a.id}
    post = {
        "wp_id": 7,
        "post_type": "post",
        "title": "Old",
        "content": "<p>x</p>",
        "excerpt": "",
        "link": "https://example.com/test-page",
    }
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[site]), patch(
        "app.services.seo_score_wp_apply.user_owns_wp_site", return_value=True
    ), patch("app.services.seo_score_wp_apply.fetch_post_by_url", return_value=post), patch(
        "app.services.seo_score_wp_apply.get_site_credentials",
        return_value={"url": "https://example.com", "username": "u", "app_password": "p"},
    ), patch("app.services.seo_score_wp_apply._wp_patch", return_value={}):
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project.id,
            url="https://example.com/test-page",
            page_field="title",
            before="Old",
            after="New title applied",
        )
    assert result["applied"] is True
    assert result["applied_value"] == "New title applied"


def test_13_user_a_cannot_apply_other_project(api_client):
    tc, db, user_a, user_b = api_client
    other = db.query(Project).filter(Project.user_id == user_b.id).first()
    token = create_access_token(user_id=user_a.id)
    with patch("app.routers.seo_score.assert_public_http_url"):
        res = tc.post(
            "/api/seo-score/apply-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": other.id,
                "url": "https://other.com/x",
                "page_field": "title",
                "before": "a",
                "after": "b",
            },
        )
    assert res.status_code == 404


def test_14_ai_fix_no_credit_on_error(api_client):
    _, db, user_a, _ = api_client
    info = finalize_seo_score_ai_fix_credit(
        db, user_a, success=False, url="https://example.com/x", issue_id="title_length"
    )
    assert info.get("charged") == 0


def test_15_reset_button_clears_results_and_modal():
    from pathlib import Path

    html = Path(__file__).resolve().parents[1].joinpath("templates/seo_url_score.html").read_text(encoding="utf-8")
    assert "Làm lại" in html
    assert "function clearFormAndResults" in html
    assert "lastResponseData = null" in html
    assert "closeAiFixModal()" in html
    assert 'id="ssTenNav"' in html


def test_16_mobile_and_dark_theme_css():
    from pathlib import Path

    css = Path(__file__).resolve().parents[1].joinpath("static/css/seo-score-page.css").read_text(encoding="utf-8")
    assert "@media (max-width: 640px)" in css
    assert "@media (max-width: 720px)" in css
    assert "--ss-text:" in css
    assert ".ss-ai-compare-grid" in css
    assert ".ss-link-stats-grid" in css


def test_17_other_product_modules_still_importable():
    """Smoke: Content AI / Technical / Schema / Keyword routers không bị gãy import."""
    from app.routers import analyze  # noqa: F401
    from app.services import content_ai_credit_service  # noqa: F401

    assert hasattr(analyze, "analyze_url_seo_scoreboard")
    assert ensure_ten_groups_complete([])[0]["id"] in GROUP_WEIGHTS
