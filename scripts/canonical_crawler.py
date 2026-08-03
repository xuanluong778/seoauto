"""
Lightweight HTTP fetch of a declared canonical target (no recursion, no Playwright).

Used to validate indexability, title, and lexical similarity vs the source document.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from app.services.indexability import assess_indexability
from app.services.js_analysis import compute_text_similarity
from app.services.raw_html_fetch import fetch_raw_html
from app.services.seo_normalize import normalize_url_safe


def _norm(u: str) -> str:
    return (normalize_url_safe(u) if u else "").strip().lower().rstrip("/")


def _extract_title(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        return (t.get_text(" ", strip=True) if t else "")[:500]
    except Exception:
        return ""


def _extract_canonical_href(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("link", rel=True):
            rels = [str(x).lower() for x in (link.get("rel") or [])]
            if "canonical" in rels and link.get("href"):
                return str(link.get("href")).strip()
    except Exception:
        pass
    return ""


def crawl_canonical_target(
    url: str,
    canonical_url: str,
    *,
    source_html: str = "",
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """
    Fetch ``canonical_url`` once. Compare to source page ``url`` / ``source_html``.

    Returns keys aligned with the audit layer: status, indexability, title, similarity, chain validity.
    """
    src = _norm(url or "")
    canon = _norm(canonical_url or "")

    empty: dict[str, Any] = {
        "fetched": False,
        "target_status": None,
        "target_indexable": True,
        "target_title": "",
        "similarity_score": None,
        "canonical_chain_valid": True,
        "target_canonical_href": None,
        "canonical_points_back_to_source": False,
        "fetch_error": None,
    }

    if not canon or canon == src:
        return empty

    pkg = fetch_raw_html(canonical_url.strip(), timeout_seconds=timeout_seconds)
    st = int(pkg.get("status") or 0)
    thtml = str(pkg.get("html") or "")
    err = pkg.get("error")

    out = dict(empty)
    out["fetched"] = True
    out["target_status"] = st
    out["fetch_error"] = err

    if err or st == 0:
        out["target_indexable"] = False
        out["canonical_chain_valid"] = False
        out["similarity_score"] = 0.0
        return out

    hdrs = dict(pkg.get("response_headers") or {})
    idx = assess_indexability(thtml, hdrs, st)
    out["target_indexable"] = bool(idx.get("indexable"))
    out["target_title"] = _extract_title(thtml)
    t_canon = _extract_canonical_href(thtml)
    out["target_canonical_href"] = t_canon or None

    sim_pack = compute_text_similarity(source_html or "", thtml)
    out["similarity_score"] = float(sim_pack.get("text_similarity_score") or 0.0)

    tcn = _norm(t_canon)
    if tcn == src:
        out["canonical_points_back_to_source"] = True
        out["canonical_chain_valid"] = False
    elif st >= 400:
        out["canonical_chain_valid"] = False
    else:
        out["canonical_chain_valid"] = True

    return out
