"""
SEO Intelligence Core v3 — unified reasoning bundle for technical audit responses.
"""

from __future__ import annotations

from typing import Any

from app.services.entity_hierarchy import build_entity_hierarchy
from app.services.query_intent_engine import build_cluster_query_intent
from app.services.ranking_decision_v3 import build_site_ranking_decision_v3
from app.services.seo_penalty_engine import compute_seo_penalties
from app.services.seo_strategy_ai import build_seo_strategy_ai_site
from app.services.serp_dominance import compute_serp_dominance
from app.services.topic_entity_resolver import cluster_keywords_from_topics


def _indexability_summary(page_audits: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    ok = 0
    blockers: list[str] = []
    for row in page_audits or []:
        if int(row.get("status") or 0) != 200:
            continue
        total += 1
        sim = dict(row.get("simulation") or {})
        dec = dict(row.get("decision") or {})
        rs = dict(dec.get("resolved_signals") or {})
        idx = bool(rs.get("final_indexability", True))
        will = sim.get("will_index")
        if will is False:
            blockers.append(f"{row.get('url')}: simulation will_index=false")
        if not idx:
            blockers.append(f"{row.get('url')}: resolved final_indexability=false")
        if idx and will is not False:
            ok += 1
    ratio = round(ok / max(1, total), 3) if total else 0.0
    return {
        "indexable_ratio": ratio,
        "indexable_pages": ok,
        "evaluated_200_pages": total,
        "primary_blockers": blockers[:12],
        "explain": "Aggregated from per-URL decision + simulation (200 responses only).",
    }


def _aggregate_page_signals(page_audits: list[dict[str, Any]]) -> dict[str, Any]:
    cloaking = False
    cloak_lvl = "low"
    js_max = "low"
    for row in page_audits or []:
        if int(row.get("status") or 0) != 200:
            continue
        dec = dict(row.get("decision") or {})
        rs = dict(dec.get("resolved_signals") or {})
        ca = dict(rs.get("cloaking_advanced") or dec.get("cloaking_analysis") or {})
        lvl = str(ca.get("cloaking_risk_level") or "").lower()
        if lvl in ("high", "medium"):
            cloaking = True
            if lvl == "high":
                cloak_lvl = "high"
            elif cloak_lvl != "high":
                cloak_lvl = "medium"
        j = str(rs.get("js_dependency_level") or "low").lower()
        if j == "high":
            js_max = "high"
        elif j == "medium" and js_max == "low":
            js_max = "medium"
    return {"cloaking_risk": cloaking, "cloaking_level": cloak_lvl, "js_dependency_level": js_max}


def _mean_serp_alignment_from_topical(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.5
    s = sum(float(r.get("serp_alignment_score") or 0.5) for r in rows)
    return s / len(rows)


def _mean_topical_authority(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.35
    s = sum(float(r.get("authority_score") or 0) for r in rows)
    return s / len(rows)


def _mean_ranking_score(page_audits: list[dict[str, Any]]) -> float:
    vals = [
        float((dict(r.get("ranking") or {}).get("ranking_score") or 0))
        for r in page_audits or []
        if int(r.get("status") or 0) == 200
    ]
    if not vals:
        return 40.0
    return sum(vals) / len(vals)


def _serp_intel_summary(
    url_serp_overlay: dict[str, dict[str, Any]],
    keyword_intelligence: dict[str, Any] | None,
) -> dict[str, Any]:
    overlays = list((url_serp_overlay or {}).values())
    competitor_advantages: list[str] = []
    difficulties: list[float] = []
    for slot in overlays:
        sa = dict(slot.get("serp_analysis") or {})
        inner = dict(sa.get("serp_analysis") or sa)
        for adv in inner.get("competitor_advantage") or []:
            if isinstance(adv, str) and adv not in competitor_advantages:
                competitor_advantages.append(adv)
        if inner.get("difficulty_score") is not None:
            difficulties.append(float(inner.get("difficulty_score") or 0))
    kw = keyword_intelligence or {}
    return {
        "overlay_count": len(overlays),
        "mean_serp_difficulty": round(sum(difficulties) / max(1, len(difficulties)), 2) if difficulties else None,
        "competitor_advantage_samples": competitor_advantages[:10],
        "keyword_cluster_count": len(kw.get("clusters") or []),
        "explain": "Summarizes SERP competitor overlays + keyword intel footprint.",
    }


def build_seo_intelligence_core_v3(
    *,
    page_audits: list[dict[str, Any]],
    technical_summary: dict[str, Any],
    site_graph_summary: dict[str, Any],
    keyword_intelligence: dict[str, Any] | None,
    topical_authority: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    gsc_queries: list[dict[str, Any]] | None,
    url_serp_overlay: dict[str, dict[str, Any]],
    start_url: str,
) -> dict[str, Any]:
    """
    Unified v3 brain: indexability, ranking decision, topical, SERP summary, keyword ref, strategy.

    Designed for ``TechnicalAnalyzeResponse.seo_intelligence_core``.
    """
    idx_pkg = _indexability_summary(page_audits)
    indexable_ratio = float(idx_pkg.get("indexable_ratio") or 0.0)

    # Query intent: GSC > clusters > start URL host page text
    clusters = (keyword_intelligence or {}).get("clusters") or []
    flat_kw: list[dict[str, Any]] = []
    for cl in clusters:
        for r in cl.get("keywords") or []:
            if isinstance(r, dict):
                flat_kw.append(r)
    first_page = next((p for p in pages if str(p.get("url") or "") == start_url), pages[0] if pages else {})
    fallback = str((first_page.get("html") or ""))[:800]
    query_pkg = build_cluster_query_intent(
        gsc_queries=gsc_queries,
        cluster_keyword_rows=flat_kw,
        fallback_topic_label=start_url,
    )

    # SERP dominance from first available topical row's serp_intent block + synthetic distribution
    dom_pkg = {"serp_dominance_score": 0.5, "dominant_type": "blog", "serp_volatility": 0.4}
    if topical_authority:
        serp_int = dict((topical_authority[0] or {}).get("serp_intent") or {})
        if serp_int.get("type_distribution"):
            dom_pkg = compute_serp_dominance(serp_int)
        else:
            # build minimal distribution from dominant type
            dt = str(serp_int.get("serp_dominant_type") or "blog")
            dom_pkg = compute_serp_dominance({"type_distribution": {dt: 8}})

    mean_align = _mean_serp_alignment_from_topical(topical_authority)
    mean_top = _mean_topical_authority(topical_authority)
    mean_rnk = _mean_ranking_score(page_audits)
    tech_health = float(technical_summary.get("health_score") or 65.0)

    # Trust propagation: worst cluster trust (conservative)
    trust_scores = [float((r.get("topical_trust") or {}).get("trust_score") or 0.55) for r in topical_authority]
    trust_score = min(trust_scores) if trust_scores else 0.55
    wa = {}
    for r in topical_authority:
        tw = dict(r.get("topical_trust") or {})
        if tw.get("weight_adjustment"):
            wa = dict(tw["weight_adjustment"])
            break

    intent_mismatch = False
    for r in topical_authority:
        si = str((r.get("serp_intent") or {}).get("serp_intent") or "")
        ci = str((r.get("intent_analysis") or {}).get("dominant_intent") or "")
        if si and ci and si != ci and "navigational" not in (si, ci):
            intent_mismatch = True
            break

    page_sig = _aggregate_page_signals(page_audits)
    penalties = compute_seo_penalties(
        intent_mismatch=intent_mismatch,
        serp_alignment_score=mean_align,
        topical_trust_score=trust_score,
        cloaking_risk=bool(page_sig.get("cloaking_risk")),
        cloaking_level=str(page_sig.get("cloaking_level") or "low"),
        js_dependency_level=str(page_sig.get("js_dependency_level") or "low"),
        serp_volatility=float(dom_pkg.get("serp_volatility") or 0.0),
    )

    ranking_decision = build_site_ranking_decision_v3(
        technical_health=tech_health,
        indexable_ratio=indexable_ratio,
        mean_ranking_score_0_100=mean_rnk,
        mean_topical_authority_0_1=mean_top,
        mean_serp_alignment=mean_align,
        penalties=penalties,
        trust_weight_adjustment=wa or None,
    )

    strategy = build_seo_strategy_ai_site(
        topical_authority=topical_authority,
        ranking_decision=ranking_decision,
        keyword_intelligence=keyword_intelligence,
    )

    # Entity hierarchy (primary cluster)
    entity_hierarchy: dict[str, Any] = {"hierarchy": {}, "explain": "no_topical_cluster"}
    if topical_authority:
        row0 = topical_authority[0]
        label = str(row0.get("topic") or "topic")
        cid = str(row0.get("cluster_id") or "")
        tc = dict(site_graph_summary.get("topic_clusters") or {})
        cl = tc.get(cid) or {}
        urls = list(cl.get("pages") or [])[:24]
        topics_by = dict(site_graph_summary.get("topics_by_url") or {})
        raw_phrases: list[str] = []
        er = row0.get("entity_resolution") or {}
        for g in er.get("groups") or []:
            c = str(g.get("canonical_entity") or "")
            if c:
                raw_phrases.append(c)
            for v in g.get("variants") or []:
                if isinstance(v, str):
                    raw_phrases.append(v)
        kws = cluster_keywords_from_topics(urls or [start_url], topics_by)
        entity_hierarchy = build_entity_hierarchy(
            topic_label=label,
            raw_entity_phrases=raw_phrases or [label],
            cluster_keywords=kws,
        )

    serp_intel = _serp_intel_summary(url_serp_overlay, keyword_intelligence)
    serp_intel["serp_dominance"] = dom_pkg
    serp_intel["query_intent"] = {
        "sample_queries": (query_pkg.get("queries") or [])[:8],
        "cluster_summary": {k: v for k, v in query_pkg.items() if k != "queries"},
    }

    return {
        "version": "v3",
        "indexability": idx_pkg,
        "ranking_decision": ranking_decision,
        "topical_authority": topical_authority,
        "serp_intelligence": serp_intel,
        "keyword_intelligence": keyword_intelligence or {},
        "strategy": strategy,
        "entity_hierarchy": entity_hierarchy,
        "penalties": penalties,
        "trust_propagation": {
            "trust_score": trust_score,
            "weight_adjustment": wa,
            "explain": "Worst-cluster trust + weight_adjustment from topical_trust_engine.",
        },
        "query_intent_engine": query_pkg,
    }
