"""Tests for SEO Score apply-fix to WordPress."""

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
from app.models.seo import Project, SeoScoreApplyLog
from app.models.user import User
from app.routers.seo_score import router as seo_score_router
from app.services.seo_score_wp_apply import (
    MANUAL_APPLY_MESSAGE,
    SeoScoreApplyError,
    _apply_heading_html,
    _apply_image_alt_html,
    apply_seo_score_fix_to_wordpress,
    record_seo_score_apply_log,
    url_belongs_to_project,
)
from app.services.trial_access import require_active_trial


@pytest.fixture()
def client():
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
    user_a = User(email="a@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    user_b = User(email="b@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    db.add_all([user_a, user_b])
    db.flush()
    project_a = Project(user_id=user_a.id, domain="example.com")
    project_b = Project(user_id=user_b.id, domain="other.com")
    db.add_all([project_a, project_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.refresh(project_a)

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
    yield tc, db, user_a, user_b, project_a
    app.dependency_overrides.clear()
    db.close()


def test_url_belongs_to_project_host_match():
    assert url_belongs_to_project("https://www.example.com/page", "example.com")
    assert not url_belongs_to_project("https://evil.com/page", "example.com")


def test_apply_heading_html_updates_h1():
    html = "<p>Intro</p><h1>Old</h1>"
    out = _apply_heading_html(
        html,
        {"h1": ["New H1"], "h2": [], "h3": []},
        {"h1": ["Old"], "h2": [], "h3": []},
    )
    assert "New H1" in out
    assert "Old" not in out


def test_apply_heading_before_mismatch_raises():
    html = "<h1>Changed on WP</h1>"
    with pytest.raises(SeoScoreApplyError) as exc:
        _apply_heading_html(
            html,
            {"h1": ["New H1"], "h2": [], "h3": []},
            {"h1": ["Old"], "h2": [], "h3": []},
        )
    assert exc.value.manual_only is True


def test_apply_image_alt_html_updates_matching_src():
    html = '<img src="/a.png" alt=""><p>x</p>'
    out = _apply_image_alt_html(html, [{"src": "/a.png", "alt": "Desc A"}], base="https://example.com")
    assert 'alt="Desc A"' in out


def test_no_project_returns_manual_only(client):
    _, db, user_a, _, _ = client
    result = apply_seo_score_fix_to_wordpress(
        db,
        user_id=user_a.id,
        project_id=None,
        url="https://unknown-domain.test/post",
        page_field="title",
        before="Old",
        after="New title for testing",
    )
    assert result["applied"] is False
    assert result["manual_only"] is True


def test_no_wp_site_returns_manual_only(client):
    _, db, user_a, _, project_a = client
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[]):
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project_a.id,
            url="https://example.com/hello",
            page_field="title",
            before="Old",
            after="New title",
        )
    assert result["applied"] is False
    assert result["manual_only"] is True
    assert result["message"] == MANUAL_APPLY_MESSAGE


def test_apply_meta_success_with_wp_mock(client):
    _, db, user_a, _, project_a = client
    site = {"id": "site-1", "url": "https://example.com", "user_id": user_a.id}
    post = {
        "wp_id": 43,
        "post_type": "post",
        "title": "Page",
        "content": "<p>Body</p>",
        "excerpt": "Old meta",
        "link": "https://example.com/hello",
    }
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[site]), patch(
        "app.services.seo_score_wp_apply.user_owns_wp_site", return_value=True
    ), patch("app.services.seo_score_wp_apply.fetch_post_by_url", return_value=post), patch(
        "app.services.seo_score_wp_apply.get_site_credentials",
        return_value={"url": "https://example.com", "username": "u", "app_password": "pwd"},
    ), patch("app.services.seo_score_wp_apply._wp_patch", return_value={}), patch(
        "app.services.seo_score_wp_apply._patch_seo_meta"
    ):
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project_a.id,
            url="https://example.com/hello",
            page_field="meta_description",
            before="Old meta",
            after="New meta description for SEO testing purposes only.",
        )
    assert result["applied"] is True
    assert result["applied_value"].startswith("New meta")


def test_apply_heading_success_with_before(client):
    _, db, user_a, _, project_a = client
    site = {"id": "site-1", "url": "https://example.com", "user_id": user_a.id}
    post = {
        "wp_id": 44,
        "post_type": "page",
        "title": "Page",
        "content": "<h1>Old H1</h1><p>Body</p>",
        "excerpt": "",
        "link": "https://example.com/about",
    }
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[site]), patch(
        "app.services.seo_score_wp_apply.user_owns_wp_site", return_value=True
    ), patch("app.services.seo_score_wp_apply.fetch_post_by_url", return_value=post), patch(
        "app.services.seo_score_wp_apply.get_site_credentials",
        return_value={"url": "https://example.com", "username": "u", "app_password": "pwd"},
    ), patch("app.services.seo_score_wp_apply._wp_patch", return_value={}) as mock_patch:
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project_a.id,
            url="https://example.com/about",
            page_field="heading",
            before={"h1": ["Old H1"], "h2": [], "h3": []},
            after={"h1": ["New H1"], "h2": [], "h3": []},
        )
    assert result["applied"] is True
    sent = mock_patch.call_args.kwargs.get("body") or mock_patch.call_args[1].get("body")
    assert sent and "New H1" in sent.get("content", "")


