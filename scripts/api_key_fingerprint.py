from __future__ import annotations

import hashlib


def api_key_fingerprint(plain_key: str) -> str:
    normalized = str(plain_key or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
