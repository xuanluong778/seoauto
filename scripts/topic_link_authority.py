"""
Internal link authority flow: anchor relevance + topic-personalized PageRank on cluster subgraph.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.crawler import _extract_links, normalize_url
from app.services.internal_link_graph import _host_key, _safe_normalize


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9\u00c0-\u024f]{3,}", (s or "").lower()) if len(t) > 2}


def _anchor_relevance(anchor: str, target_url: str, target_html: str) -> float:
    """0–1: anchor text vs target page title/H1/body bag."""
    if not anchor.strip():
        return 0.25
    a = _tokens(anchor)
    if not a:
        return 0.2
    try:
        soup = BeautifulSoup(target_html or "", "html.parser")
        title = soup.find("title")
        h1 = soup.find("h1")
        blob = ""
        if title:
            blob += title.get_text(" ", strip=True) + " "
        if h1:
            blob += h1.get_text(" ", strip=True) + " "
        blob += soup.get_text(" ", strip=True)[:4000]
    except Exception:
        blob = target_html or ""
    b = _tokens(blob)
    if not b:
        path = (urlparse(target_url).path or "").replace("/", " ")
        b = _tokens(path)
    inter = len(a & b)
    return round(min(1.0, inter / max(3, len(a) * 0.6)), 4)


def collect_weighted_internal_edges(
    pages: list[dict[str, Any]],
    *,
    node_set: set[str],
) -> list[dict[str, Any]]:
    """
    For each page, extract internal links with anchor text; keep edges inside ``node_set``.
    """
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for p in pages:
        src = _safe_normalize(str(p.get("url") or ""))
        if not src or src not in node_set:
            continue
        html = str(p.get("html") or "")
        if not html.strip():
            continue
        host_k = _host_key(urlparse(src).netloc)
        try:
            base_n = normalize_url(src)
        except Exception:
            base_n = src
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            soup = BeautifulSoup("", "html.parser")
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if href.startswith("/"):
                href = f"{urlparse(base_n).scheme}://{urlparse(base_n).netloc}{href}"
            nu = _safe_normalize(href)
            if not nu or nu not in node_set or nu == src:
                continue
            try:
                if _host_key(urlparse(nu).netloc) != host_k:
                    continue
            except Exception:
                continue
            anchor = a.get_text(" ", strip=True)[:180]
            key = (src, nu)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": src, "to": nu, "anchor": anchor})
        for href in _extract_links(base_n, html):
            nu = _safe_normalize(href)
            if not nu or nu not in node_set or nu == src:
                continue
            try:
                if _host_key(urlparse(nu).netloc) != host_k:
                    continue
            except Exception:
                continue
            key = (src, nu)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": src, "to": nu, "anchor": ""})
    return edges


def compute_edge_relevance_weights(
    edges: list[dict[str, Any]],
    pages_by_url: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for e in edges:
        u, v = str(e.get("from") or ""), str(e.get("to") or "")
        if not u or not v:
            continue
        tgt = pages_by_url.get(v) or {}
        html = str(tgt.get("html") or "")
        rel = _anchor_relevance(str(e.get("anchor") or ""), v, html)
        out[(u, v)] = max(out.get((u, v), 0.0), rel)
    return out


def build_cluster_subgraph(cluster_urls: set[str], full_graph: dict[str, Any]) -> dict[str, Any]:
    """Induced directed graph on cluster URLs using full graph edges."""
    nodes_f = dict(full_graph.get("nodes") or {})
    sub: dict[str, dict[str, list[str]]] = {u: {"outgoing": [], "incoming": []} for u in cluster_urls if u in nodes_f}
    for u in list(sub.keys()):
        for v in nodes_f.get(u, {}).get("outgoing") or []:
            if v in sub and v != u:
                sub[u]["outgoing"].append(v)
                sub[v]["incoming"].append(u)
    return {"nodes": sub, "orphan_urls": [], "crawl_depth": {}, "entry_urls_normalized": []}


def compute_topic_personalized_pagerank(
    subgraph: dict[str, Any],
    *,
    teleport_bias: dict[str, float] | None = None,
    damping: float = 0.88,
    max_iter: int = 60,
    tol: float = 1e-5,
) -> dict[str, float]:
    """PageRank on subgraph with optional teleport bias toward ``teleport_bias`` URLs."""
    nodes_dict: dict[str, dict[str, list[str]]] = dict(subgraph.get("nodes") or {})
    urls = sorted(nodes_dict.keys())
    n = len(urls)
    if n == 0:
        return {}
    if n == 1:
        return {urls[0]: 1.0}
    idx = {u: i for i, u in enumerate(urls)}
    out_adj: list[list[int]] = []
    for u in urls:
        outs = nodes_dict[u].get("outgoing") or []
        out_adj.append([idx[v] for v in outs if v in idx])

    pref = [0.0] * n
    if teleport_bias:
        s = sum(max(0.0, float(teleport_bias.get(u, 0.0))) for u in urls)
        if s > 1e-9:
            for u in urls:
                pref[idx[u]] = max(0.0, float(teleport_bias.get(u, 0.0))) / s
        else:
            pref = [1.0 / n] * n
    else:
        pref = [1.0 / n] * n

    pr = [1.0 / n] * n
    base = [(1.0 - damping) * p for p in pref]

    for _ in range(max_iter):
        new = list(base)
        dangling_mass = 0.0
        for i, targets in enumerate(out_adj):
            share = damping * pr[i]
            if not targets:
                dangling_mass += share
            else:
                w = share / len(targets)
                for j in targets:
                    new[j] += w
        if dangling_mass > 0:
            for i in range(n):
                new[i] += damping * dangling_mass * pref[i]
        delta = sum(abs(new[i] - pr[i]) for i in range(n))
        pr = new
        if delta < tol:
            break

    mn, mx = min(pr), max(pr)
    span = mx - mn
    if span <= 1e-12:
        return {urls[i]: 1.0 / n for i in range(n)}
    return {urls[i]: (pr[i] - mn) / span for i in range(n)}


def evaluate_internal_authority_flow(
    cluster: dict[str, Any],
    *,
    full_graph: dict[str, Any],
    pages_by_url: dict[str, dict[str, Any]],
    global_pagerank: dict[str, float],
) -> dict[str, Any]:
    """
    Returns ``authority_flow_score`` 0–1, ``weak_pages``, ``topic_pr`` (subset), ``edge_relevance_avg``.
    """
    urls = [str(u) for u in (cluster.get("pages") or []) if u]
    if not urls:
        return {
            "topic": str(cluster.get("topic_label") or ""),
            "authority_flow_score": 0.0,
            "weak_pages": [],
            "explain": "empty_cluster",
        }
    node_set = set(urls)
    edges = collect_weighted_internal_edges(list(pages_by_url.values()), node_set=node_set)
    rel_w = compute_edge_relevance_weights(edges, pages_by_url)
    avg_rel = sum(rel_w.values()) / max(1, len(rel_w))

    sub = build_cluster_subgraph(set(urls), full_graph)
    bias = {u: 1.0 + 2.5 * float(global_pagerank.get(u) or 0.0) for u in urls}
    topic_pr = compute_topic_personalized_pagerank(sub, teleport_bias=bias)

    # Flow score: mean topic PR + edge relevance + global PR mass inside cluster
    pr_vals = [float(topic_pr.get(u) or 0.0) for u in urls]
    g_vals = [float(global_pagerank.get(u) or 0.0) for u in urls]
    flow = 0.5 * (sum(pr_vals) / max(1, len(pr_vals))) + 0.35 * min(1.0, avg_rel * 1.15) + 0.15 * (
        sum(g_vals) / max(1, len(g_vals))
    )
    flow = round(max(0.0, min(1.0, flow)), 4)

    ranked = sorted(urls, key=lambda u: float(topic_pr.get(u) or 0.0) + float(global_pagerank.get(u) or 0.0) * 0.35)
    weak_pages = ranked[: max(1, min(4, len(urls) // 3))] if flow < 0.55 else ranked[:1]

    return {
        "topic": str(cluster.get("topic_label") or ""),
        "authority_flow_score": flow,
        "weak_pages": weak_pages,
        "topic_pagerank": {u: round(float(topic_pr.get(u) or 0.0), 4) for u in urls},
        "edge_relevance_avg": round(float(avg_rel), 4),
        "internal_weighted_edges": len(rel_w),
        "explain": "Subgraph personalized PageRank + anchor–target token overlap on internal edges.",
    }
