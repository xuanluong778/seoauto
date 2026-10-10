"""Public auth API responses — refresh token cookie-only."""

from __future__ import annotations

from app.core.security import create_access_token, create_service_access_token
from app.schemas.auth import TokenResponse
from app.services.session_auth_rollout import (
    legacy_user_jwt_blocked,
    server_sessions_enabled,
    service_tokens_enabled,
)


def public_token_json(token: TokenResponse) -> dict:
    """Browser-facing JSON: access_token only; refresh stays HttpOnly cookie."""
    from app.services.session_auth_rollout import refresh_token_http_only_only

    data = token.model_dump(exclude_none=True)
    if refresh_token_http_only_only():
        data.pop("refresh_token", None)
    return data


def create_auth_token_for_user(user_id: int) -> str:
    """Load tests / scripts: service token when legacy user JWT is blocked."""
    if server_sessions_enabled() and legacy_user_jwt_blocked() and service_tokens_enabled():
        return create_service_access_token(int(user_id))
    return create_access_token(int(user_id))
