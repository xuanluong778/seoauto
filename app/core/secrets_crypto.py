"""At-rest encryption for API keys, tokens, and passwords stored in JSON files."""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

_ENC_PREFIX = "enc:v1:"
_DEFAULT_DEV_SECRET = "change-this-in-production"


def _key_from_passphrase(secret: str, *, tagged: bool) -> bytes:
    raw = f"secrets:{secret}" if tagged else str(secret or "")
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _master_key_bytes() -> bytes:
    raw = (os.getenv("SECRETS_MASTER_KEY") or "").strip()
    if raw:
        try:
            return base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception:
            pass
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
    # Prefer live env so scripts that load dotenv before import work even when
    # `app.core.security.SECRET_KEY` was imported too early.
    secret = (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "").strip()
    if not secret:
        from app.core.security import SECRET_KEY as _FALLBACK

        secret = str(_FALLBACK or "").strip() or _DEFAULT_DEV_SECRET
    return _key_from_passphrase(secret, tagged=True)


def _candidate_key_bytes() -> list[bytes]:
    keys: list[bytes] = []
    seen: set[bytes] = set()

    def add(key: bytes) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    add(_master_key_bytes())
    jwt = (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "").strip()
    if jwt:
        add(_key_from_passphrase(jwt, tagged=True))
        add(_key_from_passphrase(jwt, tagged=False))
    previous = (
        os.getenv("JWT_SECRET_PREVIOUS")
        or os.getenv("SECRET_KEY_PREVIOUS")
        or os.getenv("SECRETS_PREVIOUS_KEY")
        or ""
    ).strip()
    if previous:
        add(_key_from_passphrase(previous, tagged=True))
        add(_key_from_passphrase(previous, tagged=False))
    add(_key_from_passphrase(_DEFAULT_DEV_SECRET, tagged=True))
    add(_key_from_passphrase(_DEFAULT_DEV_SECRET, tagged=False))
    return keys


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(_master_key_bytes())


@lru_cache(maxsize=1)
def _fernets() -> tuple[Fernet, ...]:
    return tuple(Fernet(k) for k in _candidate_key_bytes())


def encrypt_secret(plain: str) -> str:
    """Encrypt a secret for persistence. Empty strings stay empty."""
    s = str(plain or "")
    if not s:
        return ""
    if s.startswith(_ENC_PREFIX):
        return s
    token = _fernet().encrypt(s.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{token}"


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored secret. Legacy plaintext values pass through unchanged.

    Tries current key then legacy JWT / default-key variants. Never logs plaintext.
    """
    s = str(stored or "")
    if not s:
        return ""
    if not s.startswith(_ENC_PREFIX):
        return s
    blob = s[len(_ENC_PREFIX) :]
    raw = blob.encode("ascii")
    for fr in _fernets():
        try:
            return fr.decrypt(raw).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            continue
    return ""
