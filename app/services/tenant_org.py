"""Tenant resolution helpers for multi-tenant user data."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.wordpress_plugin_security import personal_organization_id as _personal_org_id


class OrganizationForbiddenError(PermissionError):
    """Caller is not a member of the requested organization."""

    def __init__(self, message: str = "Không được dùng organization của tài khoản khác.") -> None:
        self.code = "organization_forbidden"
        super().__init__(message)


def personal_organization_id(user_id: int) -> int:
    return _personal_org_id(user_id)


def resolve_organization_id(
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> int:
    """
    Active org for requests. Personal workspace default = user_id.

    Never trusts a client-supplied organization_id without membership proof:
    - None / invalid → personal org
    - Equals personal → personal org
    - Any other id → requires db + active OrganizationMember row
    """
    personal = personal_organization_id(user_id)
    if organization_id is None:
        return personal
    try:
        oid = int(organization_id)
    except (TypeError, ValueError) as exc:
        raise OrganizationForbiddenError("organization_id không hợp lệ.") from exc
    if oid <= 0:
        return personal
    if oid == personal:
        return personal
    if db is None:
        # Cannot verify membership without a session — never accept foreign org.
        raise OrganizationForbiddenError()
    if not user_belongs_to_organization(db, user_id=int(user_id), organization_id=oid):
        raise OrganizationForbiddenError()
    return oid


def ensure_personal_organization(db: Session, user_id: int) -> int:
    """Create personal org id=user_id if missing. Never reassigns unknown records."""
    from app.models.organization import Organization, OrganizationMember
    from app.models.user import User

    uid = int(user_id)
    if uid <= 0:
        raise ValueError("invalid_user_id")
    user = db.get(User, uid)
    if user is None:
        raise ValueError("user_not_found")

    org_id = personal_organization_id(uid)
    org = db.get(Organization, org_id)
    if org is None:
        email = str(getattr(user, "email", "") or f"user-{uid}")
        local = email.split("@")[0][:40] or f"user{uid}"
        db.add(
            Organization(
                id=org_id,
                slug=f"personal-{uid}-{local}"[:64],
                name=f"Personal · {email}"[:255],
                status="active",
                kind="personal",
            )
        )
        db.flush()
    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == uid,
            OrganizationMember.deleted_at.is_(None),
        )
        .first()
    )
    if member is None:
        db.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=uid,
                role="owner",
            )
        )
        db.flush()
    return org_id


def user_belongs_to_organization(db: Session, *, user_id: int, organization_id: int) -> bool:
    from app.models.organization import OrganizationMember

    uid = int(user_id)
    oid = int(organization_id)
    if oid <= 0 or uid <= 0:
        return False
    if oid == personal_organization_id(uid):
        return True
    row = (
        db.query(OrganizationMember.id)
        .filter(
            OrganizationMember.organization_id == oid,
            OrganizationMember.user_id == uid,
            OrganizationMember.deleted_at.is_(None),
        )
        .first()
    )
    return row is not None


def resolve_org_member_role(db: Session, user_id: int, organization_id: int) -> str:
    """
    Effective org member role for permission checks.

    Personal workspace (org_id == user_id) → owner when no explicit row.
    Shared org without membership → viewer (deny writes via org layer).
    """
    from app.models.organization import OrganizationMember
    from app.services.permissions import normalize_org_role

    uid = int(user_id)
    oid = int(organization_id)
    if oid <= 0 or uid <= 0:
        return "viewer"
    if oid == personal_organization_id(uid):
        row = (
            db.query(OrganizationMember.role)
            .filter(
                OrganizationMember.organization_id == oid,
                OrganizationMember.user_id == uid,
                OrganizationMember.deleted_at.is_(None),
            )
            .first()
        )
        if row is not None:
            return normalize_org_role(row[0])
        return "owner"
    row = (
        db.query(OrganizationMember.role)
        .filter(
            OrganizationMember.organization_id == oid,
            OrganizationMember.user_id == uid,
            OrganizationMember.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        return "viewer"
    return normalize_org_role(row[0])
