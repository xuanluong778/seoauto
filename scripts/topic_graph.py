"""
Entity / topic graph from on-page signals (title, H1–H2, main content).

Uses noun-phrase style n-grams + weighted co-occurrence — not raw keyword density.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from bs4 import BeautifulSoup, Tag

_STOP = frozenset(
    """
    a an the and or but if for to of in on at by from as is was are were been be
    has have had do does did will would could should may might must can with into over
    under your our their its this that these those what which who how all each few
    more most other some such no not only same so than too very just also about
    và hoặc thì là có được các những một này đó cho với trong từ về như không
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9\u00c0-\u024f]{2,}", re.I)


def _tokens(text: str, cap: int = 600) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(text or ""):
        t = m.group(0).lower()
        if len(t) < 2 or t in _STOP:
            continue
        out.append(t)
        if len(out) >= cap:
            break
    return out


def _strip_chrome(soup: BeautifulSoup) -> None:
    for sel in ("nav", "footer", "header", "aside", "form", "noscript", "script", "style"):
        for el in soup.find_all(sel):
            el.decompose()
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        role = (el.get("role") or "").lower()
        if role in ("navigation", "contentinfo", "banner", "complementary"):
            el.decompose()


def _main_text(soup: BeautifulSoup) -> str:
    _strip_chrome(soup)
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
    if main:
        return main.get_text(" ", strip=True)
    body = soup.find("body")
    if body:
        return body.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def _phrases_from_tokens(tokens: list[str], *, min_len: int = 2, max_n: int = 3) -> list[tuple[str, float]]:
    """Return (phrase, weight) for n-grams; unigrams only if repeated in window."""
    out: list[tuple[str, float]] = []
    n = len(tokens)
    for i in range(n):
        for L in range(min_len, min(max_n, n - i) + 1):
            chunk = tokens[i : i + L]
            if len(chunk) < min_len:
                continue
            phrase = " ".join(chunk)
            if len(phrase) < 5:
                continue
            w = 1.0 + 0.35 * (L - 2)  # longer phrases slightly more specific
            out.append((phrase, w))
    return out


def extract_topic_graph(html: str, *, max_nodes: int = 48, max_edges: int = 120) -> dict[str, Any]:
    """
    Build a topic/entity graph for one document.

    Returns ``nodes`` (topic + importance 0–1) and ``edges`` (from, to, weight 0–1).
    """
    raw = html if isinstance(html, str) else ""
    if not raw.strip():
        return {"nodes": [], "edges": [], "explain": "empty_html"}

    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        soup = BeautifulSoup("", "html.parser")

    title = ""
    t_el = soup.find("title")
    if t_el:
        title = t_el.get_text(" ", strip=True)
    h1 = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h1")[:4])
    h2 = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h2")[:16])

    try:
        soup2 = BeautifulSoup(raw, "html.parser")
    except Exception:
        soup2 = BeautifulSoup("", "html.parser")
    body = _main_text(soup2)

    head_toks = _tokens(f"{title} {h1} {h2}", 200)
    body_toks = _tokens(body, 500)

    node_weight: defaultdict[str, float] = defaultdict(float)
    zone_w = {"title_h": 3.2, "body": 1.0}

    for ph, w in _phrases_from_tokens(head_toks, min_len=2, max_n=3):
        node_weight[ph] += w * zone_w["title_h"]
    for tok in head_toks[:24]:
        if len(tok) >= 4:
            node_weight[tok] += 0.85 * zone_w["title_h"]

    for ph, w in _phrases_from_tokens(body_toks, min_len=2, max_n=3):
        node_weight[ph] += w * zone_w["body"]
    for tok in body_toks[:40]:
        if len(tok) >= 5:
            node_weight[tok] += 0.25 * zone_w["body"]

    if not node_weight:
        return {"nodes": [], "edges": [], "explain": "no_entities_extracted"}

    mx = max(node_weight.values()) or 1.0
    ranked = sorted(node_weight.items(), key=lambda x: -x[1])[:max_nodes]
    nodes = [{"topic": k, "importance": round(min(1.0, v / mx), 4)} for k, v in ranked]

    topic_set = {k for k, _ in ranked}
    # Co-occurrence in sliding windows over body (+ heads)
    stream = head_toks + ["|"] + body_toks
    edge_acc: defaultdict[tuple[str, str], float] = defaultdict(float)
    win = 10
    for i in range(len(stream)):
        if stream[i] == "|":
            continue
        slice_toks = []
        for j in range(i, min(len(stream), i + win)):
            if stream[j] == "|":
                break
            slice_toks.append(stream[j])
        phrases_i = {p for p in topic_set if p in " ".join(slice_toks)}
        if len(slice_toks) < 3:
            continue
        # pair frequent topics that appear in same window as bigrams from slice
        local_phrases: list[str] = []
        for L in (2, 3):
            for k in range(len(slice_toks) - L + 1):
                cand = " ".join(slice_toks[k : k + L])
                if cand in topic_set:
                    local_phrases.append(cand)
        for a in local_phrases:
            for b in local_phrases:
                if a >= b:
                    continue
                edge_acc[(a, b)] += 1.0

    if not edge_acc:
        # fallback: connect top node to next tiers
        topn = [k for k, _ in ranked[:8]]
        for i in range(len(topn) - 1):
            edge_acc[(topn[i], topn[i + 1])] += 0.5

    emax = max(edge_acc.values()) or 1.0
    edges_raw = sorted(edge_acc.items(), key=lambda x: -x[1])[:max_edges]
    edges = [
        {"from": a, "to": b, "weight": round(min(1.0, w / emax), 4)} for (a, b), w in edges_raw
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "explain": "noun_phrase_and_cooccurrence_window",
        "source_zones": {"title_h1_h2_tokens": len(head_toks), "body_tokens": len(body_toks)},
    }


