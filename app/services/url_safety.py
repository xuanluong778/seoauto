"""SSRF guards for user-supplied URLs."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from fastapi import HTTPException

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
    }
)

# Extra ranges not always covered by ipaddress flags alone.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_SCHEMES = frozenset({"file", "ftp", "gopher", "data", "javascript", "dict", "sftp", "tftp"})

DEFAULT_FETCH_TIMEOUT_S = 10
DEFAULT_MAX_HTML_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3

_FETCH_UA = "Mozilla/5.0 (compatible; SchemaGenerator/1.1; +https://schema.org/docs)"


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    for net in _BLOCKED_NETWORKS:
        try:
            if ip in net:
                return True
        except TypeError:
            continue
    return False


def _host_resolves_to_blocked_ip(host: str) -> bool:
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # fail closed for fetch paths

    if not addr_infos:
        return True

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return True
    return False



def validate_public_http_url(url: str) -> str | None:
    """
    Return an error code if URL is unsafe for server-side fetch, else None.

    Error codes are stable for API/tests (no secrets, no HTML).
    """
    raw = str(url or "").strip()
    if not raw:
        return "url_empty"

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return "url_scheme_blocked"
    if scheme not in _ALLOWED_SCHEMES:
        return "url_must_be_http_https"

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "url_invalid_host"
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        return "url_host_blocked"
    if host in ("0.0.0.0", "::", "[::]"):
        return "url_invalid_host"

    # Literal IP in hostname
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if _is_blocked_ip(ip):
            return "url_ip_blocked"
        return None
    except ValueError:
        pass

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "url_dns_failed"

    if not addr_infos:
        return "url_dns_failed"

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return "url_ip_blocked"
    return None


def assert_public_http_url(url: str, *, label: str = "URL") -> str:
    """Reject localhost, private IP, non-http(s) — dùng trước crawl/fetch."""
    code = validate_public_http_url(url)
    if code is None:
        return str(url or "").strip()

    messages = {
        "url_empty": f"{label} không được để trống.",
        "url_must_be_http_https": f"{label} phải dùng http hoặc https.",
        "url_scheme_blocked": f"{label} dùng scheme không được phép.",
        "url_invalid_host": f"{label} không hợp lệ.",
        "url_host_blocked": f"{label} không được trỏ tới mạng nội bộ.",
        "url_ip_blocked": f"{label} không được trỏ tới IP nội bộ hoặc metadata.",
        "url_dns_failed": f"{label} không phân giải được hostname.",
    }
    raise HTTPException(status_code=400, detail=messages.get(code, f"{label} không hợp lệ."))


def safe_http_get(
    url: str,
    *,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: dict[str, str] | None = None,
) -> tuple[str, str | None]:
    """
    Fetch a public http(s) URL with SSRF protections.

    Returns ``(body_text, error_code_or_None)``. Never logs response body.
    """
    current = str(url or "").strip()
    err = validate_public_http_url(current)
    if err:
        return "", err

    req_headers = {"User-Agent": _FETCH_UA}
    if headers:
        req_headers.update(headers)

    try:
        for hop in range(max_redirects + 1):
            err = validate_public_http_url(current)
            if err:
                return "", err

            # Re-check DNS/IP on every hop (including first).
            host = (urlparse(current).hostname or "").strip().lower()
            if host and _host_resolves_to_blocked_ip(host):
                return "", "url_ip_blocked"

            with requests.get(
                current,
                timeout=timeout_s,
                headers=req_headers,
                allow_redirects=False,
                stream=True,
            ) as resp:
                if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                    if hop >= max_redirects:
                        return "", "too_many_redirects"
                    loc = (resp.headers.get("Location") or "").strip()
                    if not loc:
                        return "", "redirect_missing_location"
                    current = urljoin(current, loc)
                    continue

                if resp.status_code >= 400:
                    return "", f"http_{resp.status_code}"

                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        return "", "html_too_large"
                    chunks.append(chunk)

                raw = b"".join(chunks)
                encoding = resp.encoding or getattr(resp, "apparent_encoding", None) or "utf-8"
                try:
                    text = raw.decode(encoding, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return text, None

        return "", "too_many_redirects"
    except requests.Timeout:
        return "", "fetch_timeout"
    except requests.RequestException:
        return "", "fetch_error"
    except Exception:  # noqa: BLE001 — never leak internals
        return "", "fetch_error"


def public_url_error_payload(error_code: str) -> dict[str, Any]:
    """Stable, non-sensitive error metadata for API responses."""
    return {"error": error_code}
