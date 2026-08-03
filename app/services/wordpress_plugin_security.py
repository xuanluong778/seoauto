"""Helpers for WordPress plugin pairing — domain normalize, secret encrypt, code hash.

Does not create billing. organization_id defaults to user_id for personal workspaces.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import string
from typing import Any
from urllib.parse import urlparse

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.core.security import SECRET_KEY

_WWW_RE = re.compile(r"^www\.", re.IGNORECASE)
_SA_ALPHABET = "".join(c for c in (string.ascii_uppercase + string.digits) if c not in "01OI")
_SA_CODE_RE = re.compile(r"^SA-[A-Z2-9]{4}-[A-Z2-9]{4}$")


def personal_organization_id(user_id: int) -> int:
    """Personal tenant until a real organizations table exists."""
    return int(user_id)


def assert_same_tenant(
    *,
    row_user_id: int,
    row_organization_id: int,
    user_id: int,
    organization_id: int,
) -> None:
    """Raise PermissionError if caller tenant does not own the row."""
    if int(row_organization_id) != int(organization_id):
        raise PermissionError("cross_organization_forbidden")
    if int(row_user_id) != int(user_id):
        raise PermissionError("cross_user_forbidden")


def normalize_domain(url_or_host: str) -> str:
    """Normalize site host for unique constraints: lowercase, strip scheme/path/www/port."""
    raw = str(url_or_host or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        host = str(url_or_host or "").strip().lower()
        host = host.split("/")[0].split("?")[0]
        if "@" in host:
            host = host.split("@", 1)[-1]
    host = _WWW_RE.sub("", host)
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]
    return host.rstrip(".")


def normalize_site_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw.rstrip("/")


def require_https_site_url(url: str, *, allow_localhost_http: bool = False) -> str:
    """Normalize and require HTTPS (optional localhost http for dev)."""
    site = normalize_site_url(url)
    parsed = urlparse(site)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https":
        return site
    if allow_localhost_http and scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return site
    raise ValueError("https_required")


def encrypt_site_secret(plain: str) -> str:
    return encrypt_secret(plain)


def decrypt_site_secret(stored: str) -> str:
    return decrypt_secret(stored)


def _pairing_pepper() -> bytes:
    env = (os.getenv("WORDPRESS_PAIRING_PEPPER") or "").strip()
    if env:
        return env.encode("utf-8")
    return f"wp-pairing:{SECRET_KEY}".encode("utf-8")


def normalize_pairing_code(plain_code: str) -> str:
    return str(plain_code or "").strip().upper().replace(" ", "")


def hash_pairing_code(plain_code: str) -> str:
    """HMAC-SHA256 of pairing code. Store only the hex digest."""
    code = normalize_pairing_code(plain_code)
    return hmac.new(_pairing_pepper(), code.encode("utf-8"), hashlib.sha256).hexdigest()


def pairing_code_prefix(plain_code: str, *, length: int = 8) -> str:
    code = normalize_pairing_code(plain_code)
    return code[: max(4, min(length, len(code)))]


def generate_pairing_code() -> str:
    """One-time display code: SA-XXXX-XXXX (no ambiguous chars)."""

    def _block() -> str:
        return "".join(secrets.choice(_SA_ALPHABET) for _ in range(4))

    return f"SA-{_block()}-{_block()}"


def is_valid_pairing_code_format(plain_code: str) -> bool:
    return bool(_SA_CODE_RE.match(normalize_pairing_code(plain_code)))


def verify_pairing_code(plain_code: str, stored_hash: str) -> bool:
    expected = hash_pairing_code(plain_code)
    return hmac.compare_digest(expected, str(stored_hash or ""))


def generate_site_secret(*, nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_site_id() -> str:
    return "wps_" + secrets.token_hex(16)


def _entitlement_signing_key() -> bytes:
    env = (os.getenv("WORDPRESS_ENTITLEMENT_SIGNING_KEY") or "").strip()
    if env:
        return env.encode("utf-8")
    return f"wp-entitlement:{SECRET_KEY}".encode("utf-8")


def sign_entitlement_payload(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(_entitlement_signing_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_entitlement_for_site(payload: dict[str, Any], site_secret: str) -> str:
    """Bind entitlement to paired site_secret (verified by WP plugin)."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(str(site_secret or "").encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def build_signed_entitlement(payload: dict[str, Any], *, site_secret: str | None = None) -> dict[str, Any]:
    data = dict(payload)
    data.pop("signature", None)
    sig = (
        sign_entitlement_for_site(data, site_secret)
        if site_secret
        else sign_entitlement_payload(data)
    )
    out = dict(data)
    out["signature"] = sig
    return out


def verify_signed_entitlement(payload: dict[str, Any], *, site_secret: str | None = None) -> bool:
    data = dict(payload)
    sig = str(data.pop("signature", "") or "")
    if not sig:
        return False
    if site_secret:
        expected = sign_entitlement_for_site(data, site_secret)
    else:
        expected = sign_entitlement_payload(data)
    return hmac.compare_digest(expected, sig)
