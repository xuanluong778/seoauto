"""Production guards for Social Auto publish (mock mode, environment)."""

from __future__ import annotations

import os

from fastapi import HTTPException, status

from app.models.user import User
from app.services.rbac import is_admin


def is_production() -> bool:
    env = str(os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if env in {"production", "prod"}:
        return True
    base = str(os.getenv("APP_BASE_URL") or "").strip().lower()
    return "seoauto.vn" in base and "localhost" not in base and "127.0.0.1" not in base


def assert_publish_not_mock(user: User, *, is_mock: bool, platform: str = "") -> None:
    """Block non-admin users from publishing via mock credentials on production."""
    if not is_mock:
        return
    if is_admin(user):
        return
    if is_production():
        label = platform or "nền tảng"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Production không cho phép đăng bài mock ({label}). "
                "Cấu hình OAuth/API thật hoặc liên hệ quản trị viên."
            ),
        )
