"""Encrypted storage for platform integration API keys."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.models.platform_integration import PlatformIntegration
from app.services.api_key_fingerprint import api_key_fingerprint

PROVIDER_SINBYTE = "sinbyte"
PROVIDER_LABELS = {
    PROVIDER_SINBYTE: "Sinbyte",
}


def mask_api_key(value: str) -> str:
    """Mask key as abcd********xyz — never expose full key."""
    s = str(value or "")
    if not s:
        return ""
    if len(s) <= 7:
        return "*" * len(s)
    return s[:4] + ("*" * 8) + s[-3:]


def _env_sinbyte_key() -> str:
    return (os.getenv("SINBYTE_API_KEY") or "").strip()


def _row_or_none(db: Session, provider: str) -> PlatformIntegration | None:
    return db.get(PlatformIntegration, provider)


def get_decrypted_api_key(db: Session, provider: str) -> str | None:
    row = _row_or_none(db, provider)
    if row and row.api_key_encrypted:
        plain = decrypt_secret(row.api_key_encrypted).strip()
        if plain:
            return plain
    if provider == PROVIDER_SINBYTE:
        env_key = _env_sinbyte_key()
        return env_key or None
    return None


def get_integration_status(db: Session, provider: str) -> dict[str, Any]:
    row = _row_or_none(db, provider)
    env_key = _env_sinbyte_key() if provider == PROVIDER_SINBYTE else ""
    db_key = decrypt_secret(row.api_key_encrypted).strip() if row and row.api_key_encrypted else ""

    configured = bool(db_key or env_key)
    source = "database" if db_key else ("env" if env_key else "")
    active_key = db_key or env_key

    connected = bool(row and row.last_test_ok) if db_key else False

    return {
        "ok": True,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "configured": configured,
        "connected": connected,
        "source": source,
        "api_key_masked": mask_api_key(active_key) if active_key else "",
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "last_test_at": row.last_test_at.isoformat() if row and row.last_test_at else None,
        "last_test_ok": row.last_test_ok if row else None,
        "last_test_message": (row.last_test_message or "") if row else (
            "Đang dùng API key từ biến môi trường." if env_key and not db_key else ""
        ),
    }


def save_api_key(
    db: Session,
    *,
    provider: str,
    api_key: str,
    user_id: int,
) -> dict[str, Any]:
    plain = (api_key or "").strip()
    if not plain:
        raise ValueError("empty_api_key")

    now = datetime.now(timezone.utc)
    row = _row_or_none(db, provider)
    if row is None:
        row = PlatformIntegration(provider=provider)
        db.add(row)

    row.api_key_encrypted = encrypt_secret(plain)
    row.key_fingerprint = api_key_fingerprint(plain)
    row.updated_by_user_id = user_id
    row.updated_at = now
    row.last_test_ok = None
    row.last_test_message = ""
    row.last_test_at = None
    db.flush()

    return get_integration_status(db, provider)


def delete_api_key(db: Session, *, provider: str) -> dict[str, Any]:
    row = _row_or_none(db, provider)
    if row is not None:
        db.delete(row)
        db.flush()
    return get_integration_status(db, provider)


def record_test_result(
    db: Session,
    *,
    provider: str,
    ok: bool,
    message: str,
) -> None:
    row = _row_or_none(db, provider)
    if row is None:
        return
    row.last_test_at = datetime.now(timezone.utc)
    row.last_test_ok = ok
    row.last_test_message = (message or "")[:500]
    db.flush()
