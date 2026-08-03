"""
Crawl HTML của tối đa 10 URL organic từ SERP để lấy word count / heading thực tế
(phục vụ so sánh depth & benchmark — không thay thế crawl site đầy đủ).
"""

from __future__ import annotations

import ipaddress
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.services.crawler import LINK_CHECK_HEADERS, normalize_url
from app.services.parser import parse_page_seo_data

DEFAULT_TIMEOUT = float(os.getenv("SERP_TOP10_CRAWL_TIMEOUT", "7"))
DEFAULT_MAX_BYTES = int(os.getenv("SERP_TOP10_CRAWL_MAX_BYTES", "450000"))
DEFAULT_WORKERS = int(os.getenv("SERP_TOP10_CRAWL_WORKERS", "4"))


def _row_url(row: dict[str, Any]) -> str:
    return str(row.get("url") or row.get("link") or "").strip()


def _url_host_blocked(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return True
        host = (p.hostname or "").lower()
        if not host or host == "localhost":
            return True
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        except ValueError:
            pass
        if host.endswith(".local"):
            return True
    except Exception:
        return True
    return False


def _normalize_for_match(u: str) -> str:
    try:
        return normalize_url(u).rstrip("/").lower()
    except Exception:
        return (u or "").strip().rstrip("/").lower()


def _fetch_one(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "url": url,
        "ok": False,
        "status_code": 0,
        "word_count": 0,
        "h1_count": 0,
        "h2_count": 0,
        "title": "",
        "error": None,
        "elapsed_ms": 0,
    }
    if _url_host_blocked(url):
        out["error"] = "blocked_or_invalid_url"
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return out
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers=dict(LINK_CHECK_HEADERS),
            allow_redirects=True,
        )
        out["status_code"] = int(r.status_code or 0)
        if out["status_code"] != 200:
            out["error"] = f"http_{out['status_code']}"
            out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            return out
        raw = (r.text or "")[:max_bytes]
        pd = parse_page_seo_data(raw)
        out["title"] = str(pd.get("title") or "")[:300]
        out["word_count"] = int(pd.get("word_count") or 0)
        out["h1_count"] = int(pd.get("h1_count") or 0)
        try:
            sp = BeautifulSoup(raw, "html.parser")
            for tag in sp(["script", "style", "noscript"]):
                tag.decompose()
            out["h2_count"] = len(sp.find_all("h2"))
        except Exception:
            out["h2_count"] = 0
        out["ok"] = True
    except requests.Timeout:
        out["error"] = "timeout"
    except requests.RequestException as e:
        out["error"] = e.__class__.__name__
    except Exception as e:
        out["error"] = str(e)[:120]
    out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def crawl_serp_top_urls(
    serp_rows: list[dict[str, Any]],
    *,
    exclude_url: str | None = None,
    keyword: str | None = None,
    max_pages: int = 10,
    timeout: float | None = None,
    max_bytes: int | None = None,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """
    Crawl tối đa ``max_pages`` URL đầu từ ``serp_results``; bỏ qua URL trùng ``exclude_url`` (trang đang chấm).
    """
    kw_clean = (keyword or "").strip() or None
    timeout = float(timeout if timeout is not None else DEFAULT_TIMEOUT)
    max_bytes = int(max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES)
    max_workers = max(1, min(8, int(max_workers if max_workers is not None else DEFAULT_WORKERS)))

    exclude_set: set[str] = set()
    if exclude_url:
        exclude_set.add(_normalize_for_match(exclude_url))

    targets: list[str] = []
    seen: set[str] = set()
    for row in (serp_rows or [])[: max_pages + 5]:
        u = _row_url(row)
        if not u:
            continue
        key = _normalize_for_match(u)
        if key in exclude_set or key in seen:
            continue
        if _url_host_blocked(u):
            continue
        seen.add(key)
        targets.append(u)
        if len(targets) >= max_pages:
            break

    pages: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    if not targets:
        return {
            "enabled": True,
            "pages": [],
            "stats": {
                "attempted": 0,
                "successful": 0,
                "median_word_count": 0,
                "mean_word_count": 0.0,
                "p75_word_count": 0,
                "avg_h2": 0.0,
                "keyword_in_title_hits": 0,
            },
            "keyword_used": kw_clean,
            "note": "Không có URL SERP hợp lệ để crawl (hoặc toàn bộ trùng URL đang chấm).",
            "total_elapsed_ms": 0,
        }

    workers = min(max_workers, len(targets))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_map = {ex.submit(_fetch_one, u, timeout=timeout, max_bytes=max_bytes): u for u in targets}
        for fut in as_completed(fut_map):
            try:
                pages.append(fut.result())
            except Exception as e:
                pages.append(
                    {
                        "url": fut_map[fut],
                        "ok": False,
                        "status_code": 0,
                        "word_count": 0,
                        "h1_count": 0,
                        "h2_count": 0,
                        "title": "",
                        "error": str(e)[:120],
                        "elapsed_ms": 0,
                    }
                )

    def _sort_key(p: dict[str, Any]) -> int:
        u = p.get("url") or ""
        try:
            return targets.index(u)
        except ValueError:
            return 999

    pages.sort(key=_sort_key)
    ok_pages = [p for p in pages if p.get("ok")]
    wcs = sorted(int(p.get("word_count") or 0) for p in ok_pages if int(p.get("word_count") or 0) > 0)
    median_wc = 0
    mean_wc = 0.0
    p75_wc = 0
    if wcs:
        median_wc = wcs[len(wcs) // 2]
        mean_wc = round(sum(wcs) / len(wcs), 1)
        idx = min(len(wcs) - 1, int(len(wcs) * 0.75))
        p75_wc = wcs[idx]
    h2s = [int(p.get("h2_count") or 0) for p in ok_pages]
    avg_h2 = round(sum(h2s) / len(h2s), 2) if h2s else 0.0
    kw_l = (kw_clean or "").lower()
    kw_hits = 0
    if kw_l:
        for p in ok_pages:
            t = str(p.get("title") or "").lower()
            if kw_l in t:
                kw_hits += 1

    return {
        "enabled": True,
        "pages": pages,
        "stats": {
            "attempted": len(targets),
            "successful": len(ok_pages),
            "median_word_count": int(median_wc),
            "mean_word_count": float(mean_wc),
            "p75_word_count": int(p75_wc),
            "avg_h2": float(avg_h2),
            "keyword_in_title_hits": kw_hits,
        },
        "keyword_used": kw_clean,
        "note": f"Crawl HTTP GET (tối đa {max_bytes // 1000}kB/HTML); không chạy JS.",
        "total_elapsed_ms": int((time.perf_counter() - t_all) * 1000),
    }
