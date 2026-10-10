"""Prompt 5 — previously-public costly APIs require auth + gate + rate limit + tenant."""

from __future__ import annotations

import inspect

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.keyword_intelligence import router as ki_router
from app.routers.schema import router as schema_router
from app.routers.serp_intel import router as serp_router
from app.services.rate_limiter import RATE_RULES

app = FastAPI()
app.include_router(schema_router)
app.include_router(ki_router)
app.include_router(serp_router)
client = TestClient(app)

_COSTLY = [
    ("POST", "/schema-generator", {"html": "<html><title>x</title></html>", "fetch_serp": False}),
    ("GET", "/api/keyword-intelligence", None),
    ("POST", "/api/keyword-intelligence", {"seed_keyword": "seo"}),
    ("POST", "/api/serp/keyword-intelligence", {"keyword": "seo"}),
]

_LIGHT_AUTH = [
    ("GET", "/api/schema-preview", None),
    ("POST", "/api/schema/validate", {"json_ld": {"@type": "Organization", "name": "X"}}),
]


def test_costly_apis_reject_anonymous():
    for method, path, body in _COSTLY:
        if method == "GET":
            r = client.get(path, params={"seed_keyword": "seo"})
        else:
            r = client.post(path, json=body or {})
        assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"


def test_schema_light_apis_reject_anonymous():
    for method, path, body in _LIGHT_AUTH:
        if method == "GET":
            r = client.get(path, params={"url": "https://example.com/"})
        else:
            r = client.post(path, json=body or {})
        assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"


def test_ip_rate_rules_cover_dangerous_paths():
    for prefix in (
        "/schema-generator",
        "/api/schema-preview",
        "/api/schema/validate",
        "/api/keyword-intelligence",
        "/api/serp/keyword-intelligence",
    ):
        assert prefix in RATE_RULES
        assert RATE_RULES[prefix][0] > 0


def test_routers_enforce_auth_gate_rate_tenant():
    from app.routers import keyword_intelligence, schema, serp_intel

    schema_src = inspect.getsource(schema.api_schema_generator)
    assert "require_active_trial" in schema_src
    assert "saas_action_gate" in schema_src
    assert "check_user_rate_limit" in schema_src
    assert "organization_id" in schema_src
    assert "personal_organization_id" in schema_src

    preview_src = inspect.getsource(schema.api_schema_preview)
    assert "get_current_user" in preview_src
    assert "check_user_rate_limit" in preview_src

    validate_src = inspect.getsource(schema.api_schema_validate)
    assert "get_current_user" in validate_src

    ki_src = inspect.getsource(keyword_intelligence._run_gated)
    assert "saas_action_gate" in ki_src
    assert "check_user_rate_limit" in ki_src
    assert "organization_id" in ki_src

    serp_src = inspect.getsource(serp_intel.post_keyword_intelligence)
    assert "require_active_trial" in serp_src
    assert "saas_action_gate" in serp_src
    assert "check_user_rate_limit" in serp_src
    assert "organization_id" in serp_src


def test_user_rate_limit_blocks_burst():
    from fastapi import HTTPException

    from app.services.cost_control.runtime import check_user_rate_limit

    uid = 9_001_234
    scope = "prompt5_rate_test"
    for _ in range(3):
        check_user_rate_limit(scope=scope, user_id=uid, limit_per_min=3)
    try:
        check_user_rate_limit(scope=scope, user_id=uid, limit_per_min=3)
        raised = False
    except HTTPException as exc:
        raised = True
        assert exc.status_code == 429
        assert exc.detail.get("code") == "rate_limited"
    assert raised
