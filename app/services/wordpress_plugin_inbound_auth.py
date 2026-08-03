"""Authenticate inbound HMAC requests from WordPress SEO Helper → SEOAuto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.wordpress_plugin import WordpressConnection
from app.services.wordpress_plugin_hmac import MAX_SKEW_SECONDS, normalize_path, verify
from app.services.wordpress_plugin_security import decrypt_site_secret


@dataclass(frozen=True)
class PluginHmacIdentity:
    connection: WordpressConnection
    site_id: str
    connection_id: int
    request_id: str


def _header(request: Request, name: str) -> str:
    return str(request.headers.get(name) or "").strip()


def authenticate_plugin_hmac(request: Request, db: Session, *, body: bytes | str = b"") -> PluginHmacIdentity:
    """Verify X-SEOAuto-* HMAC headers and return the paired connection."""
    site_id = _header(request, "X-SEOAuto-Site-ID")
    conn_raw = _header(request, "X-SEOAuto-Connection-ID")
    ts = _header(request, "X-SEOAuto-Timestamp")
    nonce = _header(request, "X-SEOAuto-Nonce")
    req_id = _header(request, "X-SEOAuto-Request-ID")
    signature = _header(request, "X-SEOAuto-Signature")

    if not all([site_id, conn_raw, ts, nonce, req_id, signature]):
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_missing_header", "message": "Thiếu header HMAC bắt buộc."},
        )

    try:
        connection_id = int(conn_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_invalid_connection", "message": "Connection ID không hợp lệ."},
        ) from exc

    try:
        ts_i = int(ts)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_invalid_timestamp", "message": "Timestamp không hợp lệ."},
        ) from exc

    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts_i) > MAX_SKEW_SECONDS:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_timestamp_skew", "message": "Timestamp ngoài cửa sổ cho phép."},
        )

    conn = db.get(WordpressConnection, connection_id)
    if conn is None or str(conn.status or "").lower() not in {"active", "pending"}:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_connection_not_found", "message": "Không tìm thấy kết nối."},
        )
    if str(conn.publishing_site_id or "") != site_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_site_mismatch", "message": "Site ID không khớp kết nối."},
        )

    secret = decrypt_site_secret(conn.site_secret_encrypted or "")
    if not secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_missing_secret", "message": "Thiếu site secret."},
        )

    path = normalize_path(request.url.path)
    method = (request.method or "GET").upper()
    if not verify(secret, signature, method, path, ts, nonce, req_id, body):
        raise HTTPException(
            status_code=401,
            detail={"code": "seoauto_bad_signature", "message": "Chữ ký HMAC không hợp lệ."},
        )

    return PluginHmacIdentity(
        connection=conn,
        site_id=site_id,
        connection_id=connection_id,
        request_id=req_id,
    )


def has_plugin_hmac_headers(request: Request) -> bool:
    return bool(_header(request, "X-SEOAuto-Signature") and _header(request, "X-SEOAuto-Site-ID"))
