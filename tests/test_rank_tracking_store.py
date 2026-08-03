"""Rank tracking store tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import rank_tracking_store as store


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_FILE", tmp_path / "rank_tracking_projects.json")
    monkeypatch.setattr(store, "KEYWORDS_FILE", tmp_path / "rank_tracking_keywords.json")
    monkeypatch.setattr(store, "RESULTS_FILE", tmp_path / "rank_tracking_results.json")
    (tmp_path / "rank_tracking_projects.json").write_text("[]", encoding="utf-8")
    (tmp_path / "rank_tracking_keywords.json").write_text("[]", encoding="utf-8")
    (tmp_path / "rank_tracking_results.json").write_text("[]", encoding="utf-8")
    yield


def test_project_keyword_result_flow():
    uid = 7
    project = store.create_project(
        user_id=uid,
        name="Main",
        domain="seoauto.vn",
        location_name="Vietnam",
        language_name="Vietnamese",
        device="desktop",
    )
    kw = store.create_keyword(user_id=uid, project_id=project["id"], keyword="seo auto")
    result = store.append_result(
        user_id=uid,
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
    assert result["rank_absolute"] == 12
    latest = store.latest_result_for_keyword(kw["id"], uid)
    assert latest and latest["id"] == result["id"]
    assert len(store.list_projects(uid)) == 1
    assert len(store.list_keywords(uid, project_id=project["id"])) == 1


def test_user_isolation():
    p1 = store.create_project(user_id=1, name="A", domain="a.com")
    p2 = store.create_project(user_id=2, name="B", domain="b.com")
    assert len(store.list_projects(1)) == 1
    assert store.list_projects(1)[0]["id"] == p1["id"]
    assert store.list_projects(2)[0]["id"] == p2["id"]
    with pytest.raises(HTTPException):
        store.get_project(p2["id"], 1)
