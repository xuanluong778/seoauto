"""Concurrent rank check — single-flight + DB row lock."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base
from app.models.user import User
from app.services import rank_tracking_store as store
from app.services.rank_tracking_service import check_keyword_now
from app.services.tenant_org import personal_organization_id


@pytest.fixture()
def rt_env():
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
    user = User(email="rt-conc@test.local", password_hash=hash_password("x"), has_password=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    org = personal_organization_id(user.id)
    project = store.create_project(
        session, user_id=user.id, name="P", domain="seoauto.vn", organization_id=org
    )
    kw = store.create_keyword(
        session,
        user_id=user.id,
        project_id=project["id"],
        keyword="seo tool",
        organization_id=org,
    )
    session.commit()
    yield engine, Session, user, org, kw["id"]
    session.close()


def _mock_serp(*_a, **_k):
    return {
        "items": [
            {
                "type": "organic",
                "rank_absolute": 3,
                "rank_group": 3,
                "domain": "seoauto.vn",
                "url": "https://seoauto.vn/",
                "title": "Home",
            }
        ],
        "mock": True,
    }


def test_concurrent_check_keyword_one_wins(rt_env):
    engine, Session, user, org, keyword_id = rt_env
    user_id = int(user.id)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker(tag: str) -> None:
        db = Session()
        try:
            barrier.wait(timeout=5)
            with patch(
                "app.services.rank_tracking_service.dataforseo_client.google_serp_live_advanced",
                side_effect=_mock_serp,
            ):
                check_keyword_now(db, user_id, keyword_id, organization_id=org, depth=50)
            results.append(f"{tag}:ok")
        except HTTPException as exc:
            results.append(f"{tag}:{exc.status_code}")
        except Exception as exc:
            results.append(f"{tag}:err:{type(exc).__name__}")
        finally:
            db.close()

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    ok_count = sum(1 for r in results if r.endswith(":ok"))
    conflict_count = sum(1 for r in results if ":409" in r or ":409" == r.split(":")[-1])
    assert ok_count == 1
    assert conflict_count >= 1 or any("409" in r for r in results)


def test_concurrent_store_lock(rt_env):
    engine, Session, user, org, keyword_id = rt_env
    user_id = int(user.id)
    outcomes: list[int] = []

    def lock_once() -> None:
        db = Session()
        try:
            store.acquire_keyword_check_lock(db, keyword_id, user_id, organization_id=org)
            db.commit()
            time.sleep(0.15)
            store.clear_keyword_check_lock(db, keyword_id, user_id, organization_id=org)
            db.commit()
            outcomes.append(200)
        except HTTPException as exc:
            outcomes.append(exc.status_code)
        finally:
            db.close()

    threads = [threading.Thread(target=lock_once) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert 409 in outcomes
    assert outcomes.count(200) >= 1
