"""WordPress SEO Helper — list/check/disconnect connections for Settings UI."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wordpress_plugin import (
    WordpressCommandLog,
    WordpressConnection,
    WordpressEntitlement,
    WordpressPairingCode,
)
from app.services.plugin_entitlement_service import check_plugin_entitlement
from app.services.wordpress_pairing_service import _count_org_sites, resolve_organization_id
from app.services.wordpress_plugin_client import plugin_get_json
from app.services.wordpress_plugin_security import (
    build_signed_entitlement,
    decrypt_site_secret,
    personal_organization_id,
)

_ACTIVE_STATUSES = ("active", "pending")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime | None) -> str | None:
    val = _aware(dt)
    return val.isoformat() if val else None


def _raise(code: str, message: str, *, http_status: int = 400, **extra: Any) -> None:
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update(extra)
    raise HTTPException(status_code=http_status, detail=detail)


def _org_id(user: User) -> int:
    return personal_organization_id(int(user.id))


def _entitlement_snapshot(ent: WordpressEntitlement | None) -> dict[str, Any] | None:
    if ent is None:
        return None
    features: list[str] = []
    try:
        raw = json.loads(ent.enabled_features_json or "[]")
        if isinstance(raw, list):
            features = [str(x) for x in raw]
    except (TypeError, ValueError):
        features = []
    return {
        "allowed": bool(ent.allowed),
        "reason": str(ent.reason or ""),
        "plan_code": ent.plan_code,
        "subscription_status": ent.subscription_status,
        "expires_at": _iso(ent.expires_at),
        "grace_until": _iso(ent.grace_until),
        "max_sites": int(ent.max_sites or 0),
        "enabled_features": features,
        "snapshot_at": _iso(ent.snapshot_at),
    }


def _pairing_meta(db: Session, connection_id: int) -> dict[str, str | None]:
    row = (
        db.query(WordpressCommandLog)
        .filter(
            WordpressCommandLog.connection_id == int(connection_id),
            WordpressCommandLog.command_type == "pairing_redeemed",
        )
        .order_by(WordpressCommandLog.created_at.desc())
        .first()
    )
    if row is None or not row.payload_json:
        return {"wp_version": None, "seo_plugin": None, "php_version": None}
    try:
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict):
            return {"wp_version": None, "seo_plugin": None, "php_version": None}
        return {
            "wp_version": (payload.get("wp_version") or None),
            "seo_plugin": (payload.get("seo_plugin") or None),
            "php_version": (payload.get("php_version") or None),
        }
    except (TypeError, ValueError):
        return {"wp_version": None, "seo_plugin": None, "php_version": None}


def _connection_to_dict(
    conn: WordpressConnection,
    *,
    meta: dict[str, str | None] | None = None,
    entitlement: WordpressEntitlement | None = None,
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    live = live or {}
    return {
        "id": int(conn.id),
        "domain": conn.domain_normalized,
        "site_url": conn.site_url,
        "status": str(conn.status or ""),
        "plugin_version": live.get("plugin_version") or conn.plugin_version,
        "wp_version": live.get("wp_version") or meta.get("wp_version"),
        "seo_plugin": live.get("seo_plugin") or meta.get("seo_plugin"),
        "php_version": meta.get("php_version"),
        "last_seen_at": _iso(conn.last_seen_at),
        "connected_at": _iso(conn.created_at),
        "publishing_site_id": conn.publishing_site_id,
        "entitlement": _entitlement_snapshot(entitlement),
        "reachable": live.get("reachable"),
        "check_message": live.get("check_message"),
    }


def _entitlement_ui(db: Session, user: User) -> dict[str, Any]:
    site_count = _count_org_sites(db, _org_id(user))
    ent = check_plugin_entitlement(db, user, current_site_count=site_count)
    data = ent.to_dict()
    can_connect = bool(ent.allowed)
    message = None
    if not ent.allowed:
        if ent.reason in {"no_subscription", "subscription_inactive", "expired", "canceled"}:
            message = "Gói hiện tại chưa hỗ trợ SEOAuto SEO Helper."
        elif ent.reason == "site_limit_exceeded":
            message = f"Đã đạt giới hạn {ent.max_sites} website. Nâng cấp gói để kết nối thêm."
        else:
            message = "Gói hiện tại chưa hỗ trợ SEOAuto SEO Helper."
    data["current_sites"] = site_count
    data["can_connect"] = can_connect and (
        ent.max_sites < 0 or site_count < max(0, int(ent.max_sites))
    )
    data["message"] = message
    return data


def list_connections_for_user(db: Session, user: User) -> dict[str, Any]:
    org_id = _org_id(user)
    rows = (
        db.query(WordpressConnection)
        .filter(
            WordpressConnection.organization_id == org_id,
            WordpressConnection.user_id == int(user.id),
            WordpressConnection.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(WordpressConnection.created_at.desc())
        .all()
    )
    ent_map: dict[int, WordpressEntitlement] = {}
    if rows:
        ent_rows = (
            db.query(WordpressEntitlement)
            .filter(
                WordpressEntitlement.organization_id == org_id,
                WordpressEntitlement.connection_id.in_([int(r.id) for r in rows]),
            )
            .all()
        )
        ent_map = {int(e.connection_id): e for e in ent_rows}

    connections = [
        _connection_to_dict(
            conn,
            meta=_pairing_meta(db, int(conn.id)),
            entitlement=ent_map.get(int(conn.id)),
        )
        for conn in rows
    ]
    return {
        "ok": True,
        "organization_id": org_id,
        "entitlement": _entitlement_ui(db, user),
        "connections": connections,
    }


def get_pairing_code_status(
    db: Session,
    user: User,
    pairing_code_id: int,
) -> dict[str, Any]:
    org_id = _org_id(user)
    row = (
        db.query(WordpressPairingCode)
        .filter(
            WordpressPairingCode.id == int(pairing_code_id),
            WordpressPairingCode.organization_id == org_id,
            WordpressPairingCode.user_id == int(user.id),
        )
        .first()
    )
    if row is None:
        _raise("pairing_not_found", "Không tìm thấy mã ghép nối.", http_status=404)

    now = _utc_now()
    expires = _aware(row.expires_at)
    status = str(row.status or "pending").lower()
    if status == "pending" and expires is not None and expires <= now:
        status = "expired"

    expires_in = 0
    if expires is not None and expires > now:
        expires_in = max(0, int((expires - now).total_seconds()))

    connection = None
    if row.connection_id:
        conn = db.get(WordpressConnection, int(row.connection_id))
        if conn is not None and int(conn.organization_id) == org_id:
            ent = (
                db.query(WordpressEntitlement)
                .filter(
                    WordpressEntitlement.organization_id == org_id,
                    WordpressEntitlement.connection_id == int(conn.id),
                )
                .first()
            )
            connection = _connection_to_dict(
                conn,
                meta=_pairing_meta(db, int(conn.id)),
                entitlement=ent,
            )

    return {
        "ok": True,
        "pairing_code_id": int(row.id),
        "status": status,
        "code_prefix": row.code_prefix,
        "expires_at": _iso(row.expires_at),
        "expires_in_seconds": expires_in,
        "connection_id": int(row.connection_id) if row.connection_id else None,
        "connection": connection,
    }


def disconnect_connection(db: Session, user: User, connection_id: int) -> dict[str, Any]:
    org_id = _org_id(user)
    conn = db.execute(
        select(WordpressConnection).where(
            WordpressConnection.id == int(connection_id),
            WordpressConnection.organization_id == org_id,
            WordpressConnection.user_id == int(user.id),
        ).limit(1)
    ).scalar_one_or_none()
    if conn is None:
        _raise("connection_not_found", "Không tìm thấy kết nối.", http_status=404)

    conn.status = "disconnected"
    conn.updated_at = _utc_now()
    db.commit()
    return {
        "ok": True,
        "disconnected": True,
        "connection_id": int(conn.id),
        "summary": list_connections_for_user(db, user),
    }


def check_connection(db: Session, user: User, connection_id: int) -> dict[str, Any]:
    org_id = _org_id(user)
    conn = db.execute(
        select(WordpressConnection).where(
            WordpressConnection.id == int(connection_id),
            WordpressConnection.organization_id == org_id,
            WordpressConnection.user_id == int(user.id),
            WordpressConnection.status.in_(_ACTIVE_STATUSES),
        ).limit(1)
    ).scalar_one_or_none()
    if conn is None:
        _raise("connection_not_found", "Không tìm thấy kết nối.", http_status=404)

    meta = _pairing_meta(db, int(conn.id))
    ent = (
        db.query(WordpressEntitlement)
        .filter(
            WordpressEntitlement.organization_id == org_id,
            WordpressEntitlement.connection_id == int(conn.id),
        )
        .first()
    )

    live: dict[str, Any] = {"reachable": False, "check_message": ""}
    secret = decrypt_site_secret(conn.site_secret_encrypted or "")
    site_id = str(conn.publishing_site_id or "")
    if secret and site_id:
        req_id = str(uuid.uuid4())
        result, err = plugin_get_json(
            site_url=conn.site_url,
            site_id=site_id,
            connection_id=int(conn.id),
            secret=secret,
            path="/wp-json/seoauto/v1/status",
            request_id=req_id,
            timeout=20,
        )
        secret = ""
        if err is None and isinstance(result, dict):
            live["reachable"] = True
            live["check_message"] = "Plugin phản hồi bình thường."
            live["plugin_version"] = result.get("plugin_version") or result.get("version")
            live["wp_version"] = result.get("wp_version") or result.get("wordpress_version")
            live["seo_plugin"] = result.get("seo_plugin")
            now = _utc_now()
            conn.last_seen_at = now
            if live.get("plugin_version"):
                conn.plugin_version = str(live["plugin_version"])[:32]
            conn.updated_at = now
            db.commit()
            db.refresh(conn)
        else:
            code = str(getattr(err, "error_code", "unreachable") if err else "unreachable")
            msg = str(getattr(err, "message", "") if err else "Không kết nối được plugin.")
            live["check_message"] = f"Không kết nối được plugin ({code}): {msg[:240]}"
    else:
        live["check_message"] = "Thiếu thông tin bí mật kết nối — hãy ghép nối lại plugin."

    return {
        "ok": bool(live.get("reachable")),
        "connection": _connection_to_dict(
            conn,
            meta=meta,
            entitlement=ent,
            live=live,
        ),
    }


def get_entitlement_for_user(db: Session, user: User) -> dict[str, Any]:
    resolve_organization_id(user, None)
    return {"ok": True, "entitlement": _entitlement_ui(db, user)}


def refresh_entitlement_for_connection(db: Session, conn: WordpressConnection) -> dict[str, Any]:
    """Recompute + sign entitlement for a paired plugin connection (HMAC caller).

    Updates wordpress_entitlements cache. Does not burn credits or change pairing secrets.
    """
    user = db.get(User, int(conn.user_id))
    if user is None:
        _raise("seoauto_user_missing", "Connection user missing", http_status=401)

    site_count = _count_org_sites(db, int(conn.organization_id))
    ent = check_plugin_entitlement(db, user, current_site_count=site_count)
    now = _utc_now()

    features_json = json.dumps(list(ent.enabled_features), ensure_ascii=False)
    snap = (
        db.query(WordpressEntitlement)
        .filter(
            WordpressEntitlement.organization_id == int(conn.organization_id),
            WordpressEntitlement.connection_id == int(conn.id),
        )
        .one_or_none()
    )
    if snap is None:
        snap = WordpressEntitlement(
            user_id=int(user.id),
            organization_id=int(conn.organization_id),
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

    site_secret_plain = decrypt_site_secret(conn.site_secret_encrypted or "")
    if not site_secret_plain:
        _raise("seoauto_bad_secret", "Invalid connection secret", http_status=401)

    entitlement_payload = {
        "allowed": ent.allowed,
        "reason": ent.reason,
        "plan_code": ent.plan_code,
        "subscription_status": ent.subscription_status,
        "expires_at": ent.expires_at.isoformat() if ent.expires_at else None,
        "grace_until": ent.grace_until.isoformat() if ent.grace_until else None,
        "max_sites": ent.max_sites,
        "enabled_features": list(ent.enabled_features),
        "connection_id": int(conn.id),
        "site_id": str(conn.publishing_site_id or ""),
        "organization_id": int(conn.organization_id),
        "issued_at": now.isoformat(),
    }
    signed = build_signed_entitlement(entitlement_payload, site_secret=site_secret_plain)
    db.commit()
    return {"ok": True, "entitlement": signed}
