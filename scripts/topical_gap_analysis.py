"""
SERP-aligned topical gap: compare cluster footprint vs organic leaders (optional live SERP).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from app.services.topic_graph import extract_topic_graph, merge_cluster_topic_graphs


def _serp_hints_from_snapshot(serp_results: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    """Entity-like n-grams from titles/snippets."""
    blob = []
    for r in serp_results[:12]:
        blob.append(str(r.get("title") or ""))
        blob.append(str(r.get("snippet") or ""))
    text = " ".join(blob).lower()
    toks = [t for t in re.findall(r"[a-z0-9]{3,}", text) if len(t) > 2]
    ng: list[str] = []
    for i in range(len(toks) - 1):
        ng.append(f"{toks[i]} {toks[i + 1]}")
    freq: dict[str, int] = {}
    for g in ng:
        if len(g) > 6:
            freq[g] = freq.get(g, 0) + 1
    top = [k for k, _ in sorted(freq.items(), key=lambda x: -x[1])[:20]]
    return top, {"organic_results_used": len(serp_results), "hint_count": len(top)}


def _infer_your_site_profile(
    urls: list[str],
    pages_by_url: dict[str, dict[str, Any]],
    topics_by_url: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Heuristic dominant on-site content type + format for cluster URLs."""
    types: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    intents: Counter[str] = Counter()
    from app.services.search_intent import classify_search_intent

    for u in urls:
        p = pages_by_url.get(u) or {}
        path = ""
        try:
            path = (urlparse(u).path or "").lower()
        except Exception:
            path = ""
        html = str(p.get("html") or "").lower()
        if "/product" in path or "add to cart" in html or "woocommerce" in html:
            types["ecommerce"] += 1
        elif re.search(r"/(blog|news|article|post|learn)/", path):
            types["blog"] += 1
        elif re.search(r"/(categor|collection|shop)(/|$)", path):
            types["category"] += 1
        else:
            types["blog"] += 1
        if re.search(r"\b(price|buy|cart|checkout)\b", html):
            formats["transactional_landing"] += 1
        elif re.search(r"\b(vs\.?|compare|best)\b", html):
            formats["comparison"] += 1
        elif re.search(r"\b(how to|guide)\b", html):
            formats["guide"] += 1
        row = (topics_by_url or {}).get(u) or {}
        pq = " ".join(
            [str(row.get("primary_topic") or ""), " ".join(str(x) for x in (row.get("keywords") or [])[:6])]
        ).strip()[:200]
        if pq:
            intents[classify_search_intent(pq).get("intent") or "informational"] += 1
    dom_t = types.most_common(1)[0][0] if types else "blog"
    dom_f = formats.most_common(1)[0][0] if formats else "guide"
    dom_i = intents.most_common(1)[0][0] if intents else "informational"
    return {
        "your_dominant_type": dom_t,
        "your_dominant_format": dom_f,
        "your_dominant_intent": dom_i,
    }


