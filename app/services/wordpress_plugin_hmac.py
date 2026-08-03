"""Sign outbound HMAC requests from SEOAuto → WordPress SEO Helper plugin."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlparse


MAX_SKEW_SECONDS = 300


def normalize_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if "?" in path:
        path = path.split("?", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def canonical(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    request_id: str,
    body: str | bytes,
) -> str:
    if isinstance(body, bytes):
        body_bytes = body
    else:
        body_bytes = (body or "").encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return "\n".join(
        [
            (method or "GET").upper().strip(),
            normalize_path(path),
            str(timestamp),
            str(nonce),
            str(request_id),
            body_hash,
        ]
    )


def sign(
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    request_id: str,
    body: str | bytes = "",
) -> str:
    payload = canonical(method, path, timestamp, nonce, request_id, body)
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(
    secret: str,
    signature: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    request_id: str,
    body: str | bytes = "",
) -> bool:
    expected = sign(secret, method, path, timestamp, nonce, request_id, body)
    return hmac.compare_digest(expected, str(signature or ""))


def build_headers(
    *,
    site_id: str,
    connection_id: int,
    secret: str,
    method: str,
    url_or_path: str,
    body: str | bytes = "",
    timestamp: int | None = None,
    nonce: str | None = None,
    request_id: str | None = None,
) -> dict[str, str]:
    parsed = urlparse(url_or_path)
    path = normalize_path(parsed.path if parsed.scheme else url_or_path)
    ts = str(int(timestamp if timestamp is not None else time.time()))
    nonce_v = nonce or secrets.token_hex(16)
    req_id = request_id or str(uuid.uuid4())
    signature = sign(secret, method, path, ts, nonce_v, req_id, body)
    return {
        "X-SEOAuto-Site-ID": site_id,
        "X-SEOAuto-Connection-ID": str(int(connection_id)),
        "X-SEOAuto-Timestamp": ts,
        "X-SEOAuto-Nonce": nonce_v,
        "X-SEOAuto-Request-ID": req_id,
        "X-SEOAuto-Signature": signature,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def headers_for_json(
    *,
    site_id: str,
    connection_id: int,
    secret: str,
    method: str,
    url: str,
    json_body: str,
) -> dict[str, Any]:
    return build_headers(
        site_id=site_id,
        connection_id=connection_id,
        secret=secret,
        method=method,
        url_or_path=url,
        body=json_body,
    )
