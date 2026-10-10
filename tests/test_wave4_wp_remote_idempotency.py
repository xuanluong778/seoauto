"""WAVE 4 — remote WordPress idempotency (request_id → post_id)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.models.wordpress_plugin import WordpressPublishJob, WordpressRequestIdempotency
from app.services.wordpress_plugin_retry import ErrorClassification
from app.services.wordpress_plugin_security import encrypt_site_secret, personal_organization_id
from app.services.wordpress_publish_idempotency import (
    get_cached_publish_result,
    probe_remote_publish_by_request_id,
    publish_idempotency_key,
    recover_publish_after_remote_error,
    save_publish_result,
)


@pytest.fixture()
def wp_db():
    import app.models.payment_order  # noqa: F401
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
    db = Session()
    user = User(
        email="wave4-remote@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    from app.models.wordpress_plugin import WordpressConnection

    conn = WordpressConnection(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        publishing_site_id="wps_remote",
        domain_normalized="remote.test",
        site_url="https://remote.test",
        status="active",
        site_secret_encrypted=encrypt_site_secret("test-secret-32bytes-long-xxxx"),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    yield db, user, conn
    db.close()


def test_save_and_load_publish_idempotency_mapping(wp_db):
    db, user, conn = wp_db
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        connection_id=int(conn.id),
        request_id="remote-req-1",
        command_type="post_create",
        status="running",
        payload_json="{}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    save_publish_result(db, job, {"post_id": 77, "permalink": "https://remote.test/p/77"})
    cached = get_cached_publish_result(
        db, organization_id=int(job.organization_id), request_id="remote-req-1"
    )
    assert cached is not None
    assert cached["post_id"] == 77
    row = db.execute(
        select(WordpressRequestIdempotency).where(
            WordpressRequestIdempotency.idempotency_key == publish_idempotency_key("remote-req-1")
        )
    ).scalar_one()
    assert row.response_code == 200


def test_wp_response_lost_after_success_recovers_via_probe(wp_db):
    db, user, conn = wp_db
    from app.services.wordpress_plugin_publish_service import create_publish_job, execute_publish_job
    from app.services.plugin_entitlement_service import PluginEntitlement

    ent = PluginEntitlement(
        allowed=True,
        reason="active",
        plan_code="pro",
        subscription_status="active",
        expires_at=None,
        grace_until=None,
        max_sites=5,
        enabled_features=["seo_helper"],
    )
    with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
        with patch("app.services.wordpress_plugin_publish_service._count_org_sites", return_value=1):
            with patch("app.workers.wordpress_publish_worker.enqueue_publish_job", return_value="t1"):
                job = create_publish_job(
                    db,
                    user=user,
                    payload={"title": "T", "content": "c"},
                    connection_id=int(conn.id),
                    request_id="lost-response-1",
                    enqueue=False,
                )

    timeout_err = ErrorClassification(True, False, "network_error", "timed out", None, None)

    with patch(
        "app.services.wordpress_plugin_publish_service.plugin_post_json",
        return_value=(None, timeout_err),
    ):
        with patch(
            "app.services.wordpress_publish_idempotency.probe_remote_publish_by_request_id",
            return_value={"post_id": 88, "permalink": "https://remote.test/p/88", "idempotent_replay": True},
        ):
            with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
                result = execute_publish_job(db, job.id)

    assert result.get("ok") is True
    db.refresh(job)
    assert job.wp_post_id == 88
    assert job.status == "success"


def test_wp_retry_after_remote_success_via_probe(wp_db):
    db, user, conn = wp_db
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        connection_id=int(conn.id),
        request_id="probe-req-1",
        command_type="post_create",
        status="running",
        payload_json="{}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    err = ErrorClassification(True, False, "network_error", "connection reset", None, None)
    with patch(
        "app.services.wordpress_publish_idempotency.probe_remote_publish_by_request_id",
        return_value={"post_id": 55, "permalink": "https://remote.test/p/55", "idempotent_replay": True},
    ):
        recovered = recover_publish_after_remote_error(db, job, conn, "secret", err)
    assert recovered is not None
    assert recovered.get("ok") is True
    db.refresh(job)
    assert job.status == "success"
    assert job.wp_post_id == 55


def test_remote_article_exists_response(wp_db):
    db, user, conn = wp_db
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        connection_id=int(conn.id),
        request_id="exists-req",
        command_type="post_create",
        status="running",
        payload_json="{}",
    )
    db.add(job)
    db.commit()
    err = ErrorClassification(
        False,
        True,
        "seoauto_article_exists",
        "already published",
        409,
        {"post_id": 66, "permalink": "https://remote.test/p/66"},
    )
    recovered = recover_publish_after_remote_error(db, job, conn, "secret", err, raw_body=err.body)
    assert recovered is not None
    assert recovered.get("ok") is True
    db.refresh(job)
    assert job.wp_post_id == 66


def test_payload_includes_idempotency_key(wp_db):
    db, user, conn = wp_db
    from app.services.wordpress_plugin_publish_service import execute_publish_job
    from app.services.plugin_entitlement_service import PluginEntitlement

    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=personal_organization_id(int(user.id)),
        connection_id=int(conn.id),
        request_id="idem-key-check",
        command_type="post_create",
        status="queued",
        payload_json="{}",
    )
    db.add(job)
    db.commit()
    ent = PluginEntitlement(
        allowed=True,
        reason="active",
        plan_code="pro",
        subscription_status="active",
        expires_at=None,
        grace_until=None,
        max_sites=5,
        enabled_features=["seo_helper"],
    )
    captured = {}

    def _post(**kwargs):
        captured.update(kwargs.get("payload") or {})
        return {"post_id": 1, "link": "https://x/p/1"}, None

    with patch("app.services.wordpress_plugin_publish_service.plugin_post_json", side_effect=_post):
        with patch("app.services.wordpress_plugin_publish_service.check_plugin_entitlement", return_value=ent):
            execute_publish_job(db, job.id)
    assert captured.get("request_id") == "idem-key-check"
    assert captured.get("idempotency_key") == "idem-key-check"


def test_probe_remote_publish_by_request_id_parses_post():
    with patch(
        "app.services.wordpress_publish_idempotency.plugin_get_json",
        return_value=({"post_id": 12, "permalink": "https://x/p/12"}, None),
    ):
        out = probe_remote_publish_by_request_id(
            site_url="https://x",
            site_id="s",
            connection_id=1,
            secret="sec",
            request_id="r1",
        )
    assert out and out["post_id"] == 12
