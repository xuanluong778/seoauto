"""RBAC permission matrix — platform + org roles, allow/deny on key endpoints."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.routers.admin import api_router as admin_api_router
from app.routers.rank_tracking import router as rank_tracking_router
from app.services.permissions import (
    PERM_ADMIN_ACCESS,
    PERM_API_KEYS_MANAGE,
    PERM_ORG_MEMBERS_MANAGE,
    PERM_WORKSPACE_READ,
    PERM_WORKSPACE_WRITE,
    has_permission,
    permission_matrix,
)
from app.services.rbac import can_write, is_admin, require_admin_user, require_write_user
from app.services.tenant_org import ensure_personal_organization, personal_organization_id, resolve_org_member_role


def _ns(role: str, *, user_id: int = 1, email: str = "u@test.local") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role, email=email, status="active")


# --- Matrix structure ---


def test_permission_matrix_covers_all_platform_roles():
    matrix = permission_matrix()
    assert set(matrix["platform"]) >= {"super_admin", "admin", "user", "editor", "viewer"}
    assert set(matrix["organization"]) == {"owner", "admin", "editor", "viewer"}
    assert PERM_WORKSPACE_WRITE in matrix["platform"]["editor"]
    assert PERM_WORKSPACE_WRITE not in matrix["platform"]["viewer"]
    assert PERM_ADMIN_ACCESS not in matrix["platform"]["user"]


def test_platform_role_allow_deny():
    assert has_permission(_ns("viewer"), PERM_WORKSPACE_READ) is True
    assert has_permission(_ns("viewer"), PERM_WORKSPACE_WRITE) is False
    assert has_permission(_ns("editor"), PERM_WORKSPACE_WRITE) is True
    assert has_permission(_ns("user"), PERM_WORKSPACE_WRITE) is True
    assert has_permission(_ns("admin"), PERM_ADMIN_ACCESS) is True
    assert has_permission(_ns("user"), PERM_ADMIN_ACCESS) is False
    assert has_permission(_ns("super_admin"), PERM_API_KEYS_MANAGE) is True


def test_can_write_delegates_to_permission_matrix():
    assert can_write(_ns("editor")) is True
    assert can_write(_ns("viewer")) is False


# --- Org-scoped permissions ---


@pytest.fixture()
def org_db():
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.rank_tracking  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.user  # noqa: F401
    from app.models.rank_tracking import RankTrackingKeyword, RankTrackingProject, RankTrackingResult

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Organization.__table__,
            OrganizationMember.__table__,
            RankTrackingProject.__table__,
            RankTrackingKeyword.__table__,
            RankTrackingResult.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    owner = User(
        email="owner@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="editor",
        status="active",
    )
    member = User(
        email="member@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="editor",
        status="active",
    )
    session.add_all([owner, member])
    session.flush()
    ensure_personal_organization(session, owner.id)
    ensure_personal_organization(session, member.id)

    shared_org_id = 900001
    session.add(
        Organization(
            id=shared_org_id,
            slug="team-acme",
            name="Team Acme",
            status="active",
            kind="team",
        )
    )
    session.add(
        OrganizationMember(
            organization_id=shared_org_id,
            user_id=owner.id,
            role="owner",
        )
    )
    session.add(
        OrganizationMember(
            organization_id=shared_org_id,
            user_id=member.id,
            role="viewer",
        )
    )
    session.commit()
    yield session, owner, member, shared_org_id
    session.close()


def test_org_owner_can_write(org_db):
    session, owner, _member, org_id = org_db
    assert resolve_org_member_role(session, owner.id, org_id) == "owner"
    assert has_permission(owner, PERM_WORKSPACE_WRITE, db=session, organization_id=org_id) is True
    assert has_permission(owner, PERM_ORG_MEMBERS_MANAGE, db=session, organization_id=org_id) is True


def test_org_viewer_denied_write_even_when_platform_editor(org_db):
    session, _owner, member, org_id = org_db
    assert resolve_org_member_role(session, member.id, org_id) == "viewer"
    assert has_permission(member, PERM_WORKSPACE_READ, db=session, organization_id=org_id) is True
    assert has_permission(member, PERM_WORKSPACE_WRITE, db=session, organization_id=org_id) is False


def test_platform_viewer_denied_write_on_personal_org(org_db):
    session, owner, _member, _org_id = org_db
    owner.role = "viewer"
    session.commit()
    personal = personal_organization_id(owner.id)
    assert resolve_org_member_role(session, owner.id, personal) == "owner"
    assert has_permission(owner, PERM_WORKSPACE_WRITE, db=session, organization_id=personal) is False


# --- Admin API endpoint ---


def _create_user(db, email: str, *, role: str) -> User:
    local, _, domain = email.partition("@")
    unique = f"{local}+{uuid.uuid4().hex[:8]}@{domain or 'example.com'}"
    u = User(
        email=unique,
        password_hash=hash_password("TestPass123!"),
        has_password=True,
        role=role,
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def admin_api_client():
    app = FastAPI()
    app.include_router(admin_api_router, prefix="/api/admin")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "role,expected",
    [
        ("admin", 200),
        ("super_admin", 200),
        ("user", 403),
        ("editor", 403),
        ("viewer", 403),
    ],
)
def test_admin_users_list_allow_deny_by_role(admin_api_client, role, expected):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = _create_user(db, f"rbac_{role}@example.com", role=role)
        token = create_access_token(user_id=user.id)
    finally:
        db.close()
    r = admin_api_client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == expected


# --- Rank tracking endpoints ---


@pytest.fixture()
def rank_tracking_client(org_db):
    session, owner, member, shared_org_id = org_db
    app = FastAPI()

    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.include_router(rank_tracking_router, prefix="/api/rank-tracking")

    with TestClient(app) as client:
        yield client, session, owner, member, shared_org_id


def test_rank_tracking_viewer_can_read_projects(rank_tracking_client):
    client, _session, owner, _member, _org_id = rank_tracking_client
    owner.role = "viewer"
    token = create_access_token(user_id=owner.id)
    r = client.get("/api/rank-tracking/projects", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_rank_tracking_viewer_denied_create_project(rank_tracking_client):
    client, _session, owner, _member, _org_id = rank_tracking_client
    owner.role = "viewer"
    token = create_access_token(user_id=owner.id)
    r = client.post(
        "/api/rank-tracking/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"domain": "example.com", "name": "Test"},
    )
    assert r.status_code == 403


def test_rank_tracking_editor_can_create_project(rank_tracking_client):
    client, _session, owner, _member, _org_id = rank_tracking_client
    owner.role = "editor"
    token = create_access_token(user_id=owner.id)
    r = client.post(
        "/api/rank-tracking/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"domain": "example.com", "name": "Test"},
    )
    assert r.status_code == 200
    assert r.json()["item"]["domain"] == "example.com"


def test_rank_tracking_viewer_denied_check_now(rank_tracking_client):
    client, session, owner, _member, _org_id = rank_tracking_client
    from app.services import rank_tracking_store as store

    owner.role = "editor"
    token = create_access_token(user_id=owner.id)
    project = store.create_project(
        session,
        user_id=owner.id,
        name="P",
        domain="seoauto.vn",
        organization_id=personal_organization_id(owner.id),
    )
    kw = store.create_keyword(
        session,
        user_id=owner.id,
        project_id=project["id"],
        keyword="seo",
        organization_id=personal_organization_id(owner.id),
    )
    session.commit()

    owner.role = "viewer"
    session.commit()
    viewer_token = create_access_token(user_id=owner.id)

    r = client.post(
        "/api/rank-tracking/check-now",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"keyword_id": kw["id"]},
    )
    assert r.status_code == 403


def test_require_write_user_blocks_viewer():
    viewer = _ns("viewer")
    with pytest.raises(Exception) as exc:
        require_write_user(viewer)
    assert getattr(exc.value, "status_code", None) == 403


def test_require_admin_user_blocks_user():
    user = _ns("user")
    with pytest.raises(Exception) as exc:
        require_admin_user(user)
    assert getattr(exc.value, "status_code", None) == 403
