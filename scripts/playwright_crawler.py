"""
Playwright technical crawl — STEALTH mode by default.

- Real Chrome UAs (mobile / desktop rotation), randomized viewport & deviceScaleFactor.
- Chromium flags: AutomationControlled off, no-sandbox, infobars off, dev-shm.
- Init script: webdriver undefined, minimal chrome object, languages, permissions.query.
- Navigation: domcontentloaded → body → document.complete → random delay → human scroll/mouse.
- Multi-profile fallback (mobile → desktop → desktop no-JS) on challenge / hard block.
- Per-page: crawl_status, block_reason, render_status, render_confidence, stealth_used, profile_used, js_dependency.

Set PLAYWRIGHT_USE_GOOGLEBOT_RAW=1 to fetch raw HTML with legacy Googlebot UA instead of Chrome desktop.
Set STEALTH_DEBUG_LOG=1 (or CRAWLER_DEBUG_LOG=1) to write JSON under data/crawl_debug/run_<id>/.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

from app.services.crawler import _extract_links, normalize_url
from app.services.playwright_stealth import (
    CHROMIUM_LAUNCH_ARGS,
    RAW_HTML_STEALTH_UA,
    STEALTH_INIT_SCRIPT,
    StealthDebugSession,
    advanced_wait_after_navigation,
    assess_partial_render,
    attach_stealth_listeners,
    detect_blocked_generic,
    human_like_interaction,
    scroll_lazy_pass,
    stealth_context_options,
    stealth_debug_dir,
    stealth_debug_enabled,
)
from app.services.raw_html_fetch import GOOGLEBOT_UA, fetch_raw_html
from app.services.seo_crawl_enrichment import enrich_crawl_page_record

_LOGGER = logging.getLogger(__name__)

_DEBUG_CRAWL = os.getenv("CRAWLER_DEBUG_LOG", "").lower() in ("1", "true", "yes")

# Legacy Googlebot UA (optional raw snapshot only).
PLAYWRIGHT_GOOGLEBOT_UA = (
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/41.0.2272.96 Mobile Safari/537.36 "
    "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)

_USE_GOOGLEBOT_RAW = os.getenv("PLAYWRIGHT_USE_GOOGLEBOT_RAW", "").lower() in ("1", "true", "yes")

_MAX_GOTO_RETRIES = int(os.getenv("PLAYWRIGHT_GOTO_MAX_RETRIES", "3"))
_INITIAL_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_INITIAL_TIMEOUT_MS", "55000"))
_MIN_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_MIN_TIMEOUT_MS", "25000"))
_MAX_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_MAX_TIMEOUT_MS", "140000"))


class _AdaptiveNavTimeout:
    """Prefer successful render over speed — widen window after slow pages / timeouts."""

    def __init__(self) -> None:
        self._ms = max(_MIN_TIMEOUT_MS, min(_MAX_TIMEOUT_MS, _INITIAL_TIMEOUT_MS))

    @property
    def ms(self) -> int:
        return self._ms

    def on_success(self, elapsed_sec: float) -> None:
        if elapsed_sec < 5.0:
            self._ms = max(_MIN_TIMEOUT_MS, self._ms - 4000)
        elif elapsed_sec > 28.0:
            self._ms = min(_MAX_TIMEOUT_MS, self._ms + 12000)

    def on_timeout(self) -> None:
        self._ms = min(_MAX_TIMEOUT_MS, self._ms + 18000)


def _redirect_chain_from_response(response: Any) -> list[str]:
    if response is None:
        return []
    try:
        req = response.request
    except Exception:
        return []
    chain: list[str] = []
    cur: Any = req
    while cur:
        try:
            chain.insert(0, cur.url)
        except Exception:
            break
        cur = getattr(cur, "redirected_from", None)
    return chain


def _is_html_response_pw(response: Any) -> bool:
    if not response:
        return False
    try:
        ct = (response.headers or {}).get("content-type", "")
    except Exception:
        return False
    return "text/html" in str(ct).lower()


def _compute_js_dependency(raw_html: str, rendered_html: str) -> bool:
    raw = raw_html or ""
    ren = rendered_html or ""
    lr, le = len(raw), len(ren)
    if lr < 800 and le > 6000:
        return True
    if lr <= 0:
        return le > 4000
    ratio = le / float(lr)
    if ratio >= 2.2 and le >= 8000:
        return True
    if ratio >= 1.6 and (le - lr) >= 12000:
        return True
    return False


def _log_crawl_page(
    url: str,
    *,
    pw_status: int,
    raw_status: int,
    summary: dict[str, Any],
    indexable: bool | None = None,
) -> None:
    if not _DEBUG_CRAWL:
        return
    _LOGGER.info(
        "crawl url=%s pw_status=%s raw_status=%s identical=%s ratio=%s title_match=%s indexable=%s",
        url,
        pw_status,
        raw_status,
        summary.get("identical"),
        summary.get("content_length_ratio"),
        summary.get("title_match"),
        indexable,
    )


def _goto_with_retries(page: Any, url: str, timeout_ms: int) -> tuple[Any | None, str | None]:
    last_err: str | None = None
    for attempt in range(max(1, _MAX_GOTO_RETRIES)):
        if attempt > 0:
            time.sleep(float(2 ** (attempt - 1)))
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return resp, None
        except Exception as exc:
            last_err = str(exc)[:500]
            _LOGGER.debug("goto attempt %s/%s failed %s: %s", attempt + 1, _MAX_GOTO_RETRIES, url, exc)
    return None, last_err


def _profile_sequence() -> list[tuple[str, bool]]:
    """(playwright_profile_key, java_script_enabled)."""
    return [
        ("mobile", True),
        ("desktop", True),
        ("desktop", False),
    ]


def _ordered_profiles(preferred: str | None) -> list[tuple[str, bool]]:
    """Prefer a profile first (from domain intelligence); keep full fallback chain."""
    full = _profile_sequence()
    if not preferred:
        return full
    key = str(preferred).strip().lower()
    if key == "desktop_nojs":
        priority = [("desktop", False), ("desktop", True), ("mobile", True)]
    elif key == "mobile":
        priority = [("mobile", True), ("desktop", True), ("desktop", False)]
    elif key == "desktop":
        priority = [("desktop", True), ("mobile", True), ("desktop", False)]
    else:
        return full
    out: list[tuple[str, bool]] = []
    for p in priority:
        if p not in out:
            out.append(p)
    for p in full:
        if p not in out:
            out.append(p)
    return out


def _pw_debug_counts(js_errors: list[str], network_log: list[Any]) -> dict[str, int]:
    return {"js_error_count": len(js_errors), "network_log_len": len(network_log)}


def _profile_used_label(profile: str, js_enabled: bool) -> str:
    if profile == "desktop" and not js_enabled:
        return "desktop_nojs"
    return profile


def _playwright_proxy_dict(
    proxy_server: str | None,
    proxy_username: str | None,
    proxy_password: str | None,
) -> dict[str, str] | None:
    if not (proxy_server or "").strip():
        return None
    d: dict[str, str] = {"server": proxy_server.strip()}
    if proxy_username:
        d["username"] = proxy_username
    if proxy_password:
        d["password"] = proxy_password
    return d


def crawl_site_detailed_rendered(
    start_url: str,
    max_pages: int = 50,
    *,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    external_playwright: Any | None = None,
    external_browser: Any | None = None,
    profile_preference: str | None = None,
    timeout_scale: float = 1.0,
    interaction_delay_scale: float = 1.0,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    if max_pages <= 0:
        return {"pages": [], "total": 0, "edges": [], "domain": ""}

    try:
        normalized_start = normalize_url(start_url)
    except ValueError:
        return {"pages": [], "total": 0, "edges": [], "domain": ""}

    _ts = max(0.35, min(3.0, float(timeout_scale)))
    _is = max(0.5, min(3.0, float(interaction_delay_scale)))

    base_domain = urlparse(normalized_start).netloc
    queue: deque[str] = deque([normalized_start])
    seen: set[str] = {normalized_start}
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    adaptive = _AdaptiveNavTimeout()

    dbg = StealthDebugSession() if stealth_debug_enabled() else None
    dbg_dir = stealth_debug_dir() if dbg else None

    raw_fetch_ua = GOOGLEBOT_UA if _USE_GOOGLEBOT_RAW else RAW_HTML_STEALTH_UA
    req_proxies: dict[str, str] | None = None
    if (proxy_server or "").strip():
        ps = proxy_server.strip()
        req_proxies = {"http": ps, "https": ps}
    proxy_play = _playwright_proxy_dict(proxy_server, proxy_username, proxy_password)

    own_pw = external_playwright is None or external_browser is None
    if own_pw:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=list(CHROMIUM_LAUNCH_ARGS))
    else:
        pw = external_playwright
        browser = external_browser

    try:
        while queue and len(pages) < max_pages:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            raw_pkg = fetch_raw_html(current, user_agent=raw_fetch_ua, proxies=req_proxies)
            raw_html = str(raw_pkg.get("html") or "")
            raw_status = int(raw_pkg.get("status") or 0)
            raw_chain = list(raw_pkg.get("redirect_history") or [current])
            raw_headers = dict(raw_pkg.get("response_headers") or {})
            raw_err = raw_pkg.get("error")
            try:
                raw_final_norm = normalize_url(str(raw_pkg.get("final_url") or current))
            except ValueError:
                raw_final_norm = current

            timeout_ms = int(adaptive.ms * _ts)

            best: dict[str, Any] | None = None
            last_block: tuple[str, str | None] | None = None
            profiles = _ordered_profiles(profile_preference)

            for idx, (profile, js_on) in enumerate(profiles):
                interaction_log: list[dict[str, Any]] = []
                network_log: list[dict[str, Any]] = []
                js_errors: list[str] = []

                ctx_opts = stealth_context_options(profile=profile, java_script_enabled=js_on)
                if proxy_play:
                    ctx_opts = {**ctx_opts, "proxy": proxy_play}
                if dbg:
                    dbg.add_profile_record(
                        {
                            "url": current,
                            "profile": _profile_used_label(profile, js_on),
                            "context_options": {k: v for k, v in ctx_opts.items() if k != "user_agent"}
                            | {"user_agent_prefix": (ctx_opts.get("user_agent") or "")[:60]},
                        }
                    )

                context = browser.new_context(**ctx_opts)
                try:
                    context.add_init_script(STEALTH_INIT_SCRIPT)
                    page = context.new_page()
                    attach_stealth_listeners(page, network_log=network_log, js_errors=js_errors)

                    t0 = time.perf_counter()
                    resp, goto_err = _goto_with_retries(page, current, timeout_ms)
                    elapsed = time.perf_counter() - t0

                    if resp is None:
                        adaptive.on_timeout()
                        if dbg:
                            dbg.extend_interactions(interaction_log)
                            dbg.extend_network(network_log + [{"type": "js_errors", "items": js_errors}])
                        if idx < len(profiles) - 1:
                            continue
                        enriched_to = enrich_crawl_page_record(
                            rendered_html="",
                            raw_html=raw_html,
                            final_effective_url=current,
                            raw_final_url=raw_final_norm,
                            playwright_status=0,
                            raw_http_status=raw_status,
                            playwright_headers={},
                            raw_headers=raw_headers,
                            raw_fetch_error=raw_err,
                        )
                        best = {
                            "url": current,
                            "status": 0,
                            "html": "",
                            "raw_html": raw_html,
                            "raw_http_status": raw_status,
                            "raw_redirect_history": raw_chain,
                            "raw_response_headers": raw_headers,
                            "redirect_history": [current],
                            "response_headers": {},
                            "crawl_status": "timeout",
                            "block_reason": goto_err,
                            "render_status": "partial",
                            "render_confidence": 0.0,
                            "stealth_used": True,
                            "profile_used": _profile_used_label(profile, js_on),
                            "js_dependency": False,
                            **_pw_debug_counts(js_errors, network_log),
                            **enriched_to,
                        }
                        break

                    adaptive.on_success(elapsed)

                    final_url = page.url
                    try:
                        normalized_final = normalize_url(final_url)
                    except ValueError:
                        normalized_final = current

                    status = int(resp.status) if resp else 0
                    headers = dict(resp.headers) if resp else {}
                    red_chain = _redirect_chain_from_response(resp) or [current, final_url]

                    st0, br0 = detect_blocked_generic(http_status=status, html="", response_headers=headers)
                    if st0 == "blocked":
                        last_block = (st0, br0)
                        if dbg:
                            dbg.extend_interactions(interaction_log)
                            dbg.extend_network(network_log + [{"type": "js_errors", "items": js_errors}])
                        if idx < len(profiles) - 1:
                            continue
                        enriched = enrich_crawl_page_record(
                            rendered_html="",
                            raw_html=raw_html,
                            final_effective_url=normalized_final,
                            raw_final_url=raw_final_norm,
                            playwright_status=status,
                            raw_http_status=raw_status,
                            playwright_headers=headers,
                            raw_headers=raw_headers,
                            raw_fetch_error=raw_err,
                        )
                        rvr = enriched.get("raw_vs_rendered")
                        if isinstance(rvr, dict):
                            rvr["playwright_skip_reason"] = "blocked_http_status"
                        best = {
                            "url": current,
                            "status": status,
                            "html": "",
                            "raw_html": raw_html,
                            "raw_http_status": raw_status,
                            "raw_redirect_history": raw_chain,
                            "raw_response_headers": raw_headers,
                            "redirect_history": red_chain,
                            "response_headers": headers,
                            "crawl_status": "blocked",
                            "block_reason": br0,
                            "render_status": "partial",
                            "render_confidence": 0.25,
                            "stealth_used": True,
                            "profile_used": _profile_used_label(profile, js_on),
                            "js_dependency": False,
                            **_pw_debug_counts(js_errors, network_log),
                            **enriched,
                        }
                        break

                    if status != 200 or not _is_html_response_pw(resp):
                        enriched = enrich_crawl_page_record(
                            rendered_html="",
                            raw_html=raw_html,
                            final_effective_url=normalized_final,
                            raw_final_url=raw_final_norm,
                            playwright_status=status,
                            raw_http_status=raw_status,
                            playwright_headers=headers,
                            raw_headers=raw_headers,
                            raw_fetch_error=raw_err,
                        )
                        rvr = enriched.get("raw_vs_rendered")
                        if isinstance(rvr, dict):
                            rvr["playwright_skip_reason"] = "non_200_or_non_html"
                        rs, rc = assess_partial_render("")
                        best = {
                            "url": current,
                            "status": status,
                            "html": "",
                            "raw_html": raw_html,
                            "raw_http_status": raw_status,
                            "raw_redirect_history": raw_chain,
                            "raw_response_headers": raw_headers,
                            "redirect_history": red_chain,
                            "response_headers": headers,
                            "crawl_status": "success",
                            "block_reason": None,
                            "render_status": rs,
                            "render_confidence": rc,
                            "stealth_used": True,
                            "profile_used": _profile_used_label(profile, js_on),
                            "js_dependency": False,
                            **_pw_debug_counts(js_errors, network_log),
                            **enriched,
                        }
                        if dbg:
                            dbg.extend_interactions(interaction_log)
                            dbg.extend_network(network_log + [{"type": "js_errors", "items": js_errors}])
                        break

                    try:
                        advanced_wait_after_navigation(page, interaction_log)
                        human_like_interaction(page, interaction_log)
                        scroll_lazy_pass(page, interaction_log)
                        time.sleep(random.uniform(0.35, 1.05) * _is)  # noqa: S311
                    except Exception as exc:
                        _LOGGER.debug("post-navigation interaction failed %s: %s", current, exc)
                        interaction_log.append({"action": "post_nav_error", "error": str(exc)[:300]})

                    rendered = page.content()
                    st_b, br_b = detect_blocked_generic(http_status=status, html=rendered, response_headers=headers)
                    rs, rc = assess_partial_render(rendered)
                    js_dep = _compute_js_dependency(raw_html, rendered)

                    if st_b == "blocked":
                        last_block = (st_b, br_b)
                        if dbg:
                            dbg.extend_interactions(interaction_log)
                            dbg.extend_network(network_log + [{"type": "js_errors", "items": js_errors}])
                        if idx < len(profiles) - 1:
                            continue
                        enriched = enrich_crawl_page_record(
                            rendered_html=rendered,
                            raw_html=raw_html,
                            final_effective_url=normalized_final,
                            raw_final_url=raw_final_norm,
                            playwright_status=status,
                            raw_http_status=raw_status,
                            playwright_headers=headers,
                            raw_headers=raw_headers,
                            raw_fetch_error=raw_err,
                        )
                        rvr = enriched.get("raw_vs_rendered")
                        if isinstance(rvr, dict):
                            rvr["playwright_skip_reason"] = "blocked_body_heuristic"
                        best = {
                            "url": normalized_final,
                            "status": status,
                            "html": rendered,
                            "raw_html": raw_html,
                            "raw_http_status": raw_status,
                            "raw_redirect_history": raw_chain,
                            "raw_response_headers": raw_headers,
                            "internal_links": [],
                            "redirect_history": red_chain,
                            "response_headers": headers,
                            "crawl_status": "blocked",
                            "block_reason": br_b,
                            "render_status": rs,
                            "render_confidence": rc,
                            "stealth_used": True,
                            "profile_used": _profile_used_label(profile, js_on),
                            "js_dependency": js_dep,
                            **_pw_debug_counts(js_errors, network_log),
                            **enriched,
                        }
                        break

                    enriched = enrich_crawl_page_record(
                        rendered_html=rendered,
                        raw_html=raw_html,
                        final_effective_url=normalized_final,
                        raw_final_url=raw_final_norm,
                        playwright_status=status,
                        raw_http_status=raw_status,
                        playwright_headers=headers,
                        raw_headers=raw_headers,
                        raw_fetch_error=raw_err,
                    )
                    summary = enriched.get("raw_vs_rendered") or {}
                    _log_crawl_page(
                        current,
                        pw_status=status,
                        raw_status=raw_status,
                        summary=summary,
                        indexable=(enriched.get("indexability") or {}).get("indexable"),
                    )

                    internal_links: list[str] = []
                    for link in _extract_links(normalized_final, rendered):
                        try:
                            nl = normalize_url(link)
                        except ValueError:
                            continue
                        if urlparse(nl).netloc != base_domain:
                            continue
                        internal_links.append(nl)
                        edges.append({"from": normalized_final, "to": nl})
                        if nl not in seen and nl not in visited:
                            seen.add(nl)
                            queue.append(nl)

                    best = {
                        "url": normalized_final,
                        "status": status,
                        "html": rendered,
                        "raw_html": raw_html,
                        "raw_http_status": raw_status,
                        "raw_redirect_history": raw_chain,
                        "raw_response_headers": raw_headers,
                        "internal_links": sorted(set(internal_links)),
                        "redirect_history": red_chain,
                        "response_headers": headers,
                        "crawl_status": "success",
                        "block_reason": None,
                        "render_status": rs,
                        "render_confidence": rc,
                        "stealth_used": True,
                        "profile_used": _profile_used_label(profile, js_on),
                        "js_dependency": js_dep,
                        **_pw_debug_counts(js_errors, network_log),
                        **enriched,
                    }
                    if dbg:
                        dbg.extend_interactions(interaction_log)
                        dbg.extend_network(network_log + [{"type": "js_errors", "items": js_errors}])
                    break

                finally:
                    try:
                        context.close()
                    except Exception:
                        pass

            if best is None:
                br = last_block[1] if last_block else "unknown"
                best = {
                    "url": current,
                    "status": 0,
                    "html": "",
                    "raw_html": raw_html,
                    "raw_http_status": raw_status,
                    "raw_redirect_history": raw_chain,
                    "raw_response_headers": raw_headers,
                    "redirect_history": [current],
                    "response_headers": {},
                    "crawl_status": "blocked",
                    "block_reason": br,
                    "render_status": "partial",
                    "render_confidence": 0.2,
                    "stealth_used": True,
                    "profile_used": "desktop_nojs",
                    "js_dependency": False,
                    **_pw_debug_counts([], []),
                }
                enriched = enrich_crawl_page_record(
                    rendered_html="",
                    raw_html=raw_html,
                    final_effective_url=current,
                    raw_final_url=raw_final_norm,
                    playwright_status=0,
                    raw_http_status=raw_status,
                    playwright_headers={},
                    raw_headers=raw_headers,
                    raw_fetch_error=raw_err,
                )
                best.update(enriched)

            if best:
                pages.append(best)

            if dbg and dbg_dir:
                dbg.flush(dbg_dir)

    finally:
        if own_pw:
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    return {"pages": pages, "total": len(pages), "edges": edges, "domain": base_domain}
