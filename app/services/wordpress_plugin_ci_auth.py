"""CI/CD release token auth — separate from WordPress site_secret HMAC."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, status


def _expected_ci_token() -> str:
    return str(
        os.getenv("WP_PLUGIN_CI_RELEASE_TOKEN")
        or os.getenv("SEOAUTO_PLUGIN_CI_TOKEN")
        or ""
    ).strip()


def require_ci_release_token(request: Request) -> str:
    """
    Authenticate internal release APIs.

    Headers (first match wins):
      Authorization: Bearer <token>
      X-SEOAuto-CI-Token: <token>
      X-Internal-Token: <token>  (only if equals WP_PLUGIN_CI_RELEASE_TOKEN)
    """
    expected = _expected_ci_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ci_token_not_configured", "message": "WP_PLUGIN_CI_RELEASE_TOKEN not set"},
        )

    auth = (request.headers.get("Authorization") or "").strip()
    bearer = ""
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()

    candidates = [
        bearer,
        (request.headers.get("X-SEOAuto-CI-Token") or "").strip(),
        (request.headers.get("X-Internal-Token") or "").strip(),
    ]
    for got in candidates:
        if got and secrets.compare_digest(got, expected):
            return "ci"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "ci_unauthorized", "message": "Invalid CI release token"},
    )
