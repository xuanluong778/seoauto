"""WordPress SEO Helper pairing — create SA-XXXX codes and redeem from plugin."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import update as sql_update

from app.models.user import User
from app.models.wordpress_plugin import (
    WordpressCommandLog,
    WordpressConnection,
    WordpressEntitlement,
    WordpressPairingCode,
    WordpressRequestIdempotency,
)
from app.services.plugin_entitlement_service import check_plugin_entitlement
from app.services.security_audit_log import log_audit_event
from app.services.wordpress_plugin_security import (
    build_signed_entitlement,
    encrypt_site_secret,
    generate_pairing_code,
    generate_site_id,
    generate_site_secret,
    hash_pairing_code,
    is_valid_pairing_code_format,
    normalize_domain,
    normalize_pairing_code,
    pairing_code_prefix,
    personal_organization_id,
    require_https_site_url,
    verify_pairing_code,
)

PAIRING_TTL_MINUTES = 10
PAIRING_CREATE_RATE_PER_MIN = int(os.getenv("WP_PAIRING_CREATE_RATE_PER_MIN", "5"))
PAIRING_REDEEM_RATE_PER_MIN = int(os.getenv("WP_PAIRING_REDEEM_RATE_PER_MIN", "20"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _allow_localhost_http() -> bool:
    return os.getenv("WP_PAIRING_ALLOW_LOCALHOST_HTTP", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _raise(code: str, message: str, *, http_status: int = 400, **extra: Any) -> None:
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update(extra)
    raise HTTPException(status_code=http_status, detail=detail)


def _rate_limit(*, scope: str, key: str, limit_per_min: int) -> None:
    from app.services.cost_control.runtime import check_user_rate_limit

    # Reuse user-scoped limiter; key may be user_id or hashed IP bucket id.
    try:
        bucket = int(key) if str(key).isdigit() else abs(hash(f"{scope}:{key}")) % (10**9)
    except Exception:
        bucket = abs(hash(f"{scope}:{key}")) % (10**9)
    check_user_rate_limit(scope=scope, user_id=bucket, limit_per_min=limit_per_min)


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd[:64]
    if request.client:
        return str(request.client.host or "unknown")[:64]
    return "unknown"


def _count_org_sites(db: Session, organization_id: int) -> int:
    return (
        db.query(WordpressConnection)
        .filter(
            WordpressConnection.organization_id == int(organization_id),
            WordpressConnection.status.in_(("active", "pending")),
        )
        .count()
    )


def resolve_organization_id(user: User, organization_id: int | None) -> int:
    personal = personal_organization_id(user.id)
    if organization_id is None:
        return personal
    oid = int(organization_id)
    # Until real org membership exists, only personal org is allowed.
    if oid != personal:
        _raise(
            "organization_forbidden",
            "Không được dùng organization của tài khoản khác.",
            http_status=403,
        )
    return oid


def create_pairing_code(
    db: Session,
    user: User,
    *,
    organization_id: int | None = None,
    domain_hint: str | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Authenticated: mint SA-XXXX-XXXX (plaintext once). Stores hash only."""
    _rate_limit(
        scope="wp_pairing_create",
        key=str(user.id),
        limit_per_min=PAIRING_CREATE_RATE_PER_MIN,
    )
    org_id = resolve_organization_id(user, organization_id)

    # Pre-check plan / site capacity (count current sites; pairing itself adds +1 later)
    site_count = _count_org_sites(db, org_id)
    ent = check_plugin_entitlement(db, user, current_site_count=site_count)
    if not ent.allowed and ent.reason not in {"site_limit_exceeded"}:
        # site_limit at create time: still allow code creation only if under cap;
        # if already over, block minting new codes.
        log_audit_event(
            action="wp_pairing.create_denied",
            user_id=user.id,
            resource_type="wordpress_pairing_code",
            detail={"reason": ent.reason, "organization_id": org_id},
            request=request,
        )
        _raise(
            ent.reason or "entitlement_denied",
            "Gói hiện tại không cho phép kết nối plugin WordPress.",
            http_status=403,
            plan_code=ent.plan_code,
            max_sites=ent.max_sites,
        )
    if ent.reason == "site_limit_exceeded" or (
        ent.max_sites >= 0 and site_count >= ent.max_sites and not (
            # admin unlimited
            ent.max_sites < 0
        )
    ):
        # At capacity — cannot mint codes that would add another site
        if ent.max_sites >= 0 and site_count >= max(0, ent.max_sites):
            log_audit_event(
                action="wp_pairing.create_denied",
                user_id=user.id,
                resource_type="wordpress_pairing_code",
                detail={"reason": "site_limit_exceeded", "organization_id": org_id, "sites": site_count},
                request=request,
            )
            _raise(
                "site_limit_exceeded",
                f"Đã đạt giới hạn website ({ent.max_sites}). Nâng cấp gói để kết nối thêm.",
                http_status=403,
                max_sites=ent.max_sites,
                current_sites=site_count,
            )

    plain = generate_pairing_code()
    # Extremely unlikely collision — retry a few times
    for _ in range(5):
        digest = hash_pairing_code(plain)
        exists = db.query(WordpressPairingCode).filter_by(code_hash=digest).first()
        if exists is None:
            break
        plain = generate_pairing_code()
    else:
        _raise("code_generation_failed", "Không tạo được mã ghép nối. Thử lại.", http_status=500)

    now = _utc_now()
    domain_norm = normalize_domain(domain_hint) if domain_hint else None
    row = WordpressPairingCode(
        user_id=int(user.id),
        organization_id=int(org_id),
        code_hash=hash_pairing_code(plain),
        code_prefix=pairing_code_prefix(plain),
        domain_normalized=domain_norm or None,
        expires_at=now + timedelta(minutes=PAIRING_TTL_MINUTES),
        status="pending",
    )
    db.add(row)
    db.flush()

    log_audit_event(
        action="wp_pairing.created",
        user_id=user.id,
        resource_type="wordpress_pairing_code",
        resource_id=str(row.id),
        detail={
            "organization_id": org_id,
            "code_prefix": row.code_prefix,
            "expires_at": row.expires_at.isoformat(),
        },
        request=request,
    )
    db.commit()
    db.refresh(row)
    return {
        "code": plain,
        "code_prefix": row.code_prefix,
        "expires_at": row.expires_at.isoformat(),
        "expires_in_seconds": PAIRING_TTL_MINUTES * 60,
        "organization_id": org_id,
        "pairing_code_id": row.id,
    }


