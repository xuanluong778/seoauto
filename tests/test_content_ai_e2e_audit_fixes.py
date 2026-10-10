"""E2E-style tests for Content AI audit fixes (suggest-stream, draft, regenerate, VI/EN, WP publish)."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password, validate_jwt_secret_at_startup
from app.db import Base, SessionLocal, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.user import User
from app.routers.pages import (
    ContentDraftRequest,
    ContentSuggestRequest,
    WordpressDraftPublishRequest,
    content_ai_draft,
    content_ai_suggest,
    content_ai_suggest_stream,
)
from app.routers.report import router as report_router
from app.services.content_ai_project_store import get_content_ai_project
from app.services.llm_content_writer import _content_ai_system_prompt_base, _normalize_output_language


class _FakeUser:
    id = 77
    role = "user"
    plan_slug = "pro"
    plan = "pro"
    is_admin = False
    api_access_enabled = False
    email = "e2e-user@test.invalid"
    trial_used = False
    trial_expires_at = None
    trial_started_at = None
    status = "active"


@pytest.fixture()
def auth_report_client():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            email=f"e2e-report-{uuid.uuid4().hex[:10]}@test.invalid",
            password_hash=hash_password("x"),
            role="user",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user_id=user.id)
        app = FastAPI()
        app.include_router(report_router)
        client = TestClient(app)
        yield client, token
    finally:
        db.close()


def _mock_llm_gate():
    return {
        "use_system_llm": True,
        "charge_credits": False,
        "unit_cost": 0,
        "quote": {},
        "prompt_word_count": 800,
    }


def test_normalize_output_language_vi_en():
    assert _normalize_output_language("vi") == "vi"
    assert _normalize_output_language("en-US") == "en"
    assert _normalize_output_language("english") == "en"
    assert "English" in _content_ai_system_prompt_base(output_language="en")
    assert "tiếng Việt" in _content_ai_system_prompt_base(output_language="vi")


def test_suggest_stream_route_and_language_wiring():
    """SSE route exists; output_language is declared and passed into stream path."""
    assert "output_language" in ContentSuggestRequest.model_fields
    from pathlib import Path

    pages_src = Path(__file__).resolve().parents[1].joinpath("app/routers/pages.py").read_text(encoding="utf-8")
    assert "def content_ai_suggest_stream" in pages_src
    assert "output_language=payload.output_language" in pages_src
    assert "iter_content_ai_content_stream_deltas" in pages_src


def test_draft_save_persists_project(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_CONTENT_AI_PG", "0")
    monkeypatch.setenv("TENANT_CONTENT_AI_JSON_WRITE", "1")
    monkeypatch.setenv("TENANT_CONTENT_AI_DUAL_READ", "0")
    monkeypatch.chdir(tmp_path)

    payload = ContentDraftRequest(
        title="Draft E2E",
        content="<p>Draft body</p>",
        slug="draft-e2e",
        primary_keyword="draft kw",
        target_website="https://draft.test",
    )
    user = SimpleNamespace(id=5)
    req = MagicMock()
    req.query_params = {}

    with patch("app.routers.pages.log_audit_event"):
        resp = content_ai_draft(request=req, payload=payload, current_user=user)

    data = json.loads(resp.body)
    pid = data.get("project_id")
    assert pid
    row = get_content_ai_project(str(pid), user_id=5)
    assert row is not None
    assert "Draft body" in str(row.get("content") or "")


def test_regenerate_suggest_updates_output():
    """Regenerate = second suggest call with updated content (same contract)."""
    payload = ContentSuggestRequest(
        field="title",
        primary_keyword="regen kw",
        title="Old title",
        output_language="en",
    )
    user = _FakeUser()
    db = MagicMock()
    req = MagicMock()
    req.headers = {"X-Request-Id": "regen-1"}
    req.query_params = {}

    @contextmanager
    def _fake_credit_session(*args, **kwargs):
        ctrl = MagicMock()
        ctrl.hold = None
        ctrl.abort = MagicMock()
        yield ctrl

    @contextmanager
    def _noop_gate(*args, **kwargs):
        yield MagicMock()

    with (
        patch("app.routers.pages._content_ai_suggest_llm_gate", return_value=_mock_llm_gate()),
        patch("app.routers.pages.assert_content_ai_feature"),
        patch("app.services.user_api_access.load_llm_config_for_request", return_value=MagicMock()),
        patch("app.routers.pages.detect_search_intent", return_value="informational"),
        patch("app.services.content_ai_knowledge_context.get_relevant_knowledge_for_keyword", return_value={"found": False}),
        patch(
            "app.routers.pages.generate_content_ai_suggestion",
            side_effect=["First title", "Regenerated title EN"],
        ) as gen,
        patch(
            "app.services.content_ai_credit_service.content_ai_provider_credit_session",
            side_effect=_fake_credit_session,
        ),
        patch("app.routers.pages.content_ai_llm_gate", side_effect=_noop_gate),
        patch("app.services.content_ai_llm_providers.coerce_user_ai_provider", return_value="auto"),
        patch("app.services.entitlement_service.resolve_effective_plan", return_value="pro"),
        patch("app.services.content_draft_builder.content_ai_finalize_brief_field_value", side_effect=lambda **kw: kw["text"]),
        patch("app.routers.pages.record_content_ai_usage"),
    ):
        r1 = content_ai_suggest(request=req, payload=payload, current_user=user, db=db)
        r2 = content_ai_suggest(request=req, payload=payload, current_user=user, db=db)

    b1 = json.loads(r1.body)
    b2 = json.loads(r2.body)
    assert b1.get("value") == "First title"
    assert b2.get("value") == "Regenerated title EN"
    assert gen.call_count == 2
    assert gen.call_args_list[-1].kwargs.get("output_language") == "en"


def test_wp_publish_duplicate_guard():
    from app.services.content_ai_wp_publish_executor import guard_wp_publish_project_duplicate

    db = MagicMock()
    schedule = MagicMock()
    schedule.wp_post_id = 42
    schedule.wp_post_url = "https://wp.test/?p=42"

    with (
        patch(
            "app.services.content_ai_publish_schedule_service._resolve_publish_now_duplicate",
            return_value=schedule,
        ),
        patch("app.services.idempotency_guard.find_usage_by_key"),
        patch("app.services.content_ai_project_store.get_content_ai_project"),
        patch("app.services.content_ai_project_store.update_content_ai_project_fields"),
    ):
        out = guard_wp_publish_project_duplicate(db, user_id=1, project_id="proj-1")

    assert out is not None
    assert out["idempotent"] is True
    assert out["post_id"] == 42


def test_report_api_requires_auth(auth_report_client):
    client, token = auth_report_client
    anon = client.get("/api/report")
    assert anon.status_code in (401, 403)
    ok = client.get("/api/report", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code in (200, 404)


def test_jwt_secret_rejects_weak_in_production():
    with patch.dict("os.environ", {"JWT_SECRET": "change-this-in-production"}, clear=False):
        with pytest.raises(RuntimeError):
            validate_jwt_secret_at_startup(production=True)
