"""
Data-tied explanation strings: positive drivers, blockers, competitor gaps, misleading signals.
"""

from __future__ import annotations

from typing import Any

from app.services.serp_fetcher import normalize_serp_url


def _wc(row: dict[str, Any]) -> int:
    cm = dict(row.get("ranking", {}).get("content_metrics") or {})
    return int(cm.get("word_count") or 0)


def _top3_from_serp(serp_latest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not serp_latest:
        return []
    rows = list(serp_latest.get("results") or serp_latest.get("latest", {}).get("results") or [])
    out = []
    for r in rows[:3]:
        out.append(
            {
                "rank": int(r.get("rank") or 0),
                "url": str(r.get("url") or "")[:200],
                "title": str(r.get("title") or "")[:120],
                "content_type": r.get("content_type"),
            }
        )
    return out


def build_explanation_groups(
    *,
    feature_names: list[str],
    normalized: dict[str, float],
    raw_signed: dict[str, float],
    feature_values: dict[str, float],
    page_row: dict[str, Any],
    topical_row: dict[str, Any] | None,
    serp_latest: dict[str, Any] | None,
    query: str,
    actual_rank: int | None,
    ranking_probability: float,
) -> dict[str, Any]:
    """
    Split features into top_positive / top_negative / neutral with concrete ``reason`` strings.
    """
    pairs = [
        (n, float(normalized.get(n, 0.0)), float(raw_signed.get(n, 0.0)), float(feature_values.get(n, 0.5)))
        for n in feature_names
    ]
    pairs.sort(key=lambda t: abs(t[1]), reverse=True)

    pos, neg, neu = [], [], []
    thr = 0.08
    for name, nv, rv, fv in pairs:
        reason = _reason_for_feature(
            name=name,
            norm_val=nv,
            raw_val=rv,
            fv=fv,
            page_row=page_row,
            topical_row=topical_row,
            query=query,
        )
        item = {"feature": name, "impact": round(nv, 4), "raw_effect": round(rv, 5), "value": fv, "reason": reason}
        if nv > thr:
            pos.append(item)
        elif nv < -thr:
            neg.append(item)
        else:
            neu.append(item)

    pos.sort(key=lambda z: -z["impact"])
    neg.sort(key=lambda z: z["impact"])
    return {
        "top_positive": pos[:8],
        "top_negative": neg[:8],
        "neutral": neu[:12],
    }


def _reason_for_feature(
    *,
    name: str,
    norm_val: float,
    raw_val: float,
    fv: float,
    page_row: dict[str, Any],
    topical_row: dict[str, Any] | None,
    query: str,
) -> str:
    rnk = dict(page_row.get("ranking") or {})
    gm = dict(rnk.get("graph_metrics") or {})
    cm = dict(rnk.get("content_metrics") or {})
    top = dict(topical_row or {})

    if name == "content_quality":
        return (
            f"Composite on-page ranking_score proxy is {float(rnk.get('ranking_score') or 0):.1f}/100 "
            f"(normalized feature {fv:.2f}); {'supports' if norm_val > 0 else 'limits'} modeled viability."
        )
    if name == "intent_match":
        si = str((top.get("serp_intent") or {}).get("serp_intent") or "?")
        ci = str((top.get("intent_analysis") or {}).get("dominant_intent") or "?")
        return (
            f"SERP-derived intent «{si}» vs cluster/page intent «{ci}» for query «{(query or '')[:80]}» "
            f"(match strength {fv:.2f})."
        )
    if name == "serp_alignment":
        sa = float(top.get("serp_alignment_score") or 0.0)
        return f"Topical gap/SERP alignment score = {sa:.2f} (feature {fv:.2f}) from topical_gap vs winners."
    if name == "internal_linking":
        return (
            f"Internal graph: in_degree={int(gm.get('in_degree') or 0)}, "
            f"pagerank={float(gm.get('pagerank_score') or 0):.4f} → feature {fv:.2f}."
        )
    if name == "page_speed":
        dec = dict(page_row.get("decision") or {})
        rs = dict(dec.get("resolved_signals") or {})
        js = str(rs.get("js_dependency_level") or "low")
        return f"Render/JS dependency level «{js}» maps to crawl/render confidence feature {fv:.2f}."
    if name == "indexability":
        dec = dict(page_row.get("decision") or {})
        rs = dict(dec.get("resolved_signals") or {})
        fi = bool(rs.get("final_indexability", True))
        return f"Resolved indexability signal = {fi} (feature {fv:.2f})."
    if name == "technical_health":
        dec = dict(page_row.get("decision") or {})
        summ = dict(dec.get("summary") or {})
        sc = float(summ.get("score") or 0.0)
        return f"Decision technical summary score ≈ {sc:.1f}/100 (normalized {fv:.2f})."
    if name == "keyword_query_fit":
        wc = int(cm.get("word_count") or 0)
        hs = float(cm.get("heading_structure_score") or 0.0)
        return f"Word_count={wc}, heading_structure_score={hs:.2f} → query/content fit feature {fv:.2f}."
    if name == "topical_authority":
        return f"Topical authority composite (cluster row) feature value {fv:.2f}."
    if name == "entity_match":
        ng = len((top.get("entity_resolution") or {}).get("groups") or [])
        return f"Entity resolution groups observed: {ng} (feature {fv:.2f})."
    if name == "trust_score":
        tt = dict(top.get("topical_trust") or {})
        ts = float(tt.get("trust_score") or tt.get("topical_confidence_score") or 0.0)
        return f"Topical trust / confidence ≈ {ts:.2f} (mapped feature {fv:.2f})."
    if name == "domain_authority_proxy":
        pr = float(gm.get("pagerank_score") or 0.0)
        return f"Internal PageRank proxy {pr:.4f} (feature {fv:.2f})."
    if name == "historical_momentum":
        return f"Historical SERP momentum feature {fv:.2f} (from snapshots when provided)."
    return f"Feature «{name}» value {fv:.2f}, signed attribution mass {raw_val:.5f} (normalized {norm_val:+.3f})."


def build_competitor_context(
    *,
    serp_latest: dict[str, Any] | None,
    page_row: dict[str, Any],
    gap_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    top3 = _top3_from_serp(serp_latest)
    mine = _wc(page_row)
    gaps: list[str] = []
    bench_wc = None
    if gap_analysis:
        bench_wc = int((gap_analysis.get("your_avg_word_count") or gap_analysis.get("avg_word_count") or 0) or 0)
    if bench_wc and mine:
        gaps.append(f"Your crawl word_count={mine} vs cluster SERP-aligned avg ≈{bench_wc} (gap_analysis).")
    for i, c in enumerate(top3):
        gaps.append(
            f"#{c['rank']} competitor {c.get('title') or c['url'][:60]} "
            f"({'type: ' + str(c.get('content_type')) if c.get('content_type') else 'SERP row'})"
        )
    return {"top_three": top3, "gaps": gaps[:10], "your_word_count": mine}


def detect_misleading_signals(
    *,
    top_positive: list[dict[str, Any]],
    actual_rank: int | None,
    normalized: dict[str, float],
    feature_values: dict[str, float],
    ranking_probability: float,
) -> list[dict[str, Any]]:
    """
    Flags features that look helpful in-model but disagree with observed SERP position / probability.
    """
    out: list[dict[str, Any]] = []
    if actual_rank is None:
        return out
    weak = actual_rank > 20
    over = ranking_probability >= 0.62 and weak
    for item in top_positive[:5]:
        fn = str(item.get("feature") or "")
        if weak and fn in ("intent_match", "serp_alignment") and float(feature_values.get(fn, 0) or 0) >= 0.62:
            out.append(
                {
                    "feature": fn,
                    "note": "High modeled driver but weak observed rank — SERP slice, volatility, or intent drift may invalidate this signal for this query.",
                    "actual_rank": actual_rank,
                }
            )
        if over and fn == "content_quality":
            out.append(
                {
                    "feature": fn,
                    "note": "Strong content_quality contribution yet deep rank — check off-site factors, duplicates, or query-specific relevance not captured in crawl features.",
                    "actual_rank": actual_rank,
                }
            )
    return out[:6]


def resolve_actual_rank(target_url: str, serp_latest: dict[str, Any] | None) -> int | None:
    if not serp_latest or not target_url:
        return None
    tu = normalize_serp_url(target_url.strip())
    rows = list(serp_latest.get("results") or serp_latest.get("latest", {}).get("results") or [])
    for r in rows:
        if normalize_serp_url(str(r.get("url") or "")) == tu:
            return int(r.get("rank") or 0) or None
    return None
