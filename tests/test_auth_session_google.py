"""Google OAuth leaves HttpOnly seo_token; SPA hydrates via GET /auth/session."""

from __future__ import annotations

from app.core.security import create_access_token, create_google_login_state, is_google_login_state


def test_google_login_state_roundtrip():
    st = create_google_login_state()
    assert is_google_login_state(st) is True
    assert is_google_login_state("not-a-jwt") is False


def test_access_token_has_user_id_claim():
    token = create_access_token(user_id=99)
    assert isinstance(token, str) and len(token) > 20
