"""
Site-wide topical layer (AI v2): entity resolve → graph v2 → coverage → intent → SERP classify
→ gap + alignment → trust → authority v2 → actions.

SERP is treated as ground truth when available; confidence drops on weak crawl data.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.content_analysis import analyze_content
from app.services.serp_intent_classifier import classify_serp_results
from app.services.topic_cluster_health import analyze_cluster_health
from app.services.topic_clustering import cluster_topics
from app.services.topic_coverage import compute_topic_cluster_coverage
from app.services.topic_entity_resolver import (
    cluster_keywords_from_topics,
    raw_entities_from_graph,
    resolve_entity_groups,
)
from app.services.topic_extraction import extract_topics
from app.services.topic_gap_analysis import detect_topic_gaps
from app.services.topic_graph import build_resolved_topic_graph_v2, extract_topic_graph, merge_cluster_topic_graphs
from app.services.topic_intent_engine import analyze_cluster_intent
from app.services.topic_link_authority import evaluate_internal_authority_flow
from app.services.topic_relevance import compute_page_topic_relevance
from app.services.topical_actions import build_topical_actions
from app.services.topical_authority import compute_topical_authority, compute_topical_authority_v2
from app.services.topical_debug_writer import maybe_write_topical_debug
from app.services.topical_gap_analysis import analyze_topical_serp_gap
from app.services.topical_trust_engine import compute_topical_trust


def _depth_score_for_urls(urls: list[str], ranking_data: dict[str, dict[str, Any]]) -> float:
    vals: list[float] = []
    for u in urls:
        row = dict(ranking_data.get(u) or {})
        wc = int(row.get("word_count") or 0)
        d = str(row.get("content_depth") or "thin")
        base = 0.35 if d == "thin" else 0.65 if d == "normal" else 1.0
        vals.append(min(1.0, base * min(1.0, wc / 1200.0)))
    return sum(vals) / max(1, len(vals))


def _mean_entity_centrality(cluster_graph: dict[str, Any]) -> float:
    nodes = list(cluster_graph.get("nodes") or [])
    if not nodes:
        return 0.35
    s = sum(float(n.get("entity_centrality_score") or 0.0) for n in nodes)
    return round(s / len(nodes), 4)


def build_topical_layer_for_site(
    pages: list[dict[str, Any]],
    *,
    url_to_html: dict[str, str],
    graph: dict[str, Any],
    pagerank: dict[str, float],
) -> dict[str, Any]:
    """
    Build topic clusters and per-URL topical signals for ranking integration.

    ``url_to_html``: normalized URL -> raw HTML (200 pages only expected).
    """
    pages_topics: list[dict[str, Any]] = []
    ranking_data: dict[str, dict[str, Any]] = {}

    for page in pages:
        url = str(page.get("url") or "").strip()
        if not url:
            continue
        html = str(url_to_html.get(url) or "")
        st = int(page.get("status") or 0)
        if st == 200 and html.strip():
            topics = extract_topics(html)
            topics["url"] = url
            pages_topics.append(topics)
            cm = analyze_content(html)
            ranking_data[url] = {
                "pagerank_score": float(pagerank.get(url) or 0.0),
                "word_count": int(cm.get("word_count") or 0),
                "content_depth": str(cm.get("content_depth") or "thin"),
            }
        else:
            pages_topics.append(
                {
                    "url": url,
                    "primary_topic": "unknown",
                    "secondary_topics": [],
                    "topic_confidence": 0.0,
                    "keywords": [],
                }
            )
            ranking_data[url] = {
                "pagerank_score": float(pagerank.get(url) or 0.0),
                "word_count": 0,
                "content_depth": "thin",
            }

    clustered = cluster_topics(pages_topics)
    clusters = dict(clustered.get("clusters") or {})
    page_cluster: dict[str, str] = dict(clustered.get("page_cluster") or {})

    pages_by_url = {str(p.get("url") or ""): p for p in pages if p.get("url")}
    topics_by_url = {str(p["url"]): p for p in pages_topics if p.get("url")}

    use_serp_gap = os.getenv("TOPICAL_GAP_USE_SERP", "0").lower() in ("1", "true", "yes")
    fetch_serp_v2 = use_serp_gap or os.getenv("TOPICAL_SERP_FETCH_FOR_V2", "1").lower() in ("1", "true", "yes")
    embed_on = os.getenv("TOPICAL_USE_EMBEDDINGS", "0").lower() in ("1", "true", "yes")

    authority_by_cluster: dict[str, dict[str, Any]] = {}
    topical_authority_report: list[dict[str, Any]] = []

    for cid, cl in clusters.items():
        label = str(cl.get("topic_label") or "mixed")
        urls = list(cl.get("pages") or [])

        per_url_graphs: list[dict[str, Any]] = []
        for u in urls:
            html = str((pages_by_url.get(u) or {}).get("html") or "")
            if html.strip():
                per_url_graphs.append(extract_topic_graph(html))
        raw_graph = merge_cluster_topic_graphs(per_url_graphs) if per_url_graphs else {"nodes": [], "edges": []}

        cluster_kws = cluster_keywords_from_topics(urls, topics_by_url)
        entity_groups = resolve_entity_groups(raw_entities_from_graph(raw_graph), cluster_keywords=cluster_kws)
        cluster_graph = build_resolved_topic_graph_v2(
            raw_graph,
            entity_groups,
            per_url_graphs=per_url_graphs or None,
        )

        intent_pkg = analyze_cluster_intent(cl, topics_by_url=topics_by_url, topic_label=label)

        serp_snap = None
        if fetch_serp_v2 and label not in ("mixed", "unknown", ""):
            try:
                from app.services.serp_snapshot import build_serp_snapshot

                serp_snap = build_serp_snapshot(label)
            except Exception:
                serp_snap = None

        serp_results = list((serp_snap or {}).get("serp_results") or [])
        serp_intent_pkg = classify_serp_results(serp_results)

        gap_pkg = analyze_topical_serp_gap(
            label,
            cluster=cl,
            pages_by_url=pages_by_url,
            ranking_data=ranking_data,
            cluster_graph=cluster_graph,
            serp_snapshot=serp_snap,
            serp_classifier_pkg=serp_intent_pkg,
            cluster_intent_pkg=intent_pkg,
            topics_by_url=topics_by_url,
        )
        hints = list(gap_pkg.get("serp_entity_hints") or [])

        cov_pkg = compute_topic_cluster_coverage(
            cl,
            pages_topics_by_url=topics_by_url,
            ranking_data=ranking_data,
            cluster_graph=cluster_graph,
            serp_entity_hints=hints if hints else None,
        )

        flow_pkg = evaluate_internal_authority_flow(
            cl,
            full_graph=graph,
            pages_by_url=pages_by_url,
            global_pagerank=pagerank,
        )

        legacy = compute_topical_authority(cl, graph, ranking_data)
        depth_cluster = _depth_score_for_urls(urls, ranking_data)
        cent_mean = _mean_entity_centrality(cluster_graph)

        trust_pkg = compute_topical_trust(
            urls,
            pages_by_url=pages_by_url,
            serp_results_count=len(serp_results),
            embedding_used=embed_on,
        )
        trust_signal = float(trust_pkg.get("topical_confidence_score") or 0.55)

        composite = compute_topical_authority_v2(
            coverage_score=float(cov_pkg.get("coverage_score") or 0.0),
            authority_flow_score=float(flow_pkg.get("authority_flow_score") or 0.0),
            gap_score=float(gap_pkg.get("gap_score") or 0.5),
            serp_alignment_score=float(gap_pkg.get("serp_alignment_score") or 0.5),
            intent_consistency_score=float(intent_pkg.get("intent_consistency_score") or 0.5),
            entity_centrality_score=cent_mean,
            trust_score=trust_signal,
            legacy_authority_0_100=float(legacy.get("authority_score") or 0.0),
        )
        composite["topic"] = label

        health_pkg = analyze_cluster_health(
            cl,
            coverage_score=float(cov_pkg.get("coverage_score") or 0.0),
            authority_flow_score=float(flow_pkg.get("authority_flow_score") or 0.0),
            pages_by_url=pages_by_url,
            graph=graph,
        )

        actions = build_topical_actions(
            topic=label,
            coverage=cov_pkg,
            gap=gap_pkg,
            health=health_pkg,
            flow=flow_pkg,
            authority=composite,
            serp_pkg=serp_intent_pkg,
            cluster_intent=intent_pkg,
            entity_groups=entity_groups,
        )

        serp_alignment_debug = {
            "serp_alignment_score": gap_pkg.get("serp_alignment_score"),
            "misalignment_reasons": gap_pkg.get("misalignment_reasons"),
            "your_site_profile": gap_pkg.get("your_site_profile"),
            "serp_structure": gap_pkg.get("serp_structure"),
        }

        row = {
            "topic": label,
            "cluster_id": cid,
            "authority_score": float(composite.get("authority_score") or 0.0),
            "authority_score_0_100": float(composite.get("authority_score_0_100") or 0.0),
            "authority_level": composite.get("authority_level"),
            "confidence": composite.get("confidence"),
            "coverage_score": float(cov_pkg.get("coverage_score") or 0.0),
            "gap_score": float(gap_pkg.get("gap_score") or 0.0),
            "serp_alignment_score": float(gap_pkg.get("serp_alignment_score") or 0.0),
            "authority_flow_score": float(flow_pkg.get("authority_flow_score") or 0.0),
            "content_depth_score": round(depth_cluster, 4),
            "intent_analysis": intent_pkg,
            "serp_intent": serp_intent_pkg,
            "entity_resolution": {"groups": entity_groups[:24], "resolved_node_count": len(cluster_graph.get("nodes") or [])},
            "topical_trust": trust_pkg,
            "components": composite.get("components"),
            "cluster_health": health_pkg.get("cluster_health"),
            "health_issues": health_pkg.get("issues"),
            "actions": actions,
            "explain": {
                "composite": composite.get("explain"),
                "coverage": cov_pkg.get("explain"),
                "gap": gap_pkg.get("explain"),
                "flow": flow_pkg.get("explain"),
                "health": health_pkg.get("explain"),
                "trust": trust_pkg.get("explain"),
            },
            "debug_refs": {
                "topic_graph_v2": {
                    "node_count": len(cluster_graph.get("nodes") or []),
                    "edge_count": len(cluster_graph.get("edges") or []),
                },
            },
        }
        topical_authority_report.append(row)

        maybe_write_topical_debug(
            label,
            topic_graph=cluster_graph,
            topic_coverage=cov_pkg,
            topical_gap=gap_pkg,
            topical_authority_row=row,
            entity_resolved=entity_groups,
            intent_analysis=intent_pkg,
            serp_alignment=serp_alignment_debug,
            topical_trust=trust_pkg,
        )

        authority_by_cluster[cid] = {
            **legacy,
            "authority_score": float(composite.get("authority_score_0_100") or legacy.get("authority_score") or 0.0),
            "authority_composite_0_1": float(composite.get("authority_score") or 0.0),
            "authority_level": composite.get("authority_level") or legacy.get("authority_level"),
            "confidence": composite.get("confidence"),
            "coverage_engine": cov_pkg,
            "gap_analysis": gap_pkg,
            "authority_flow": flow_pkg,
            "cluster_health": health_pkg,
            "topical_actions": actions,
            "intent_engine": intent_pkg,
            "serp_intent_classifier": serp_intent_pkg,
            "entity_groups": entity_groups,
            "topic_graph_v2": cluster_graph,
            "topical_trust": trust_pkg,
        }

    main_cluster_id = ""
    if clusters:
        main_cluster_id = max(clusters.keys(), key=lambda k: int(clusters[k].get("cluster_size") or 0))
    total_urls = max(1, len(pages_topics))
    main_size = int(clusters.get(main_cluster_id, {}).get("cluster_size") or 0)
    main_share = main_size / total_urls

    per_url: dict[str, dict[str, Any]] = {}

    for p in pages_topics:
        url = str(p.get("url") or "")
        if not url:
            continue
        cid = page_cluster.get(url, "")
        cl = clusters.get(cid, {"topic_label": "unknown", "pages": [url], "cluster_size": 1})
        rel = compute_page_topic_relevance(p, cl)
        auth = authority_by_cluster.get(cid) or {
            "authority_score": 0.0,
            "authority_level": "low",
            "coverage_score": 0.0,
            "internal_linking_score": 0.0,
        }
        ac = auth.get("authority_composite_0_1")
        ac_f = float(ac) if ac is not None else None
        asc = float(auth.get("authority_score") or 0.0)
        norm_auth = min(1.0, max(0.0, ac_f if ac_f is not None else asc / 100.0))
        outside = bool(
            cid
            and main_cluster_id
            and cid != main_cluster_id
            and main_share >= 0.28
            and main_size >= 2
        )
        cov_s = float((auth.get("coverage_engine") or {}).get("coverage_score") or auth.get("coverage_score") or 0.0)
        weak_cov = (
            str(auth.get("authority_level")) == "low"
            or cov_s < 0.32
            or (ac_f < 0.35 if ac_f is not None else asc < 38.0)
        )

        per_url[url] = {
            "topic": {
                "primary_topic": p.get("primary_topic"),
                "cluster_id": cid or None,
                "relevance_score": rel.get("relevance_score"),
            },
            "authority": {
                "cluster_authority_score": asc,
                "authority_level": auth.get("authority_level"),
                "authority_composite_0_1": ac_f,
            },
            "cluster_authority_normalized": norm_auth,
            "topic_relevance_score": float(rel.get("relevance_score") or 0.0),
            "outside_main_cluster": outside,
            "weak_topic_coverage": weak_cov,
            "topic_relevance_detail": rel,
            "cluster_authority_detail": auth,
        }

    gaps = detect_topic_gaps(clusters, authority_by_cluster=authority_by_cluster)

    authority_summary = {
        "cluster_count": len(clusters),
        "main_cluster_id": main_cluster_id or None,
        "main_cluster_share": round(main_share, 3),
        "mean_cluster_authority": round(
            sum(float(a.get("authority_score") or 0) for a in authority_by_cluster.values())
            / max(1, len(authority_by_cluster)),
            1,
        ),
        "mean_composite_authority": round(
            sum(float(r.get("authority_score") or 0) for r in topical_authority_report) / max(1, len(topical_authority_report)),
            3,
        )
        if topical_authority_report
        else 0.0,
        "topical_ai_version": "v2",
    }

    return {
        "topic_clusters": clusters,
        "page_cluster": page_cluster,
        "authority_by_cluster": authority_by_cluster,
        "authority_summary": authority_summary,
        "topic_gaps": gaps,
        "topics_by_url": topics_by_url,
        "per_url": per_url,
        "topical_authority": topical_authority_report,
    }
