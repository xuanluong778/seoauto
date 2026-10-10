"""DataForSEO API client — Google Organic SERP Live Advanced."""

from __future__ import annotations

import hashlib
import os
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_BASE_URL = "https://api.dataforseo.com"
SERP_ENDPOINT = "/v3/serp/google/organic/live/advanced"


def is_dataforseo_enabled() -> bool:
    return os.getenv("DATAFORSEO_ENABLED", "0").lower() in ("1", "true", "yes")


def get_basic_auth() -> tuple[str, str] | None:
    login = (os.getenv("DATAFORSEO_LOGIN") or "").strip()
    password = (os.getenv("DATAFORSEO_PASSWORD") or "").strip()
    if not login or not password:
        return None
    return login, password


def _base_url() -> str:
    return (os.getenv("DATAFORSEO_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def _mock_organic_items(keyword: str, depth: int) -> list[dict[str, Any]]:
    """Deterministic mock SERP for local dev when API is disabled."""
    depth = max(10, min(int(depth or 100), 100))
    seed = int(hashlib.md5(keyword.lower().encode("utf-8")).hexdigest()[:8], 16)
    items: list[dict[str, Any]] = []
    for rank in range(1, depth + 1):
        domain_idx = (seed + rank * 7) % 20
        domain = f"example-{domain_idx}.com"
        if rank == ((seed % 47) + 3):
            domain = "seoauto.vn"
        items.append(
            {
                "type": "organic",
                "rank_absolute": rank,
                "rank_group": rank,
                "domain": domain,
                "url": f"https://{domain}/page-{rank}",
                "title": f"{keyword} — kết quả #{rank}",
            }
        )
    return items


def google_serp_live_advanced(
    keyword: str,
    *,
    location_name: str = "Vietnam",
    language_name: str = "Vietnamese",
    device: str = "desktop",
    depth: int = 100,
) -> dict[str, Any]:
    """
    Fetch Google organic SERP via DataForSEO Live Advanced API.
    Returns dict with keys: keyword, items, mock, raw (optional).
    """
    kw = str(keyword or "").strip()
    if not kw:
        return {"keyword": "", "items": [], "mock": True, "error": "empty_keyword"}

    depth = max(10, min(int(depth or 100), 100))
    auth = get_basic_auth()
    use_mock = not is_dataforseo_enabled() or auth is None

    if use_mock:
        return {
            "keyword": kw,
            "items": _mock_organic_items(kw, depth),
            "mock": True,
            "location_name": location_name,
            "language_name": language_name,
            "device": device,
            "depth": depth,
        }

    payload = [
        {
            "keyword": kw,
            "location_name": location_name,
            "language_name": language_name,
            "device": device,
            "depth": depth,
        }
    ]
    url = f"{_base_url()}{SERP_ENDPOINT}"
    timeout = max(5, min(60, int(os.getenv("DATAFORSEO_TIMEOUT_SECONDS", "35"))))
    try:
        from app.services.circuit_breaker import CircuitOpenError, call_with_circuit

        def _post():
            return requests.post(url, json=payload, auth=auth, timeout=timeout)

        try:
            resp = call_with_circuit("dataforseo:serp", _post)
        except CircuitOpenError as exc:
            return {
                "keyword": kw,
                "items": _mock_organic_items(kw, depth),
                "mock": True,
                "error": f"circuit_open:{exc.retry_after_sec:.0f}s",
                "fallback_mock": True,
            }
        data = resp.json() if resp.content else {}
    except Exception as exc:
        return {
            "keyword": kw,
            "items": _mock_organic_items(kw, depth),
            "mock": True,
            "error": str(exc),
            "fallback_mock": True,
        }

    if resp.status_code >= 400:
        return {
            "keyword": kw,
            "items": _mock_organic_items(kw, depth),
            "mock": True,
            "error": f"http_{resp.status_code}",
            "fallback_mock": True,
        }

    items = _parse_serp_items(data)
    if not items:
        return {
            "keyword": kw,
            "items": _mock_organic_items(kw, depth),
            "mock": True,
            "error": "empty_result",
            "fallback_mock": True,
            "raw_status": data.get("status_code"),
        }

    return {
        "keyword": kw,
        "items": items,
        "mock": False,
        "location_name": location_name,
        "language_name": language_name,
        "device": device,
        "depth": depth,
    }


def _parse_serp_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        return out
    for task in tasks:
        results = task.get("result") or []
        if not isinstance(results, list):
            continue
        for block in results:
            serp_items = block.get("items") or []
            if not isinstance(serp_items, list):
                continue
            for item in serp_items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").lower() != "organic":
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                domain = str(item.get("domain") or "").strip()
                if not domain:
                    domain = urlparse(url).netloc
                out.append(
                    {
                        "type": "organic",
                        "rank_absolute": item.get("rank_absolute"),
                        "rank_group": item.get("rank_group"),
                        "domain": domain,
                        "url": url,
                        "title": str(item.get("title") or "").strip(),
                    }
                )
    out.sort(key=lambda x: int(x.get("rank_absolute") or 9999))
    return out
