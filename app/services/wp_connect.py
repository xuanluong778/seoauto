"""WordPress REST URL normalization and resilient HTTP (DNS / www / scheme fallback)."""

from __future__ import annotations

import json
import os
import re
import socket
from functools import lru_cache
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


@lru_cache(maxsize=1)
def wp_server_egress_ip() -> str:
    """IPv4 this host uses to reach the public internet (for WP firewall whitelist)."""
    env_ip = (os.getenv("SEOAUTO_PUBLIC_IP") or os.getenv("SERVER_PUBLIC_IP") or "").strip()
    if env_ip:
        return env_ip
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.connect(("1.1.1.1", 80))
        ip = str(sock.getsockname()[0] or "").strip()
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return ""


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


def _normalize_timeout(timeout: float | tuple[float, float] | None) -> tuple[float, float]:
    """(connect, read). Keep connect short so a firewalled host cannot stall the UI."""
    if isinstance(timeout, (tuple, list)) and len(timeout) >= 2:
        return float(timeout[0]), float(timeout[1])
    read = float(timeout or 15)
    connect = min(4.0, max(2.0, read / 4.0))
    return (connect, read)


def _is_connect_timeout(exc: BaseException) -> bool:
    text = (repr(exc) + " " + str(exc)).lower()
    return any(
        m in text
        for m in (
            "connecttimeout",
            "connection timed out",
            "timed out",
            "timeout",
        )
    )


def _build_retry_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = True
    retry = Retry(
        total=1,
        connect=0,
        read=0,
        backoff_factor=0.2,
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
        ip = wp_server_egress_ip()
        ip_bit = f" IP server Seoauto: {ip}." if ip else ""
        return (
            f"Kết nối WordPress quá thời gian chờ ({host_label}).{ip_bit} "
            "Hosting/tường lửa của site đang chặn IP này (cổng 80/443). "
            "Whitelist IP trên cPanel CSF / Imunify / Cloudflare rồi bấm Kiểm tra kết nối lại."
        )
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


def parse_wp_response_json(resp: requests.Response) -> Any:
    """
    Parse WordPress REST body as JSON.

    Some hosts prepend PHP notices / HTML before JSON, or append tracking
    scripts after a valid JSON payload (e.g. «X Dynamic Data Flow»).
    """
    raw = resp.content or b""
    # Strip UTF-8 BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode(resp.encoding or "utf-8", errors="replace").strip()
    if not text:
        raise ValueError("empty body")

    try:
        return json.loads(text)
    except ValueError:
        pass

    # Prefer first JSON value even when junk follows (injected scripts/HTML).
    start_candidates = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not start_candidates:
        raise ValueError(f"non-json body ctype={resp.headers.get('Content-Type')!r} head={text[:120]!r}")
    start = min(start_candidates)
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text, start)
        return obj
    except ValueError as exc:
        low = text.lower()
        kind = "html"
        if "cloudflare" in low or "cf-ray" in low:
            kind = "cloudflare"
        elif "just a moment" in low or "attention required" in low:
            kind = "waf_challenge"
        elif "<html" in low or "<!doctype" in low:
            kind = "html"
        raise ValueError(
            f"{kind} body http={resp.status_code} ctype={resp.headers.get('Content-Type')!r} head={text[:120]!r}"
        ) from exc


def wp_http_status_note(resp: requests.Response) -> str:
    """Log-safe status line: HTTP code + WP error code. Never include secrets."""
    status = int(getattr(resp, "status_code", 0) or 0)
    ctype = str((resp.headers or {}).get("Content-Type") or "").split(";")[0].strip().lower()
    wp_code = ""
    try:
        data = resp.json()
        if isinstance(data, dict):
            wp_code = str(data.get("code") or "")[:80]
    except Exception:
        wp_code = ""
    kind = "json"
    if "html" in ctype or (resp.text or "").lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        kind = "html/waf"
    parts = [f"HTTP {status}", kind]
    if wp_code:
        parts.append(wp_code)
    return " ".join(parts)


def wp_get_json(
    path: str,
    *,
    url: str,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float | tuple[float, float] = 15,
    params: dict[str, Any] | None = None,
) -> tuple[requests.Response, str]:
    """
    GET REST path trying host/scheme variants on connection errors,
    redirects, and 401/403/404 (www vs apex). Returns (response, working_base_url).
    """
    candidates = iter_wp_base_candidates(url)
    if not candidates:
        raise ValueError("URL WordPress không hợp lệ.")
    path = path if path.startswith("/") else f"/{path}"
    session = _build_retry_session()
    req_headers = merge_wp_headers(headers)
    verify = _ssl_verify()
    proxies = _request_proxies()
    req_timeout = _normalize_timeout(timeout)
    last_exc: Exception | None = None
    last_resp: requests.Response | None = None
    last_base = candidates[0]
    last_host = urlparse(candidates[0]).netloc or candidates[0]

    for base in candidates:
        last_host = urlparse(base).netloc or base
        last_base = base
        full = f"{base}{path}"
        try:
            from app.services.url_safety import validate_public_http_url

            blocked = validate_public_http_url(full)
            if blocked:
                raise ValueError(f"SSRF blocked: {blocked}")
            resp = session.get(
                full,
                headers=req_headers,
                auth=auth,
                timeout=req_timeout,
                params=params,
                verify=verify,
                proxies=proxies,
                allow_redirects=False,
            )
        except ValueError as exc:
            last_exc = exc
            break
        except (requests.RequestException, socket.gaierror, OSError, ProtocolError) as exc:
            last_exc = exc
            # Timeout / firewalled IP: www and http are usually the same box — do not burn 80s+.
            if _is_connect_timeout(exc):
                break
            if not _is_transient_connect_error(exc):
                break
            continue

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = str((resp.headers or {}).get("Location") or "").strip()
            if loc:
                from urllib.parse import urljoin

                nxt = urljoin(full, loc)
                try:
                    from app.services.url_safety import validate_public_http_url

                    if not validate_public_http_url(nxt):
                        nxt_base = normalize_wp_base_url(nxt)
                        if nxt_base and nxt_base not in candidates:
                            candidates.append(nxt_base)
                except Exception:
                    pass
            last_resp = resp
            continue
        if resp.status_code in (401, 403, 404) and base != candidates[-1]:
            last_resp = resp
            continue
        return resp, base

    if last_resp is not None:
        return last_resp, last_base
    if last_exc is not None:
        raise requests.RequestException(format_wp_request_error(last_exc, host=last_host)) from last_exc
    raise requests.RequestException("Không kết nối được WordPress.")
