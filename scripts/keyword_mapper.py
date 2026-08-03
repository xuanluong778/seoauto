"""
Map keyword clusters to on-site URLs using title/H1/body overlap + optional ranking scores.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.serp_fetcher import normalize_serp_url


def _page_text_bundle(page: dict[str, Any]) -> tuple[str, str]:
    html = str(page.get("html") or "")[:60000]
    title = ""
    h1 = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        if t:
            title = t.get_text(" ", strip=True)
        h = soup.find("h1")
        if h:
            h1 = h.get_text(" ", strip=True)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body = soup.get_text(" ", strip=True)[:8000]
    except Exception:
        body = re.sub(r"<[^>]+>", " ", html)[:8000]
    return f"{title} {h1}".lower(), body.lower()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", s.lower()) if len(t) > 2}


def map_clusters_to_urls(
    clusters: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    *,
    ranking_by_url: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    For each cluster, pick the URL with best combined lexical overlap + optional ranking boost.
    """
    ranking_by_url = ranking_by_url or {}
    page_rows: list[tuple[str, str, str, set[str]]] = []
    for p in pages:
        u = str(p.get("url") or "")
        if not u or int(p.get("status") or 0) != 200:
            continue
        head, body = _page_text_bundle(p)
        bag = _tokens(head + " " + body[:4000])
        page_rows.append((u, head, body, bag))

    out: list[dict[str, Any]] = []
    for cl in clusters:
        cid = str(cl.get("cluster_id") or "")
        kws = cl.get("keywords") or []
        cluster_terms: set[str] = set()
        for r in kws:
            cluster_terms |= _tokens(str(r.get("keyword") or ""))
        dominant = set(cl.get("explain", {}).get("dominant_urls") or [])
        best_url = ""
        best_score = 0.0
        explain_parts: list[str] = []
        for url, head, body, bag in page_rows:
            head_t = _tokens(head)
            jc = 0.55 * _jaccard(cluster_terms, bag) + 0.25 * _jaccard(cluster_terms, head_t)
            rk = float(ranking_by_url.get(url) or 0.0) / 100.0
            score = min(1.0, jc + 0.12 * rk)
            if dominant:
                nu = normalize_serp_url(url)
                if nu in dominant:
                    score = min(1.0, score + 0.24)
            if score > best_score:
                best_score = score
                best_url = url
                explain_parts = [
                    f"jaccard_body={round(_jaccard(cluster_terms, bag), 3)}",
                    f"jaccard_headings={round(_jaccard(cluster_terms, head_t), 3)}",
                    f"ranking_boost={round(rk, 3)}",
                ]
        out.append(
            {
                "cluster_id": cid,
                "target_url": best_url or "",
                "match_score": round(best_score, 4),
                "explain": {"signals": explain_parts},
            }
        )
    return out


def build_keyword_signals_by_url(
    clusters: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    URL → signals merged into ranking ``topical_signals``: volume coverage + cluster relevance.
    """
    cluster_by_id = {str(c.get("cluster_id")): c for c in clusters}
    url_to_clusters: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for m in mappings:
        u = str(m.get("target_url") or "")
        if not u:
            continue
        cid = str(m.get("cluster_id") or "")
        cl = cluster_by_id.get(cid) or {}
        vol = float(cl.get("total_search_volume") or 0)
        ms = float(m.get("match_score") or 0)
        url_to_clusters.setdefault(u, []).append((ms * (1.0 + min(vol, 200000) / 200000.0), cl))

    out: dict[str, dict[str, float]] = {}
    for url, pairs in url_to_clusters.items():
        pairs.sort(key=lambda x: -x[0])
        top_ms, top_cl = pairs[0]
        vol = float(top_cl.get("total_search_volume") or 0)
        vol_n = min(1.0, (vol ** 0.35) / 120.0)
        rel = min(1.0, top_ms)
        out[url] = {
            "keyword_volume_coverage": round(vol_n, 4),
            "keyword_cluster_relevance": round(rel, 4),
        }
    return out
