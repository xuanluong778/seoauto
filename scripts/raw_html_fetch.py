"""Fetch initial HTML over HTTP (no JS) — same bot identity as Playwright crawl."""

from __future__ import annotations

import logging
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)


def fetch_raw_html(
    url: str,
    *,
    timeout_seconds: float = 25.0,
    user_agent: str | None = None,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    GET ``url`` with redirects enabled. No JavaScript execution.

    Returns:
        html, status, final_url, redirect_history, response_headers, error (optional).
    """
    headers = {"User-Agent": (user_agent or GOOGLEBOT_UA).strip() or GOOGLEBOT_UA}
    out: dict[str, Any] = {
        "html": "",
        "status": 0,
        "final_url": url,
        "redirect_history": [url],
        "response_headers": {},
        "error": None,
    }
    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=True,
            proxies=proxies,
        )
    except requests.exceptions.Timeout as exc:
        out["error"] = f"timeout: {exc}"
        _LOGGER.debug("raw fetch timeout %s", url)
        return out
    except requests.exceptions.RequestException as exc:
        out["error"] = str(exc)
        _LOGGER.debug("raw fetch failed %s: %s", url, exc)
        return out

    chain = [h.url for h in r.history] + [r.url]
    out["html"] = r.text or ""
    out["status"] = int(r.status_code)
    out["final_url"] = r.url or url
    out["redirect_history"] = chain or [url]
    try:
        out["response_headers"] = {k: v for k, v in r.headers.items()}
    except Exception:
        out["response_headers"] = {}
    return out