def test_apply_image_alt_success_with_before(client):
    _, db, user_a, _, project_a = client
    site = {"id": "site-1", "url": "https://example.com", "user_id": user_a.id}
    post = {
        "wp_id": 45,
        "post_type": "post",
        "title": "Page",
        "content": '<img src="/a.png" alt=""><p>x</p>',
        "excerpt": "",
        "link": "https://example.com/post",
    }
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[site]), patch(
        "app.services.seo_score_wp_apply.user_owns_wp_site", return_value=True
    ), patch("app.services.seo_score_wp_apply.fetch_post_by_url", return_value=post), patch(
        "app.services.seo_score_wp_apply.get_site_credentials",
        return_value={"url": "https://example.com", "username": "u", "app_password": "pwd"},
    ), patch("app.services.seo_score_wp_apply._wp_patch", return_value={}) as mock_patch:
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project_a.id,
            url="https://example.com/post",
            page_field="image_alt",
            before=[{"src": "/a.png", "alt": ""}],
            after=[{"src": "/a.png", "alt": "Desc A"}],
        )
    assert result["applied"] is True
    sent = mock_patch.call_args.kwargs.get("body") or mock_patch.call_args[1].get("body")
    assert sent and 'alt="Desc A"' in sent.get("content", "")


def test_apply_logs_success(client):
    _, db, user_a, _, project_a = client
    record_seo_score_apply_log(
        db,
        user_id=user_a.id,
        project_id=project_a.id,
        url="https://example.com/x",
        page_field="title",
        before="a",
        after="b",
        status="success",
    )
    db.commit()
    row = db.query(SeoScoreApplyLog).order_by(SeoScoreApplyLog.id.desc()).first()
    assert row is not None
    assert row.user_id == user_a.id
    assert row.project_id == project_a.id
    assert row.status == "success"
    assert row.page_field == "title"


def test_apply_title_success_with_wp_mock(client):
    _, db, user_a, _, project_a = client
    site = {"id": "site-1", "url": "https://example.com", "user_id": user_a.id}
    post = {
        "wp_id": 42,
        "post_type": "post",
        "title": "Old",
        "content": "<p>Body</p>",
        "excerpt": "",
        "link": "https://example.com/hello",
    }
    with patch("app.services.seo_score_wp_apply.list_sites", return_value=[site]), patch(
        "app.services.seo_score_wp_apply.user_owns_wp_site", return_value=True
    ), patch("app.services.seo_score_wp_apply.fetch_post_by_url", return_value=post), patch(
        "app.services.seo_score_wp_apply.get_site_credentials",
        return_value={"url": "https://example.com", "username": "u", "app_password": "pwd"},
    ), patch("app.services.seo_score_wp_apply._wp_patch", return_value={"title": "New title"}):
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=user_a.id,
            project_id=project_a.id,
            url="https://example.com/hello",
            page_field="title",
            before="Old",
            after="New title",
        )
    assert result["applied"] is True
    assert result["wp_id"] == 42
    assert result["applied_value"] == "New title"


def test_api_apply_manual_only_without_wp(client):
    tc, db, user_a, _, project_a = client
    token = create_access_token(user_id=user_a.id)
    with patch("app.routers.seo_score.assert_public_http_url"), patch(
        "app.services.seo_score_wp_apply.list_sites", return_value=[]
    ):
        res = tc.post(
            "/api/seo-score/apply-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": project_a.id,
                "url": "https://example.com/post",
                "page_field": "title",
                "before": "Old",
                "after": "New",
                "issue_id": "title_length",
            },
        )
    assert res.status_code == 200
    data = res.json()
    assert data["applied"] is False
    assert data["manual_only"] is True


def test_user_cannot_apply_other_users_project(client):
    tc, db, user_a, user_b, project_a = client
    other_project = db.query(Project).filter(Project.user_id == user_b.id).first()
    token = create_access_token(user_id=user_a.id)
    with patch("app.routers.seo_score.assert_public_http_url"):
        res = tc.post(
            "/api/seo-score/apply-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": other_project.id,
                "url": "https://other.com/post",
                "page_field": "title",
                "before": "x",
                "after": "y",
            },
        )
    assert res.status_code == 404


def test_api_wp_error_returns_502(client):
    tc, db, user_a, _, project_a = client
    token = create_access_token(user_id=user_a.id)
    with patch("app.routers.seo_score.assert_public_http_url"), patch(
        "app.routers.seo_score.apply_seo_score_fix_to_wordpress",
        side_effect=SeoScoreApplyError("WordPress lỗi"),
    ):
        res = tc.post(
            "/api/seo-score/apply-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": project_a.id,
                "url": "https://example.com/post",
                "page_field": "title",
                "before": "Old",
                "after": "New",
            },
        )
    assert res.status_code == 502
