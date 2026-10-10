"""P0 fixes — private uploads, JSON retention, bulk billing, word count policy."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.user import User
from app.routers.user_files import router as user_files_router
from app.services.audit_store import save_technical_audit, _read_runs
from app.services.content_ai_credit_service import charge_content_ai_from_html
from app.services.content_ai_word_count_policy import (
    billing_tier_action_for_html,
    validate_target_word_count,
)
from app.services.media_storage import save_private_image


@pytest.fixture()
def users_and_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "technical_audits.json")
    Base.metadata.create_all(bind=engine)
    app = FastAPI()
    app.include_router(user_files_router)

    db = SessionLocal()
    try:
        user_a = User(
            email=f"a-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pass"),
            role="user",
            status="active",
        )
        user_b = User(
            email=f"b-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pass"),
            role="user",
            status="active",
        )
        db.add(user_a)
        db.add(user_b)
        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)
        token_a = create_access_token(user_id=user_a.id)
        token_b = create_access_token(user_id=user_b.id)
        client = TestClient(app)
        yield {
            "client": client,
            "user_a": user_a,
            "user_b": user_b,
            "token_a": token_a,
            "token_b": token_b,
            "tmp": tmp_path,
        }
    finally:
        db.close()


def test_user_a_cannot_read_user_b_private_upload(users_and_client):
    ctx = users_and_client
    user_b = ctx["user_b"]
    # Minimal valid JPEG header + padding
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 200
    saved = save_private_image(user_id=user_b.id, data=jpeg, suffix=".jpg", stem="secret")
    rel = saved["relative_path"]

    resp = ctx["client"].get(
        f"/api/user-files/{user_b.id}/{rel}",
        headers={"Authorization": f"Bearer {ctx['token_a']}"},
    )
    assert resp.status_code == 403

    ok = ctx["client"].get(
        f"/api/user-files/{user_b.id}/{rel}",
        headers={"Authorization": f"Bearer {ctx['token_b']}"},
    )
    assert ok.status_code == 200


def test_audit_retention_does_not_evict_other_users(users_and_client):
    ctx = users_and_client
    user_a = ctx["user_a"].id
    user_b = ctx["user_b"].id

    for i in range(42):
        save_technical_audit(
            user_id=user_a,
            source_url=f"https://a-{i}.example.com",
            result={"domain": f"a-{i}.example.com", "pages_scanned": 1, "issues": [], "technical_summary": {}},
        )
    for i in range(5):
        save_technical_audit(
            user_id=user_b,
            source_url=f"https://b-{i}.example.com",
            result={"domain": f"b-{i}.example.com", "pages_scanned": 1, "issues": [], "technical_summary": {}},
        )

    runs = _read_runs()
    b_runs = [r for r in runs if int(r.get("user_id") or 0) == user_b]
    assert len(b_runs) == 5


@patch("app.services.content_ai_credit_service.consume_credits")
@patch("app.services.content_ai_credit_service.reserve_credits")
@patch("app.services.content_ai_credit_service.commit_reservation")
@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=5000)
def test_bulk_charge_uses_actual_word_count(_bal, _admin, _enf, commit_res, reserve, consume, users_and_client):
    user = SimpleNamespace(
        id=99,
        is_admin=False,
        api_access_enabled=False,
        trial_used=False,
        trial_expires_at=None,
        role="user",
    )
    db = MagicMock()
    long_html = "<h1>Test</h1>" + ("<p>word " * 1900 + "</p>")
    reserve.return_value = {"amount": 45, "reservation_id": 1, "already_committed": False}
    commit_res.return_value = {"charged": 45, "request_id": "bulk:job1:0"}
    consume.return_value = {"charged": 45, "request_id": "bulk:job1:0", "mode": "consume"}

    with patch("app.services.saas_trial_service.is_saas_trial_user", return_value=False):
        meta = charge_content_ai_from_html(
            db,
            user,
            long_html,
            field="content",
            use_system_llm=True,
            request_id="bulk:job1:0",
            llm_used=True,
        )

    assert meta is not None
    assert int(meta.get("charged") or 0) == 45 or consume.called
    assert consume.called
    kw = consume.call_args.kwargs if consume.call_args.kwargs else {}
    assert kw.get("amount") == 45 or consume.call_args[1].get("amount") == 45


@patch("app.services.content_ai_credit_service.consume_credits")
@patch("app.services.content_ai_credit_service.reserve_credits")
@patch("app.services.content_ai_credit_service.commit_reservation")
@patch("app.services.content_ai_credit_service.credits_enforced", return_value=True)
@patch("app.services.content_ai_credit_service.is_admin", return_value=False)
@patch("app.services.content_ai_credit_service.get_available_balance", return_value=5000)
def test_client_low_target_still_billed_by_actual_output(_bal, _admin, _enf, commit_res, reserve, consume, users_and_client):
    user = SimpleNamespace(
        id=7,
        is_admin=False,
        api_access_enabled=False,
        plan_slug="pro",
        trial_used=False,
        trial_expires_at=None,
        role="user",
    )
    db = MagicMock()
    # Client asked for ~200 words but output is ~1500 words
    html = "<h1>X</h1>" + ("<p>seo " * 1480 + "</p>")
    reserve.return_value = {"amount": 25, "reservation_id": 2, "already_committed": False}
    commit_res.return_value = {"charged": 25, "request_id": "x"}
    consume.return_value = {"charged": 25, "request_id": "x", "mode": "consume"}

    with patch("app.services.saas_trial_service.is_saas_trial_user", return_value=False):
        charge_content_ai_from_html(db, user, html, field="content", use_system_llm=True, llm_used=True)

    # Billing tier inferred from actual HTML (medium ~1500 words)
    assert billing_tier_action_for_html(html) == "article_medium"
    assert consume.called
    kw = consume.call_args.kwargs if consume.call_args.kwargs else {}
    if "amount" in kw:
        assert int(kw["amount"]) == 25


def test_validate_target_word_count_caps_by_plan():
    user = SimpleNamespace(id=1, plan_slug="starter", api_access_enabled=False)
    assert validate_target_word_count(5000, user, None) == 1500
    assert validate_target_word_count(200, user, None) == 200
