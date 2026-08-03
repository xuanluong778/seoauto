"""Web 2.0 provider adapter tests (mock mode)."""

from __future__ import annotations

import os

import pytest

from app.services.web20_providers.blogger import BloggerProvider, is_mock_mode as blogger_mock
from app.services.web20_providers.google_sites_manual import GoogleSitesManualProvider, build_manual_package
from app.services.web20_providers.medium import MediumProvider
from app.services.web20_providers.tumblr import TumblrProvider


@pytest.fixture(autouse=True)
def _enable_mocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEB20_BLOGGER_MOCK", "1")
    monkeypatch.setenv("WEB20_TUMBLR_MOCK", "1")
    monkeypatch.setenv("WEB20_MEDIUM_MOCK", "1")


def test_blogger_mock_publish():
    assert blogger_mock() is True
    provider = BloggerProvider()
    account = {"id": "acc1", "external_id": "mock_blog_1", "default_status": "draft"}
    secrets = {"access_token": "mock_blogger_token"}
    post = {"title": "Test Blogger", "html_content": "<p>Hello</p>", "wp_status": "draft"}
    result = provider.publish_post(account, secrets, post)
    assert result["mode"] == "mock"
    assert result["status"] == "draft"
    assert result["external_id"]


def test_tumblr_mock_publish_draft():
    provider = TumblrProvider()
    account = {"id": "acc2", "external_id": "mock.tumblr.com", "default_status": "draft"}
    secrets = {"access_token": "mock_tumblr_token"}
    post = {"title": "Tumblr post", "html_content": "<p>Queue me</p>", "wp_status": "draft"}
    result = provider.publish_post(account, secrets, post)
    assert result["mode"] == "mock"
    assert result["status"] == "draft"


def test_medium_mock_publish():
    provider = MediumProvider()
    account = {"id": "acc3", "external_id": "mock_medium_user", "default_status": "draft"}
    secrets = {"integration_token": "mock_medium_token", "medium_user_id": "mock_medium_user"}
    post = {"title": "Medium Beta", "html_content": "<p>HTML draft</p>", "tags": ["seo"], "wp_status": "draft"}
    result = provider.publish_post(account, secrets, post)
    assert result["mode"] == "mock"
    assert result["status"] == "draft"
    assert "medium.com" in result["published_url"]


def test_google_sites_manual_package():
    provider = GoogleSitesManualProvider()
    post = {
        "title": "Hướng dẫn SEO",
        "excerpt": "Tóm tắt ngắn",
        "html_content": "<p>Nội dung sạch</p>",
        "tags": ["seo", "local"],
    }
    pkg = build_manual_package(post, main_site_url="https://main.com")
    assert "Hướng dẫn SEO" in pkg["html"]
    assert pkg["slug"]
    assert pkg["image_prompt"]
    assert pkg["cta"]
    assert pkg["copy_bundle"]
    assert len(pkg["checklist"]) >= 4
    assert "main.com" in " ".join(pkg["checklist"])
    result = provider.publish_post({"id": "m1", "main_site_url": "https://main.com"}, {}, post)
    assert result["mode"] == "manual"
    assert result["manual_package"]["plain_text"]


def test_blogger_list_blogs_mock():
    provider = BloggerProvider()
    test = provider.test_connection({}, {"access_token": "mock_blogger_token"})
    assert test["ok"] is True
    assert test["blogs"]
