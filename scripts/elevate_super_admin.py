#!/usr/bin/env python3
"""Elevate a user to super_admin (idempotent) with audit log and rollback.

Usage:
  python scripts/elevate_super_admin.py --email xuanluong778@gmail.com
  python scripts/elevate_super_admin.py --email xuanluong778@gmail.com --rollback
  python scripts/elevate_super_admin.py --email xuanluong778@gmail.com --dry-run

Does not hard-code emails in app modules — email is a CLI argument only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local", override=True)
# Also load .env if present (prod variants)
load_dotenv(ROOT / ".env", override=False)

from app.db import SessionLocal, engine
from app.models import knowledge as _knowledge_models  # noqa: F401
from app.models import seo as _seo_models  # noqa: F401
from app.models.security_audit_log import SecurityAuditLog
from app.models.user import User
from app.services.admin_auth import ensure_super_admin_user_fields, normalize_email
from app.services.rbac import is_admin, is_super_admin, normalize_role
from app.services.security_audit_log import log_audit_event


def _db_label() -> str:
    try:
        return engine.url.render_as_string(hide_password=True)
    except Exception:
        return str(engine.url)

ACTION_ELEVATE = "admin.user.elevate_super_admin"
ACTION_ROLLBACK = "admin.user.rollback_super_admin"


def _snapshot(user: User) -> dict:
    return {
        "id": int(user.id),
        "email": str(user.email or ""),
        "role": normalize_role(user.role),
        "status": str(user.status or ""),
        "api_access_enabled": bool(getattr(user, "api_access_enabled", False)),
        "use_admin_api_pool": bool(getattr(user, "use_admin_api_pool", False)),
        "allow_custom_api_key": bool(getattr(user, "allow_custom_api_key", False)),
    }


def _latest_elevate_detail(db, user_id: int) -> dict | None:
    row = (
        db.query(SecurityAuditLog)
        .filter(
            SecurityAuditLog.user_id == int(user_id),
            SecurityAuditLog.action == ACTION_ELEVATE,
        )
        .order_by(SecurityAuditLog.created_at.desc())
        .first()
    )
    if not row or not row.detail_json:
        return None
    try:
        data = json.loads(row.detail_json)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def elevate(db, *, email: str, dry_run: bool) -> int:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        print(f"ERROR: user not found: {email}")
        return 2

    before = _snapshot(user)
    print("before:", json.dumps(before, ensure_ascii=False))

    if is_super_admin(user):
        # Idempotent: still ensure fields, no role churn.
        ensure_super_admin_user_fields(user)
        if dry_run:
            db.rollback()
            print("dry-run: already super_admin (no write)")
            return 0
        db.commit()
        log_audit_event(
            action=ACTION_ELEVATE,
            user_id=int(user.id),
            resource_type="user",
            resource_id=str(user.id),
            detail={"idempotent": True, "before": before, "after": _snapshot(user)},
        )
        print("after:", json.dumps(_snapshot(user), ensure_ascii=False))
        print("OK: already super_admin (idempotent)")
        return 0

    ensure_super_admin_user_fields(user)
    after = _snapshot(user)
    if dry_run:
        db.rollback()
        print("dry-run after:", json.dumps(after, ensure_ascii=False))
        return 0

    db.commit()
    db.refresh(user)
    after = _snapshot(user)
    log_audit_event(
        action=ACTION_ELEVATE,
        user_id=int(user.id),
        resource_type="user",
        resource_id=str(user.id),
        detail={"idempotent": False, "before": before, "after": after},
    )
    print("after:", json.dumps(after, ensure_ascii=False))
    print("OK: elevated to super_admin")
    assert is_admin(user) and is_super_admin(user)
    return 0


def rollback(db, *, email: str, dry_run: bool) -> int:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        print(f"ERROR: user not found: {email}")
        return 2

    before = _snapshot(user)
    detail = _latest_elevate_detail(db, int(user.id))
    prev = (detail or {}).get("before") if detail else None
    if not isinstance(prev, dict) or not prev.get("role"):
        print("ERROR: no elevate audit snapshot found — cannot rollback safely.")
        print("Hint: restore role manually via admin UI or SQL.")
        return 3

    restore_role = normalize_role(prev.get("role"))
    if restore_role == "super_admin":
        restore_role = "admin"

    print("before:", json.dumps(before, ensure_ascii=False))
    print("restore_from_audit:", json.dumps(prev, ensure_ascii=False))

    user.role = restore_role
    user.status = str(prev.get("status") or "active")
    if "api_access_enabled" in prev:
        user.api_access_enabled = bool(prev["api_access_enabled"])
    if "use_admin_api_pool" in prev:
        user.use_admin_api_pool = bool(prev["use_admin_api_pool"])
    if "allow_custom_api_key" in prev:
        user.allow_custom_api_key = bool(prev["allow_custom_api_key"])

    after = _snapshot(user)
    if dry_run:
        db.rollback()
        print("dry-run after:", json.dumps(after, ensure_ascii=False))
        return 0

    db.commit()
    db.refresh(user)
    after = _snapshot(user)
    log_audit_event(
        action=ACTION_ROLLBACK,
        user_id=int(user.id),
        resource_type="user",
        resource_id=str(user.id),
        detail={"before": before, "after": after, "restored_from": prev},
    )
    print("after:", json.dumps(after, ensure_ascii=False))
    print(f"OK: rolled back to role={after['role']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Elevate / rollback super_admin role")
    parser.add_argument("--email", required=True, help="Target user email")
    parser.add_argument("--rollback", action="store_true", help="Restore previous role from audit")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without commit")
    args = parser.parse_args()

    email = normalize_email(args.email)
    if not email or "@" not in email:
        print("ERROR: invalid email")
        return 1

    print("database:", _db_label())
    if "sqlite" in _db_label().lower():
        print("WARNING: connected to SQLite — production DigiSEO uses PostgreSQL. Check env.local DATABASE_URL.")

    db = SessionLocal()
    try:
        if args.rollback:
            return rollback(db, email=email, dry_run=args.dry_run)
        return elevate(db, email=email, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
