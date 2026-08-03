"""Private SEO Helper plugin updates — check + short-lived download tokens.



Independent of Billing/Credit. LOCKED connections still receive security patches.

Uses existing site_secret HMAC (does not change HMAC algorithm).

ZIP packages live in StorageAdapter (R2/S3); never in DB blobs.

"""



from __future__ import annotations



import hashlib

import hmac

import json

import os

import secrets

import tempfile

from datetime import datetime, timedelta, timezone

from pathlib import Path

from typing import Any, Iterator



from fastapi import HTTPException, Request, status

from sqlalchemy.orm import Session



from app.models.wordpress_plugin import (

    WordpressConnection,

    WordpressPluginDownloadToken,

    WordpressPluginRelease,

    WordpressPluginUpdateEvent,

)

from app.services.storage_adapter import get_storage_adapter, looks_like_storage_key, redact_url_for_log

from app.services.wordpress_plugin_hmac import MAX_SKEW_SECONDS, normalize_path, verify

from app.services.wordpress_plugin_security import decrypt_site_secret



PLUGIN_SLUG = "seoauto-seo-helper"

DOWNLOAD_TTL_SECONDS = int(os.getenv("WP_PLUGIN_DOWNLOAD_TTL_SECONDS", "900"))  # 15 min

ALLOWED_CHANNELS = frozenset({"stable", "beta"})

PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "https://seoauto.vn").rstrip("/")

RELEASE_STORAGE = Path(

    os.getenv("WP_PLUGIN_RELEASE_STORAGE", str(Path(__file__).resolve().parents[2] / "data" / "plugin_releases"))

)





def _utc_now() -> datetime:

    return datetime.now(timezone.utc)





def _norm_ver(raw: str) -> str:

    return str(raw or "").strip().lstrip("vV")





def _newer_than(candidate: str, current: str) -> bool:

    """PEP 440-ish compare via tuple of ints + suffix; avoids packaging dependency."""



    def parts(v: str) -> tuple:

        v = _norm_ver(v)

        main, _, pre = v.partition("-")

        nums = []

        for p in main.split("."):

            try:

                nums.append(int(p))

            except ValueError:

                nums.append(0)

        while len(nums) < 3:

            nums.append(0)

        pre_rank = 1 if pre == "" else 0

        return (tuple(nums), pre_rank, pre)



    try:

        return parts(candidate) > parts(current)

    except Exception:

        return _norm_ver(candidate) != _norm_ver(current) and _norm_ver(candidate) > _norm_ver(current)





def _hash_token(token: str) -> str:

    return hashlib.sha256(token.encode("utf-8")).hexdigest()





