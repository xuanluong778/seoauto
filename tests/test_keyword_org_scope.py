"""Keyword org scope, suggest API, KI auth — UI → API → worker."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db import Base, get_db
from app.models.keyword_cluster_project import KeywordClusterProject
from app.models.keyword_research_project import KeywordResearchProject
from app.models.organization import Organization, OrganizationMember
import app.models.knowledge  # noqa: F401
import app.models.seo  # noqa: F401  # User.projects → Project
from app.models.user import User
from app.routers.keyword_intelligence import router as ki_router
from app.routers.keywords import router as keywords_router
from app.services.auth import get_current_user
from app.services.job_store import create_job, get_job_for_user
from app.services.tenant_org import ensure_personal_organization, personal_organization_id


@contextmanager
def _noop_cost_gate(_req):
    yield MagicMock()


@contextmanager
def _saas_gate_ok():
    from app.schemas.saas import EntitlementResult

    with patch("app.services.permissions.has_permission", return_value=True), patch(
        "app.services.saas_gate.user_has_software_access", return_value=True
    ), patch("app.services.saas_gate.entitlement_service.check_feature") as cf, patch(
        "app.services.saas_gate.entitlement_service.resolve_effective_plan", return_value="pro"
    ), patch("app.services.cost_control.settings.cost_control_enforced", return_value=False), patch(
        "app.services.cost_control.gate.cost_gate_session", _noop_cost_gate
    ):
        cf.return_value = EntitlementResult(
            allowed=True,
            reason_code="ok",
            message="ok",
            feature_key="keyword_research",
            plan_slug="pro",
        )
        yield


@pytest.fixture()
def kw_db():
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.user  # noqa: F401
    from app.models.organization import Organization, OrganizationMember

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
            KeywordResearchProject.__table__,
            KeywordClusterProject.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    owner = User(
        email="kw-owner@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="editor",
        status="active",
    )
    member = User(
        email="kw-member@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="editor",
        status="active",
    )
    outsider = User(
        email="kw-out@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="editor",
        status="active",
    )
    session.add_all([owner, member, outsider])
    session.flush()
    for u in (owner, member, outsider):
        ensure_personal_organization(session, u.id)

    team_org_id = 880001
    session.add(
        Organization(
            id=team_org_id,
            slug="kw-team",
            name="KW Team",
            status="active",
            kind="team",
        )
    )
    session.add(OrganizationMember(organization_id=team_org_id, user_id=owner.id, role="owner"))
    session.add(OrganizationMember(organization_id=team_org_id, user_id=member.id, role="editor"))
    session.commit()

    app = FastAPI()

    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    from app.services.trial_access import require_active_trial

    def _trial_bypass(user: User = Depends(get_current_user)):
        return user

    app.dependency_overrides[require_active_trial] = _trial_bypass
    app.include_router(keywords_router)
    app.include_router(ki_router)

    with TestClient(app) as client:
        yield {
            "session": session,
            "client": client,
            "owner": owner,
            "member": member,
            "outsider": outsider,
            "team_org_id": team_org_id,
            "token_owner": create_access_token(user_id=owner.id),
            "token_member": create_access_token(user_id=member.id),
            "token_out": create_access_token(user_id=outsider.id),
        }
    session.close()


def test_cluster_history_org_member_can_read(kw_db):
    session = kw_db["session"]
    row = KeywordClusterProject(
        user_id=kw_db["owner"].id,
        organization_id=kw_db["team_org_id"],
        project_name="Team cluster",
        keywords_label="team kw",
        keywords_json='["alpha","beta"]',
        language="vi",
        country="vn",
        device="desktop",
        cluster_strictness="normal",
        fetch_serp=0,
        brand_url="",
        result_json='{"clusters":[{"main_keyword":"alpha"}]}',
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    r = kw_db["client"].get(
        f"/keywords/cluster/history/{row.id}",
        headers={"Authorization": f"Bearer {kw_db['token_member']}"},
    )
    assert r.status_code == 200
    assert r.json()["project"]["id"] == row.id


def test_cluster_history_outsider_denied(kw_db):
    session = kw_db["session"]
    row = KeywordClusterProject(
        user_id=kw_db["owner"].id,
        organization_id=kw_db["team_org_id"],
        keywords_label="secret",
        keywords_json='["x"]',
        language="vi",
        country="vn",
        device="desktop",
        cluster_strictness="normal",
        fetch_serp=0,
        brand_url="",
        result_json='{"clusters":[]}',
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    r = kw_db["client"].get(
        f"/keywords/cluster/history/{row.id}",
        headers={"Authorization": f"Bearer {kw_db['token_out']}"},
    )
    assert r.status_code == 404


def test_research_history_team_org_list(kw_db):
    session = kw_db["session"]
    session.add(
        KeywordResearchProject(
            user_id=kw_db["owner"].id,
            organization_id=kw_db["team_org_id"],
            keywords_label="team research",
            seeds_json='["seo"]',
            language="vi",
            country="vn",
            engine="google",
            location_label="Vietnam",
            status="completed",
            result_json='{"keywords":[{"keyword":"seo tool"}],"meta":{"count":1}}',
        )
    )
    session.commit()

    r = kw_db["client"].get(
        "/keywords/research/history",
        params={"organization_id": kw_db["team_org_id"]},
        headers={"Authorization": f"Bearer {kw_db['token_member']}"},
    )
    assert r.status_code == 200
    assert len(r.json()["projects"]) == 1

    r_out = kw_db["client"].get(
        "/keywords/research/history",
        params={"organization_id": kw_db["team_org_id"]},
        headers={"Authorization": f"Bearer {kw_db['token_out']}"},
    )
    assert r_out.status_code == 403


def test_personal_org_research_history_visible(kw_db):
    session = kw_db["session"]
    owner = kw_db["owner"]
    personal = personal_organization_id(owner.id)
    session.add(
        KeywordResearchProject(
            user_id=owner.id,
            organization_id=personal,
            keywords_label="personal",
            seeds_json='["kw"]',
            language="vi",
            country="vn",
            engine="google",
            location_label="Vietnam",
            status="completed",
            result_json='{"keywords":[],"meta":{}}',
        )
    )
    session.commit()

    r = kw_db["client"].get(
        "/keywords/research/history",
        headers={"Authorization": f"Bearer {kw_db['token_owner']}"},
    )
    assert r.status_code == 200
    assert len(r.json()["projects"]) == 1


def test_suggest_requires_auth():
    app = FastAPI()
    app.include_router(keywords_router)
    client = TestClient(app)
    r = client.post("/keywords/suggest", json={"seeds": ["seo"]})
    assert r.status_code in (401, 403)


def test_suggest_viewer_denied(kw_db):
    session = kw_db["session"]
    viewer = User(
        email=f"viewer-{uuid.uuid4().hex[:6]}@test.local",
        password_hash=hash_password("x"),
        has_password=True,
        role="viewer",
        status="active",
    )
    session.add(viewer)
    session.commit()
    token = create_access_token(user_id=viewer.id)

    r = kw_db["client"].post(
        "/keywords/suggest",
        headers={"Authorization": f"Bearer {token}"},
        json={"seeds": ["seo tool"]},
    )
    assert r.status_code == 403


def test_suggest_returns_keywords_mocked(kw_db):
    mock_rows = [
        {"keyword": "seo automation", "search_volume": 100, "source": "dataforseo"},
        {"keyword": "seo tool vietnam", "search_volume": 50, "source": "dataforseo"},
    ]

    with _saas_gate_ok(), patch("app.routers.keywords.enforce_saas_access", return_value="pro"), patch(
        "app.routers.keywords.cost_gate_session", _noop_cost_gate
    ), patch(
        "app.services.credits.credits_enforced", return_value=False
    ), patch(
        "app.services.dataforseo_billing_service.preview_research_billing"
    ) as prev, patch(
        "app.services.dataforseo_billing_service.user_may_use_dataforseo_live", return_value=False
    ), patch(
        "app.services.keyword_ads_expand.expand_keyword_ideas", return_value=mock_rows
    ), patch(
        "app.services.cau_ai_fix_entitlement.resolve_cau_ai_plan_slug", return_value="pro"
    ), patch(
        "app.services.usage_tracking_service.record_successful_usage", lambda *a, **k: None
    ), patch(
        "app.services.dataforseo_billing_service.log_dataforseo_usage", lambda *a, **k: None
    ):
        preview = MagicMock()
        preview.credit_cost = 5
        preview.cache_hits = 1
        preview.api_tasks = 0
        preview.api_mode = "cache"
        preview.to_dict.return_value = {"credit_cost": 5}
        prev.return_value = preview

        r = kw_db["client"].post(
            "/keywords/suggest",
            headers={"Authorization": f"Bearer {kw_db['token_owner']}"},
            json={"seeds": ["seo tool"], "country": "vn", "language": "vi"},
        )

    assert r.status_code == 200
    body = r.json()
    assert len(body["keywords"]) == 2
    assert body["meta"]["organization_id"] == personal_organization_id(kw_db["owner"].id)


def test_cluster_job_stores_organization_id(kw_db, monkeypatch):
    import app.db as dbmod
    import app.services.job_store as job_store
    from app.models.keyword_cluster_job import KeywordClusterJob

    monkeypatch.setenv("CREDITS_ENABLED", "0")
    monkeypatch.setenv("SAAS_ENFORCEMENT", "0")
    Session = sessionmaker(bind=kw_db["session"].get_bind())
    monkeypatch.setattr(job_store, "SessionLocal", Session)
    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    Base.metadata.create_all(bind=kw_db["session"].get_bind(), tables=[KeywordClusterJob.__table__])
    job_store.ensure_job_schema()
    owner = kw_db["owner"]
    org_id = kw_db["team_org_id"]
    job = create_job(
        job_type="keyword_cluster",
        message="test",
        payload={"user_id": owner.id, "organization_id": org_id, "keywords": ["a"]},
        user_id=int(owner.id),
        organization_id=org_id,
    )
    assert job.organization_id == org_id
    fetched = get_job_for_user(job.job_id, user_id=int(owner.id), organization_id=org_id)
    assert fetched is not None
    denied = get_job_for_user(
        job.job_id,
        user_id=int(kw_db["outsider"].id),
        organization_id=org_id,
    )
    assert denied is None


def test_keyword_intelligence_api_auth_and_gate(kw_db):
    with _saas_gate_ok(), patch(
        "app.services.keyword_intelligence_api.build_keyword_intelligence_response",
        return_value={"keywords": [], "clusters": [], "intent_summary": {}},
    ), patch("app.services.credits.credits_enforced", return_value=False), patch(
        "app.services.cost_control.runtime.check_user_rate_limit", lambda *a, **k: None
    ), patch("app.services.usage_tracking_service.record_successful_usage", lambda *a, **k: None):
        r = kw_db["client"].post(
            "/api/keyword-intelligence",
            headers={"Authorization": f"Bearer {kw_db['token_owner']}"},
            json={"seed_keyword": "seo"},
        )
    assert r.status_code == 200
    assert "keywords" in r.json()


def test_keyword_intelligence_anonymous_denied():
    app = FastAPI()
    app.include_router(ki_router)
    client = TestClient(app)
    r = client.post("/api/keyword-intelligence", json={"seed_keyword": "seo"})
    assert r.status_code in (401, 403)
