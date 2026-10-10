"""Prompt 4 — paid APIs must go through saas_action_gate; no-plan / no-credit cannot bypass."""

from __future__ import annotations

import inspect
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services.credits import get_available_balance, grant_credits
from app.services.saas_gate import saas_action_gate


@pytest.fixture()
def db(monkeypatch):
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.credit_reservation  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.usage_limit  # noqa: F401

    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setattr(
        "app.services.saas_economics_guard.check_economics_after_burn",
        lambda *a, **k: None,
        raising=False,
    )

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _user(db, *, balance: int = 0) -> User:
    u = User(
        email=f"gate-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="user",
    )
    db.add(u)
    db.flush()
    if balance > 0:
        grant_credits(
            db,
            user_id=u.id,
            amount=balance,
            reason="test_grant",
            note="gate_bypass",
            source_type="admin",
        )
        db.flush()
    return u


@contextmanager
def _access_ok():
    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature") as cf, patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan", return_value="pro"
    ), patch("app.services.cost_control.settings.cost_control_enforced", return_value=False):
        from app.schemas.saas import EntitlementResult

        cf.return_value = EntitlementResult(
            allowed=True,
            reason_code="ok",
            message="ok",
            feature_key="keyword_research",
            plan_slug="pro",
        )
        yield


def test_zero_credit_cannot_reserve_through_central_gate(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=0)
    assert get_available_balance(db, user.id) == 0
    with _access_ok():
        with pytest.raises(HTTPException) as ei:
            with saas_action_gate(
                db,
                user,
                feature_code="keyword_research",
                credit_cost=5,
                quota_units=1,
                job_id=f"j-{uuid.uuid4().hex}",
                idempotency_key=f"k-{uuid.uuid4().hex}",
                charge_mode="reserve",
            ):
                raise AssertionError("must not enter paid action body")
    assert ei.value.status_code == 402


def test_no_software_access_blocked_before_action(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=100)
    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=False
    ), patch(
        "app.services.saas_gate.resolve_ai_access_state",
        return_value={"state": "plan_required", "message": "Cần gói"},
    ):
        with pytest.raises(HTTPException) as ei:
            with saas_action_gate(
                db,
                user,
                feature_code="seo_score",
                credit_cost=1,
                charge_mode="reserve",
            ):
                raise AssertionError("must not enter")
    assert ei.value.status_code == 403
    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "plan_required"


def test_feature_denied_cannot_bypass_gate(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=100)
    from app.schemas.saas import EntitlementResult

    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature") as cf, patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan",
        return_value="free_trial_5d",
    ):
        cf.return_value = EntitlementResult(
            allowed=False,
            reason_code="trial_feature_blocked",
            message="blocked",
            feature_key="keyword_research",
        )
        with pytest.raises(HTTPException) as ei:
            with saas_action_gate(
                db,
                user,
                feature_code="keyword_research",
                credit_cost=0,
                charge_mode="none",
            ):
                raise AssertionError("must not enter")
    assert ei.value.status_code == 403


def test_paid_routers_use_saas_action_gate_not_raw_consume():
    from app.routers import (
        google_map_seo,
        index_control,
        keyword_intelligence,
        keywords,
        rank_tracking,
        schema,
        seo_score,
        serp_intel,
    )

    checks = [
        (rank_tracking.api_check_now, "saas_action_gate"),
        (schema.api_schema_generator, "saas_action_gate"),
        (keyword_intelligence._run_gated, "saas_action_gate"),
        (serp_intel.post_keyword_intelligence, "saas_action_gate"),
        (seo_score.api_seo_score_ai_fix, "execute_seo_score_ai_fix_billed"),
        (index_control.index_control_submit_indexing, "saas_action_gate"),
        (keywords.api_cluster_save, "saas_action_gate"),
        (keywords.api_import_keywords_excel, "saas_action_gate"),
        (google_map_seo._run_google_map_ai, "saas_action_gate"),
        (google_map_seo.gbp_profile_generate, "_run_google_map_ai"),
        (google_map_seo.gbp_review_ai_reply, "_run_google_map_ai"),
        (google_map_seo.gbp_posts_generate, "_run_google_map_ai"),
        (google_map_seo.gbp_media_ai_caption, "_run_google_map_ai"),
    ]
    for fn, needle in checks:
        src = inspect.getsource(fn)
        assert needle in src, f"{fn.__qualname__} missing {needle}"
        assert "consume_credits(" not in src, f"{fn.__qualname__} still uses consume_credits bypass"

    from app.services import seo_score_ai_fix as ssaf

    gmap_src = inspect.getsource(google_map_seo._run_google_map_ai)
    assert "saas_action_gate" in gmap_src
    assert "sgate.commit()" in gmap_src
    assert "sgate.release" in gmap_src
    assert "organization_id" in gmap_src

    seo_fix_src = inspect.getsource(ssaf.execute_seo_score_ai_fix_billed)
    assert "seo_score_ai_fix_billing_session" in seo_fix_src
    assert "sgate.commit()" in seo_fix_src


def test_schema_generator_rejects_anonymous(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    client = TestClient(app, base_url="https://seoauto.vn")
    r = client.post(
        "/schema-generator",
        json={"html": "<html><title>x</title></html>", "fetch_serp": False},
    )
    assert r.status_code in (401, 403)


def test_serp_intel_rejects_anonymous(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app, base_url="https://seoauto.vn")
    r = client.post("/api/serp/keyword-intelligence", json={"keyword": "seo"})
    assert r.status_code in (401, 403)


def test_keyword_intelligence_rejects_anonymous(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app, base_url="https://seoauto.vn")
    r = client.get("/api/keyword-intelligence", params={"seed_keyword": "seo"})
    assert r.status_code in (401, 403)
