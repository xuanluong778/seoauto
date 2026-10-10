"""SSRF guards for user-supplied URLs and safe outbound HTTP/https fetches.

All server-side fetches of user-controlled URLs MUST go through helpers here
(or assert_public_http_url before connecting). Blocks private/metadata IPs,
DNS rebinding (re-resolve per hop), dangerous schemes, and redirects to
internal addresses.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from fastapi import HTTPException

_LOG = logging.getLogger(__name__)

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
        "metadata.azure.com",
        "instance-data",
    }
)

# Extra ranges not always covered by ipaddress flags alone.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_SCHEMES = frozenset(
    {"file", "ftp", "gopher", "data", "javascript", "dict", "sftp", "tftp", "ldap", "jar"}
)

DEFAULT_FETCH_TIMEOUT_S = 10
DEFAULT_MAX_HTML_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_BINARY_BYTES = 15 * 1024 * 1024

_FETCH_UA = "Mozilla/5.0 (compatible; SchemaGenerator/1.1; +https://schema.org/docs)"


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Map IPv4-mapped IPv6 to IPv4 for checks
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
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


def _normalize_host(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    # Trailing dots (DNS absolute names)
    while h.endswith("."):
        h = h[:-1]
    return h


def _host_resolves_to_blocked_ip(host: str) -> bool:
    host = _normalize_host(host)
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
    # Reject credentials in URL userinfo (SSRF / smuggling)
    if "@" in raw.split("://", 1)[-1].split("/", 1)[0]:
        # allow only if not user:pass style; still block
        host_part = raw.split("://", 1)[-1].split("/", 1)[0]
        if "@" in host_part:
            return "url_userinfo_blocked"

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return "url_scheme_blocked"
    if scheme not in _ALLOWED_SCHEMES:
        return "url_must_be_http_https"

    host = _normalize_host(parsed.hostname or "")
    if not host:
        return "url_invalid_host"
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        return "url_host_blocked"
    if host in ("0.0.0.0", "::", "[::]"):
        return "url_invalid_host"
    # Decimal / octal IP tricks: try interpret whole host as int IP
    if host.isdigit():
        try:
            ip = ipaddress.ip_address(int(host))
            if _is_blocked_ip(ip):
                return "url_ip_blocked"
        except (ValueError, OverflowError):
            pass

    # Literal IP in hostname
    try:
        ip = ipaddress.ip_address(host)
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
        "url_userinfo_blocked": f"{label} không được chứa userinfo.",
    }
    raise HTTPException(status_code=400, detail=messages.get(code, f"{label} không hợp lệ."))


def is_safe_public_http_url(url: str) -> bool:
    return validate_public_http_url(url) is None


def ensure_safe_playwright_url(url: str) -> str:
    """Validate URL before Playwright navigation; raises ValueError if unsafe."""
    code = validate_public_http_url(url)
    if code:
        raise ValueError(code)
    # Re-resolve immediately before navigate (DNS rebinding window still race-prone;
    # playwright cannot pin IP easily — callers should prefer safe_http_get for secrets).
    host = _normalize_host(urlparse(url).hostname or "")
    if host and _host_resolves_to_blocked_ip(host):
        raise ValueError("url_ip_blocked")
    return str(url).strip()


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
    body, err, _meta = safe_http_get_bytes(
        url,
        timeout_s=timeout_s,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        headers=headers,
    )
    if err:
        return "", err
    encoding = _meta.get("encoding") or "utf-8"
    try:
        return body.decode(encoding, errors="replace"), None
    except LookupError:
        return body.decode("utf-8", errors="replace"), None


def safe_http_get_bytes(
    url: str,
    *,
    timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BINARY_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str | None, dict[str, Any]]:
    """Fetch bytes with SSRF protections. Returns (body, error_code, meta)."""
    current = str(url or "").strip()
    err = validate_public_http_url(current)
    if err:
        return b"", err, {}

    req_headers = {"User-Agent": _FETCH_UA}
    if headers:
        req_headers.update(headers)

    meta: dict[str, Any] = {"final_url": current, "status_code": 0, "encoding": "utf-8"}
    try:
        for hop in range(max_redirects + 1):
            err = validate_public_http_url(current)
            if err:
                return b"", err, meta

            host = _normalize_host(urlparse(current).hostname or "")
            if host and _host_resolves_to_blocked_ip(host):
                return b"", "url_ip_blocked", meta

            with requests.get(
                current,
                timeout=timeout_s,
                headers=req_headers,
                allow_redirects=False,
                stream=True,
            ) as resp:
                meta["status_code"] = int(resp.status_code)
                if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                    if hop >= max_redirects:
                        return b"", "too_many_redirects", meta
                    loc = (resp.headers.get("Location") or "").strip()
                    if not loc:
                        return b"", "redirect_missing_location", meta
                    current = urljoin(current, loc)
                    meta["final_url"] = current
                    # Validate redirect target before next hop
                    err = validate_public_http_url(current)
                    if err:
                        return b"", err, meta
                    rhost = _normalize_host(urlparse(current).hostname or "")
                    if rhost and _host_resolves_to_blocked_ip(rhost):
                        return b"", "url_ip_blocked", meta
                    continue

                if resp.status_code >= 400:
                    return b"", f"http_{resp.status_code}", meta

                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        return b"", "html_too_large", meta
                    chunks.append(chunk)

                raw = b"".join(chunks)
                # Do not use resp.apparent_encoding: it re-reads .content after stream
                # consumption and raises RuntimeError → false "fetch_error" on images.
                meta["encoding"] = resp.encoding or "utf-8"
                meta["content_type"] = resp.headers.get("Content-Type") or ""
                meta["final_url"] = current
                return raw, None, meta

        return b"", "too_many_redirects", meta
    except requests.Timeout:
        return b"", "fetch_timeout", meta
    except requests.RequestException:
        return b"", "fetch_error", meta
    except Exception:  # noqa: BLE001 — never leak internals
        _LOG.debug("safe_http_get_bytes unexpected error", exc_info=True)
        return b"", "fetch_error", meta


def safe_requests_get(
    url: str,
    *,
    timeout: float = DEFAULT_FETCH_TIMEOUT_S,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> requests.Response:
    """
    Drop-in-ish replacement for requests.get on user URLs.
    Validates URL + each redirect target. Raises ValueError with error code on block.
    """
    current = str(url or "").strip()
    if params:
        # Let requests build query only after host is safe
        pass
    code = validate_public_http_url(current)
    if code:
        raise ValueError(code)
    host = _normalize_host(urlparse(current).hostname or "")
    if host and _host_resolves_to_blocked_ip(host):
        raise ValueError("url_ip_blocked")

    sess = requests.Session()
    sess.max_redirects = max_redirects
    req_headers = {"User-Agent": _FETCH_UA}
    if headers:
        req_headers.update(headers)

    # Manual redirect follow with revalidation (same as safe_http_get)
    for hop in range(max_redirects + 1):
        code = validate_public_http_url(current)
        if code:
            raise ValueError(code)
        host = _normalize_host(urlparse(current).hostname or "")
        if host and _host_resolves_to_blocked_ip(host):
            raise ValueError("url_ip_blocked")
        resp = sess.get(
            current,
            timeout=timeout,
            headers=req_headers,
            params=params if hop == 0 else None,
            allow_redirects=False,
        )
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            if hop >= max_redirects:
                raise ValueError("too_many_redirects")
            loc = (resp.headers.get("Location") or "").strip()
            if not loc:
                raise ValueError("redirect_missing_location")
            current = urljoin(current, loc)
            params = None
            continue
        return resp
    raise ValueError("too_many_redirects")


def public_url_error_payload(error_code: str) -> dict[str, Any]:
    """Stable, non-sensitive error metadata for API responses."""
    return {"error": error_code}
