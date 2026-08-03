"""
Canonical URL resolution: declared <link rel=canonical> vs effective URL after redirects.

All URL equality uses ``normalize_url`` where possible for stable host/path comparison.
"""

from __future__ import annotations

from typing import Any
from bs4 import BeautifulSoup

from app.services.seo_normalize import normalize_canonical, normalize_text


def _normalize_url(value: str) -> str:
    from app.services.crawler import normalize_url

    try:
        return normalize_url(value.strip()) if value else ""
    except ValueError:
        return (value or "").strip()


def _rel_has(rel_val: str | list | None, token: str) -> bool:
    if not rel_val:
        return False
    if isinstance(rel_val, list):
        parts = {str(p).strip().lower() for p in rel_val if p}
        return token.lower() in parts
    parts = {p.strip().lower() for p in str(rel_val).split() if p.strip()}
    return token.lower() in parts


def extract_declared_canonical_href(html: str, _base_url: str = "") -> str:
    """Raw href from DOM (before resolution to absolute)."""
    if not html or not isinstance(html, str):
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("link"):
        rel = link.get("rel")
        if _rel_has(rel, "canonical") and link.get("href"):
            return normalize_text(str(link.get("href") or ""))
    return ""


def resolve_canonical_signals(
    rendered_html: str,
    final_effective_url: str,
    *,
    raw_final_url_after_redirects: str | None = None,
) -> dict[str, Any]:
    """
    ``final_effective_url``: normalized URL of the document after Playwright navigation.

    Returns canonical_url (normalized absolute or null), self-reference flags, mismatch vs effective URL.
    """
    fe = (final_effective_url or "").strip()
    fe_n = _normalize_url(fe) if fe else ""

    raw_href = extract_declared_canonical_href(rendered_html or "", fe_n or fe)
    canonical_url: str | None = None
    if raw_href:
        resolved = normalize_canonical(raw_href, fe_n or fe)
        canonical_url = resolved if resolved else None
        if canonical_url:
            canonical_url = _normalize_url(canonical_url)

    raw_final_n = (
        _normalize_url(raw_final_url_after_redirects.strip())
        if raw_final_url_after_redirects and raw_final_url_after_redirects.strip()
        else ""
    )

    if canonical_url:
        is_self = canonical_url == fe_n
        canonical_mismatch = canonical_url != fe_n
    else:
        is_self = True
        canonical_mismatch = False

    return {
        "canonical_url": canonical_url,
        "final_effective_url": fe_n or fe,
        "is_canonical_self": is_self,
        "canonical_mismatch": canonical_mismatch,
        "raw_http_final_url": raw_final_n or None,
    }
