"""Tests for chatbot workflow runner (mocked backend services)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.chatbot_workflow_runner import (
    STEP_KEYWORD_RESEARCH,
    STEP_WRITE_ARTICLE,
    build_workflow_run_reply,
    run_keyword_cluster_to_article_workflow,
)


@pytest.fixture(autouse=True)
def _grant_saas_access(monkeypatch):
    monkeypatch.setattr("app.services.saas_gate.user_has_software_access", lambda db, uid: True)
    monkeypatch.setattr("app.services.software_access_service.user_has_software_access", lambda db, uid: True)


def _mock_research_payload():
    return {
        "keywords": [
            {"keyword": "đào tạo SEO", "search_volume": {"avg_monthly": 1200}},
            {"keyword": "khóa học SEO", "search_volume": {"avg_monthly": 800}},
            {"keyword": "học SEO online", "search_volume": {"avg_monthly": 500}},
        ],
        "clusters": [
            {
                "cluster_id": "cluster_1",
                "primary_keyword": "đào tạo SEO",
                "variations": ["đào tạo SEO", "khóa học SEO", "học SEO online"],
                "intent": "informational",
                "total_volume": 2500,
                "score": 88.5,
            }
        ],
        "meta": {"entity": "cluster", "count": 1},
    }


@patch("app.services.chatbot_workflow_runner._apply_images_to_project")
@patch("app.services.chatbot_workflow_runner._apply_internal_links_to_content")
@patch("app.services.chatbot_workflow_runner._enforce_chatbot_article_word_count")
@patch("app.services.chatbot_workflow_runner.get_content_ai_project")
@patch("app.services.chatbot_workflow_runner.write_content_ai_article")
@patch("app.services.chatbot_workflow_runner.build_keyword_research_api_response")
def test_workflow_enforces_word_count_when_short(
    mock_research, mock_write, mock_get_project, mock_enforce, mock_links, mock_images
):
    mock_research.return_value = _mock_research_payload()
    mock_write.return_value = "proj-wc-1"
    mock_links.return_value = ("<h1>Test</h1><p>short</p>", 0)
    mock_images.return_value = (0, {"inline_images_count": 0})
    long_html = "<h1>Test</h1><p>" + "word " * 1200 + "</p>"
    mock_get_project.return_value = {
        "id": "proj-wc-1",
        "title": "Hướng dẫn đào tạo SEO cho người mới",
        "primary_keyword": "đào tạo SEO",
        "content": "<h1>Test</h1><p>short</p>",
    }
    mock_enforce.return_value = long_html

    run = run_keyword_cluster_to_article_workflow(
        user_id=42,
        primary_keyword="đào tạo SEO",
        word_count=1200,
        language="vi",
        country="VN",
        include_internal_links=False,
        include_images=False,
        credits_used=10,
        planning_snapshot={
            "primary_keyword": "đào tạo SEO",
            "outline": "<h2>Intro</h2>",
            "secondary_keywords": ["khóa học SEO"],
            "search_volume": 1200,
        },
    )

    assert run.status == "completed"
    mock_enforce.assert_called_once()
    assert mock_enforce.call_args.kwargs["validated_wc"] == 1200
    assert run.article["validated_word_count"] == 1200


@patch("app.services.chatbot_workflow_runner._apply_images_to_project")
@patch("app.services.chatbot_workflow_runner._apply_internal_links_to_content")
@patch("app.services.chatbot_workflow_runner.get_content_ai_project")
@patch("app.services.chatbot_workflow_runner.write_content_ai_article")
@patch("app.services.chatbot_workflow_runner.build_keyword_research_api_response")
def test_workflow_completes_all_steps(
    mock_research, mock_write, mock_get_project, mock_links, mock_images
):
    mock_research.return_value = _mock_research_payload()
    mock_write.return_value = "proj-abc-123"
    mock_links.return_value = ("<h1>Test</h1><p><a href='/x'>link</a></p>", 1)
    mock_images.return_value = (2, {"inline_images_count": 2})
    mock_get_project.return_value = {
        "id": "proj-abc-123",
        "title": "Hướng dẫn đào tạo SEO cho người mới",
        "primary_keyword": "đào tạo SEO",
        "content": "<h1>Test</h1><p>content</p>",
    }

    run = run_keyword_cluster_to_article_workflow(
        user_id=42,
        primary_keyword="đào tạo SEO",
        word_count=1200,
        language="vi",
        country="VN",
        include_internal_links=True,
        include_images=True,
        credits_used=18,
    )

    assert run.status == "completed"
    assert len(run.steps) == 8
    assert all(s.status == "done" for s in run.steps)
    assert run.cluster is not None
    assert run.cluster["primary_keyword"] == "đào tạo SEO"
    assert run.planning is not None
    assert "đào tạo SEO" in (run.planning.get("outline") or "")
    assert run.article is not None
    assert run.article["article_id"] == "proj-abc-123"
    assert run.stats is not None
    assert run.stats.get("internal_links_inserted") == 1
    assert "content-ai?article_id=" in run.actions[0]["url"]

    mock_research.assert_called_once()
    mock_write.assert_called_once()
    write_kw = mock_write.call_args.kwargs
    assert write_kw["user_id"] == 42
    assert write_kw["primary_keyword"] == "đào tạo SEO"
    assert write_kw["target_word_count"] == 1200

    reply = build_workflow_run_reply(run)
    assert "hoàn tất" in reply.lower()
    assert "Mở trong Content AI" in reply
    assert "proj-abc-123" in reply
    assert "Internal link" in reply or "internal link" in reply.lower()


@patch("app.services.chatbot_workflow_runner.build_keyword_research_api_response")
def test_workflow_fails_on_empty_keywords(mock_research):
    mock_research.return_value = {"keywords": [], "clusters": [], "meta": {}}

    run = run_keyword_cluster_to_article_workflow(
        user_id=1,
        primary_keyword="test keyword",
    )

    assert run.status == "failed"
    assert run.error_code == "no_keywords"
    failed = [s for s in run.steps if s.status == "failed"]
    assert failed and failed[0].id == STEP_KEYWORD_RESEARCH
    reply = build_workflow_run_reply(run)
    assert "không hoàn tất" in reply.lower()


@patch("app.services.chatbot_workflow_runner.write_content_ai_article")
@patch("app.services.chatbot_workflow_runner.build_keyword_research_api_response")
def test_workflow_fails_on_write_error(mock_research, mock_write):
    mock_research.return_value = _mock_research_payload()
    mock_write.side_effect = RuntimeError("LLM timeout")

    run = run_keyword_cluster_to_article_workflow(
        user_id=1,
        primary_keyword="đào tạo SEO",
    )

    assert run.status == "failed"
    assert run.error_code == "write_failed"
    failed = [s for s in run.steps if s.status == "failed"]
    assert failed[0].id == STEP_WRITE_ARTICLE


def test_workflow_requires_login():
    run = run_keyword_cluster_to_article_workflow(
        user_id=None,
        primary_keyword="đào tạo SEO",
    )
    assert run.status == "failed"
    assert run.error_code == "login_required"
