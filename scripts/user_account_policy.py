"""Which user emails are real accounts vs test/junk (admin UI + cleanup)."""

from __future__ import annotations

import os

from app.services.admin_auth import admin_emails_from_env


def is_real_gmail(email: str) -> bool:
    e = (email or "").strip().lower()
    return e.endswith("@gmail.com") or e.endswith("@googlemail.com")


def retained_user_emails() -> frozenset[str]:
    keep = set(admin_emails_from_env())
    extra = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if extra:
        keep.add(extra)
    return frozenset(e for e in keep if e)


def is_retained_user_email(email: str) -> bool:
    """Gmail thật hoặc email admin trong env — ẩn/xóa phần còn lại (@example.com, test, …)."""
    e = (email or "").strip().lower()
    if not e:
        return False
    if e in retained_user_emails():
        return True
    return is_real_gmail(e)
