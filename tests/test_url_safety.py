"""SSRF URL guards."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.url_safety import assert_public_http_url, safe_http_get_bytes


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


def test_safe_http_get_bytes_stream_image_no_apparent_encoding(monkeypatch):
    """After stream body read, never touch resp.apparent_encoding (crashes = fetch_error)."""
    jpeg = b"\xff\xd8\xff" + b"\x00" * 500

    class _StreamResp:
        status_code = 200
        is_redirect = False
        encoding = None  # images often have no charset
        headers = {"Content-Type": "image/jpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, chunk_size=64 * 1024):
            yield jpeg

        @property
        def content(self):
            raise RuntimeError("The content for this response was already consumed")

        @property
        def apparent_encoding(self):
            return self.content  # would blow up if accessed

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr("app.services.url_safety.requests.get", lambda *a, **k: _StreamResp())

    data, err, meta = safe_http_get_bytes("https://example.com/photo.jpg", timeout_s=5, max_bytes=1_000_000)
    assert err is None
    assert data == jpeg
    assert "image/jpeg" in str(meta.get("content_type") or "")
