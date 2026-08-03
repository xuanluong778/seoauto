"""WordPress SEO Helper pairing API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user, get_optional_current_user
from app.services.rate_limiter import RATE_RULES
from app.services.wordpress_pairing_service import create_pairing_code, redeem_pairing_code
from app.services.wordpress_plugin_ci_auth import require_ci_release_token
from app.services.wordpress_plugin_connection_service import (
    check_connection,
    disconnect_connection,
    get_entitlement_for_user,
    get_pairing_code_status,
    list_connections_for_user,
    refresh_entitlement_for_connection,
)
from app.services.wordpress_plugin_publish_service import (
    create_publish_job,
    get_job_for_user,
    job_to_dict,
)
from app.services.wordpress_plugin_release_service import (
    create_release,
    get_release,
    list_releases,
    publish_release,
    release_to_dict,
    withdraw_release,
)
from app.services.wordpress_plugin_update_service import (
    check_for_update,
    resolve_download,
    _require_plugin_hmac,
)
from app.services.wordpress_plugin_phase2_service import (
    enqueue_ai_suggestions,
    enqueue_intent_check,
    get_ai_suggestions,
    get_intent_check,
)

router = APIRouter(prefix="/wordpress-plugin", tags=["wordpress-plugin"])

# Register IP rate-limit rules (used by global middleware if wired; service also enforces).
RATE_RULES.setdefault("/api/wordpress-plugin/pair", (30, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/pairing-codes", (20, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/pairing-codes/{pairing_code_id}", (120, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/connections", (60, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/connections/{connection_id}", (40, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/connections/{connection_id}/check", (30, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/entitlement", (60, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/jobs", (60, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/jobs/{job_id}", (120, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/updates/check", (30, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/updates/download/{token}", (60, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/releases", (30, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/releases/{version}", (60, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/releases/{version}/publish", (20, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/releases/{version}/withdraw", (20, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/publish-guard/intent-checks", (40, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/publish-guard/intent-checks/{job_id}", (120, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/ai-seo/suggestions", (30, 300))
RATE_RULES.setdefault("/api/wordpress-plugin/ai-seo/suggestions/{job_id}", (120, 300))


class CreatePairingCodeBody(BaseModel):
    organization_id: int | None = None
    domain_hint: str | None = Field(default=None, max_length=255)


class RedeemPairingBody(BaseModel):
    code: str = Field(..., min_length=8, max_length=32)
    domain: str = Field(..., min_length=1, max_length=255)
    site_url: str | None = Field(default=None, max_length=2000)
    wp_version: str | None = Field(default=None, max_length=32)
    php_version: str | None = Field(default=None, max_length=32)
    seo_plugin: str | None = Field(default=None, max_length=64)
    plugin_version: str | None = Field(default=None, max_length=32)
    organization_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


@router.get("/entitlement")
def api_plugin_entitlement(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    """Entitlement for Settings UI (JWT) or plugin refresh (HMAC).

    Plugin HMAC path recomputes features (content_ops only when opt-in granted) and returns a
    site_secret-signed snapshot. Does not burn credits or change pairing.
    """
    if (request.headers.get("X-SEOAuto-Signature") or "").strip():
        conn = _require_plugin_hmac(db, request, b"")
        return refresh_entitlement_for_connection(db, conn)
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_auth_required", "message": "JWT or HMAC required"},
        )
    return get_entitlement_for_user(db, current_user)


@router.get("/connections")
def api_list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List plugin connections for current tenant."""
    return list_connections_for_user(db, current_user)


