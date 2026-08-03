"""
SERP competitor intelligence: snapshot → fetch → content features → benchmark → gaps → strategy.

Public entry: :func:`build_serp_competitor_analysis`.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.services.content_analysis import analyze_content
from app.services.seo_rule_engine import _issue
from app.services.serp_aggregator import aggregate_serp_benchmark, competitor_cluster_view
from app.services.serp_competitor_fetcher import fetch_competitor_pages
from app.services.serp_content_analyzer import analyze_competitor_content
from app.services.serp_difficulty import compute_serp_difficulty
from app.services.serp_gap_analyzer import analyze_serp_gaps
from app.services.serp_ranking_inference import infer_ranking_factors
from app.services.serp_snapshot import build_serp_snapshot
from app.services.serp_strategy import build_content_strategy


def infer_competitor_advantages(
    *,
    benchmark: dict[str, Any],
    gap_issues: list[dict[str, Any]],
    your_features: dict[str, Any],
    ranking_factors: list[dict[str, Any]],
) -> list[str]:
    """Human-readable WHY competitors rank vs your page (multi-signal)."""
    adv: list[str] = []
    y_wc = int(your_features.get("word_count") or 0)
    b_wc = int(benchmark.get("avg_word_count") or 0)
    if b_wc > y_wc * 1.15:
        adv.append("Higher content depth vs your page (SERP average word count).")

    b_il = float(benchmark.get("avg_internal_links") or 0)
    y_il = int(your_features.get("internal_link_count") or 0)
    if b_il > y_il * 1.2 and b_il >= 6:
        adv.append("Better internal linking density in winning URLs.")

    b_h = float(benchmark.get("avg_heading_score") or 0)
    y_h = float(your_features.get("heading_structure_score") or 0)
    if b_h > y_h + 0.12:
        adv.append("Stronger heading / structure patterns in top results.")

    for g in gap_issues or []:
        issue = str(g.get("issue") or "")
        if issue == "semantic_depth_gap":
            adv.append("Richer topical / semantic coverage on competitors (depth gap).")
        elif issue == "keyword_coverage_gap":
            adv.append("Closer lexical alignment to query intent in SERP leaders.")

    for rf in ranking_factors or []:
        fac = str(rf.get("factor") or "")
        imp = float(rf.get("importance") or 0)
        if imp >= 0.55 and fac == "content_depth":
            adv.append("SERP variance suggests content depth separates winners here.")
        elif imp >= 0.55 and fac == "internal_links":
            adv.append("SERP variance suggests internal link patterns separate winners here.")

    if not adv:
        adv.append("Competitors align more tightly with aggregated SERP centroid (length + structure + links).")
    return adv[:10]


def _sev_rank(s: Any) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(s or "").lower(), 0)


def _page_by_url(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in pages:
        u = str(p.get("url") or "").strip()
        if u:
            out[u] = p
            out[u.rstrip("/")] = p
    return out


def _your_page_features(
    *,
    keyword: str,
    your_url: str | None,
    your_html: str | None,
    your_page_features: dict[str, Any] | None,
    pages: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    """Resolve ``your_page`` dict and effective URL for strategy."""
    if your_page_features:
        u = str(your_page_features.get("url") or your_url or "").strip()
        return dict(your_page_features), u
    html = (your_html or "").strip()
    u = (your_url or "").strip()
    if not html and pages and u:
        row = _page_by_url(pages).get(u) or _page_by_url(pages).get(u.rstrip("/"))
        if row:
            html = str(row.get("html") or "")
    if not html:
        return {
            "url": u,
            "word_count": 0,
            "heading_structure_score": 0.0,
            "internal_link_count": 0,
            "keyword_coverage": 0.0,
            "content_depth_score": 0.25,
            "content_depth": "thin",
        }, u
    base = analyze_content(html)
    extra = analyze_competitor_content(html, keyword, u or "https://example.com/", base_features=base)
    internal_ct = 0
    if pages and u:
        pr = _page_by_url(pages).get(u) or _page_by_url(pages).get(u.rstrip("/"))
        if pr is not None:
            il = pr.get("internal_links")
            if isinstance(il, list):
                internal_ct = len(il)
            elif pr.get("internal_link_count") is not None:
                internal_ct = int(pr.get("internal_link_count") or 0)
    merged = {
        "url": u,
        "word_count": int(extra.get("word_count") or base.get("word_count") or 0),
        "heading_structure_score": float(extra.get("heading_structure_score") or base.get("heading_structure_score") or 0.0),
        "internal_link_count": internal_ct,
        "keyword_coverage": float(extra.get("keyword_coverage") or 0.0),
        "content_depth_score": float(extra.get("content_depth_score") or 0.5),
        "content_depth": str(extra.get("content_depth_label") or base.get("content_depth") or "normal"),
    }
    return merged, u


def gaps_to_synthetic_decision_issues(
    gaps: list[dict[str, Any]],
    *,
    keyword: str,
) -> list[dict[str, Any]]:
    """Map gap rows to decision-engine issue dicts (unique ``rule_id`` per gap type)."""
    rid_map = {
        "content_too_thin_vs_serp": "serp_gap_thin_content",
        "heading_structure_behind_serp": "serp_gap_heading_structure",
        "weak_internal_linking_vs_serp": "serp_gap_internal_links",
        "keyword_coverage_gap": "serp_gap_keyword_coverage",
        "semantic_depth_gap": "serp_gap_semantic_depth",
    }
    out: list[dict[str, Any]] = []
    for g in gaps:
        key = str(g.get("issue") or "")
        rid = rid_map.get(key, "serp_gap_generic")
        sev = str(g.get("severity") or "medium").lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        trig = str(g.get("triggered_by_competitors") or "SERP leaders")
        why = str(g.get("why") or g.get("recommendation") or "")
        rec = str(g.get("recommendation") or "")
        conf = 0.55 + 0.08 * float(g.get("gap_score") or 0.5)
        out.append(
            _issue(
                rid,
                f"SERP competition: {key.replace('_', ' ')} for «{keyword}»",
                sev,
                min(0.92, conf),
                "content",
                why=why or "Benchmarked against live SERP competitors for this query.",
                detected_from=["serp_competitor_intelligence", trig[:200]],
                causes=[f"competitor_pattern:{key}", f"triggered_by:{trig[:240]}"],
                fixes=[rec] if rec else ["Review SERP benchmark and expand on-page signals."],
                validation=["Re-fetch SERP after changes", "Compare word count and headings to top 10"],
            )
        )
    return out


def build_serp_competitor_analysis(
    keyword: str,
    *,
    your_url: str | None = None,
    your_page_html: str | None = None,
    your_page_features: dict[str, Any] | None = None,
    pages: list[dict[str, Any]] | None = None,
    top_n: int | None = None,
    include_html_in_output: bool = False,
) -> dict[str, Any]:
    """
    Full competitor intelligence for one keyword.

    Returns ``{ keyword, serp_analysis: { benchmark, competitors, cluster_view, gap_analysis,
    ranking_factors, strategy, difficulty_score, explainability, ... } }``.
    """
    snap = build_serp_snapshot(keyword, top_n=top_n)
    results = list(snap.get("serp_results") or [])
    urls = [str(r.get("url") or "") for r in results if r.get("url")]

    fetch_rows = fetch_competitor_pages(urls)
    content_rows: list[dict[str, Any]] = []
    competitors_out: list[dict[str, Any]] = []

    for fr in fetch_rows:
        url = str(fr.get("url") or "")
        html_ex = str(fr.get("html_excerpt") or "")
        feat = analyze_competitor_content(html_ex, keyword.strip(), url, base_features=fr)
        merged = {**fr, **feat}
        pub = {k: v for k, v in merged.items() if k != "html_excerpt" or include_html_in_output}
        if not include_html_in_output:
            pub.pop("html_excerpt", None)
        competitors_out.append(pub)
        content_rows.append({**fr, **feat})

    bench = aggregate_serp_benchmark(content_rows, keyword=keyword.strip())
    cluster_view = competitor_cluster_view(fetch_rows)
    dom_names = [str(d.get("domain") or "") for d in cluster_view.get("dominant_domains") or [] if d.get("domain")]

    yfeat, eff_url = _your_page_features(
        keyword=keyword.strip(),
        your_url=your_url,
        your_html=your_page_html,
        your_page_features=your_page_features,
        pages=pages,
    )

    gaps = analyze_serp_gaps(yfeat, bench, keyword=keyword.strip(), competitor_domains=dom_names)
    inf = infer_ranking_factors(bench, content_rows)
    factors = list(inf.get("dominant_factors") or [])
    strat = build_content_strategy(
        keyword.strip(),
        target_url=eff_url or your_url or "",
        benchmark=bench,
        gap_issues=gaps,
        ranking_factors=factors,
    )
    diff_pkg = compute_serp_difficulty(bench, cluster_view, competitor_count=len(fetch_rows))
    diff_score = float(diff_pkg.get("difficulty_score") or 0.0)

    explainability = {
        "gap_recommendations": [
            {
                "issue": g.get("issue"),
                "why": g.get("why"),
                "recommendation": g.get("recommendation"),
                "competitors_reference": g.get("triggered_by_competitors"),
                "severity": g.get("severity"),
                "gap_score": g.get("gap_score"),
            }
            for g in gaps
        ],
        "ranking_inference": inf.get("explain"),
        "difficulty": diff_pkg.get("explain"),
        "snapshot_source": snap.get("fetch_source"),
    }

    competitor_advantage = infer_competitor_advantages(
        benchmark=bench,
        gap_issues=gaps,
        your_features=yfeat,
        ranking_factors=factors,
    )

    serp_analysis = {
        "benchmark": bench,
        "competitors": competitors_out,
        "cluster_view": cluster_view,
        "gap_analysis": gaps,
        "ranking_factors": factors,
        "strategy": strat,
        "difficulty_score": diff_score,
        "difficulty_detail": diff_pkg,
        "competitor_advantage": competitor_advantage,
        "synthetic_decision_issues": gaps_to_synthetic_decision_issues(gaps, keyword=keyword.strip()),
        "explainability": explainability,
        "serp_snapshot_meta": {"result_count": len(results), "fetched_count": len(fetch_rows)},
    }
    return {"keyword": keyword.strip(), "serp_analysis": serp_analysis}


def build_url_serp_audit_overlay(
    bundle: dict[str, Any],
    pages: list[dict[str, Any]],
    *,
    max_clusters: int | None = None,
) -> dict[str, dict[str, Any]]:
    """
    For mapped cluster targets, run SERP analysis and produce per-URL overlay:

    ``{ url: { serp_difficulty_score, serp_analysis, synthetic_issues, keywords_checked[] } }``.
    """
    if os.getenv("KEYWORD_SERP_INTEL", "0").lower() not in ("1", "true", "yes"):
        return {}
    cap = max_clusters if max_clusters is not None else int(os.getenv("KEYWORD_SERP_CLUSTER_MAX", "4"))
    clusters = list(bundle.get("clusters") or [])
    mappings = {str(m.get("cluster_id") or ""): m for m in (bundle.get("mappings") or [])}

    overlay: dict[str, dict[str, Any]] = {}
    used = 0
    for cl in clusters:
        if used >= cap:
            break
        cid = str(cl.get("cluster_id") or "")
        mp = mappings.get(cid) or {}
        target = str(mp.get("target_url") or "").strip()
        kws = list(cl.get("keywords") or [])
        if not kws:
            continue
        rep = max(kws, key=lambda r: len(str(r.get("keyword") or "")))
        kw = str(rep.get("keyword") or "").strip()
        if not kw or not target:
            continue
        try:
            report = build_serp_competitor_analysis(
                kw,
                your_url=target,
                pages=pages,
            )
        except Exception as exc:
            report = {
                "keyword": kw,
                "serp_analysis": {
                    "error": str(exc)[:500],
                    "difficulty_score": 0.0,
                    "synthetic_decision_issues": [],
                },
            }
        sa = dict(report.get("serp_analysis") or {})
        diff = float(sa.get("difficulty_score") or 0.0)
        syn = list(sa.get("synthetic_decision_issues") or [])
        slot = overlay.setdefault(
            target,
            {
                "serp_difficulty_score": 0.0,
                "serp_analysis": {},
                "synthetic_issues": [],
                "keywords_checked": [],
            },
        )
        slot["keywords_checked"].append(kw)
        if diff >= float(slot.get("serp_difficulty_score") or 0.0):
            slot["serp_difficulty_score"] = diff
            slot["serp_analysis"] = report
        slot["synthetic_issues"].extend(syn)
        cl["serp_analysis"] = report
        used += 1
    for u, slot in overlay.items():
        # Dedupe synthetic issues by rule_id keeping highest severity
        by_id: dict[str, dict[str, Any]] = {}
        for it in slot.get("synthetic_issues") or []:
            rid = str(it.get("rule_id") or "")
            if not rid:
                continue
            prev = by_id.get(rid)
            if prev is None or _sev_rank(it.get("severity")) > _sev_rank(prev.get("severity")):
                by_id[rid] = it
        slot["synthetic_issues"] = list(by_id.values())
    return overlay
