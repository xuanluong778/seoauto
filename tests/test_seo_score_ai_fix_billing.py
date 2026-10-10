"""Prompt 6 — SEO Score AI Fix billing: default billable, reserve/commit/release."""

from __future__ import annotations

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
from app.services.seo_score_ai_fix import (
    SeoScoreAiFixError,
    execute_seo_score_ai_fix_billed,
    seo_score_ai_fix_billing_enabled,
    seo_score_ai_fix_billing_session,
)


@contextmanager
def _noop_module_gate(*_args, **_kwargs):
    yield MagicMock()


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
    import app.models.usage_limit  # noqa: F401
    import app.models.user  # noqa: F401

    monkeypatch.delenv("SEO_SCORE_AI_FIX_BILLING_ENABLED", raising=False)
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


def _user(db, *, balance: int = 50) -> User:
    u = User(
        email=f"billing-{uuid.uuid4().hex[:8]}@test.local",
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
            reason="test",
            note="ai_fix_billing",
            source_type="admin",
        )
        db.flush()
    return u


def _entitlement_ok():
    from app.schemas.saas import EntitlementResult

    return EntitlementResult(
        allowed=True,
        reason_code="ok",
        message="ok",
        feature_key="seo_score",
        plan_slug="pro",
    )


def test_billing_enabled_by_default(monkeypatch):
    monkeypatch.delenv("SEO_SCORE_AI_FIX_BILLING_ENABLED", raising=False)
    assert seo_score_ai_fix_billing_enabled() is True


def test_billing_disabled_only_when_explicit_zero(monkeypatch):
    monkeypatch.setenv("SEO_SCORE_AI_FIX_BILLING_ENABLED", "0")
    assert seo_score_ai_fix_billing_enabled() is False


def test_billing_session_releases_on_ai_error(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=50)
    start = get_available_balance(db, user.id)

    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature", return_value=_entitlement_ok()), patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan", return_value="pro"
    ), patch("app.services.cost_control.settings.cost_control_enforced", return_value=False), patch(
        "app.services.cost_control.module_gates.seo_score_ai_fix_gate", _noop_module_gate
    ), patch(
        "app.services.seo_score_ai_fix.run_seo_score_ai_fix", side_effect=SeoScoreAiFixError("fail")
    ):
        with pytest.raises(SeoScoreAiFixError):
            execute_seo_score_ai_fix_billed(
                db,
                user,
                url="https://example.com/p",
                keyword="seo",
                group_key="title",
                issue_id="i1",
                page_field="title",
                current_value="Old title here",
                evidence={},
                llm_cfg=None,
            )

    assert get_available_balance(db, user.id) == start


def test_billing_session_commits_on_success(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=50)
    cost = 2

    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature", return_value=_entitlement_ok()), patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan", return_value="pro"
    ), patch("app.services.cost_control.settings.cost_control_enforced", return_value=False), patch(
        "app.services.cost_control.module_gates.seo_score_ai_fix_gate", _noop_module_gate
    ), patch(
        "app.services.seo_score_ai_fix.run_seo_score_ai_fix",
        return_value={
            "before": "a",
            "after": "b",
            "reason": "ok",
            "confidence": 0.9,
            "warnings": [],
        },
    ):
        result, credit_info = execute_seo_score_ai_fix_billed(
            db,
            user,
            url="https://example.com/p",
            keyword="seo",
            group_key="title",
            issue_id="i1",
            page_field="title",
            current_value="Old title here",
            evidence={},
            llm_cfg=None,
        )

    assert result["after"] == "b"
    assert credit_info.get("charged") == cost
    assert credit_info.get("prepaid") is True
    assert get_available_balance(db, user.id) == 50 - cost


def test_zero_credit_blocked_at_reserve(db, monkeypatch):
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    user = _user(db, balance=0)

    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature", return_value=_entitlement_ok()), patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan", return_value="pro"
    ), patch("app.services.cost_control.settings.cost_control_enforced", return_value=False):
        with pytest.raises(HTTPException) as ei:
            with seo_score_ai_fix_billing_session(db, user, page_field="title"):
                raise AssertionError("must not enter")
        assert ei.value.status_code == 402
