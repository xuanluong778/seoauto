"""Sync publishing WordPress sites into Content Auto Update store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import wp_site_connector as cau
from app.services import publishing_sites_store as pub


@pytest.fixture
def isolated_site_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cau_file = tmp_path / "cau_sites.json"
    pub_file = tmp_path / "pub_sites.json"
    monkeypatch.setattr(cau, "SITES_FILE", cau_file)
    monkeypatch.setattr(pub, "SITES_FILE", pub_file)
    return cau_file, pub_file


def test_list_sites_imports_wordpress_publishing_sites(isolated_site_files, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pub,
        "encrypt_secret",
        lambda value: f"enc:{value}",
    )
    monkeypatch.setattr(
        pub,
        "decrypt_secret",
        lambda value: str(value).removeprefix("enc:"),
    )
    monkeypatch.setattr(
        cau,
        "encrypt_secret",
        lambda value: f"enc:{value}",
    )
    monkeypatch.setattr(
        cau,
        "decrypt_secret",
        lambda value: str(value).removeprefix("enc:"),
    )

    pub.create_site(
        {
            "platform": "wordpress",
            "name": "Blog chính",
            "url": "https://example.com",
            "username": "admin",
            "app_password": "abcd-efgh-ijkl",
        },
        user_id=7,
    )

    items = cau.list_sites(7)
    assert len(items) == 1
    assert items[0]["label"] == "Blog chính"
    assert items[0]["url"] == "https://example.com"

    raw = json.loads(isolated_site_files[0].read_text(encoding="utf-8"))
    assert len(raw) == 1
    assert raw[0]["publishing_site_id"]
    assert cau.decrypt_secret(raw[0]["app_password"]) == "abcd-efgh-ijkl"


def test_connect_site_upserts_publishing_store(isolated_site_files, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pub, "encrypt_secret", lambda value: f"enc:{value}")
    monkeypatch.setattr(pub, "decrypt_secret", lambda value: str(value).removeprefix("enc:"))
    monkeypatch.setattr(cau, "encrypt_secret", lambda value: f"enc:{value}")
    monkeypatch.setattr(cau, "decrypt_secret", lambda value: str(value).removeprefix("enc:"))
    monkeypatch.setattr(
        cau,
        "test_connection",
        lambda **_: {"ok": True, "message": "ok"},
    )

    item = cau.connect_site(
        user_id=9,
        url="https://thegioidigi.com",
        username="editor",
        app_password="abcd-efgh",
        label="Site chính",
    )
    assert item["url"] == "https://thegioidigi.com"
    assert item["label"] == "Site chính"

    pub_items = pub.list_sites(user_id=9, platform="wordpress")
    assert len(pub_items) == 1
    assert pub_items[0]["name"] == "Site chính"

    cau_items = cau.list_sites(9)
    assert len(cau_items) == 1
    assert cau_items[0]["id"] == item["id"]


def test_list_sites_updates_existing_entry_by_url(isolated_site_files, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pub, "encrypt_secret", lambda value: f"enc:{value}")
    monkeypatch.setattr(pub, "decrypt_secret", lambda value: str(value).removeprefix("enc:"))
    monkeypatch.setattr(cau, "encrypt_secret", lambda value: f"enc:{value}")
    monkeypatch.setattr(cau, "decrypt_secret", lambda value: str(value).removeprefix("enc:"))

    monkeypatch.setattr(
        cau,
        "test_connection",
        lambda **_: {"ok": True, "message": "ok"},
    )
    created = pub.create_site(
        {
            "platform": "wordpress",
            "name": "Site A",
            "url": "https://shop.test",
            "username": "editor",
            "app_password": "pass-one",
        },
        user_id=3,
    )
    cau.connect_site(
        user_id=3,
        url="https://shop.test",
        username="legacy",
        app_password="legacy-pass",
        label="Legacy",
    )

    pub.update_site(
        created["id"],
        {"username": "editor", "app_password": "pass-two", "name": "Site A+"},
        user_id=3,
    )

    items = cau.list_sites(3)
    assert len(items) == 1
    assert items[0]["label"] == "Site A+"

    cred = cau.get_site_credentials(items[0]["id"], 3)
    assert cred["username"] == "editor"
    assert cred["app_password"] == "pass-two"
