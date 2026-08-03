"""Web 2.0 Publisher — store & safety tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import social_auto_web20_safety as safety
from app.services import social_auto_web20_store as store


@pytest.fixture()
def web20_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(store, "POSTS_FILE", tmp_path / "posts.json")
    monkeypatch.setattr(store, "LOGS_FILE", tmp_path / "logs.json")
    return tmp_path


def test_user_cannot_access_other_account(web20_files):
    store.create_account(
        user_id=1,
        site_url="https://satellite-a.com",
        username="u1",
        app_password="pass-a",
    )
    assert store.list_accounts(2) == []


def test_default_wp_status_draft(web20_files):
    acc = store.create_account(
        user_id=5,
        site_url="https://blog.example.com",
        username="editor",
        app_password="abcd efgh",
        default_status="draft",
    )
    assert acc["default_status"] == "draft"


def test_safety_rejects_copy_and_too_many_main_links(web20_files):
    source = "Đây là nội dung bài gốc dài về SEO và marketing cho website chính của chúng tôi."
    html = source + " " + source
    html += ' <a href="https://main.com/a">a</a>'
    html += ' <a href="https://main.com/b">b</a>'
    html += ' <a href="https://main.com/c">c</a>'
    html += ' <a href="https://main.com/d">d</a>'
    result = safety.run_web20_safety_checks(
        1,
        title="Test",
        html_content=html,
        account_id="acc-1",
        main_site_url="https://main.com",
        source_content=source,
    )
    assert result["score"] <= 70
    assert result["can_publish"] is False
    codes = {c["code"] for c in result["checks"]}
    assert "main_site_links" in codes or "copy_source" in codes


def test_legacy_account_defaults_wordpress_platform(web20_files):
    acc = store.create_account(
        user_id=3,
        site_url="https://legacy-wp.com",
        username="admin",
        app_password="pass",
    )
    assert acc["platform"] == "wordpress_2_0"


def test_medium_account_store(web20_files):
    acc = store.create_medium_account(
        user_id=7,
        integration_token="mock_medium_token",
        medium_user_id="uid123",
        label="My Medium",
    )
    assert acc["platform"] == "medium"
    listed = store.list_accounts(7, platform="medium")
    assert len(listed) == 1


def test_safety_passes_rewritten_content(web20_files):
    result = safety.run_web20_safety_checks(
        1,
        title="Góc nhìn mới về SEO local",
        html_content="<p>Bài viết spin hoàn toàn khác, tập trung kinh nghiệm thực tế tại quận 1.</p>"
        '<p><a href="https://main.com/dich-vu">Xem dịch vụ</a></p>',
        account_id="acc-1",
        main_site_url="https://main.com",
        source_content="Nội dung gốc hoàn toàn khác chủ đề và cấu trúc khác biệt.",
    )
    assert result["score"] >= 60
