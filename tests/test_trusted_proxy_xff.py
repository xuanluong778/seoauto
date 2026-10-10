"""Trusted proxy X-Forwarded-For / X-Real-IP resolution."""

from __future__ import annotations

from starlette.requests import Request

from app.services.trusted_proxy import resolve_client_ip


def _req(*, peer: str, headers: list[tuple[bytes, bytes]]) -> Request:
    hdrs = list(headers)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": hdrs,
        "client": (peer, 0),
    }
    return Request(scope)


def test_untrusted_peer_ignores_spoofed_xff(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "1")
    req = _req(
        peer="203.0.113.99",
        headers=[(b"x-forwarded-for", b"1.2.3.4")],
    )
    assert resolve_client_ip(req) == "203.0.113.99"


def test_trusted_nginx_peer_uses_x_real_ip(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "1")
    req = _req(
        peer="127.0.0.1",
        headers=[
            (b"x-real-ip", b"203.0.113.50"),
            (b"x-forwarded-for", b"1.2.3.4, 203.0.113.50"),
        ],
    )
    assert resolve_client_ip(req) == "203.0.113.50"


def test_trusted_peer_xff_chain_uses_rightmost_client(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "1")
    req = _req(
        peer="127.0.0.1",
        headers=[(b"x-forwarded-for", b"spoofed, 198.51.100.22")],
    )
    assert resolve_client_ip(req) == "198.51.100.22"


def test_legacy_mode_trusts_first_xff(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_XFF", "0")
    req = _req(
        peer="203.0.113.99",
        headers=[(b"x-forwarded-for", b"1.2.3.4")],
    )
    assert resolve_client_ip(req) == "1.2.3.4"