def _lookup_pending_code(db: Session, plain_code: str) -> WordpressPairingCode | None:
    digest = hash_pairing_code(plain_code)
    return db.query(WordpressPairingCode).filter(WordpressPairingCode.code_hash == digest).first()


def _idempotency_get(
    db: Session, organization_id: int, key: str
) -> WordpressRequestIdempotency | None:
    return (
        db.query(WordpressRequestIdempotency)
        .filter(
            WordpressRequestIdempotency.organization_id == int(organization_id),
            WordpressRequestIdempotency.idempotency_key == key,
        )
        .first()
    )


def redeem_pairing_code(
    db: Session,
    *,
    code: str,
    domain: str,
    site_url: str | None = None,
    wp_version: str | None = None,
    php_version: str | None = None,
    seo_plugin: str | None = None,
    plugin_version: str | None = None,
    organization_id: int | None = None,
    idempotency_key: str | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Public plugin endpoint: exchange one-time code for connection + site_secret (once)."""
    ip = _client_ip(request)
    _rate_limit(scope="wp_pairing_redeem", key=ip, limit_per_min=PAIRING_REDEEM_RATE_PER_MIN)

    plain = normalize_pairing_code(code)
    if not is_valid_pairing_code_format(plain):
        log_audit_event(
            action="wp_pairing.redeem_denied",
            resource_type="wordpress_pairing_code",
            detail={"reason": "invalid_code_format", "ip": ip},
            request=request,
        )
        _raise("invalid_code", "Mã ghép nối không hợp lệ.", http_status=400)

    raw_url = site_url or domain
    try:
        site = require_https_site_url(raw_url, allow_localhost_http=_allow_localhost_http())
    except ValueError:
        log_audit_event(
            action="wp_pairing.redeem_denied",
            resource_type="wordpress_pairing_code",
            detail={"reason": "https_required", "domain": domain, "ip": ip},
            request=request,
        )
        _raise("https_required", "Website phải dùng HTTPS.", http_status=400)

    domain_norm = normalize_domain(domain or site)
    if not domain_norm or "." not in domain_norm and domain_norm not in {"localhost"}:
        if domain_norm != "localhost":
            _raise("invalid_domain", "Domain không hợp lệ.", http_status=400)

    row = _lookup_pending_code(db, plain)
    if row is None or not verify_pairing_code(plain, row.code_hash):
        log_audit_event(
            action="wp_pairing.redeem_denied",
            resource_type="wordpress_pairing_code",
            detail={"reason": "invalid_code", "domain": domain_norm, "ip": ip},
            request=request,
        )
        _raise("invalid_code", "Mã ghép nối sai hoặc không tồn tại.", http_status=400)

    now = _utc_now()
    expires = _aware(row.expires_at)
    status_l = str(row.status or "").lower()

    if status_l == "consumed" or row.consumed_at is not None:
        log_audit_event(
            action="wp_pairing.redeem_denied",
            user_id=row.user_id,
            resource_type="wordpress_pairing_code",
            resource_id=str(row.id),
            detail={"reason": "code_already_used", "domain": domain_norm, "ip": ip},
            request=request,
        )
        _raise("code_already_used", "Mã đã được sử dụng.", http_status=409)

    if status_l not in {"pending"} or (expires is not None and expires <= now):
        if status_l == "pending" and expires is not None and expires <= now:
            row.status = "expired"
            db.flush()
        log_audit_event(
            action="wp_pairing.redeem_denied",
            user_id=row.user_id,
            resource_type="wordpress_pairing_code",
            resource_id=str(row.id),
            detail={"reason": "code_expired", "domain": domain_norm, "ip": ip},
            request=request,
        )
        _raise("code_expired", "Mã đã hết hạn. Tạo mã mới trên SEOAuto.", http_status=410)

    # Organization mismatch if plugin claims a different org than the code owner
    if organization_id is not None and int(organization_id) != int(row.organization_id):
        log_audit_event(
            action="wp_pairing.redeem_denied",
            user_id=row.user_id,
            resource_type="wordpress_pairing_code",
            resource_id=str(row.id),
            detail={
                "reason": "organization_mismatch",
                "code_org": row.organization_id,
                "claimed_org": organization_id,
                "domain": domain_norm,
                "ip": ip,
            },
            request=request,
        )
        _raise(
            "organization_mismatch",
            "Mã không thuộc organization này.",
            http_status=403,
        )

    # Domain already owned by another organization
    existing = (
        db.query(WordpressConnection)
        .filter(WordpressConnection.domain_normalized == domain_norm)
        .all()
    )
    for conn in existing:
        if int(conn.organization_id) != int(row.organization_id):
            log_audit_event(
                action="wp_pairing.redeem_denied",
                user_id=row.user_id,
                resource_type="wordpress_connection",
                resource_id=str(conn.id),
                detail={
                    "reason": "organization_mismatch",
                    "domain": domain_norm,
                    "owner_org": conn.organization_id,
                    "code_org": row.organization_id,
                    "ip": ip,
                },
                request=request,
            )
            _raise(
                "organization_mismatch",
                "Domain đã được kết nối bởi organization khác.",
                http_status=403,
            )

    user = db.query(User).filter(User.id == int(row.user_id)).one_or_none()
    if user is None:
        _raise("user_not_found", "Tài khoản SEOAuto không tồn tại.", http_status=404)

    # Site limit: count other sites; same-domain re-pair within org does not add
    same_org_existing = next(
        (c for c in existing if int(c.organization_id) == int(row.organization_id)),
        None,
    )
    site_count = _count_org_sites(db, row.organization_id)
    # Deny when post-pair total would exceed max (service uses count > max_sites).
    check_count = site_count + (0 if same_org_existing else 1)
    ent = check_plugin_entitlement(db, user, current_site_count=check_count, now=now)
    if not ent.allowed:
        log_audit_event(
            action="wp_pairing.redeem_denied",
            user_id=user.id,
            resource_type="wordpress_pairing_code",
            resource_id=str(row.id),
            detail={
                "reason": ent.reason,
                "domain": domain_norm,
                "max_sites": ent.max_sites,
                "sites": site_count,
                "ip": ip,
            },
            request=request,
        )
        http = 403
        _raise(
            ent.reason or "entitlement_denied",
            "Không đủ quyền kết nối plugin (gói / giới hạn website).",
            http_status=http,
            plan_code=ent.plan_code,
            max_sites=ent.max_sites,
            current_sites=site_count,
        )

    idem_key = (idempotency_key or "").strip()[:128]
    if idem_key:
        prior = _idempotency_get(db, row.organization_id, idem_key)
        if prior is not None and prior.response_body_json:
            import json

            try:
                cached = json.loads(prior.response_body_json)
                if isinstance(cached, dict) and cached.get("connection_id"):
                    # Do not re-expose site_secret
                    cached = dict(cached)
                    cached.pop("site_secret", None)
                    cached["idempotent_replay"] = True
                    return cached
            except (TypeError, ValueError):
                pass

    # Atomically consume code (prevents concurrent double-redeem).
    consumed = db.execute(
        sql_update(WordpressPairingCode)
        .where(
            WordpressPairingCode.id == int(row.id),
            WordpressPairingCode.status == "pending",
            WordpressPairingCode.consumed_at.is_(None),
        )
        .values(status="consumed", consumed_at=now)
    )
    db.flush()
    if int(getattr(consumed, "rowcount", 0) or 0) != 1:
        _raise("code_already_used", "Mã đã được sử dụng.", http_status=409)

    site_secret_plain = generate_site_secret()
    # Preserve publishing_site_id on re-pair so canary allowlists survive reconnect.
    if same_org_existing is not None:
        conn = same_org_existing
        site_id = str(conn.publishing_site_id or "").strip() or generate_site_id()
        conn.site_url = site
        conn.site_secret_encrypted = encrypt_site_secret(site_secret_plain)
        conn.publishing_site_id = site_id
        conn.plugin_version = (plugin_version or conn.plugin_version or "")[:32] or None
        conn.status = "active"
        conn.last_seen_at = now
    else:
        site_id = generate_site_id()
        conn = WordpressConnection(
            user_id=int(user.id),
            organization_id=int(row.organization_id),
            publishing_site_id=site_id,
            site_url=site,
            domain_normalized=domain_norm,
            site_secret_encrypted=encrypt_site_secret(site_secret_plain),
            plugin_version=(plugin_version or "")[:32] or None,
            status="active",
            last_seen_at=now,
        )
        db.add(conn)
        db.flush()

    row.connection_id = conn.id
    if row.domain_normalized is None:
        row.domain_normalized = domain_norm
    db.flush()

    # Persist entitlement snapshot (no credit burn)
    import json

    features_json = json.dumps(ent.enabled_features, ensure_ascii=False)
    snap = (
        db.query(WordpressEntitlement)
        .filter(
            WordpressEntitlement.organization_id == int(row.organization_id),
            WordpressEntitlement.connection_id == int(conn.id),
        )
        .one_or_none()
    )
    if snap is None:
        snap = WordpressEntitlement(
            user_id=int(user.id),
            organization_id=int(row.organization_id),
            connection_id=int(conn.id),
        )
        db.add(snap)
    snap.allowed = bool(ent.allowed)
    snap.reason = str(ent.reason or "")
    snap.plan_code = ent.plan_code
    snap.subscription_status = ent.subscription_status
    snap.expires_at = ent.expires_at
    snap.grace_until = ent.grace_until
    snap.max_sites = int(ent.max_sites)
    snap.enabled_features_json = features_json
    snap.snapshot_at = now
    db.flush()

    entitlement_payload = {
        "allowed": ent.allowed,
        "reason": ent.reason,
        "plan_code": ent.plan_code,
        "subscription_status": ent.subscription_status,
        "expires_at": ent.expires_at.isoformat() if ent.expires_at else None,
        "grace_until": ent.grace_until.isoformat() if ent.grace_until else None,
        "max_sites": ent.max_sites,
        "enabled_features": list(ent.enabled_features),
        "connection_id": conn.id,
        "site_id": site_id,
        "organization_id": row.organization_id,
        "issued_at": now.isoformat(),
    }
    signed = build_signed_entitlement(entitlement_payload, site_secret=site_secret_plain)

    db.add(
        WordpressCommandLog(
            user_id=int(user.id),
            organization_id=int(row.organization_id),
            connection_id=int(conn.id),
            command_type="pairing_redeemed",
            direction="wp_to_saas",
            payload_json=json.dumps(
                {
                    "domain": domain_norm,
                    "wp_version": wp_version,
                    "php_version": php_version,
                    "seo_plugin": seo_plugin,
                    "plugin_version": plugin_version,
                },
                ensure_ascii=False,
            ),
            status="done",
            request_id=idem_key or str(uuid.uuid4()),
            completed_at=now,
        )
    )

    response = {
        "connection_id": conn.id,
        "site_id": site_id,
        "site_secret": site_secret_plain,
        "organization_id": row.organization_id,
        "domain": domain_norm,
        "site_url": site,
        "entitlement": signed,
    }

    if idem_key:
        # Store without site_secret for safe replay
        safe = dict(response)
        safe.pop("site_secret", None)
        prior = _idempotency_get(db, row.organization_id, idem_key)
        if prior is None:
            db.add(
                WordpressRequestIdempotency(
                    user_id=int(user.id),
                    organization_id=int(row.organization_id),
                    connection_id=int(conn.id),
                    idempotency_key=idem_key,
                    request_path="/api/wordpress-plugin/pair",
                    response_code=200,
                    response_body_json=json.dumps(safe, ensure_ascii=False),
                )
            )

    log_audit_event(
        action="wp_pairing.redeemed",
        user_id=user.id,
        resource_type="wordpress_connection",
        resource_id=str(conn.id),
        detail={
            "organization_id": row.organization_id,
            "domain": domain_norm,
            "site_id": site_id,
            "wp_version": wp_version,
            "php_version": php_version,
            "seo_plugin": seo_plugin,
            "ip": ip,
        },
        request=request,
    )
    db.commit()
    return response
