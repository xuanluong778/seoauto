"""Internal release registry management (CI token) — create / publish / withdraw.

Does not use WordPress site_secret. Package bytes live in StorageAdapter (R2/S3).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.wordpress_plugin import WordpressPluginRelease, WordpressPluginUpdateEvent
from app.services.storage_adapter import (
    build_release_storage_key,
    get_storage_adapter,
    looks_like_storage_key,
)
from app.services.wordpress_plugin_update_service import (
    ALLOWED_CHANNELS,
    PLUGIN_SLUG,
    _newer_than,
    _norm_ver,
)

logger = logging.getLogger(__name__)

MIN_KEEP_PUBLISHED = int(os.getenv("WP_PLUGIN_MIN_KEEP_RELEASES", "3"))
RELEASE_SIGNING_KEY = lambda: str(os.getenv("WP_PLUGIN_RELEASE_SIGNING_KEY") or "").strip()
# Fixed manual-install URL stays the same across upgrades; publish refreshes the file.
# Example: https://seoauto.vn/static/downloads/seoauto-seo-helper-latest.zip
PUBLIC_DOWNLOAD_DIR = Path(
    os.getenv(
        "WP_PLUGIN_PUBLIC_DOWNLOAD_DIR",
        str(Path(__file__).resolve().parents[2] / "static" / "downloads"),
    )
).expanduser()
PUBLIC_LATEST_NAME = "seoauto-seo-helper-latest.zip"
# Comma-separated; empty = all channels. Use "stable" to only promote GA to the button URL.
PUBLIC_SYNC_CHANNELS = {
    c.strip().lower()
    for c in (os.getenv("WP_PLUGIN_PUBLIC_SYNC_CHANNELS") or "stable,beta").split(",")
    if c.strip()
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sign_package_release(*, version: str, sha256: str, channel: str) -> str:
    key = RELEASE_SIGNING_KEY()
    if not key:
        # Deterministic fallback for local staging only — production must set env.
        key = "local-dev-release-signing-key"
    payload = f"{_norm_ver(version)}|{sha256.lower()}|{channel}"
    return hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_package_release_signature(*, version: str, sha256: str, channel: str, signature: str) -> bool:
    expected = sign_package_release(version=version, sha256=sha256, channel=channel)
    return bool(signature) and hmac.compare_digest(expected, signature.lower().strip())


def _parse_site_id_list(raw: str | list | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return [p.strip() for p in s.split(",") if p.strip()]


def release_to_dict(row: WordpressPluginRelease) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "slug": row.slug,
        "version": row.version,
        "channel": row.channel,
        "status": row.status,
        "storage_key": row.storage_key or "",
        "sha256": row.package_sha256,
        "signature": row.package_signature or "",
        "changelog_url": row.changelog_url or "",
        "changelog": row.changelog_md or "",
        "requires_wp": row.requires_wp,
        "requires_php": row.requires_php,
        "tested_wp": row.tested,
        "tested": row.tested,
        "autoupdate": bool(row.autoupdate),
        "security_patch": bool(row.security_patch),
        "rollout_percent": int(row.rollout_percent or 100),
        "allowed_site_ids": _parse_site_id_list(row.allowed_site_ids_json),
        "blocked_site_ids": _parse_site_id_list(row.blocked_site_ids_json),
        "released_at": row.released_at.isoformat() if row.released_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "min_from_version": row.min_from_version,
    }


def _audit(db: Session, event_type: str, release: WordpressPluginRelease | None, detail: dict[str, Any]) -> None:
    safe = dict(detail)
    for k in ("package", "package_url", "token", "site_secret", "download_url"):
        safe.pop(k, None)
    release_id = None
    if release is not None and getattr(release, "id", None) is not None:
        release_id = int(release.id)
    db.add(
        WordpressPluginUpdateEvent(
            connection_id=None,
            release_id=release_id,
            event_type=event_type,
            current_version=None,
            target_version=release.version if release else None,
            detail_json=json.dumps(safe, ensure_ascii=False),
        )
    )


def _reject_dev_suffix_for_stable(version: str, channel: str) -> None:
    v = _norm_ver(version)
    if channel == "stable" and re.search(r"-(dev|alpha|rc)\b", v, re.I):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "dev_suffix_forbidden",
                "message": "Stable releases cannot use -dev / -alpha / -rc version suffixes",
            },
        )


def create_release(
    db: Session,
    *,
    version: str,
    channel: str = "stable",
    storage_key: str,
    sha256: str,
    signature: str = "",
    changelog_url: str = "",
    changelog_md: str | None = None,
    requires_wp: str = "6.0",
    requires_php: str = "8.1",
    tested_wp: str = "6.7",
    autoupdate: bool = False,
    security_patch: bool = False,
    rollout_percent: int = 100,
    allowed_site_ids: list[str] | None = None,
    blocked_site_ids: list[str] | None = None,
    min_from_version: str | None = None,
    verify_object_exists: bool = True,
    verify_signature: bool = True,
) -> WordpressPluginRelease:
    channel = channel if channel in ALLOWED_CHANNELS else "stable"
    version = _norm_ver(version)
    _reject_dev_suffix_for_stable(version, channel)
    sha256 = sha256.lower().strip()
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise HTTPException(status_code=400, detail={"code": "bad_sha256", "message": "sha256 must be 64 hex chars"})
    if not storage_key or not looks_like_storage_key(storage_key):
        raise HTTPException(status_code=400, detail={"code": "bad_storage_key", "message": "storage_key required"})
    # storage_key already validated above


    if verify_signature:
        if signature:
            if not verify_package_release_signature(
                version=version, sha256=sha256, channel=channel, signature=signature
            ):
                raise HTTPException(status_code=400, detail={"code": "bad_signature", "message": "Release signature mismatch"})
        else:
            signature = sign_package_release(version=version, sha256=sha256, channel=channel)

    storage = get_storage_adapter()
    if verify_object_exists and not storage.exists(storage_key):
        raise HTTPException(
            status_code=400,
            detail={"code": "package_missing_in_storage", "message": f"Object not found for key (redacted)"},
        )

    existing = (
        db.query(WordpressPluginRelease)
        .filter(
            WordpressPluginRelease.slug == PLUGIN_SLUG,
            WordpressPluginRelease.version == version,
            WordpressPluginRelease.channel == channel,
        )
        .first()
    )
    if existing and existing.status == "published":
        raise HTTPException(status_code=409, detail={"code": "already_published", "message": "Published release exists"})

    rollout_percent = max(0, min(100, int(rollout_percent)))
    allowed_json = json.dumps(allowed_site_ids or [], ensure_ascii=False)
    blocked_json = json.dumps(blocked_site_ids or [], ensure_ascii=False)

    if existing:
        row = existing
        row.status = "draft"
        row.storage_key = storage_key
        row.package_storage_path = storage_key  # keep legacy field in sync with key
        row.package_sha256 = sha256
        row.package_signature = signature.lower()
        row.requires_wp = requires_wp
        row.requires_php = requires_php
        row.tested = tested_wp
        row.changelog_url = changelog_url
        row.changelog_md = changelog_md
        row.autoupdate = autoupdate
        row.security_patch = security_patch
        row.rollout_percent = rollout_percent
        row.allowed_site_ids_json = allowed_json
        row.blocked_site_ids_json = blocked_json
        row.min_from_version = min_from_version
        row.published_at = None
        row.released_at = None
    else:
        row = WordpressPluginRelease(
            slug=PLUGIN_SLUG,
            version=version,
            channel=channel,
            status="draft",
            storage_key=storage_key,
            package_storage_path=storage_key,
            package_sha256=sha256,
            package_signature=signature.lower(),
            requires_wp=requires_wp,
            requires_php=requires_php,
            tested=tested_wp,
            changelog_url=changelog_url,
            changelog_md=changelog_md,
            autoupdate=autoupdate,
            security_patch=security_patch,
            rollout_percent=rollout_percent,
            allowed_site_ids_json=allowed_json,
            blocked_site_ids_json=blocked_json,
            min_from_version=min_from_version,
        )
        db.add(row)

    db.flush()
    _audit(db, "release_create", row, {"channel": channel, "sha256": sha256, "storage_key": storage_key})
    db.commit()
    db.refresh(row)
    return row


def sync_public_manual_download(release: WordpressPluginRelease) -> dict[str, Any] | None:
    """Refresh fixed public ZIP used by SEOAuto “Tải plugin” button.

    The button URL never changes; only the file bytes are replaced on publish.
    """
    channel = str(release.channel or "stable").strip().lower()
    if PUBLIC_SYNC_CHANNELS and channel not in PUBLIC_SYNC_CHANNELS:
        logger.info("skip public download sync for channel=%s", channel)
        return None

    key = (release.storage_key or release.package_storage_path or "").strip()
    if not key or not looks_like_storage_key(key):
        raise ValueError("release storage_key missing")

    storage = get_storage_adapter()
    if not storage.exists(key):
        raise FileNotFoundError(f"package missing in storage for {release.version}")

    blob = storage.get_bytes(key)
    if not blob:
        raise ValueError("empty package bytes")

    PUBLIC_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    versioned = PUBLIC_DOWNLOAD_DIR / f"seoauto-seo-helper-{release.version}.zip"
    latest = PUBLIC_DOWNLOAD_DIR / PUBLIC_LATEST_NAME
    sha_file = PUBLIC_DOWNLOAD_DIR / f"{PUBLIC_LATEST_NAME}.sha256"

    versioned.write_bytes(blob)
    latest.write_bytes(blob)
    digest = (release.package_sha256 or hashlib.sha256(blob).hexdigest()).lower()
    sha_file.write_text(f"{digest}  {PUBLIC_LATEST_NAME}\n", encoding="utf-8")

    try:
        os.chmod(versioned, 0o644)
        os.chmod(latest, 0o644)
        os.chmod(sha_file, 0o644)
    except OSError:
        pass

    info = {
        "version": release.version,
        "channel": channel,
        "bytes": len(blob),
        "sha256": digest,
        "latest_path": str(latest),
        "versioned_path": str(versioned),
        "public_url": f"/static/downloads/{PUBLIC_LATEST_NAME}",
    }
    logger.info(
        "public manual download synced version=%s channel=%s bytes=%s path=%s",
        release.version,
        channel,
        len(blob),
        latest,
    )
    return info


def publish_release(db: Session, *, version: str, channel: str = "stable") -> WordpressPluginRelease:
    channel = channel if channel in ALLOWED_CHANNELS else "stable"
    version = _norm_ver(version)
    row = (
        db.query(WordpressPluginRelease)
        .filter(
            WordpressPluginRelease.slug == PLUGIN_SLUG,
            WordpressPluginRelease.version == version,
            WordpressPluginRelease.channel == channel,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "release_not_found", "message": "Release not found"})
    if row.status == "withdrawn":
        raise HTTPException(status_code=400, detail={"code": "withdrawn", "message": "Cannot publish withdrawn release"})
    _reject_dev_suffix_for_stable(row.version, channel)

    storage = get_storage_adapter()
    key = row.storage_key or row.package_storage_path
    if not key or not storage.exists(key):
        raise HTTPException(
            status_code=400,
            detail={"code": "package_missing_in_storage", "message": "Package missing; refuse publish"},
        )

    now = _utc_now()
    row.status = "published"
    row.published_at = now
    row.released_at = now
    _audit(db, "release_publish", row, {"channel": channel})
    db.commit()
    db.refresh(row)

    # Keep at least MIN_KEEP_PUBLISHED published versions for rollback (do not auto-delete objects).
    _ensure_min_published_kept(db, channel=channel)

    # Fixed “Tải plugin” URL: same path forever; overwrite ZIP on each publish.
    try:
        sync_public_manual_download(row)
    except Exception as exc:  # noqa: BLE001 — publish must succeed even if static sync fails
        logger.exception("public download sync failed version=%s: %s", row.version, exc)
        _audit(db, "release_public_sync_failed", row, {"error": str(exc)[:300]})
        db.commit()

    return row


def withdraw_release(db: Session, *, version: str, channel: str = "stable", reason: str = "") -> WordpressPluginRelease:
    channel = channel if channel in ALLOWED_CHANNELS else "stable"
    version = _norm_ver(version)
    row = (
        db.query(WordpressPluginRelease)
        .filter(
            WordpressPluginRelease.slug == PLUGIN_SLUG,
            WordpressPluginRelease.version == version,
            WordpressPluginRelease.channel == channel,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "release_not_found", "message": "Release not found"})
    row.status = "withdrawn"
    _audit(db, "release_withdraw", row, {"channel": channel, "reason": reason[:500]})
    db.commit()
    db.refresh(row)
    return row


def get_release(db: Session, *, version: str, channel: str = "stable") -> WordpressPluginRelease:
    channel = channel if channel in ALLOWED_CHANNELS else "stable"
    version = _norm_ver(version)
    row = (
        db.query(WordpressPluginRelease)
        .filter(
            WordpressPluginRelease.slug == PLUGIN_SLUG,
            WordpressPluginRelease.version == version,
            WordpressPluginRelease.channel == channel,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "release_not_found", "message": "Release not found"})
    return row


def list_releases(db: Session, *, channel: str | None = None, status: str | None = None, limit: int = 50) -> list[WordpressPluginRelease]:
    q = db.query(WordpressPluginRelease).filter(WordpressPluginRelease.slug == PLUGIN_SLUG)
    if channel:
        q = q.filter(WordpressPluginRelease.channel == channel)
    if status:
        q = q.filter(WordpressPluginRelease.status == status)
    rows = q.order_by(WordpressPluginRelease.id.desc()).limit(max(1, min(200, limit))).all()
    return rows


def _ensure_min_published_kept(db: Session, *, channel: str) -> None:
    """Document retention: never auto-withdraw below MIN_KEEP; only audit count."""
    published = (
        db.query(WordpressPluginRelease)
        .filter(
            WordpressPluginRelease.slug == PLUGIN_SLUG,
            WordpressPluginRelease.channel == channel,
            WordpressPluginRelease.status == "published",
        )
        .all()
    )
    published.sort(key=lambda r: _norm_ver(r.version), reverse=True)
    # Soft policy: leave all published; CI/operators withdraw bad ones manually.
    # Guardrail: if somehow fewer than MIN_KEEP after withdraw, log warning event.
    if len(published) < MIN_KEEP_PUBLISHED:
        _audit(
            db,
            "release_keep_warning",
            published[0] if published else None,
            {"channel": channel, "published_count": len(published), "min_keep": MIN_KEEP_PUBLISHED},
        )
        db.commit()


def site_eligible_for_release(release: WordpressPluginRelease, site_id: str) -> bool:
    """Canary / allow / block lists."""
    site_id = str(site_id or "").strip()
    blocked = set(_parse_site_id_list(release.blocked_site_ids_json))
    if site_id and site_id in blocked:
        return False
    allowed = _parse_site_id_list(release.allowed_site_ids_json)
    if allowed and site_id not in set(allowed):
        return False
    pct = int(release.rollout_percent if release.rollout_percent is not None else 100)
    if pct >= 100:
        return True
    if pct <= 0:
        return False
    # Stable bucket by site_id hash.
    h = int(hashlib.sha256(f"{release.version}|{site_id}".encode()).hexdigest()[:8], 16)
    return (h % 100) < pct