@router.get("/pairing-codes/{pairing_code_id}")
def api_get_pairing_code_status(
    pairing_code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll pairing code until consumed or expired."""
    return get_pairing_code_status(db, current_user, int(pairing_code_id))


@router.post("/connections/{connection_id}/check")
def api_check_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ping SEO Helper plugin for live status."""
    return check_connection(db, current_user, int(connection_id))


@router.delete("/connections/{connection_id}")
def api_disconnect_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Disconnect plugin (does not delete WordPress posts)."""
    return disconnect_connection(db, current_user, int(connection_id))


@router.post("/pairing-codes")
def api_create_pairing_code(
    body: CreatePairingCodeBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Logged-in user creates SA-XXXX-XXXX (shown once, 10 minutes, one-time)."""
    return create_pairing_code(
        db,
        current_user,
        organization_id=body.organization_id,
        domain_hint=body.domain_hint,
        request=request,
    )


@router.post("/pair")
def api_redeem_pairing_code(
    body: RedeemPairingBody,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Plugin redeems pairing code — returns site_secret once + signed entitlement."""
    return redeem_pairing_code(
        db,
        code=body.code,
        domain=body.domain,
        site_url=body.site_url,
        wp_version=body.wp_version,
        php_version=body.php_version,
        seo_plugin=body.seo_plugin,
        plugin_version=body.plugin_version,
        organization_id=body.organization_id,
        idempotency_key=body.idempotency_key,
        request=request,
    )


class CreatePublishJobBody(BaseModel):
    connection_id: int | None = None
    wp_site_id: str | None = Field(default=None, max_length=64)
    schedule_id: int | None = None
    request_id: str | None = Field(default=None, max_length=64)
    command_type: str = Field(default="post_create", max_length=64)
    source_article_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/jobs")
def api_create_publish_job(
    body: CreatePublishJobBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Enqueue WordPress publish command (entitlement check → Celery → plugin)."""
    job = create_publish_job(
        db,
        user=current_user,
        payload=body.payload,
        connection_id=body.connection_id,
        wp_site_id=body.wp_site_id,
        schedule_id=body.schedule_id,
        request_id=body.request_id,
        command_type=body.command_type,
        source_article_id=body.source_article_id,
        enqueue=True,
    )
    return {"ok": job.status not in ("blocked", "failed"), "job": job_to_dict(job)}


@router.get("/jobs/{job_id}")
def api_get_publish_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll publish job status for UI."""
    job = get_job_for_user(db, int(job_id), current_user)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job_to_dict(job)}


@router.post("/updates/check")
async def api_plugin_update_check(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """HMAC-authenticated update check from the WordPress plugin (LOCKED OK for security patches)."""
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return check_for_update(db, request, payload, raw)


@router.get("/updates/download/{token}")
def api_plugin_update_download(
    token: str,
    db: Session = Depends(get_db),
):
    """Short-lived one-time ZIP download (HTTPS). Streams from R2/S3; never logs full URL."""
    src, release, mode = resolve_download(db, token)
    filename = f"seoauto-seo-helper-{release.version}.zip"
    headers = {"X-SEOAuto-Package-SHA256": release.package_sha256}
    if mode == "path":
        assert isinstance(src, Path)
        return FileResponse(
            path=str(src),
            media_type="application/zip",
            filename=filename,
            headers=headers,
        )
    return StreamingResponse(
        src,
        media_type="application/zip",
        headers={
            **headers,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# Phase 2 — Publish Guard + AI SEO (HMAC plugin; async workers; opt-in features)
# ---------------------------------------------------------------------------


@router.post("/publish-guard/intent-checks")
async def api_publish_guard_intent_enqueue(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue duplicate/shared-intent check (async). Requires publish_guard feature."""
    raw = await request.body()
    return enqueue_intent_check(db, request, raw)


@router.get("/publish-guard/intent-checks/{job_id}")
async def api_publish_guard_intent_status(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Poll intent-check job (tenant-scoped)."""
    return get_intent_check(db, request, job_id)


@router.post("/ai-seo/suggestions")
async def api_ai_seo_suggestions_enqueue(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue AI SEO suggestions (async worker — never sync LLM). Requires ai_seo_assistant."""
    raw = await request.body()
    return enqueue_ai_suggestions(db, request, raw)


@router.get("/ai-seo/suggestions/{job_id}")
async def api_ai_seo_suggestions_status(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Poll AI suggestion job (tenant-scoped KB)."""
    return get_ai_suggestions(db, request, job_id)


# ---------------------------------------------------------------------------
# Internal CI release APIs (X-SEOAuto-CI-Token) — not WordPress site_secret
# ---------------------------------------------------------------------------


class CreateReleaseBody(BaseModel):
    version: str = Field(..., max_length=32)
    channel: str = Field(default="stable", max_length=16)
    storage_key: str = Field(..., max_length=1000)
    sha256: str = Field(..., min_length=64, max_length=64)
    signature: str = Field(default="", max_length=128)
    changelog_url: str = Field(default="", max_length=2000)
    changelog: str | None = None
    requires_wp: str = Field(default="6.0", max_length=16)
    requires_php: str = Field(default="8.1", max_length=16)
    tested_wp: str = Field(default="6.7", max_length=16)
    autoupdate: bool = False
    security_patch: bool = False
    rollout_percent: int = Field(default=100, ge=0, le=100)
    allowed_site_ids: list[str] = Field(default_factory=list)
    blocked_site_ids: list[str] = Field(default_factory=list)
    min_from_version: str | None = Field(default=None, max_length=32)
    verify_object_exists: bool = True


class WithdrawBody(BaseModel):
    reason: str = Field(default="", max_length=500)
    channel: str = Field(default="stable", max_length=16)


@router.post("/releases")
def api_ci_create_release(
    body: CreateReleaseBody,
    request: Request,
    db: Session = Depends(get_db),
    _ci: str = Depends(require_ci_release_token),
) -> dict[str, Any]:
    """Create draft release after CI uploaded ZIP to R2/S3. Does not publish."""
    row = create_release(
        db,
        version=body.version,
        channel=body.channel,
        storage_key=body.storage_key,
        sha256=body.sha256,
        signature=body.signature,
        changelog_url=body.changelog_url,
        changelog_md=body.changelog,
        requires_wp=body.requires_wp,
        requires_php=body.requires_php,
        tested_wp=body.tested_wp,
        autoupdate=body.autoupdate,
        security_patch=body.security_patch,
        rollout_percent=body.rollout_percent,
        allowed_site_ids=body.allowed_site_ids,
        blocked_site_ids=body.blocked_site_ids,
        min_from_version=body.min_from_version,
        verify_object_exists=body.verify_object_exists,
    )
    return {"ok": True, "release": release_to_dict(row)}


@router.get("/releases")
def api_ci_list_releases(
    request: Request,
    channel: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _ci: str = Depends(require_ci_release_token),
) -> dict[str, Any]:
    rows = list_releases(db, channel=channel, status=status, limit=limit)
    return {"ok": True, "releases": [release_to_dict(r) for r in rows]}


@router.get("/releases/{version}")
def api_ci_get_release(
    version: str,
    request: Request,
    channel: str = "stable",
    db: Session = Depends(get_db),
    _ci: str = Depends(require_ci_release_token),
) -> dict[str, Any]:
    row = get_release(db, version=version, channel=channel)
    return {"ok": True, "release": release_to_dict(row)}


@router.post("/releases/{version}/publish")
def api_ci_publish_release(
    version: str,
    request: Request,
    channel: str = "stable",
    db: Session = Depends(get_db),
    _ci: str = Depends(require_ci_release_token),
) -> dict[str, Any]:
    """Publish only after staging E2E. Refuses if package missing in storage."""
    row = publish_release(db, version=version, channel=channel)
    return {"ok": True, "release": release_to_dict(row)}


@router.post("/releases/{version}/withdraw")
def api_ci_withdraw_release(
    version: str,
    body: WithdrawBody,
    request: Request,
    db: Session = Depends(get_db),
    _ci: str = Depends(require_ci_release_token),
) -> dict[str, Any]:
    row = withdraw_release(db, version=version, channel=body.channel or "stable", reason=body.reason)
    return {"ok": True, "release": release_to_dict(row)}
