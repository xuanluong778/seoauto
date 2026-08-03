"""Admin panel access and user status."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.core.security import create_access_token, hash_password
from app.db import Base, SessionLocal, engine
from app.models import knowledge as knowledge_models  # noqa: F401
from app.models import seo as seo_models  # noqa: F401
from app.models.user import User
from app.routers.admin import api_router, router as admin_html_router
from app.services.rbac import normalize_status

Base.metadata.create_all(bind=engine)


def _ensure_user_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    alters = []
    if "role" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user'")
    if "status" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'")
    if "api_access_enabled" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN api_access_enabled BOOLEAN NOT NULL DEFAULT 1")
    if "use_admin_api_pool" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN use_admin_api_pool BOOLEAN NOT NULL DEFAULT 0")
    if alters:
        with engine.begin() as conn:
            for sql in alters:
                conn.execute(text(sql))


_ensure_user_columns()


def _ensure_credit_ledger_admin_columns() -> None:
    from app.migrations.ensure_credit_ledger_admin_columns import ensure_credit_ledger_admin_columns

    ensure_credit_ledger_admin_columns()


_ensure_credit_ledger_admin_columns()

app = FastAPI()
app.include_router(auth_router)
app.include_router(api_router, prefix="/admin/api")
app.include_router(api_router, prefix="/api/admin")
app.include_router(admin_html_router)
client = TestClient(app)


def _create_user(db: Session, email: str, *, role: str = "user", status: str = "active") -> User:
    local, _, domain = email.strip().lower().partition("@")
    if "@" not in email:
        domain = "example.com"
        local = email.strip().lower()
    unique_email = f"{local}+{uuid.uuid4().hex[:8]}@{domain or 'example.com'}"
    u = User(
        email=unique_email,
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role=role,
        status=status,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_normalize_status():
    assert normalize_status("BANNED") == "banned"
    assert normalize_status("") == "active"
    assert normalize_status("unknown") == "active"


def test_admin_api_forbidden_for_regular_user():
    db = SessionLocal()
    try:
        user = _create_user(db, "regular_admin_test@example.com", role="user")
        token = create_access_token(user_id=user.id)
    finally:
        db.close()
    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_api_lists_users_for_admin():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_panel_test@example.com", role="admin")
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["total"] >= 1


def test_banned_user_cannot_use_api():
    db = SessionLocal()
    try:
        user = _create_user(db, "banned_test@example.com", status="banned")
        token = create_access_token(user_id=user.id)
    finally:
        db.close()
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_toggle_user_api_access():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_api_perm@example.com", role="admin")
        target = _create_user(db, "target_api_perm@example.com", role="user")
        target_id = target.id
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    r = client.patch(
        f"/api/admin/users/{target_id}/api-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_access_enabled": True, "use_admin_api_pool": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["api_access_enabled"] is True
    assert body["user"]["use_admin_api_pool"] is True
    r2 = client.patch(
        f"/api/admin/users/{target_id}/api-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_access_enabled": False},
    )
    assert r2.status_code == 200
    assert r2.json()["user"]["use_admin_api_pool"] is False


def test_new_user_defaults_api_access_off():
    db = SessionLocal()
    try:
        user = _create_user(db, "new_api_default@example.com", role="user")
        user.api_access_enabled = False
        user.use_admin_api_pool = False
        db.commit()
        db.refresh(user)
        assert user.api_access_enabled is False
    finally:
        db.close()


def test_admin_page_redirects_non_admin():
    db = SessionLocal()
    try:
        user = _create_user(db, "nonadmin_page_403@example.com", role="user")
        token = create_access_token(user_id=user.id)
    finally:
        db.close()
    r = client.get("/admin", headers={"Authorization": f"Bearer {token}"}, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers.get("location") or ""
    assert "admin_forbidden" in loc or "error=admin" in loc


def test_admin_page_ok_for_admin():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_page_ok@example.com", role="admin")
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    r = client.get("/admin", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "Admin" in (r.text or "")


def test_admin_users_segment_activated():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_seg_filter@example.com", role="admin")
        activated = _create_user(db, "activated_seg@example.com", role="user")
        no_pw = User(
            email=f"nopw_seg+{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            has_password=False,
            role="user",
            status="active",
        )
        db.add(no_pw)
        db.commit()
        token = create_access_token(user_id=admin.id)
        activated_email = activated.email
        nopw_email = no_pw.email
    finally:
        db.close()
    r = client.get(
        "/api/admin/users?segment=activated&limit=500",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()["items"]}
    assert activated_email in emails
    assert nopw_email not in emails


def test_admin_users_filter_use_admin_api():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_filter_pool@example.com", role="admin")
        on_user = _create_user(db, "pool_on@example.com", role="user")
        off_user = _create_user(db, "pool_off@example.com", role="user")
        on_user.use_admin_api_pool = True
        off_user.use_admin_api_pool = False
        db.commit()
        token = create_access_token(user_id=admin.id)
        on_email = on_user.email
    finally:
        db.close()
    r = client.get(
        "/admin/api/users?use_admin_api=true&limit=500",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()["items"]}
    assert on_email in emails


def test_admin_api_legacy_prefix_still_works():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_legacy_api@example.com", role="admin")
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    r = client.get("/api/admin/check", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_admin_can_create_user():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_create_user@example.com", role="admin")
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    email = f"new_user_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/admin/api/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": email,
            "password": "TestPass123!",
            "role": "user",
            "status": "active",
            "initial_credits": 50,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["user"]["email"] == email
    assert data["user"]["credit_balance"] >= 50

    r_dup = client.post(
        "/admin/api/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "password": "TestPass123!"},
    )
    assert r_dup.status_code == 400


def test_admin_can_update_user_status():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_status_test@example.com", role="admin")
        target = _create_user(db, "target_status_test@example.com", role="user")
        target_id = target.id
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()
    r = client.patch(
        f"/api/admin/users/{target_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "inactive"},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.id == target_id).first()
        assert row is not None
        assert row.status == "inactive"
    finally:
        db.close()


def test_admin_grant_credits_success():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_grant_credit@example.com", role="admin")
        target = _create_user(db, "target_grant_credit@example.com", role="user")
        target_id = target.id
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()

    r = client.post(
        f"/api/admin/users/{target_id}/grant-credits",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credit_type": "admin_adjustment",
            "amount": 120,
            "reason": "Bù credit hỗ trợ khách",
            "note": "Ticket #99",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["message"] == "Đã tặng credit thành công."
    assert data["new_balance"] >= 120
    assert data["user"]["credit_balance"] >= 120

    detail = client.get(
        f"/api/admin/users/{target_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    hist = detail.json().get("credit_history") or []
    assert any(row.get("amount") == 120 and row.get("grant_reason") == "Bù credit hỗ trợ khách" for row in hist)


def test_admin_grant_credits_forbidden_for_regular_user():
    db = SessionLocal()
    try:
        user = _create_user(db, "regular_grant_credit@example.com", role="user")
        target = _create_user(db, "target_grant_credit2@example.com", role="user")
        target_id = target.id
        token = create_access_token(user_id=user.id)
    finally:
        db.close()

    r = client.post(
        f"/api/admin/users/{target_id}/grant-credits",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credit_type": "admin_adjustment",
            "amount": 10,
            "reason": "test",
        },
    )
    assert r.status_code == 403
    assert "quyền" in r.json().get("detail", "").lower()


def test_admin_grant_credits_invalid_amount():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_grant_invalid@example.com", role="admin")
        target = _create_user(db, "target_grant_invalid@example.com", role="user")
        target_id = target.id
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()

    r = client.post(
        f"/api/admin/users/{target_id}/grant-credits",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credit_type": "admin_adjustment",
            "amount": 0,
            "reason": "test",
        },
    )
    assert r.status_code == 422


def test_admin_grant_credits_user_not_found():
    db = SessionLocal()
    try:
        admin = _create_user(db, "admin_grant_missing@example.com", role="admin")
        token = create_access_token(user_id=admin.id)
    finally:
        db.close()

    r = client.post(
        "/api/admin/users/999999999/grant-credits",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "credit_type": "admin_adjustment",
            "amount": 10,
            "reason": "test",
        },
    )
    assert r.status_code == 404
    assert "Không tìm thấy user" in r.json().get("detail", "")
