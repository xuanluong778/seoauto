"""Phase 2 SaaS APIs: Publish Guard intent-checks + AI SEO suggestions (async).

HMAC plugin callers only. Jobs are tenant-scoped (user/org/connection). Workers
run asynchronously — never call AI providers synchronously in the request path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wordpress_plugin import (
    WordpressConnection,
    WordpressPublishJob,
    WordpressRequestIdempotency,
)
from app.services.plugin_entitlement_service import check_plugin_entitlement
from app.services.wordpress_pairing_service import _count_org_sites  # noqa: PLC2701
from app.services.wordpress_plugin_security import personal_organization_id
from app.services.wordpress_plugin_update_service import _require_plugin_hmac

_LOG = logging.getLogger(__name__)

CMD_INTENT = "publish_guard_intent"
CMD_AI_SUGGEST = "ai_seo_suggest"

FEATURE_INTENT = "publish_guard"
FEATURE_AI = "ai_seo_assistant"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_user(db: Session, conn: WordpressConnection) -> User:
    user = db.get(User, int(conn.user_id))
    if user is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "seoauto_user_missing", "message": "Connection owner missing"},
        )
    return user


def _require_feature(db: Session, conn: WordpressConnection, feature: str) -> User:
    user = _load_user(db, conn)
    org_id = personal_organization_id(int(user.id))
    if int(conn.organization_id) != org_id and int(conn.user_id) != int(user.id):
        raise HTTPException(
            status_code=403,
            detail={"code": "seoauto_org_mismatch", "message": "Organization mismatch"},
        )
    site_count = _count_org_sites(db, org_id)
    ent = check_plugin_entitlement(db, user, current_site_count=site_count)
    if not ent.allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": "seoauto_entitlement_denied", "message": ent.reason or "denied"},
        )
    features = set(ent.enabled_features or [])
    if feature not in features:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "seoauto_feature_disabled",
                "message": f"Feature {feature} is not enabled for this site",
                "feature": feature,
            },
        )
    return user


def _idem_key(prefix: str, request_id: str) -> str:
    return f"{prefix}:{request_id.strip()[:96]}"


def _idem_get(db: Session, org_id: int, key: str) -> WordpressRequestIdempotency | None:
    return db.execute(
        select(WordpressRequestIdempotency).where(
            WordpressRequestIdempotency.organization_id == org_id,
            WordpressRequestIdempotency.idempotency_key == key,
        )
    ).scalar_one_or_none()


def _idem_store(
    db: Session,
    *,
    user: User,
    org_id: int,
    connection_id: int,
    key: str,
    path: str,
    response: dict[str, Any],
    code: int = 200,
) -> None:
    row = WordpressRequestIdempotency(
        user_id=int(user.id),
        organization_id=org_id,
        connection_id=connection_id,
        idempotency_key=key,
        request_path=path[:255],
        response_code=code,
        response_body_json=json.dumps(response, ensure_ascii=False),
    )
    db.add(row)
    db.commit()


def _job_public(job: WordpressPublishJob) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    if job.result_json:
        try:
            parsed = json.loads(job.result_json)
            if isinstance(parsed, dict):
                result = parsed
        except ValueError:
            result = None
    out: dict[str, Any] = {
        "ok": True,
        "job_id": str(job.id),
        "id": job.id,
        "request_id": job.request_id,
        "status": job.status,
        "command_type": job.command_type,
        "result": result,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "async": True,
    }
    if result and "suggestions" in result:
        out["suggestions"] = result.get("suggestions")
    return out


def _parse_body(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "seoauto_bad_json", "message": "Invalid JSON body"},
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "seoauto_bad_json", "message": "JSON object required"},
        )
    return data


def enqueue_intent_check(db: Session, request: Request, raw: bytes) -> dict[str, Any]:
    """POST /publish-guard/intent-checks — enqueue async duplicate/shared-intent job."""
    conn = _require_plugin_hmac(db, request, raw)
    user = _require_feature(db, conn, FEATURE_INTENT)
    org_id = personal_organization_id(int(user.id))
    body = _parse_body(raw)
    request_id = str(body.get("request_id") or uuid.uuid4()).strip()[:64]
    if not request_id:
        request_id = str(uuid.uuid4())

    idem = _idem_key("pg-intent", request_id)
    prior = _idem_get(db, org_id, idem)
    if prior is not None and prior.response_body_json:
        try:
            cached = json.loads(prior.response_body_json)
            if isinstance(cached, dict):
                return cached
        except ValueError:
            pass

    existing = db.execute(
        select(WordpressPublishJob).where(
            WordpressPublishJob.organization_id == org_id,
            WordpressPublishJob.request_id == request_id,
            WordpressPublishJob.command_type == CMD_INTENT,
        )
    ).scalar_one_or_none()
    if existing is not None:
        resp = _job_public(existing)
        return resp

    payload = {
        "request_id": request_id,
        "post_id": int(body.get("post_id") or 0),
        "title": str(body.get("title") or "")[:500],
        "content_excerpt": str(body.get("content_excerpt") or "")[:2000],
        "focus_keyword": str(body.get("focus_keyword") or "")[:200],
        "permalink": str(body.get("permalink") or "")[:2000],
        "locale": str(body.get("locale") or "")[:32],
        "site_url": str(body.get("site_url") or "")[:2000],
        "connection_id": int(conn.id),
        "site_id": str(conn.publishing_site_id or ""),
        "organization_id": org_id,
        "user_id": int(user.id),
    }
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=org_id,
        connection_id=int(conn.id),
        request_id=request_id,
        command_type=CMD_INTENT,
        status="queued",
        payload_json=json.dumps(payload, ensure_ascii=False),
        max_retries=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.workers.wordpress_phase2_worker import enqueue_phase2_job

    job.celery_task_id = enqueue_phase2_job(job.id)
    db.commit()
    db.refresh(job)

    resp = _job_public(job)
    _idem_store(
        db,
        user=user,
        org_id=org_id,
        connection_id=int(conn.id),
        key=idem,
        path="/api/wordpress-plugin/publish-guard/intent-checks",
        response=resp,
    )
    return resp


def get_intent_check(db: Session, request: Request, job_id: str) -> dict[str, Any]:
    """GET /publish-guard/intent-checks/{job_id} — poll tenant-scoped job."""
    conn = _require_plugin_hmac(db, request, b"")
    user = _require_feature(db, conn, FEATURE_INTENT)
    org_id = personal_organization_id(int(user.id))
    try:
        jid = int(str(job_id).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "seoauto_bad_job_id", "message": "job_id must be int"},
        ) from exc
    job = db.get(WordpressPublishJob, jid)
    if (
        job is None
        or int(job.organization_id) != org_id
        or int(job.user_id) != int(user.id)
        or job.command_type != CMD_INTENT
        or (job.connection_id is not None and int(job.connection_id) != int(conn.id))
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "seoauto_job_not_found", "message": "Job not found"},
        )
    return _job_public(job)


def enqueue_ai_suggestions(db: Session, request: Request, raw: bytes) -> dict[str, Any]:
    """POST /ai-seo/suggestions — enqueue async AI suggest job (no sync AI)."""
    conn = _require_plugin_hmac(db, request, raw)
    user = _require_feature(db, conn, FEATURE_AI)
    org_id = personal_organization_id(int(user.id))
    body = _parse_body(raw)
    request_id = str(body.get("request_id") or uuid.uuid4()).strip()[:64]
    if not request_id:
        request_id = str(uuid.uuid4())

    # Ignore client-claimed connection/site — bind to HMAC connection only.
    claimed_site = str(body.get("site_id") or "").strip()
    if claimed_site and claimed_site != str(conn.publishing_site_id or ""):
        raise HTTPException(
            status_code=403,
            detail={"code": "seoauto_site_claim_mismatch", "message": "site_id mismatch"},
        )

    idem = _idem_key("ai-suggest", request_id)
    prior = _idem_get(db, org_id, idem)
    if prior is not None and prior.response_body_json:
        try:
            cached = json.loads(prior.response_body_json)
            if isinstance(cached, dict):
                return cached
        except ValueError:
            pass

    existing = db.execute(
        select(WordpressPublishJob).where(
            WordpressPublishJob.organization_id == org_id,
            WordpressPublishJob.request_id == request_id,
            WordpressPublishJob.command_type == CMD_AI_SUGGEST,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _job_public(existing)

    kinds = body.get("kinds") if isinstance(body.get("kinds"), list) else []
    kinds_clean = [str(k).strip()[:32] for k in kinds if str(k).strip()][:12] or [
        "title",
        "meta",
        "outline",
        "faq",
        "cta",
        "internal_links",
    ]
    payload = {
        "request_id": request_id,
        "post_id": int(body.get("post_id") or 0),
        "title": str(body.get("title") or "")[:500],
        "content": str(body.get("content") or "")[:12000],
        "focus_keyword": str(body.get("focus_keyword") or "")[:200],
        "kinds": kinds_clean,
        "locale": str(body.get("locale") or "")[:32],
        "site_url": str(body.get("site_url") or "")[:2000],
        "connection_id": int(conn.id),
        "site_id": str(conn.publishing_site_id or ""),
        "organization_id": org_id,
        "user_id": int(user.id),
        # KB must stay org-scoped — workers must never use another tenant's KB.
        "kb_scope": {"organization_id": org_id, "user_id": int(user.id)},
    }
    job = WordpressPublishJob(
        user_id=int(user.id),
        organization_id=org_id,
        connection_id=int(conn.id),
        request_id=request_id,
        command_type=CMD_AI_SUGGEST,
        status="queued",
        payload_json=json.dumps(payload, ensure_ascii=False),
        max_retries=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.workers.wordpress_phase2_worker import enqueue_phase2_job

    job.celery_task_id = enqueue_phase2_job(job.id)
    db.commit()
    db.refresh(job)

    resp = _job_public(job)
    _idem_store(
        db,
        user=user,
        org_id=org_id,
        connection_id=int(conn.id),
        key=idem,
        path="/api/wordpress-plugin/ai-seo/suggestions",
        response=resp,
    )
    return resp


def get_ai_suggestions(db: Session, request: Request, job_id: str) -> dict[str, Any]:
    """GET /ai-seo/suggestions/{job_id} — poll tenant-scoped AI job."""
    conn = _require_plugin_hmac(db, request, b"")
    user = _require_feature(db, conn, FEATURE_AI)
    org_id = personal_organization_id(int(user.id))
    try:
        jid = int(str(job_id).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "seoauto_bad_job_id", "message": "job_id must be int"},
        ) from exc
    job = db.get(WordpressPublishJob, jid)
    if (
        job is None
        or int(job.organization_id) != org_id
        or int(job.user_id) != int(user.id)
        or job.command_type != CMD_AI_SUGGEST
        or (job.connection_id is not None and int(job.connection_id) != int(conn.id))
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "seoauto_job_not_found", "message": "Job not found"},
        )
    return _job_public(job)


def execute_phase2_job(db: Session, job_id: int) -> dict[str, Any]:
    """Celery entry: run intent heuristic or enqueue AI work asynchronously."""
    job = db.get(WordpressPublishJob, int(job_id))
    if job is None:
        return {"ok": False, "error": "job_not_found"}
    if job.status in ("success", "failed", "blocked"):
        return {"ok": job.status == "success", "status": job.status, "job": _job_public(job)}

    now = _utc_now()
    job.status = "running"
    job.started_at = now
    db.commit()

    try:
        payload = json.loads(job.payload_json or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}

    try:
        if job.command_type == CMD_INTENT:
            result = _run_intent_heuristic(payload)
        elif job.command_type == CMD_AI_SUGGEST:
            # Async path only: build deterministic draft suggestions from local signals.
            # Real LLM providers must be wired via a separate worker/task later —
            # never called inline from the HTTP handler.
            result = _run_ai_suggest_async_stub(payload)
        else:
            job.status = "failed"
            job.error_code = "unknown_command"
            job.error_message = f"Unsupported command_type={job.command_type}"
            job.completed_at = _utc_now()
            db.commit()
            return {"ok": False, "status": "failed"}

        job.result_json = json.dumps(result, ensure_ascii=False)
        job.status = "success"
        job.completed_at = _utc_now()
        db.commit()
        return {"ok": True, "status": "success", "job": _job_public(job)}
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("phase2 job %s failed", job_id)
        job.status = "failed"
        job.error_code = "worker_error"
        job.error_message = str(exc)[:500]
        job.completed_at = _utc_now()
        db.commit()
        return {"ok": False, "status": "failed", "error": str(exc)[:200]}


def _normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    return t[:200]


def _run_intent_heuristic(payload: dict[str, Any]) -> dict[str, Any]:
    """Tenant-local heuristic (no external AI). Duplicate risk via title fingerprint."""
    title = _normalize_title(str(payload.get("title") or ""))
    keyword = str(payload.get("focus_keyword") or "").strip().lower()
    excerpt = str(payload.get("content_excerpt") or "")
    fingerprint = hashlib.sha256(f"{title}|{keyword}".encode()).hexdigest()[:16]
    risks: list[dict[str, Any]] = []
    if len(title) < 8:
        risks.append(
            {
                "code": "thin_title",
                "severity": "warn",
                "message": "Title is very short for intent matching",
            }
        )
    if keyword and keyword not in title and keyword not in excerpt.lower():
        risks.append(
            {
                "code": "keyword_mismatch",
                "severity": "info",
                "message": "Focus keyword not found in title/excerpt",
            }
        )
    return {
        "blocking": False,
        "fingerprint": fingerprint,
        "organization_id": payload.get("organization_id"),
        "risks": risks,
        "duplicates": [],
        "shared_intent": [],
        "engine": "heuristic_v1",
    }


def _run_ai_suggest_async_stub(payload: dict[str, Any]) -> dict[str, Any]:
    """Produce structured suggestion slots without calling an LLM in-process.

    This satisfies the async contract (HTTP returns queued; worker fills result).
    Production can replace this body with an off-band LLM task that writes the
    same result_json shape, still scoped to payload['kb_scope'].
    """
    title = str(payload.get("title") or "").strip() or "Untitled"
    keyword = str(payload.get("focus_keyword") or "").strip()
    kinds = payload.get("kinds") if isinstance(payload.get("kinds"), list) else []
    org = (payload.get("kb_scope") or {}).get("organization_id")
    suggestions: dict[str, Any] = {}
    for kind in kinds:
        k = str(kind)
        if k == "title":
            suggestions["title"] = [
                f"{title} | {keyword}".strip(" |") if keyword else f"{title} — hướng dẫn chi tiết"
            ]
        elif k == "meta":
            suggestions["meta"] = [
                f"Tóm tắt: {title[:110]}. Từ khóa: {keyword or 'n/a'}."
            ]
        elif k == "outline":
            suggestions["outline"] = [
                f"Giới thiệu {title}",
                f"Phân tích {keyword or 'chủ đề'}",
                "Kết luận & CTA",
            ]
        elif k == "faq":
            suggestions["faq"] = [
                {"q": f"{title} là gì?", "a": "…"},
                {"q": f"Cách tối ưu {keyword or title}?", "a": "…"},
            ]
        elif k == "cta":
            suggestions["cta"] = [f"Bắt đầu tối ưu {keyword or title} với SEOAuto"]
        elif k == "internal_links":
            suggestions["internal_links"] = []
        else:
            suggestions[k] = []
    return {
        "suggestions": suggestions,
        "kb_scope": {"organization_id": org},
        "engine": "async_stub_v1",
        "provider": "none_sync",
    }
