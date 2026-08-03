"""
Fetch competitor landing pages from SERP URLs (HTTP first; optional Playwright).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.content_analysis import analyze_content
from app.services.raw_html_fetch import GOOGLEBOT_UA, fetch_raw_html
from app.services.serp_fetcher import normalize_serp_url


def _meta_description(soup: BeautifulSoup) -> str:
    m = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if m and m.get("content"):
        return str(m.get("content"))[:500]
    m = soup.find("meta", attrs={"property": re.compile("^og:description$", re.I)})
    if m and m.get("content"):
        return str(m.get("content"))[:500]
    return ""


def _headings(soup: BeautifulSoup) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
    for tag, key in (("h1", "h1"), ("h2", "h2"), ("h3", "h3")):
        for el in soup.find_all(tag)[:40]:
            t = el.get_text(" ", strip=True)
            if t:
                out[key].append(t[:240])
    return out


def _internal_links(html: str, page_url: str, max_links: int = 120) -> list[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        host = (urlparse(page_url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if href.startswith("/"):
                base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
                href = base + href
            try:
                h = (urlparse(href).hostname or "").lower()
                if h.startswith("www."):
                    h = h[4:]
                if h == host:
                    nu = normalize_serp_url(href)
                    if nu and nu not in out:
                        out.append(nu)
            except Exception:
                continue
            if len(out) >= max_links:
                break
        return out
    except Exception:
        return []


def _js_dependency_heuristic(html: str) -> bool:
    low = (html or "").lower()
    scripts = low.count("<script")
    body = len(re.sub(r"<[^>]+>", " ", html or ""))
    return scripts >= 8 and body < 2500


def fetch_competitor_page(url: str) -> dict[str, Any]:
    """Single URL → competitor row with HTML-derived features + timing."""
    nu = normalize_serp_url(url)
    t0 = time.perf_counter()
    use_pw = os.getenv("SERP_COMPETITOR_USE_PLAYWRIGHT", "0").lower() in ("1", "true", "yes")
    html = ""
    status = 0
    if use_pw:
        try:
            from playwright.sync_api import sync_playwright

            from app.services.playwright_stealth import CHROMIUM_LAUNCH_ARGS, STEALTH_INIT_SCRIPT, stealth_context_options

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=list(CHROMIUM_LAUNCH_ARGS))
                try:
                    ctx = browser.new_context(**stealth_context_options(profile="desktop", java_script_enabled=True))
                    ctx.add_init_script(STEALTH_INIT_SCRIPT)
                    page = ctx.new_page()
                    page.goto(nu, wait_until="domcontentloaded", timeout=35000)
                    html = page.content() or ""
                    status = 200
                    ctx.close()
                finally:
                    browser.close()
        except Exception:
            pkg = fetch_raw_html(nu, user_agent=GOOGLEBOT_UA, timeout_seconds=22.0)
            html = str(pkg.get("html") or "")
            status = int(pkg.get("status") or 0)
    else:
        pkg = fetch_raw_html(nu, user_agent=GOOGLEBOT_UA, timeout_seconds=22.0)
        html = str(pkg.get("html") or "")
        status = int(pkg.get("status") or 0)
    load_time = round(time.perf_counter() - t0, 3)

    title = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)[:300]
        meta_desc = _meta_description(soup)
        heads = _headings(soup)
        internal = _internal_links(html, nu)
        content = analyze_content(html)
    except Exception:
        meta_desc, heads, internal = "", {"h1": [], "h2": [], "h3": []}, []
        content = analyze_content(html or "")

    max_html = int(os.getenv("SERP_COMPETITOR_HTML_MAX_CHARS", "350000"))
    return {
        "url": nu,
        "http_status": status,
        "html_excerpt": (html or "")[:max_html],
        "title": title,
        "meta_description": meta_desc,
        "headings": heads,
        "internal_links": internal,
        "internal_link_count": len(internal),
        "word_count": int(content.get("word_count") or 0),
        "content_depth": content.get("content_depth"),
        "heading_structure_score": float(content.get("heading_structure_score") or 0.0),
        "load_time_seconds": load_time,
        "js_dependency": _js_dependency_heuristic(html),
        "html_length": len(html or ""),
    }


def fetch_competitor_pages(
    urls: list[str],
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch up to ``max_pages`` competitor URLs (default ``SERP_COMPETITOR_FETCH_MAX``)."""
    cap = max_pages or int(os.getenv("SERP_COMPETITOR_FETCH_MAX", "10"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for u in urls:
        nu = normalize_serp_url(u)
        if not nu or nu in seen:
            continue
        seen.add(nu)
        try:
            out.append(fetch_competitor_page(nu))
        except Exception as exc:
            out.append(
                {
                    "url": nu,
                    "http_status": 0,
                    "html_excerpt": "",
                    "error": str(exc)[:300],
                    "title": "",
                    "meta_description": "",
                    "headings": {"h1": [], "h2": [], "h3": []},
                    "internal_links": [],
                    "internal_link_count": 0,
                    "word_count": 0,
                    "load_time_seconds": 0.0,
                    "js_dependency": False,
                }
            )
        if len(out) >= cap:
            break
    return out