def sign_release_payload(site_secret: str, version: str, sha256: str, expires_at: str) -> str:

    payload = f"{version}|{sha256.lower()}|{expires_at}"

    return hmac.new(site_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()





def _require_plugin_hmac(db: Session, request: Request, body: bytes) -> WordpressConnection:

    site_id = (request.headers.get("X-SEOAuto-Site-ID") or "").strip()

    conn_id = (request.headers.get("X-SEOAuto-Connection-ID") or "").strip()

    ts = (request.headers.get("X-SEOAuto-Timestamp") or "").strip()

    nonce = (request.headers.get("X-SEOAuto-Nonce") or "").strip()

    req_id = (request.headers.get("X-SEOAuto-Request-ID") or "").strip()

    sig = (request.headers.get("X-SEOAuto-Signature") or "").strip()



    if not all([site_id, conn_id, ts, nonce, req_id, sig]):

        raise HTTPException(status_code=401, detail={"code": "seoauto_missing_headers", "message": "Missing HMAC headers"})



    try:

        ts_i = int(ts)

    except ValueError as exc:

        raise HTTPException(status_code=401, detail={"code": "seoauto_bad_timestamp", "message": "Bad timestamp"}) from exc

    if abs(int(_utc_now().timestamp()) - ts_i) > MAX_SKEW_SECONDS:

        raise HTTPException(status_code=401, detail={"code": "seoauto_timestamp_expired", "message": "Timestamp expired"})



    try:

        cid = int(conn_id)

    except ValueError as exc:

        raise HTTPException(status_code=401, detail={"code": "seoauto_bad_connection", "message": "Bad connection id"}) from exc



    conn = db.get(WordpressConnection, cid)

    if conn is None:

        raise HTTPException(status_code=401, detail={"code": "seoauto_unknown_connection", "message": "Unknown connection"})

    stored_site = str(conn.publishing_site_id or "")

    if stored_site and stored_site != site_id:

        raise HTTPException(status_code=403, detail={"code": "seoauto_site_mismatch", "message": "Site ID mismatch"})



    secret = decrypt_site_secret(conn.site_secret_encrypted or "")

    if not secret:

        raise HTTPException(status_code=401, detail={"code": "seoauto_bad_secret", "message": "Invalid connection secret"})



    path = normalize_path(request.url.path)

    if not verify(secret, sig, request.method, path, ts, nonce, req_id, body):

        raise HTTPException(status_code=401, detail={"code": "seoauto_bad_signature", "message": "Bad signature"})



    return conn





def _log_event(

    db: Session,

    *,

    event_type: str,

    connection_id: int | None,

    release_id: int | None = None,

    current_version: str | None = None,

    target_version: str | None = None,

    detail: dict[str, Any] | None = None,

) -> None:

    # Never store package URLs or secrets.

    safe = dict(detail or {})

    for k in ("package", "package_url", "token", "site_secret", "signature", "download_url"):

        safe.pop(k, None)

    db.add(

        WordpressPluginUpdateEvent(

            connection_id=connection_id,

            release_id=release_id,

            event_type=event_type,

            current_version=current_version,

            target_version=target_version,

            detail_json=json.dumps(safe, ensure_ascii=False) if safe else None,

        )

    )





def _is_prerelease_version(version: str) -> bool:

    """True when plugin version looks like an RC/beta/alpha build."""

    import re as _re



    return bool(_re.search(r"-(?:rc|beta|alpha)(?:\.|$)", (version or "").lower()))





def _pick_release(

    db: Session,

    *,

    channel: str,

    current_version: str,

    site_id: str,

) -> WordpressPluginRelease | None:

    from app.services.wordpress_plugin_release_service import site_eligible_for_release



    channel = channel if channel in ALLOWED_CHANNELS else "stable"

    rows = (

        db.query(WordpressPluginRelease)

        .filter(

            WordpressPluginRelease.slug == PLUGIN_SLUG,

            WordpressPluginRelease.channel == channel,

            WordpressPluginRelease.status == "published",

        )

        .all()

    )

    newer: list[WordpressPluginRelease] = []

    for row in rows:

        if not _newer_than(row.version, current_version):

            continue

        if row.min_from_version and _newer_than(row.min_from_version, current_version):

            if not row.security_patch:

                continue

        if not site_eligible_for_release(row, site_id):

            continue

        newer.append(row)

    if not newer:

        return None



    newer.sort(key=lambda r: _norm_ver(r.version), reverse=True)

    return newer[0]





def _mint_download_token(db: Session, release: WordpressPluginRelease, connection: WordpressConnection) -> tuple[str, datetime]:

    token = secrets.token_urlsafe(32)

    expires = _utc_now() + timedelta(seconds=max(60, DOWNLOAD_TTL_SECONDS))

    db.add(

        WordpressPluginDownloadToken(

            release_id=int(release.id),

            connection_id=int(connection.id),

            token_hash=_hash_token(token),

            expires_at=expires,

        )

    )

    return token, expires





def check_for_update(db: Session, request: Request, payload: dict[str, Any], raw_body: bytes) -> dict[str, Any]:

    conn = _require_plugin_hmac(db, request, raw_body)



    current = str(payload.get("current_version") or "0")

    channel = str(payload.get("channel") or "stable").strip().lower()

    if channel not in ALLOWED_CHANNELS:

        channel = "stable"



    site_id = str(conn.publishing_site_id or request.headers.get("X-SEOAuto-Site-ID") or "")



    # LOCKED / disconnected still allowed for security updates (entitlement independent).

    release = _pick_release(db, channel=channel, current_version=current, site_id=site_id)

    # Fall back to beta for any install when stable has nothing newer so all
    # paired sites can see the WordPress Plugins “nâng cấp ngay” banner.

    if release is None and channel == "stable":

        release = _pick_release(db, channel="beta", current_version=current, site_id=site_id)

        if release is not None:

            channel = "beta"

    if release is None:

        _log_event(

            db,

            event_type="check",

            connection_id=int(conn.id),

            current_version=current,

            detail={"update_available": False, "channel": channel},

        )

        db.commit()

        return {

            "update_available": False,

            "version": current,

            "channel": channel,

            "message": "up_to_date",

        }



    token, expires = _mint_download_token(db, release, conn)

    secret = decrypt_site_secret(conn.site_secret_encrypted or "")

    expires_iso = expires.astimezone(timezone.utc).isoformat()

    package_url = f"{PUBLIC_BASE}/api/wordpress-plugin/updates/download/{token}"

    signature = sign_release_payload(secret, release.version, release.package_sha256, expires_iso)



    _log_event(

        db,

        event_type="check",

        connection_id=int(conn.id),

        release_id=int(release.id),

        current_version=current,

        target_version=release.version,

        detail={

            "update_available": True,

            "channel": channel,

            "security_patch": bool(release.security_patch),

            "package_host": redact_url_for_log(package_url),

        },

    )

    db.commit()



    return {

        "update_available": True,

        "version": release.version,

        "package": package_url,

        "package_url": package_url,

        "requires": release.requires_wp,

        "requires_wp": release.requires_wp,

        "requires_php": release.requires_php,

        "tested": release.tested,

        "changelog_url": release.changelog_url or f"{PUBLIC_BASE}/docs/seo-helper-changelog",

        "sha256": release.package_sha256,

        "release_signature": signature,

        "channel": release.channel,

        "autoupdate": bool(release.autoupdate),

        "download_expires_at": expires_iso,

        "security_patch": bool(release.security_patch),

    }





def resolve_download(db: Session, token: str) -> tuple[Iterator[bytes] | Path, WordpressPluginRelease, str]:

    """

    Resolve one-time download.



    Returns (stream_or_path, release, mode) where mode is 'stream' | 'path'.

    Prefer streaming from StorageAdapter; fall back to local Path for legacy rows.

    """

    digest = _hash_token(token)

    row = (

        db.query(WordpressPluginDownloadToken)

        .filter(WordpressPluginDownloadToken.token_hash == digest)

        .first()

    )

    if row is None:

        raise HTTPException(status_code=404, detail={"code": "seoauto_token_invalid", "message": "Invalid token"})

    now = _utc_now()

    exp = row.expires_at

    if exp.tzinfo is None:

        exp = exp.replace(tzinfo=timezone.utc)

    if now > exp:

        raise HTTPException(status_code=410, detail={"code": "seoauto_token_expired", "message": "Download URL expired"})

    if row.used_at is not None:

        raise HTTPException(status_code=410, detail={"code": "seoauto_token_used", "message": "Download token already used"})



    release = db.get(WordpressPluginRelease, int(row.release_id))

    if release is None or release.status != "published":

        raise HTTPException(status_code=404, detail={"code": "seoauto_release_missing", "message": "Release not found"})



    key = (release.storage_key or "").strip() or (release.package_storage_path or "").strip()

    storage = get_storage_adapter()



    row.used_at = now

    _log_event(

        db,

        event_type="download",

        connection_id=int(row.connection_id) if row.connection_id else None,

        release_id=int(release.id),

        target_version=release.version,

        detail={"ok": True, "via": "storage" if looks_like_storage_key(key) else "legacy_path"},

    )

    db.commit()



    if key and looks_like_storage_key(key) and storage.exists(key):

        return storage.open_stream(key), release, "stream"



    # Legacy absolute filesystem path

    path = Path(key) if key else Path()

    if path.is_file():

        return path, release, "path"



    alt = RELEASE_STORAGE / PLUGIN_SLUG / f"{PLUGIN_SLUG}-{release.version}.zip"

    if alt.is_file():

        return alt, release, "path"



    raise HTTPException(status_code=404, detail={"code": "seoauto_package_missing", "message": "Package file missing"})





def materialize_download_temp(db: Session, token: str) -> tuple[Path, WordpressPluginRelease]:

    """Write package to a temp file (for FileResponse callers). Caller should unlink."""

    src, release, mode = resolve_download(db, token)

    if mode == "path":

        assert isinstance(src, Path)

        return src, release

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="seoauto-plugin-")

    try:

        for chunk in src:  # type: ignore[union-attr]

            tmp.write(chunk)

        tmp.flush()

    finally:

        tmp.close()

    return Path(tmp.name), release





