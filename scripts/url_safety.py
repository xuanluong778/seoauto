"""SSRF guards for user-supplied URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

_BLOCKED_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
})


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_http_url(url: str, *, label: str = "URL") -> str:
    """Reject localhost, private IP, non-http(s) — dùng trước crawl/fetch."""
    raw = str(url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{label} không được để trống.")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"{label} phải dùng http hoặc https.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise HTTPException(status_code=400, detail=f"{label} không hợp lệ.")
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise HTTPException(status_code=400, detail=f"{label} không được trỏ tới mạng nội bộ.")
    if host in ("0.0.0.0", "::"):
        raise HTTPException(status_code=400, detail=f"{label} không hợp lệ.")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"{label} không phân giải được hostname.") from None

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail=f"{label} không được trỏ tới IP nội bộ hoặc metadata.")
    return raw
