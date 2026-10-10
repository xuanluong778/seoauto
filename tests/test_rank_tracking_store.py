"""Rank tracking PostgreSQL store tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services import rank_tracking_store as store
from app.services.tenant_org import personal_organization_id


@pytest.fixture()
def db():
    import app.models.knowledge  # noqa: F401
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
            RankTrackingProject.__table__,
            RankTrackingKeyword.__table__,
            RankTrackingResult.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    user = User(email="rt@test.local", password_hash=hash_password("x"), has_password=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    yield session, user
    session.close()


def test_project_keyword_result_flow(db):
    session, user = db
    uid = user.id
    org = personal_organization_id(uid)
    project = store.create_project(
        session,
        user_id=uid,
        name="Main",
        domain="seoauto.vn",
        organization_id=org,
    )
    kw = store.create_keyword(
        session,
        user_id=uid,
        project_id=project["id"],
        keyword="seo auto",
        organization_id=org,
    )
    session.commit()
    result = store.append_result(
        session,
        user_id=uid,
        organization_id=org,
        project_id=project["id"],
        keyword_id=kw["id"],
        keyword=kw["keyword"],
        domain=project["domain"],
        rank_absolute=12,
        rank_group=12,
        url="https://seoauto.vn/blog",
        title="SEOAuto blog",
        rank_change=None,
        mock=True,
    )
    session.commit()
    assert result["rank_absolute"] == 12
    latest = store.latest_result_for_keyword(session, kw["id"], uid, organization_id=org)
    assert latest and latest["id"] == result["id"]
    assert len(store.list_projects(session, uid, organization_id=org)) == 1
    assert len(store.list_keywords(session, uid, project_id=project["id"], organization_id=org)) == 1


def test_user_isolation(db):
    session, user = db
    import app.models.user as user_model

    user2 = user_model.User(
        email="rt2@test.local",
        password_hash=hash_password("x"),
        has_password=True,
    )
    session.add(user2)
    session.flush()
    org1 = personal_organization_id(user.id)
    org2 = personal_organization_id(user2.id)
    p1 = store.create_project(session, user_id=user.id, name="A", domain="a.com", organization_id=org1)
    p2 = store.create_project(session, user_id=user2.id, name="B", domain="b.com", organization_id=org2)
    session.commit()
    assert len(store.list_projects(session, user.id, organization_id=org1)) == 1
    assert store.list_projects(session, user.id, organization_id=org1)[0]["id"] == p1["id"]
    assert store.list_projects(session, user2.id, organization_id=org2)[0]["id"] == p2["id"]
    with pytest.raises(HTTPException):
        store.get_project(session, p2["id"], user.id, organization_id=org1)


def test_check_lock_blocks_duplicate(db):
    session, user = db
    org = personal_organization_id(user.id)
    project = store.create_project(session, user_id=user.id, name="P", domain="x.com", organization_id=org)
    kw = store.create_keyword(
        session,
        user_id=user.id,
        project_id=project["id"],
        keyword="test kw",
        organization_id=org,
    )
    session.commit()
    store.acquire_keyword_check_lock(session, kw["id"], user.id, organization_id=org)
    session.commit()
    with pytest.raises(HTTPException) as ei:
        store.acquire_keyword_check_lock(session, kw["id"], user.id, organization_id=org)
    assert ei.value.status_code == 409
    store.clear_keyword_check_lock(session, kw["id"], user.id, organization_id=org)
    session.commit()
    store.acquire_keyword_check_lock(session, kw["id"], user.id, organization_id=org)
    session.commit()