def merge_cluster_topic_graphs(per_url_graphs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graphs from multiple URLs (importance = max, edge = sum normalized)."""
    nw: defaultdict[str, float] = defaultdict(float)
    ew: defaultdict[tuple[str, str], float] = defaultdict(float)
    for g in per_url_graphs:
        for n in g.get("nodes") or []:
            t = str(n.get("topic") or "")
            if t:
                nw[t] = max(nw[t], float(n.get("importance") or 0))
        for e in g.get("edges") or []:
            a, b = str(e.get("from") or ""), str(e.get("to") or "")
            if a and b and a != b:
                key = (a, b) if a < b else (b, a)
                ew[key] += float(e.get("weight") or 0)

    if not nw:
        return {"nodes": [], "edges": [], "explain": "empty_merge"}

    mx = max(nw.values()) or 1.0
    nodes = sorted(
        ({"topic": k, "importance": round(min(1.0, v / mx), 4)} for k, v in nw.items()),
        key=lambda x: -x["importance"],
    )[:64]

    em = max(ew.values()) or 1.0
    edges = [
        {"from": k[0], "to": k[1], "weight": round(min(1.0, v / em), 4)}
        for k, v in sorted(ew.items(), key=lambda x: -x[1])[:160]
    ]
    return {"nodes": nodes, "edges": edges, "explain": "cluster_merge_max_sum"}


def _map_topic_to_canonical(topic: str, entity_groups: list[dict[str, Any]]) -> str:
    from app.services.topic_entity_resolver import normalize_entity_phrase, similarity_phrase_to_canonical

    if not entity_groups:
        return normalize_entity_phrase(topic)
    best = normalize_entity_phrase(topic)
    best_s = 0.0
    for g in entity_groups:
        c = str(g.get("canonical_entity") or "")
        if not c:
            continue
        s = similarity_phrase_to_canonical(topic, c)
        if s > best_s:
            best_s = s
            best = c
    if best_s < 0.22:
        return normalize_entity_phrase(topic)
    return best


def _semantic_edge_boost(
    a: str,
    b: str,
    *,
    use_embeddings: bool,
) -> float:
    if not use_embeddings:
        return 0.0
    try:
        import numpy as np

        from app.services.semantic_embedding import embed_keywords

        vecs = embed_keywords([a, b])
        va, vb = vecs.get(a), vecs.get(b)
        if va is None or vb is None:
            return 0.0
        return max(0.0, float(np.dot(va, vb)) * 0.15)
    except Exception:
        return 0.0


def build_resolved_topic_graph_v2(
    raw_cluster_graph: dict[str, Any],
    entity_groups: list[dict[str, Any]],
    *,
    per_url_graphs: list[dict[str, Any]] | None = None,
    use_embeddings: bool | None = None,
) -> dict[str, Any]:
    """
    Merge raw graph nodes into canonical entities; reweight edges with optional semantic boost.

    Adds ``entity_importance_score`` (TF-IDF-style + position proxy) and ``entity_centrality_score``.
    """
    import os

    if use_embeddings is None:
        use_embeddings = os.getenv("TOPICAL_USE_EMBEDDINGS", "0").lower() in ("1", "true", "yes")

    nw: defaultdict[str, float] = defaultdict(float)
    for n in raw_cluster_graph.get("nodes") or []:
        t = str(n.get("topic") or "")
        if not t:
            continue
        c = _map_topic_to_canonical(t, entity_groups)
        nw[c] += float(n.get("importance") or 0)

    # Document frequency across pages (how many URL-level graphs mention raw topic mapped to c)
    df: defaultdict[str, int] = defaultdict(int)
    n_docs = max(1, len(per_url_graphs or []))
    if per_url_graphs:
        for g in per_url_graphs:
            seen_c: set[str] = set()
            for n in g.get("nodes") or []:
                t = str(n.get("topic") or "")
                if not t:
                    continue
                c = _map_topic_to_canonical(t, entity_groups)
                if c not in seen_c:
                    seen_c.add(c)
                    df[c] += 1
    else:
        for c in nw:
            df[c] = 1

    if not nw:
        return {
            "nodes": [],
            "edges": [],
            "explain": "entity_resolved_v2_no_nodes",
            "entity_groups_count": len(entity_groups),
        }

    idf = {c: math.log1p(n_docs / (1 + df.get(c, 1))) for c in nw}
    mxw = max(nw.values()) or 1.0
    nodes_out: list[dict[str, Any]] = []
    for c, w in sorted(nw.items(), key=lambda x: -x[1])[:56]:
        tfidf = (w / mxw) * min(1.2, idf.get(c, 0.5))
        nodes_out.append(
            {
                "topic": c,
                "importance": round(min(1.0, w / mxw), 4),
                "entity_importance_score": round(min(1.0, tfidf), 4),
                "entity_centrality_score": 0.0,  # filled below
            }
        )

    canon_set = {n["topic"] for n in nodes_out}
    ew: defaultdict[tuple[str, str], float] = defaultdict(float)
    for e in raw_cluster_graph.get("edges") or []:
        a0, b0 = str(e.get("from") or ""), str(e.get("to") or "")
        if not a0 or not b0:
            continue
        a = _map_topic_to_canonical(a0, entity_groups)
        b = _map_topic_to_canonical(b0, entity_groups)
        if a == b or a not in canon_set or b not in canon_set:
            continue
        key = (a, b) if a < b else (b, a)
        base = float(e.get("weight") or 0.5)
        base += _semantic_edge_boost(a, b, use_embeddings=use_embeddings)
        ew[key] += base

    em = max(ew.values()) if ew else 1.0
    edges_out = [
        {"from": k[0], "to": k[1], "weight": round(min(1.0, v / em), 4)}
        for k, v in sorted(ew.items(), key=lambda x: -x[1])[:140]
    ]

    # Centrality: weighted degree on canonical graph
    cent: defaultdict[str, float] = defaultdict(float)
    for e in edges_out:
        w = float(e.get("weight") or 0)
        cent[str(e.get("from") or "")] += w
        cent[str(e.get("to") or "")] += w
    mx_c = max(cent.values()) if cent else 1.0
    for n in nodes_out:
        t = n["topic"]
        n["entity_centrality_score"] = round(min(1.0, cent.get(t, 0.0) / mx_c), 4)

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "explain": "entity_resolved_v2_tfidf_centrality",
        "entity_groups_count": len(entity_groups),
    }
