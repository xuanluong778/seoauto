"""WP ↔ SaaS Phase 2 contract tests — four operations from PHASE2_PUBLISH_GUARD_AI.md.

Covers:
  POST/GET publish-guard/intent-checks
  POST/GET ai-seo/suggestions

Asserts: HMAC required, feature entitlement, tenant isolation, idempotency,
async enqueue (no sync AI in request path).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.models.wordpress_plugin import WordpressConnection, WordpressPublishJob
from app.services.plugin_entitlement_service import PluginEntitlement
from app.services.wordpress_plugin_phase2_service import (
    CMD_AI_SUGGEST,
    CMD_INTENT,
    enqueue_ai_suggestions,
    enqueue_intent_check,
    execute_phase2_job,
    get_ai_suggestions,
    get_intent_check,
)
from app.services.wordpress_plugin_security import encrypt_site_secret, personal_organization_id


@pytest.fixture()
def db_session():
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.wordpress_plugin  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    user = User(
        email="phase2@test.local",
        password_hash=hash_password("secret"),
        has_password=True,
        role="user",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    org = personal_organization_id(int(user.id))
    conn = WordpressConnection(
        user_id=int(user.id),
        organization_id=org,
        publishing_site_id="wps_test_canary_site",
        domain_normalized="itsieuviet.test",
        site_url="https://itsieuviet.test",
        status="active",
        site_secret_encrypted=encrypt_site_secret("test-site-secret-32bytes-xxxxxx"),
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)
    yield session, user, conn
    session.close()


def _ent(features: list[str]) -> PluginEntitlement:
    return PluginEntitlement(
        allowed=True,
        reason="active",
        plan_code="pro",
        subscription_status="active",
        expires_at=None,
        grace_until=None,
        max_sites=5,
        enabled_features=features,
    )


def _req(path: str = "/api/wordpress-plugin/publish-guard/intent-checks"):
    req = MagicMock()
    req.method = "POST"
    req.url.path = path
    return req


@patch("app.services.wordpress_plugin_phase2_service._require_plugin_hmac")
@patch("app.services.wordpress_plugin_phase2_service.check_plugin_entitlement")
@patch("app.workers.wordpress_phase2_worker.enqueue_phase2_job", return_value="task-1")
def test_intent_check_enqueue_and_poll(mock_enq, mock_ent, mock_hmac, db_session):
    db, user, conn = db_session
    mock_hmac.return_value = conn
    mock_ent.return_value = _ent(["seo_helper", "publish_guard"])
    body = json.dumps(
        {
            "request_id": "req-intent-1",
            "post_id": 12,
            "title": "Hướng dẫn tối ưu SEO onpage",
            "content_excerpt": "Nội dung mẫu về SEO",
            "focus_keyword": "seo onpage",
        }
    ).encode()
    resp = enqueue_intent_check(db, _req(), body)
    assert resp["ok"] is True
    assert resp["status"] == "queued"
    assert resp["async"] is True
    assert resp["job_id"]
    mock_enq.assert_called_once()

    # idempotent replay
    resp2 = enqueue_intent_check(db, _req(), body)
    assert resp2["job_id"] == resp["job_id"]

    job_id = resp["job_id"]
    get_req = _req(f"/api/wordpress-plugin/publish-guard/intent-checks/{job_id}")
    get_req.method = "GET"
    polled = get_intent_check(db, get_req, job_id)
    assert polled["job_id"] == job_id
    assert polled["status"] in ("queued", "running", "success")


@patch("app.services.wordpress_plugin_phase2_service._require_plugin_hmac")
@patch("app.services.wordpress_plugin_phase2_service.check_plugin_entitlement")
def test_intent_requires_feature(mock_ent, mock_hmac, db_session):
    db, user, conn = db_session
    mock_hmac.return_value = conn
    mock_ent.return_value = _ent(["seo_helper"])  # no publish_guard
    body = b'{"request_id":"x","title":"t"}'
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        enqueue_intent_check(db, _req(), body)
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "seoauto_feature_disabled"


@patch("app.services.wordpress_plugin_phase2_service._require_plugin_hmac")
@patch("app.services.wordpress_plugin_phase2_service.check_plugin_entitlement")
@patch("app.workers.wordpress_phase2_worker.enqueue_phase2_job", return_value="task-ai")
def test_ai_suggest_enqueue_async_no_sync_provider(mock_enq, mock_ent, mock_hmac, db_session):
    db, user, conn = db_session
    mock_hmac.return_value = conn
    mock_ent.return_value = _ent(["seo_helper", "ai_seo_assistant", "content_ops"])
    body = json.dumps(
        {
            "request_id": "req-ai-1",
            "post_id": 9,
            "title": "AI SEO title",
            "content": "body",
            "focus_keyword": "ai seo",
            "kinds": ["title", "meta"],
            "site_id": "wps_test_canary_site",
            "connection_id": 99999,  # client claim ignored for ownership
        }
    ).encode()
    resp = enqueue_ai_suggestions(
        db, _req("/api/wordpress-plugin/ai-seo/suggestions"), body
    )
    assert resp["status"] == "queued"
    assert resp["async"] is True
    mock_enq.assert_called_once()

    # Worker fills result without HTTP-path AI
    out = execute_phase2_job(db, int(resp["job_id"]))
    assert out["ok"] is True
    job = db.get(WordpressPublishJob, int(resp["job_id"]))
    assert job.status == "success"
    assert job.command_type == CMD_AI_SUGGEST
    result = json.loads(job.result_json)
    assert "suggestions" in result
    assert result.get("provider") == "none_sync"
    assert result["kb_scope"]["organization_id"] == personal_organization_id(int(user.id))

    get_req = _req(f"/api/wordpress-plugin/ai-seo/suggestions/{resp['job_id']}")
    get_req.method = "GET"
    polled = get_ai_suggestions(db, get_req, resp["job_id"])
    assert "suggestions" in polled


@patch("app.services.wordpress_plugin_phase2_service._require_plugin_hmac")
@patch("app.services.wordpress_plugin_phase2_service.check_plugin_entitlement")
def test_cross_tenant_job_hidden(mock_ent, mock_hmac, db_session):
    db, user, conn = db_session
    mock_hmac.return_value = conn
    mock_ent.return_value = _ent(["seo_helper", "publish_guard"])
    other = WordpressPublishJob(
        user_id=int(user.id) + 99,
        organization_id=personal_organization_id(int(user.id)) + 99,
        connection_id=int(conn.id),
        request_id="other-tenant",
        command_type=CMD_INTENT,
        status="success",
        payload_json="{}",
        result_json='{"blocking":false}',
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    from fastapi import HTTPException

    get_req = _req(f"/api/wordpress-plugin/publish-guard/intent-checks/{other.id}")
    get_req.method = "GET"
    with pytest.raises(HTTPException) as ei:
        get_intent_check(db, get_req, str(other.id))
    assert ei.value.status_code == 404


def test_worker_intent_heuristic(db_session):
    db, user, conn = db_session
    org = personal_organization_id(int(user.id))
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=org,
        connection_id=int(conn.id),
        request_id="worker-intent",
        command_type=CMD_INTENT,
        status="queued",
        payload_json=json.dumps(
            {
                "title": "ab",
                "focus_keyword": "seo",
                "content_excerpt": "no keyword here",
                "organization_id": org,
            }
        ),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    out = execute_phase2_job(db, job.id)
    assert out["ok"] is True
    db.refresh(job)
    result = json.loads(job.result_json)
    assert result["blocking"] is False
    assert result["engine"] == "heuristic_v1"
    codes = {r["code"] for r in result["risks"]}
    assert "thin_title" in codes
