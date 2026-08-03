"""
Directed internal link graph from a crawl (rendered HTML + optional ``internal_links``).

Used for PageRank, orphan detection, and crawl depth from entry URL(s).
"""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urlparse

from app.services.crawler import _extract_links, normalize_url


def _host_key(netloc: str) -> str:
    h = (netloc or "").strip().lower()
    return h[4:] if h.startswith("www.") else h


def _safe_normalize(raw: str) -> str | None:
    try:
        return normalize_url(raw.strip())
    except Exception:
        return None


def _page_host_key(page: dict[str, Any]) -> str:
    base = (page.get("url") or "").strip()
    bn = _safe_normalize(base) or base
    try:
        return _host_key(urlparse(bn).netloc)
    except Exception:
        return ""


def _outgoing_from_page(page: dict[str, Any], node_set: set[str]) -> list[str]:
    """Same-host-as-page targets that exist in ``node_set`` (induced crawl graph)."""
    host_k = _page_host_key(page)
    if not host_k:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(u: str) -> None:
        nu = _safe_normalize(u)
        if not nu or nu in seen:
            return
        try:
            p = urlparse(nu)
        except Exception:
            return
        if _host_key(p.netloc) != host_k:
            return
        if nu not in node_set:
            return
        seen.add(nu)
        out.append(nu)

    for href in page.get("internal_links") or []:
        if isinstance(href, str):
            add(href)

    html = page.get("html")
    base = (page.get("url") or "").strip()
    if isinstance(html, str) and html.strip() and base:
        try:
            base_n = normalize_url(base)
        except Exception:
            base_n = base
        for href in _extract_links(base_n, html):
            add(href)

    return out


def build_link_graph(
    pages: list[dict[str, Any]],
    *,
    entry_urls: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build a directed graph on **crawled** URLs only (induced subgraph).

    Returns:
        ``nodes``: ``{ url: { "outgoing": [...], "incoming": [...] } }``
        ``orphan_urls``: crawled URLs with no incoming internal edge (excluding entry URLs)
        ``crawl_depth``: BFS hop count from first resolvable entry URL; ``None`` if unreachable
        ``entry_urls_normalized``: resolved list used for BFS roots
    """
    normalized_pages: list[tuple[str, dict[str, Any]]] = []
    for p in pages:
        u = (p.get("url") or "").strip()
        nu = _safe_normalize(u)
        if nu:
            normalized_pages.append((nu, p))

    node_set = {u for u, _ in normalized_pages}
    if not node_set:
        return {
            "nodes": {},
            "orphan_urls": [],
            "crawl_depth": {},
            "entry_urls_normalized": [],
        }

    nodes: dict[str, dict[str, list[str]]] = {u: {"outgoing": [], "incoming": []} for u in node_set}
    for u, p in normalized_pages:
        nodes[u]["outgoing"] = _outgoing_from_page(p, node_set)

    for u, data in nodes.items():
        for v in data["outgoing"]:
            if v in nodes:
                nodes[v]["incoming"].append(u)

    roots: list[str] = []
    if entry_urls:
        for e in entry_urls:
            ne = _safe_normalize(e)
            if ne and ne in node_set:
                roots.append(ne)
    if not roots and normalized_pages:
        roots.append(normalized_pages[0][0])

    entry_set = set(roots)
    orphan_urls = sorted(
        u for u in node_set if not nodes[u]["incoming"] and u not in entry_set
    )

    crawl_depth: dict[str, int | None] = {u: None for u in node_set}
    q: deque[tuple[str, int]] = deque()
    for r in roots:
        if r in node_set:
            crawl_depth[r] = 0
            q.append((r, 0))
    while q:
        cur, d = q.popleft()
        for nxt in nodes[cur]["outgoing"]:
            if nxt not in node_set:
                continue
            nd = d + 1
            old = crawl_depth.get(nxt)
            if old is None or nd < old:
                crawl_depth[nxt] = nd
                q.append((nxt, nd))

    return {
        "nodes": nodes,
        "orphan_urls": orphan_urls,
        "crawl_depth": crawl_depth,
        "entry_urls_normalized": roots,
    }


# --- Topic-aware extensions (anchor relevance, cluster authority flow) ---
from app.services.topic_link_authority import (  # noqa: E402
    collect_weighted_internal_edges,
    compute_edge_relevance_weights,
    evaluate_internal_authority_flow,
)