def _compute_serp_alignment(
    *,
    serp_pkg: dict[str, Any],
    site_profile: dict[str, Any],
    cluster_intent_pkg: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    serp_type = str(serp_pkg.get("serp_dominant_type") or "blog")
    serp_intent = str(serp_pkg.get("serp_intent") or "informational")
    serp_formats = list(serp_pkg.get("serp_formats") or [])

    y_type = str(site_profile.get("your_dominant_type") or "blog")
    y_intent = str(site_profile.get("your_dominant_intent") or "informational")
    y_fmt = str(site_profile.get("your_dominant_format") or "guide")

    score = 0.55
    if serp_type == y_type:
        score += 0.18
    else:
        reasons.append(f"Loại nội dung site ({y_type}) khác dominant SERP ({serp_type}).")

    if serp_intent == y_intent:
        score += 0.17
    else:
        if {serp_intent, y_intent} == {"informational", "transactional"}:
            reasons.append("Lệch intent: SERP thiên informational nhưng trang cluster thiên transactional (hoặc ngược lại).")
            score -= 0.14
        else:
            reasons.append(f"Intent cluster ({y_intent}) không khớp intent SERP ({serp_intent}).")
            score -= 0.08

    if cluster_intent_pkg:
        dom_c = str(cluster_intent_pkg.get("dominant_intent") or "")
        if dom_c and dom_c != serp_intent and serp_intent != "navigational":
            reasons.append(f"Cụm cluster dominant {dom_c} vs SERP {serp_intent}.")
            score -= 0.06

    fmt_hit = any(f in y_fmt or y_fmt in f for f in serp_formats) if serp_formats else False
    if serp_formats and fmt_hit:
        score += 0.1
    elif serp_formats and "listicle" in serp_formats and "list" not in y_fmt and "comparison" not in y_fmt:
        reasons.append("SERP ưu tiên dạng listicle; site thiếu list-style rõ ràng.")

    score = max(0.08, min(1.0, score))
    return round(score, 4), reasons[:8]


def analyze_topical_serp_gap(
    topic_label: str,
    *,
    cluster: dict[str, Any],
    pages_by_url: dict[str, dict[str, Any]],
    ranking_data: dict[str, dict[str, Any]],
    cluster_graph: dict[str, Any] | None = None,
    serp_snapshot: dict[str, Any] | None = None,
    serp_classifier_pkg: dict[str, Any] | None = None,
    cluster_intent_pkg: dict[str, Any] | None = None,
    topics_by_url: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Compare your cluster vs SERP leaders on page count, length, heading/entity overlap.

    ``serp_snapshot``: output of ``build_serp_snapshot`` (optional). If missing and
    ``TOPICAL_GAP_USE_SERP=1``, fetches snapshot for ``topic_label``.
    """
    urls = list(cluster.get("pages") or [])
    your_pages = len(urls)
    if your_pages == 0:
        return {
            "topic": topic_label,
            "competitor_avg_pages": 0,
            "your_pages": 0,
            "gap_score": 0.5,
            "missing_content_types": [],
            "serp_alignment_score": 0.5,
            "misalignment_reasons": [],
            "explain": "empty_cluster",
        }

    snap = serp_snapshot
    if snap is None and os.getenv("TOPICAL_GAP_USE_SERP", "0").lower() in ("1", "true", "yes"):
        try:
            from app.services.serp_snapshot import build_serp_snapshot

            snap = build_serp_snapshot(topic_label)
        except Exception:
            snap = None

    serp_results = list((snap or {}).get("serp_results") or [])
    hints, meta = _serp_hints_from_snapshot(serp_results) if serp_results else ([], {"organic_results_used": 0})

    # Synthetic "competitor" site size: assume each SERP URL ~1 page in topical sense
    competitor_avg_pages = max(1.0, min(12.0, len(serp_results) * 0.85)) if serp_results else 5.5

    wcs = [int(dict(ranking_data.get(u) or {}).get("word_count") or 0) for u in urls]
    avg_yours = sum(wcs) / max(1, len(wcs))
    # Competitor avg word count proxy from SERP titles/snippets length
    comp_wc = 0.0
    if serp_results:
        for r in serp_results[:10]:
            comp_wc += len(str(r.get("title") or "")) + len(str(r.get("snippet") or ""))
        comp_wc = min(3500.0, max(400.0, comp_wc / max(1, min(10, len(serp_results))) * 3.2))

    heading_entity_overlap = 0.0
    if cluster_graph and hints:
        topics = {str(n.get("topic") or "").lower() for n in (cluster_graph.get("nodes") or [])}
        hit = sum(1 for h in hints if any(h in t or t in h for t in topics))
        heading_entity_overlap = hit / max(1, len(hints))

    if (
        heading_entity_overlap < 0.4
        and os.getenv("TOPICAL_USE_EMBEDDINGS", "0").lower() in ("1", "true", "yes")
        and cluster_graph
        and hints
    ):
        try:
            import numpy as np

            from app.services.semantic_embedding import embed_keywords

            nodes = [str(n.get("topic") or "") for n in (cluster_graph.get("nodes") or [])[:12] if n.get("topic")]
            to_embed = [topic_label] + nodes[:6] + hints[:8]
            vecs = embed_keywords([x for x in to_embed if len(x) > 2])
            lab = vecs.get(topic_label)
            if lab is not None and hints:
                sims = []
                for h in hints[:8]:
                    v = vecs.get(h)
                    if v is not None:
                        sims.append(float(np.dot(lab, v)))
                if sims:
                    heading_entity_overlap = max(heading_entity_overlap, min(1.0, max(0.0, max(sims))))
        except Exception:
            pass

    # Gap: larger when competitors "thicker" and we are thinner / fewer pages
    page_ratio = competitor_avg_pages / max(1.0, float(your_pages))
    depth_gap = max(0.0, (comp_wc / max(1.0, avg_yours)) - 1.0) if avg_yours else 0.8
    gap_raw = min(
        1.0,
        0.28 * min(1.5, page_ratio / 2.0)
        + 0.38 * min(1.0, depth_gap / 1.8)
        + 0.34 * (1.0 - heading_entity_overlap),
    )
    gap_score = round(max(0.0, min(1.0, gap_raw)), 4)

    missing_types: list[str] = []
    if your_pages < competitor_avg_pages * 0.55:
        missing_types.append("supporting_articles")
    if avg_yours < comp_wc * 0.5:
        missing_types.append("deep_guide_or_pillar")
    if heading_entity_overlap < 0.25 and hints:
        missing_types.append("faq_or_comparison_block")
    if not missing_types:
        missing_types.append("entity_expansion")

    serp_pkg = serp_classifier_pkg or {
        "serp_dominant_type": "blog",
        "serp_formats": ["guide"],
        "serp_intent": "informational",
    }
    site_profile = _infer_your_site_profile(urls, pages_by_url, topics_by_url)
    align_score, misalign = _compute_serp_alignment(
        serp_pkg=serp_pkg,
        site_profile=site_profile,
        cluster_intent_pkg=cluster_intent_pkg,
    )

    return {
        "topic": topic_label,
        "competitor_avg_pages": round(competitor_avg_pages, 2),
        "your_pages": your_pages,
        "your_avg_word_count": int(round(avg_yours)),
        "competitor_proxy_word_count": int(round(comp_wc)),
        "heading_entity_overlap": round(heading_entity_overlap, 4),
        "gap_score": gap_score,
        "missing_content_types": missing_types[:8],
        "serp_entity_hints": hints,
        "serp_meta": meta,
        "serp_alignment_score": align_score,
        "misalignment_reasons": misalign,
        "your_site_profile": site_profile,
        "serp_structure": {
            "serp_dominant_type": serp_pkg.get("serp_dominant_type"),
            "serp_formats": serp_pkg.get("serp_formats"),
            "serp_intent": serp_pkg.get("serp_intent"),
        },
        "explain": "Gap blends SERP-derived n-grams vs cluster entity graph + page/length ratios (conservative).",
    }


def build_cluster_graph_from_pages(urls: list[str], pages_by_url: dict[str, dict[str, Any]]) -> dict[str, Any]:
    graphs = []
    for u in urls:
        p = pages_by_url.get(u) or {}
        html = str(p.get("html") or "")
        if html.strip():
            graphs.append(extract_topic_graph(html))
    return merge_cluster_topic_graphs(graphs) if graphs else {"nodes": [], "edges": []}
