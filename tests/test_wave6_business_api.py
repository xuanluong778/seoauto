"""WAVE 6 — business API cache + query optimization tests."""

from __future__ import annotations

from unittest import mock

import pytest

from app.services.business_api_cache import cache_get, cache_set, tenant_cache_key


def test_tenant_cache_isolation():
    k1 = tenant_cache_key(user_id=1, organization_id=10, scope="auth_me")
    k2 = tenant_cache_key(user_id=2, organization_id=10, scope="auth_me")
    assert k1 != k2
    cache_set(k1, {"id": 1}, ttl=60)
    assert cache_get(k1) == {"id": 1}
    assert cache_get(k2) is None


def test_list_entries_pg_passes_limit(monkeypatch):
    captured: dict[str, int] = {}

    class _Row:
        id = "p1"
        organization_id = 1
        user_id = 1
        created_by = 1
        title = "T"
        slug = ""
        target_website = ""
        primary_keyword = "kw"
        status = "draft"
        origin = ""
        created_at = None
        updated_at = None
        legacy_orphan = False
        payload_json = "{}"

    def _fake_all(self):
        return [_Row()]

    def _fake_q(*args, **kwargs):
        class Q:
            def options(self, *a, **k):
                return self

            def order_by(self, *a, **k):
                return self

            def offset(self, n):
                captured["offset"] = int(n)
                return self

            def limit(self, n):
                captured["limit"] = int(n)
                return self

            def all(self):
                return [_Row()]

        return Q()

    monkeypatch.setattr("app.services.content_ai_projects_pg.SessionLocal", lambda: mock.Mock())
    monkeypatch.setattr("app.services.content_ai_projects_pg.resolve_organization_id", lambda uid, org=None: 1)
    monkeypatch.setattr("app.services.content_ai_projects_pg._active_q", _fake_q)

    from app.services.content_ai_projects_pg import list_entries_pg

    rows = list_entries_pg(user_id=1, limit=5, offset=0, list_only=True)
    assert captured.get("limit") == 5
    assert len(rows) == 1


def test_request_auth_dedup_reuses_user():
    from fastapi import Request
    from starlette.datastructures import Headers

    from app.models.user import User
    from app.services.auth import get_current_user

    user = User(id=99, email="u@test.local", password_hash="x", has_password=True)
    scope = {"type": "http", "headers": [], "method": "GET", "path": "/"}
    request = Request(scope)
    request.state.current_user = user
    out = get_current_user(request=request, token="dummy", db=mock.Mock())
    assert out.id == 99


def test_audit_mine_projection_uses_columns(monkeypatch):
    from app.services.technical_audit_pg import list_mine_recent_by_domain_pg

    class _Row:
        id = "a1"
        created_at = None
        domain = "example.com"
        source_url = "https://example.com"
        pages_scanned = 1
        issue_count = 0
        truncated_issues = False
        payload_json = '{"technical_summary": {"health_score": 80}}'

    db = mock.Mock()
    db.execute.return_value.all.return_value = [_Row()]
    rows = list_mine_recent_by_domain_pg(1, limit=1, db=db)
    assert rows[0]["domain"] == "example.com"
    assert rows[0]["technical_summary"].get("health_score") == 80
