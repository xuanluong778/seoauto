"""Idempotency + audit snapshot replay for /analyze/technical."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.audit_store import get_audit_by_idempotency, save_technical_audit
from app.services.idempotency_guard import build_idempotency_key


@pytest.fixture()
def audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "technical_audits.json")
    monkeypatch.setenv("TECHNICAL_AUDITS_PG", "0")
    monkeypatch.setenv("TECHNICAL_AUDITS_PG_READ", "0")
    return tmp_path / "technical_audits.json"


def test_get_audit_by_idempotency_user_scoped(audit_file):
    user_a = 101
    user_b = 202
    key = build_idempotency_key("technical_analyze", user_a, "retry-abc")
    payload = {
        "domain": "demo.com",
        "pages_scanned": 5,
        "issues": [],
        "technical_summary": {"health_score": 77},
        "robots": {"reachable": True},
        "sitemap": {"reachable": True},
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
    }
    save_technical_audit(user_id=user_a, source_url="https://demo.com", result=payload, idempotency_key=key)
    save_technical_audit(
        user_id=user_b,
        source_url="https://demo.com",
        result={**payload, "domain": "other.com"},
        idempotency_key=key,
    )
    hit = get_audit_by_idempotency(user_a, key)
    assert hit is not None
    assert hit["domain"] == "demo.com"
    assert get_audit_by_idempotency(user_b, key)["domain"] == "other.com"
    assert get_audit_by_idempotency(user_a, "missing") is None


def test_save_stores_result_snapshot(audit_file):
    key = build_idempotency_key("technical_analyze", 1, uuid.uuid4().hex[:8])
    snap = {
        "domain": "snap.test",
        "pages_scanned": 1,
        "issues": [{"type": "t", "severity": "low", "message": "m", "url": "https://snap.test/"}],
        "technical_summary": {"health_score": 90, "total_technical_issues": 1},
        "robots": {"reachable": True, "disallow_all": False},
        "sitemap": {"reachable": True},
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
    }
    save_technical_audit(user_id=1, source_url="https://snap.test", result=snap, idempotency_key=key)
    row = get_audit_by_idempotency(1, key)
    assert row is not None
    assert row.get("result_snapshot", {}).get("domain") == "snap.test"
