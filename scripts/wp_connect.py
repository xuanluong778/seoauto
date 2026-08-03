"""WordPress REST URL normalization and resilient HTTP (DNS / www / scheme fallback)."""

from __future__ import annotations

import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import ProtocolError
from urllib3.util.retry import Retry

# Many WordPress hosts / WAFs block the default python-requests User-Agent.
DEFAULT_WP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def normalize_wp_base_url(wp_url: str) -> str:
    raw = (wp_url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _ssl_verify() -> bool | str:
    flag = str(os.getenv("WP_SSL_VERIFY", "1") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    ca = str(os.getenv("WP_SSL_CA_BUNDLE", "") or "").strip()
    return ca if ca else True


def _request_proxies() -> dict[str, str] | None:
    """Optional proxy when hosting blocks Laragon IP (set in env.local)."""
    http_p = str(os.getenv("WP_HTTP_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
    https_p = str(os.getenv("WP_HTTPS_PROXY") or os.getenv("HTTPS_PROXY") or http_p).strip()
    out: dict[str, str] = {}
    if http_p:
        out["http"] = http_p
    if https_p:
        out["https"] = https_p
    return out or None


def iter_wp_base_candidates(url: str) -> list[str]:
    """
    Base URLs to try: host variants (with/without www) × schemes (https, http).
    """
    base = normalize_wp_base_url(url)
    if not base:
        return []
    parsed = urlparse(base)
    host = (parsed.netloc or "").lower()
    if not host:
        return []
    preferred_scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    hosts: list[str] = []
    seen_hosts: set[str] = set()

    def add_host(h: str) -> None:
        h = (h or "").lower().strip()
        if h and h not in seen_hosts:
            seen_hosts.add(h)
            hosts.append(h)

    add_host(host)
    if host.startswith("www."):
        add_host(host[4:])
    else:
        add_host(f"www.{host}")

    schemes: list[str] = []
    if preferred_scheme == "https":
        schemes = ["https", "http"]
    else:
        schemes = ["http", "https"]

    out: list[str] = []
    seen_bases: set[str] = set()
    for h in hosts:
        for scheme in schemes:
            b = f"{scheme}://{h}".rstrip("/")
            if b not in seen_bases:
                seen_bases.add(b)
                out.append(b)
    return out


def merge_wp_headers(headers: dict[str, str] | None) -> dict[str, str]:
    merged = dict(DEFAULT_WP_HEADERS)
    if headers:
        merged.update(headers)
    return merged


def _build_retry_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = True
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=0.4,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "POST", "PUT", "PATCH"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _is_transient_connect_error(exc: BaseException) -> bool:
    text = repr(exc) + " " + str(exc)
    markers = (
        "ConnectionResetError",
        "Connection aborted",
        "Connection refused",
        "RemoteDisconnected",
        "Max retries exceeded",
        "SSLError",
        "SSL:",
        "timed out",
        "Timeout",
        "getaddrinfo failed",
        "NameResolutionError",
        "Failed to resolve",
        "ProtocolError",
        "10054",
        "10061",
    )
    return any(m in text for m in markers)


def format_wp_request_error(exc: Exception, *, host: str = "") -> str:
    text = str(exc)
    host_label = host or "website"
    if "getaddrinfo failed" in text or "NameResolutionError" in text or "Failed to resolve" in text:
        return (
            f"Không phân giải được tên miền «{host_label}» từ máy chạy tool (Laragon). "
            "Kiểm tra URL đúng (thử thêm/bỏ www), mạng/DNS máy tính, rồi thử lại."
        )
    if "timed out" in text.lower() or "timeout" in text.lower():
        return f"Kết nối WordPress quá thời gian chờ ({host_label}). Thử lại sau vài giây."
    if "SSLError" in text or "certificate" in text.lower():
        return (
            f"Lỗi chứng chỉ HTTPS ({host_label}). Kiểm tra URL https:// đúng domain. "
            "Nếu chứng chỉ tự ký, admin có thể đặt WP_SSL_VERIFY=0 trong env.local (không khuyến nghị production)."
        )
    if _is_transient_connect_error(exc):
        proxy_hint = ""
        if not _request_proxies():
            proxy_hint = (
                " Tool đã thử cả https/http và có/không www. Nếu trình duyệt vào site được nhưng tool không: "
                "hosting có thể chặn IP máy Laragon — whitelist IP public của bạn trên cPanel/Cloudflare, "
                "hoặc đặt WP_HTTPS_PROXY trong env.local (proxy/VPS cùng mạng với site)."
            )
        return (
            f"Không kết nối được tới WordPress ({host_label}). Máy chủ đóng kết nối (Connection reset) "
            f"trước khi WordPress trả lời REST API.{proxy_hint}"
        )
    return f"Không kết nối được tới WordPress ({host_label}): {exc}"


def wp_get_json(
    path: str,
    *,
    url: str,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 25,
    params: dict[str, Any] | None = None,
) -> tuple[requests.Response, str]:
    """
    GET REST path trying host/scheme variants on connection errors.
    Returns (response, working_base_url).
    """
    candidates = iter_wp_base_candidates(url)
    if not candidates:
        raise ValueError("URL WordPress không hợp lệ.")
    path = path if path.startswith("/") else f"/{path}"
    session = _build_retry_session()
    req_headers = merge_wp_headers(headers)
    verify = _ssl_verify()
    proxies = _request_proxies()
    req_timeout: float | tuple[float, float] = (min(12.0, timeout), timeout)
    last_exc: Exception | None = None
    last_host = urlparse(candidates[0]).netloc or candidates[0]

    for base in candidates:
        last_host = urlparse(base).netloc or base
        full = f"{base}{path}"
        try:
            resp = session.get(
                full,
                headers=req_headers,
                auth=auth,
                timeout=timeout,
                params=params,
                verify=verify,
            )
            return resp, base
        except (requests.RequestException, socket.gaierror, OSError, ProtocolError) as exc:
            last_exc = exc
            if not _is_transient_connect_error(exc):
                break
            continue

    if last_exc is not None:
        raise requests.RequestException(format_wp_request_error(last_exc, host=last_host)) from last_exc
    raise requests.RequestException("Không kết nối được WordPress.")
