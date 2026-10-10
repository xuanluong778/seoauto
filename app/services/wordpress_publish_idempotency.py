"""WordPress remote publish idempotency — request_id → post_id mapping (WAVE 4)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.wordpress_plugin import WordpressPublishJob, WordpressRequestIdempotency
from app.services.wordpress_plugin_client import plugin_get_json

_LOG = logging.getLogger(__name__)

PUBLISH_IDEM_PREFIX = "publish:post_create:"
PROBE_PATH_TEMPLATE = "/wp-json/seoauto/v1/posts/by-request-id/{request_id}"


def publish_idempotency_key(request_id: str) -> str:
    rid = str(request_id or "").strip()[:96]
    return f"{PUBLISH_IDEM_PREFIX}{rid}"


def _parse_result(body: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    post_id = int(body.get("post_id") or body.get("id") or 0) or None
    if not post_id and isinstance(body.get("data"), dict):
        post_id = int(body["data"].get("post_id") or body["data"].get("id") or 0) or None
    if not post_id:
        return None
    url = str(
        body.get("permalink")
        or body.get("link")
        or body.get("wp_post_url")
        or (body.get("data") or {}).get("permalink")
        or ""
    ).strip() or None
    return {"post_id": post_id, "permalink": url, "link": url, "idempotent_replay": True}


def get_cached_publish_result(
    db: Session,
    *,
    organization_id: int,
    request_id: str,
) -> dict[str, Any] | None:
    key = publish_idempotency_key(request_id)
    row = db.execute(
        select(WordpressRequestIdempotency).where(
            WordpressRequestIdempotency.organization_id == int(organization_id),
            WordpressRequestIdempotency.idempotency_key == key,
        ).limit(1)
    ).scalar_one_or_none()
    if row is None or not row.response_body_json:
        return None
    try:
        data = json.loads(row.response_body_json)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("post_id") else None


def save_publish_result(
    db: Session,
    job: WordpressPublishJob,
    result: dict[str, Any],
    *,
    request_path: str = "/wp-json/seoauto/v1/posts",
) -> None:
    parsed = _parse_result(result)
    if not parsed:
        return
    key = publish_idempotency_key(job.request_id)
    existing = db.execute(
        select(WordpressRequestIdempotency).where(
            WordpressRequestIdempotency.organization_id == int(job.organization_id),
            WordpressRequestIdempotency.idempotency_key == key,
        ).limit(1)
    ).scalar_one_or_none()
    body_json = json.dumps(parsed, ensure_ascii=False)
    if existing is not None:
        existing.response_body_json = body_json
        existing.response_code = 200
        existing.request_path = request_path[:255]
        db.commit()
        return
    row = WordpressRequestIdempotency(
        user_id=int(job.user_id),
        organization_id=int(job.organization_id),
        connection_id=int(job.connection_id) if job.connection_id else None,
        idempotency_key=key,
        request_path=request_path[:255],
        response_code=200,
        response_body_json=body_json,
    )
    db.add(row)
    db.commit()


def probe_remote_publish_by_request_id(
    *,
    site_url: str,
    site_id: str,
    connection_id: int,
    secret: str,
    request_id: str,
) -> dict[str, Any] | None:
    """Ask WordPress plugin for existing post created with this request_id (remote idempotency)."""
    path = PROBE_PATH_TEMPLATE.format(request_id=str(request_id).strip()[:64])
    result, err = plugin_get_json(
        site_url=site_url,
        site_id=site_id,
        connection_id=int(connection_id),
        secret=secret,
        path=path,
        request_id=f"probe-{request_id}"[:64],
    )
    if err is not None:
        return None
    return _parse_result(result)


def extract_idempotent_result_from_error(err: Any, raw_body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    code = str(getattr(err, "error_code", "") or "").lower()
    if code not in ("seoauto_article_exists", "article_exists"):
        return None
    return _parse_result(raw_body)


def recover_publish_after_remote_error(
    db: Session,
    job: WordpressPublishJob,
    connection: Any,
    secret: str,
    err: Any,
    *,
    raw_body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve success from cache or WordPress when HTTP failed but post may exist."""
    from app.services.wordpress_plugin_publish_service import _finalize_job

    cached = get_cached_publish_result(
        db, organization_id=int(job.organization_id), request_id=job.request_id
    )
    if cached:
        return _finalize_job(
            db,
            job,
            status="success",
            result=cached,
            wp_post_id=int(cached["post_id"]),
            wp_post_url=cached.get("permalink") or cached.get("link"),
        )

    parsed = extract_idempotent_result_from_error(err, raw_body or getattr(err, "body", None))
    if parsed is None and getattr(err, "retryable", False):
        parsed = probe_remote_publish_by_request_id(
            site_url=connection.site_url,
            site_id=str(connection.publishing_site_id or ""),
            connection_id=int(connection.id),
            secret=secret,
            request_id=job.request_id,
        )

    if parsed is None:
        return None

    save_publish_result(db, job, parsed)
    _LOG.info(
        "wp publish job %s recovered remote idempotency request_id=%s post_id=%s",
        job.id,
        job.request_id,
        parsed.get("post_id"),
    )
    return _finalize_job(
        db,
        job,
        status="success",
        result=parsed,
        wp_post_id=int(parsed["post_id"]),
        wp_post_url=parsed.get("permalink") or parsed.get("link"),
    )
