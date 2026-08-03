"""SSRF URL guards."""

import pytest
from fastapi import HTTPException

from app.services.url_safety import assert_public_http_url


def test_blocks_localhost():
    with pytest.raises(HTTPException) as exc:
        assert_public_http_url("http://127.0.0.1/admin")
    assert exc.value.status_code == 400


def test_blocks_metadata_host():
    with pytest.raises(HTTPException) as exc:
        assert_public_http_url("http://metadata.google.internal/")
    assert exc.value.status_code == 400


def test_allows_public_https(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake_getaddrinfo)
    assert assert_public_http_url("https://example.com/page") == "https://example.com/page"
