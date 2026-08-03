"""DataForSEO client tests."""

from __future__ import annotations

import os

import pytest

from app.services import dataforseo_client as client


def test_google_serp_mock_when_disabled(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_ENABLED", raising=False)
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    out = client.google_serp_live_advanced("seo tools", depth=20)
    assert out["mock"] is True
    assert len(out["items"]) == 20
    assert out["items"][0]["type"] == "organic"


def test_google_serp_mock_flag_respected(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_ENABLED", "0")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "user")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "pass")
    out = client.google_serp_live_advanced("test keyword", depth=15)
    assert out["mock"] is True


def test_is_dataforseo_enabled():
    assert isinstance(client.is_dataforseo_enabled(), bool)


def test_get_basic_auth_missing(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    assert client.get_basic_auth() is None
