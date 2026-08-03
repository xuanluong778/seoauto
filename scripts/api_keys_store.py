from __future__ import annotations

from typing import Any

from app.db import SessionLocal

PROVIDERS = {
    "google_gemini": "Google Gemini",
    "vertex_ai": "Vertex AI",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "custom_openai": "Custom OpenAI",
    "custom_anthropic": "Custom Anthropic",
    "fal_ai": "fal.ai (image only)",
}

MAX_KEYS = 200

_legacy_import_done = False


def _ensure_legacy_import(db) -> None:
    global _legacy_import_done
    if _legacy_import_done:
        return
    from app.models.user_api_key import UserApiKey
    from app.services.user_api_keys_db import import_legacy_json_keys

    if db.query(UserApiKey).count() == 0:
        import_legacy_json_keys(db)
    _legacy_import_done = True


def _with_db(fn):
    db = SessionLocal()
    try:
        _ensure_legacy_import(db)
        return fn(db)
    finally:
        db.close()


def list_enabled_keys_for_user(user_id: int) -> list[dict[str, Any]]:
    from app.services.user_api_keys_db import list_enabled_keys_db

    return _with_db(lambda db: list_enabled_keys_db(db, user_id))


def list_keys(*, user_id: int) -> list[dict[str, Any]]:
    from app.services.user_api_keys_db import list_keys_db

    return _with_db(lambda db: list_keys_db(db, user_id=user_id))


def get_stats(*, user_id: int) -> dict[str, int]:
    from app.services.user_api_keys_db import get_stats_db

    return _with_db(lambda db: get_stats_db(db, user_id=user_id))


def create_key(payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    from app.services.user_api_keys_db import create_key_db

    return _with_db(lambda db: create_key_db(db, payload, user_id=user_id))


def update_key(key_id: str, patch: dict[str, Any], *, user_id: int) -> dict[str, Any] | None:
    from app.services.user_api_keys_db import update_key_db

    return _with_db(lambda db: update_key_db(db, key_id, patch, user_id=user_id))


def delete_key(key_id: str, *, user_id: int) -> bool:
    from app.services.user_api_keys_db import delete_key_db

    return _with_db(lambda db: delete_key_db(db, key_id, user_id=user_id))


def get_key(key_id: str, *, user_id: int, reveal_key: bool = False) -> dict[str, Any] | None:
    from app.services.user_api_keys_db import get_key_db

    return _with_db(lambda db: get_key_db(db, key_id, user_id=user_id, reveal_key=reveal_key))
