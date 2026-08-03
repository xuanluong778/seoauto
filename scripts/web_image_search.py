from __future__ import annotations

import os
import re
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from dotenv import dotenv_values

from app.services.google_cse_images import google_cse_image_search
from app.services.image_relevance import is_blocked_image_url

_BING_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    if not env_file.is_file():
        return {}
    return {str(k): str(v or "") for k, v in (dotenv_values(env_file) or {}).items() if k}


def _getenv(name: str) -> str:
    return str((os.getenv(name) or _env_map().get(name) or "")).strip()


def _normalize_query(q: str) -> str:
    qq = re.sub(r"\s+", " ", (q or "").strip())
    if len(qq) > 200:
        qq = qq[:200].rsplit(" ", 1)[0] or qq[:200]
    return qq


def _bing_parse_tiles(html: str, *, limit: int) -> list[dict[str, Any]]:
    """Ghép đúng URL ảnh + title trong cùng tile (tránh lệch index)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in re.split(r"(?=murl&quot;:&quot;)", html):
        m_murl = re.search(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', chunk)
        if not m_murl:
            continue
        link = unescape(m_murl.group(1)).strip().replace("\\u002f", "/")
        if not link.startswith("http") or link in seen or is_blocked_image_url(link):
            continue
        m_t = re.search(r'&quot;t&quot;:&quot;([^&]+?)&quot;', chunk[:1500])
        title = unescape(m_t.group(1)).strip() if m_t else ""
        seen.add(link)
        out.append(
            {
                "link": link,
                "title": title,
                "thumbnail": link,
                "context": "bing.com",
            }
        )
        if len(out) >= limit:
            break
    return out


def bing_image_search(*, q: str, num: int = 8) -> list[dict[str, Any]]:
    qq = _normalize_query(q)
    if not qq:
        return []
    n = max(1, min(int(num or 8), 20))
    url = (
        "https://www.bing.com/images/search?"
        f"q={quote_plus(qq)}&form=HDRSC2&first=1&setlang=vi&qft=+filterui:photo-photo"
    )
    try:
        r = requests.get(
            url,
            timeout=25,
            headers={
                "User-Agent": _BING_UA,
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            },
        )
    except Exception as exc:
        raise ValueError(f"Không kết nối được Bing Images: {exc}") from exc
    if r.status_code != 200:
        raise ValueError(f"Bing Images HTTP {r.status_code}.")
    items = _bing_parse_tiles(r.text, limit=n * 2)
    return items[:n]


def pexels_image_search(*, q: str, num: int = 8) -> list[dict[str, Any]]:
    key = _getenv("PEXELS_API_KEY")
    if not key:
        return []
    qq = _normalize_query(q)
    if not qq:
        return []
    n = max(1, min(int(num or 8), 15))
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={"query": qq, "per_page": n, "locale": "vi-VN"},
            timeout=25,
        )
    except Exception:
        return []
    if r.status_code != 200:
        return []
    try:
        photos = (r.json() or {}).get("photos") or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for ph in photos:
        src = str(ph.get("src", {}).get("large") or ph.get("src", {}).get("medium") or "").strip()
        if not src or is_blocked_image_url(src):
            continue
        out.append(
            {
                "link": src,
                "title": str(ph.get("alt") or "").strip(),
                "thumbnail": str(ph.get("src", {}).get("medium") or src),
                "context": "pexels.com",
            }
        )
    return out


def serpapi_google_images(*, q: str, num: int = 8) -> list[dict[str, Any]]:
    key = _getenv("SERPAPI_KEY")
    if not key:
        return []
    qq = _normalize_query(q)
    if not qq:
        return []
    n = max(1, min(int(num or 8), 10))
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_images",
                "q": qq,
                "api_key": key,
                "hl": "vi",
                "gl": "vn",
                "num": n,
            },
            timeout=30,
        )
    except Exception:
        return []
    if r.status_code != 200:
        return []
    try:
        results = (r.json() or {}).get("images_results") or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for it in results[:n]:
        link = str(it.get("original") or it.get("thumbnail") or "").strip()
        if not link or is_blocked_image_url(link):
            continue
        out.append(
            {
                "link": link,
                "title": str(it.get("title") or "").strip(),
                "thumbnail": str(it.get("thumbnail") or link),
                "context": str(it.get("source") or "google"),
            }
        )
    return out


def _google_config_error_only(err: str) -> bool:
    low = str(err or "").lower()
    return "invalid argument" in low or (
        "không hợp lệ" in low and "cse" in low and "dấu chấm" in low
    )


def search_web_images(*, q: str, num: int = 8) -> tuple[list[dict[str, Any]], str]:
    """Tìm ảnh — ưu tiên nguồn có metadata chuẩn (Google CSE, SerpAPI, Pexels), cuối Bing."""
    qq = _normalize_query(q)
    if not qq:
        return [], "none"

    per = max(num, 12)

    try:
        items = google_cse_image_search(q=qq, num=per)
        if items:
            return items, "google_cse_image"
    except ValueError as exc:
        if _google_config_error_only(str(exc)):
            raise

    items = serpapi_google_images(q=qq, num=per)
    if items:
        return items, "serpapi_images"

    items = pexels_image_search(q=qq, num=per)
    if items:
        return items, "pexels"

    items = bing_image_search(q=qq, num=per)
    if items:
        return items, "bing_images"

    raise ValueError(f"Không tìm thấy ảnh cho: {qq}")


def image_search_status(*, test_query: str = "technology") -> dict[str, Any]:
    from app.services.google_cse_images import google_cse_probe

    base = google_cse_probe(test_query=test_query)
    qq = _normalize_query(test_query) or "technology"
    bing_ok = False
    bing_count = 0
    bing_err = ""
    try:
        bing_items = bing_image_search(q=qq, num=2)
        bing_ok = bool(bing_items)
        bing_count = len(bing_items)
    except ValueError as exc:
        bing_err = str(exc)

    active = "google_cse_image" if base.get("ok") else ("bing_images" if bing_ok else "none")
    base["bing_fallback"] = {
        "ok": bing_ok,
        "items_sample": bing_count,
        "error": bing_err or None,
    }
    base["active_provider"] = active
    base["pexels_configured"] = bool(_getenv("PEXELS_API_KEY"))
    base["serpapi_configured"] = bool(_getenv("SERPAPI_KEY"))
    return base
