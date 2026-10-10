"""Tests for SEO Score AI fix service and API."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.user import User
from app.routers.seo_score import router as seo_score_router
from app.services.seo_score_ai_fix import (
    SeoScoreAiFixError,
    finalize_seo_score_ai_fix_credit,
    run_seo_score_ai_fix,
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
    user = User(email="ai@test.com", password_hash=hash_password("x"), has_password=True, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(seo_score_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_trial] = lambda: user
    tc = TestClient(app)
    yield tc, db, user
    app.dependency_overrides.clear()
    db.close()


@contextmanager
def _noop_seo_score_ai_fix_gate(*_args, **_kwargs):
    class _Session:
        pass

    yield _Session()


@contextmanager
def _noop_saas_action_gate(*_args, **_kwargs):
    class _Ctx:
        reserved_amount = 0
        committed = False

        def commit(self):
            self.committed = True

        def release(self, **_kw):
            return None

        def record_usage(self, **_kw):
            return None

    yield _Ctx()


@contextmanager
def _noop_billing_session(*_args, **_kwargs):
    from app.services.seo_score_ai_fix import SeoScoreAiFixBillingCtx

    class _Sgate:
        committed = False

        def commit(self):
            self.committed = True

        def release(self, **_kw):
            return None

        def record_usage(self, **_kw):
            return None

    yield SeoScoreAiFixBillingCtx(sgate=_Sgate(), credit_cost=0, billable=False)


@contextmanager
def _patch_api_ai_fix_router():
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.seo_score.assert_public_http_url"))
        stack.enter_context(patch("app.routers.seo_score.load_llm_config_for_request", return_value=None))
        stack.enter_context(
            patch("app.services.seo_score_ai_fix.seo_score_ai_fix_billing_session", _noop_billing_session)
        )
        stack.enter_context(
            patch("app.services.cost_control.module_gates.seo_score_ai_fix_gate", _noop_seo_score_ai_fix_gate)
        )
        yield


def test_rule_fix_title_only():
    out = run_seo_score_ai_fix(
        user_id=1,
        url="https://example.com/page",
        keyword="seo tool",
        page_field="title",
        current_value="Short title",
        issue_id="title_length",
        force_rule_fallback=True,
    )
    assert isinstance(out["after"], str)
    assert "seo tool" in out["after"].lower()
    assert out["before"] == "Short title"
    assert out["confidence"] > 0


def test_rule_fix_meta_only():
    out = run_seo_score_ai_fix(
        user_id=1,
        url="https://example.com/page",
        keyword="dịch vụ seo",
        page_field="meta_description",
        current_value="Meta ngắn.",
        evidence={"content": "Meta ngắn."},
        force_rule_fallback=True,
    )
    assert isinstance(out["after"], str)
    assert "dịch vụ seo" in out["after"].lower()
    assert out["before"] == "Meta ngắn."


def test_rule_fix_heading_only():
    out = run_seo_score_ai_fix(
        user_id=1,
        url="https://example.com/page",
        keyword="seo audit",
        page_field="heading",
        current_value={"h1": ["Old H1", "Extra H1"], "h2": ["A"], "h3": []},
        issue_id="h1_multiple",
        force_rule_fallback=True,
    )
    assert isinstance(out["after"], dict)
    assert len(out["after"]["h1"]) == 1
    assert out["after"]["h2"] == ["A"]


def test_rule_fix_image_alt_only():
    evidence = {
        "missing_alt": [
            {"src": "/chart.png", "alt": "", "missing_alt": True},
            {"src": "/hero.jpg", "alt": "ok", "missing_alt": False},
        ],
        "missing_alt_count": 1,
    }
    out = run_seo_score_ai_fix(
        user_id=1,
        url="https://example.com/page",
        keyword="báo cáo",
        page_field="image_alt",
        current_value=evidence["missing_alt"],
        evidence=evidence,
        force_rule_fallback=True,
    )
    assert isinstance(out["after"], list)
    assert len(out["after"]) == 1
    assert out["after"][0]["src"] == "/chart.png"
    assert out["after"][0]["alt"].strip()


def test_rule_fix_rejects_empty_image_alt():
    with pytest.raises(SeoScoreAiFixError):
        run_seo_score_ai_fix(
            user_id=1,
            url="https://example.com/page",
            page_field="image_alt",
            current_value=[],
            evidence={"missing_alt": []},
            force_rule_fallback=True,
        )


def test_credit_not_charged_when_billing_disabled(client, monkeypatch):
    monkeypatch.setenv("SEO_SCORE_AI_FIX_BILLING_ENABLED", "0")
    tc, db, user = client
    token = create_access_token(user_id=user.id)
    with _patch_api_ai_fix_router(), patch(
        "app.services.seo_score_ai_fix.run_seo_score_ai_fix"
    ) as mock_run:
        mock_run.return_value = {
            "before": "x",
            "after": "y",
            "reason": "ok",
            "confidence": 0.8,
            "warnings": [],
        }
        res = tc.post(
            "/api/seo-score/ai-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "url": "https://example.com/test",
                "keyword": "seo",
                "group_key": "title_meta_slug",
                "issue_id": "title_length",
                "page_field": "title",
                "current_value": "Old title here for testing",
                "evidence": {},
            },
        )
    assert res.status_code == 200
    data = res.json()
    assert data["after"] == "y"
    assert data["credit"]["charged"] == 0


def test_api_ai_fix_title_meta_image_alt(client):
    tc, db, user = client
    token = create_access_token(user_id=user.id)
    base = {
        "url": "https://example.com/landing",
        "keyword": "seo audit",
        "group_key": "title_meta_slug",
        "evidence": {},
    }
    cases = [
        {
            "issue_id": "title_length",
            "page_field": "title",
            "current_value": "Landing page",
        },
        {
            "issue_id": "meta_length",
            "page_field": "meta_description",
            "current_value": "Short meta.",
        },
        {
            "issue_id": "h1_multiple",
            "page_field": "heading",
            "current_value": {"h1": ["H1 A", "H1 B"], "h2": ["Sec"], "h3": []},
            "evidence": {"h1": ["H1 A", "H1 B"], "h2": ["Sec"]},
        },
        {
            "issue_id": "alt_text",
            "page_field": "image_alt",
            "current_value": [{"src": "/img.png", "alt": "", "missing_alt": True}],
            "evidence": {
                "missing_alt": [{"src": "/img.png", "alt": "", "missing_alt": True}],
            },
        },
    ]
    for body_extra in cases:
        with _patch_api_ai_fix_router(), patch(
            "app.services.seo_score_ai_fix.run_seo_score_ai_fix"
        ) as mock_run:
            pf = body_extra["page_field"]
            if pf == "title":
                after = "SEO audit | Landing page optimized"
            elif pf == "meta_description":
                after = "Short meta — seo audit"
            elif pf == "heading":
                after = {"h1": ["SEO audit landing"], "h2": ["Sec"], "h3": []}
            else:
                after = [{"src": "/img.png", "alt": "Img seo audit"}]
            mock_run.return_value = {
                "before": body_extra["current_value"],
                "after": after,
                "reason": "test",
                "confidence": 0.9,
                "warnings": [],
            }
            res = tc.post(
                "/api/seo-score/ai-fix",
                headers={"Authorization": f"Bearer {token}"},
                json={**base, **body_extra},
            )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["after"] == after
        assert data["reason"] == "test"


def test_api_ai_error_no_credit_charge(client):
    tc, db, user = client
    token = create_access_token(user_id=user.id)
    with _patch_api_ai_fix_router(), patch(
        "app.services.seo_score_ai_fix.run_seo_score_ai_fix", side_effect=SeoScoreAiFixError("AI lỗi")
    ):
        res = tc.post(
            "/api/seo-score/ai-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "url": "https://example.com/x",
                "page_field": "title",
                "current_value": "t",
            },
        )
    assert res.status_code == 502, res.text
    info = finalize_seo_score_ai_fix_credit(db, user, success=False, url="https://example.com/x", issue_id="t")
    assert info.get("charged") == 0


def test_api_missing_image_alt_returns_400_no_charge(client):
    tc, db, user = client
    token = create_access_token(user_id=user.id)
    with _patch_api_ai_fix_router():
        res = tc.post(
            "/api/seo-score/ai-fix",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "url": "https://example.com/x",
                "page_field": "image_alt",
                "current_value": [],
                "evidence": {"missing_alt": []},
            },
        )
    assert res.status_code == 400, res.text
    info = finalize_seo_score_ai_fix_credit(db, user, success=False, url="https://example.com/x", issue_id="alt")
    assert info.get("charged") == 0