def register_release(

    db: Session,

    *,

    version: str,

    channel: str = "stable",

    package_path: str,

    sha256: str,

    status: str = "draft",

    requires_wp: str = "6.0",

    requires_php: str = "8.1",

    tested: str = "6.7",

    changelog_url: str = "",

    changelog_md: str | None = None,

    autoupdate: bool = False,

    security_patch: bool = False,

) -> WordpressPluginRelease:

    """Legacy helper — prefer wordpress_plugin_release_service.create_release."""

    channel = channel if channel in ALLOWED_CHANNELS else "stable"

    if status not in {"draft", "published", "withdrawn"}:

        status = "draft"

    storage_key = package_path if looks_like_storage_key(package_path) else package_path

    row = WordpressPluginRelease(

        slug=PLUGIN_SLUG,

        version=version,

        channel=channel,

        status=status,

        storage_key=storage_key if looks_like_storage_key(storage_key) else "",

        package_storage_path=package_path,

        package_sha256=sha256.lower(),

        package_signature="",

        requires_wp=requires_wp,

        requires_php=requires_php,

        tested=tested,

        changelog_url=changelog_url,

        changelog_md=changelog_md,

        autoupdate=autoupdate,

        security_patch=security_patch,

        rollout_percent=100,

        published_at=_utc_now() if status == "published" else None,

        released_at=_utc_now() if status == "published" else None,

    )

    db.add(row)

    db.commit()

    db.refresh(row)

    return row


