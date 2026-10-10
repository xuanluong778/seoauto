"""Schema tab routes, generator API, and SSRF guards."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers.schema import router as schema_router
from app.services.auth import get_current_user
from app.services.schema_api import build_schema_generator_response
from app.services.trial_access import require_active_trial
from app.services.url_safety import safe_http_get, validate_public_http_url

_app = FastAPI()
_app.include_router(schema_router)
client = TestClient(_app)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _auth_and_gate():
    user = MagicMock()
    user.id = 1
    user.role = "user"

    def _db():
        yield MagicMock()

    @contextmanager
    def _gate(*_a, **_k):
        class Ctx:
            def commit(self):
                return None

            def release(self, **_kw):
                return None

            def record_usage(self, **_kw):
                return None

        yield Ctx()

    _app.dependency_overrides[require_active_trial] = lambda: user
    _app.dependency_overrides[get_current_user] = lambda: user
    _app.dependency_overrides[get_db] = _db
    try:
        with patch("app.routers.schema.saas_action_gate", _gate), patch(
            "app.routers.schema.credits_enforced", return_value=False
        ), patch("app.routers.schema.check_user_rate_limit"):
            yield
    finally:
        _app.dependency_overrides.pop(require_active_trial, None)
        _app.dependency_overrides.pop(get_current_user, None)
        _app.dependency_overrides.pop(get_db, None)


# --- Routes -----------------------------------------------------------------


def test_schema_page_renders() -> None:
    r = client.get("/schema")
    assert r.status_code == 200
    body = r.text
    assert "Schema Generator" in body
    assert 'href="/schema"' in body or "nav.schema" in body
    assert "/static/css/schema-tool.css" in body
    assert "/static/js/schema-tool.js" in body
    assert "schema-saas-page" in body
    assert "schema-workspace" in body
    assert "<style>" not in body


def test_schema_validate_api() -> None:
    with _auth_and_gate():
        r = client.post(
            "/api/schema/validate",
            json={
                "json_ld": {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": "Demo Co",
                }
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert "validation" in data
    assert "schema_score" in data


def test_schema_preview_api() -> None:
    with _auth_and_gate():
        r = client.get(
            "/api/schema-preview",
            params={"url": "https://example.com/page", "name": "Demo", "description": "Desc"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("@context") == "https://schema.org" or "@graph" in data
    blob = str(data)
    assert "WebSite" in blob or "Organization" in blob or "WebPage" in blob


def test_schema_generator_requires_input() -> None:
    with _auth_and_gate():
        r = client.post("/schema-generator", json={})
    assert r.status_code == 422
    data = r.json()
    assert data.get("schemas") == []
    assert data.get("meta", {}).get("error") or data.get("validation")


def test_schema_generator_from_html() -> None:
    with _auth_and_gate():
        r = client.post(
            "/schema-generator",
            json={
                "html": "<html><title>Buy Widget</title><body><h1>Widget</h1>price 9.99 add to cart</body></html>",
                "url": "https://shop.example/p/1",
                "fetch_serp": False,
            },
        )
    assert r.status_code == 200
    data = r.json()
    types = {n.get("@type") for n in data.get("schemas") or []}
    assert "Product" in types
    assert data.get("primary_schema", {}).get("@type") == "Product"
    assert "validation" in data
    assert "serp_alignment" in data
    assert "meta" in data


def test_schema_generator_rejects_non_json() -> None:
    with _auth_and_gate():
        r = client.post("/schema-generator", content=b"not-json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


# --- Manual form assets -----------------------------------------------------


def test_manual_form_assets_exist_and_cover_kinds() -> None:
    css = (ROOT / "static/css/schema-tool.css").read_text(encoding="utf-8")
    js = (ROOT / "static/js/schema-tool.js").read_text(encoding="utf-8")
    html = (ROOT / "templates/schema_tool.html").read_text(encoding="utf-8")

    assert "schema-workspace" in css
    assert "schema-tabs" in css
    assert "manualKind" in html
    for kind in ("Organization", "LocalBusiness", "Article", "Product", "WebSite", "Person"):
        assert kind in html
        assert kind in js

    assert "btnManualBuild" in html
    assert "buildManualPackage" in js
    assert "/schema-generator" in js


# --- Pipeline (no network) --------------------------------------------------


def test_schema_generator_html_product_signals() -> None:
    r = build_schema_generator_response(
        html="<html><title>X</title><body><h1>Item</h1>price 9.99 add to cart</body></html>",
        url="https://shop.example/p/1",
        fetch_serp_flag=False,
    )
    assert r["ok"] is True
    types = {n.get("@type") for n in r["schemas"]}
    assert "Product" in types
    assert r["primary_schema"].get("@type") == "Product"


def test_schema_generator_faq_heading() -> None:
    r = build_schema_generator_response(
        html="<html><body><h2>Question one?</h2><p>Answer one.</p></body></html>",
        url="https://ex.com/faq",
        fetch_serp_flag=False,
    )
    assert r["ok"] is True
    faq = next((s for s in r["schemas"] if s.get("@type") == "FAQPage"), None)
    assert faq is not None
    assert isinstance(faq.get("mainEntity"), list)
    assert len(faq["mainEntity"]) >= 1


def test_schema_generator_text_input() -> None:
    r = build_schema_generator_response(
        text="How to install the app step by step guide",
        fetch_serp_flag=False,
    )
    assert r["ok"] is True
    assert r["schemas"]


# --- SSRF -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,code",
    [
        ("", "url_empty"),
        ("file:///etc/passwd", "url_scheme_blocked"),
        ("ftp://example.com/a", "url_scheme_blocked"),
        ("gopher://example.com/1", "url_scheme_blocked"),
        ("data:text/html,hi", "url_scheme_blocked"),
        ("javascript:alert(1)", "url_scheme_blocked"),
        ("http://localhost/admin", "url_host_blocked"),
        ("http://localhost.localdomain/", "url_host_blocked"),
        ("http://metadata.google.internal/", "url_host_blocked"),
        ("http://127.0.0.1/", "url_ip_blocked"),
        ("http://127.0.0.1:8080/x", "url_ip_blocked"),
        ("http://[::1]/", "url_ip_blocked"),
        ("http://0.0.0.0/", "url_invalid_host"),
        ("http://10.0.0.5/secret", "url_ip_blocked"),
        ("http://192.168.1.1/", "url_ip_blocked"),
        ("http://172.16.0.1/", "url_ip_blocked"),
        ("http://169.254.169.254/latest/meta-data/", "url_ip_blocked"),
        ("http://100.64.0.1/", "url_ip_blocked"),
    ],
)
def test_validate_public_http_url_blocks(url: str, code: str) -> None:
    assert validate_public_http_url(url) == code


def test_validate_public_http_url_allows_public_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Literal public IP — no DNS needed
    assert validate_public_http_url("https://93.184.216.34/") is None


def test_validate_blocks_dns_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(None, None, None, None, ("10.1.2.3", 0))]

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake_getaddrinfo)
    assert validate_public_http_url("https://evil.example/") == "url_ip_blocked"


def test_safe_http_get_blocks_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("requests.get must not be called for blocked URLs")

    monkeypatch.setattr("app.services.url_safety.requests.get", boom)
    body, err = safe_http_get("http://127.0.0.1/admin")
    assert body == ""
    assert err == "url_ip_blocked"
    assert called["n"] == 0


def test_safe_http_get_rechecks_redirect_target(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        def __init__(self, status_code: int, headers: dict | None = None, content: bytes = b""):
            self.status_code = status_code
            self.headers = headers or {}
            self._content = content
            self.encoding = "utf-8"

        @property
        def is_redirect(self) -> bool:
            return self.status_code in (301, 302, 303, 307, 308)

        def iter_content(self, chunk_size: int = 64 * 1024):
            yield self._content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.startswith("https://public.example"):
            return FakeResp(302, {"Location": "http://127.0.0.1/secret"})
        return FakeResp(200, content=b"<html>ok</html>")

    def fake_getaddrinfo(host, *args, **kwargs):
        if host in ("127.0.0.1", "localhost"):
            return [(None, None, None, None, ("127.0.0.1", 0))]
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr("app.services.url_safety.requests.get", fake_get)
    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake_getaddrinfo)

    body, err = safe_http_get("https://public.example/page")
    assert body == ""
    assert err == "url_ip_blocked"
    assert len(calls) == 1  # never followed to loopback


def test_safe_http_get_max_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        status_code = 302
        headers = {"Location": "https://public.example/next"}
        encoding = "utf-8"
        is_redirect = True

        def iter_content(self, chunk_size: int = 64 * 1024):
            yield b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, *a, **k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    monkeypatch.setattr("app.services.url_safety.requests.get", lambda *a, **k: FakeResp())

    body, err = safe_http_get("https://public.example/start", max_redirects=3)
    assert body == ""
    assert err == "too_many_redirects"


def test_safe_http_get_max_html_size(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        status_code = 200
        headers: dict = {}
        encoding = "utf-8"
        is_redirect = False

        def iter_content(self, chunk_size: int = 64 * 1024):
            yield b"x" * (1024 * 1024)
            yield b"y" * (1024 * 1024)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        lambda host, *a, **k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    monkeypatch.setattr("app.services.url_safety.requests.get", lambda *a, **k: FakeResp())

    body, err = safe_http_get("https://public.example/big", max_bytes=1024 * 1024)
    assert body == ""
    assert err == "html_too_large"


def test_schema_generator_ssrf_via_api(monkeypatch: pytest.MonkeyPatch) -> None:
    with _auth_and_gate():
        r = client.post(
            "/schema-generator",
            json={"url": "http://169.254.169.254/latest/meta-data/", "fetch_serp": False},
        )
    assert r.status_code == 422
    data = r.json()
    assert data.get("schemas") == []
    err = data.get("meta", {}).get("error") or (data.get("validation") or {}).get("errors")
    assert err
    # Must not echo metadata body
    assert "ami-id" not in str(data).lower()


def test_schema_generator_pipeline_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    r = build_schema_generator_response(url="http://192.168.0.10/", fetch_serp_flag=False)
    assert r["ok"] is False
    assert r["error"] == "url_ip_blocked"
