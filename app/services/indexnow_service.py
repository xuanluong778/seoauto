"""IndexNow — validate & submit URLs to search engines."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.crawler import normalize_url
from app.services.index_control_service import _host_matches_domain, normalize_domain
from app.services.url_safety import assert_public_http_url

INDEXNOW_API_URL = "https://api.indexnow.org/indexnow"
MAX_URLS_PER_SUBMIT = 100
KEY_RE = re.compile(r"^[a-zA-Z0-9-]{8,128}$")


def validate_indexnow_key(key: str) -> tuple[str | None, str | None]:
    raw = (key or "").strip()
    if not raw:
        return None, "IndexNow key trống."
    if not KEY_RE.match(raw):
        return None, "Key phải dài 8–128 ký tự, chỉ gồm chữ, số và dấu gạch ngang."
    return raw, None


def validate_indexnow_domain(raw: str) -> tuple[str | None, str | None]:
    domain = normalize_domain(raw)
    if not domain:
        return None, "Domain trống hoặc không hợp lệ."
    if len(domain) > 253:
        return None, "Domain quá dài."
    return domain, None


def _hostname_for_indexnow(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        return host
    return host


def validate_indexnow_urls(
    urls: list[str],
    *,
    domain: str,
    max_urls: int = MAX_URLS_PER_SUBMIT,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (valid_normalized_urls, invalid_entries with url + note)."""
    valid: list[str] = []
    invalid: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in urls[:max_urls + 10]:
        text = (raw or "").strip()
        if not text:
            continue
        try:
            safe = assert_public_http_url(text, label="URL")
            normalized = normalize_url(safe)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            invalid.append({"url": text[:2000], "note": str(detail)[:500]})
            continue

        parsed = urlparse(normalized)
        if not _host_matches_domain(parsed.hostname or "", domain):
            invalid.append({"url": normalized, "note": f"URL không thuộc domain {domain}."})
            continue

        if normalized in seen:
            continue
        seen.add(normalized)
        valid.append(normalized)
        if len(valid) >= max_urls:
            break

    if len(valid) > max_urls:
        valid = valid[:max_urls]

    return valid, invalid


def submit_indexnow(
    *,
    domain: str,
    key: str,
    urls: list[str],
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Gửi batch URL tới IndexNow API. Không log key."""
    if not urls:
        return {
            "ok": False,
            "error": "empty_urls",
            "message": "Không có URL hợp lệ để gửi.",
            "http_status": None,
            "api_message": None,
        }

    host = _hostname_for_indexnow(urls[0])
    payload = {
        "host": host,
        "key": key,
        "urlList": urls,
    }

    try:
        resp = requests.post(
            INDEXNOW_API_URL,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "network_error",
            "message": "Không kết nối được IndexNow API.",
            "http_status": None,
            "api_message": str(exc)[:300],
        }

    status = int(resp.status_code)
    body_preview = (resp.text or "")[:500]
    success = status in (200, 202)

    api_message = _indexnow_status_message(status, body_preview)

    return {
        "ok": success,
        "error": None if success else "indexnow_rejected",
        "message": api_message,
        "http_status": status,
        "api_message": body_preview or None,
        "host": host,
        "url_count": len(urls),
    }


def _indexnow_status_message(status: int, body: str) -> str:
    if status == 200:
        return "IndexNow đã nhận URL (200 OK)."
    if status == 202:
        return "IndexNow đã chấp nhận yêu cầu (202 Accepted)."
    if status == 400:
        return "Yêu cầu không hợp lệ (400)."
    if status == 403:
        return "Key không hợp lệ hoặc chưa được xác minh trên domain (403)."
    if status == 422:
        return "URL hoặc host không khớp key (422)."
    if status == 429:
        return "Quá nhiều yêu cầu — thử lại sau (429)."
    if body:
        return f"IndexNow trả về HTTP {status}."
    return f"IndexNow trả về HTTP {status}."
