"""
Detect ranking-impacting issues from ``seo_intelligence_core`` v3 + ground-truth bundle.

Every issue cites concrete fields (scores, penalties, SERP metrics), not generic SEO copy.
"""

from __future__ import annotations

from typing import Any


def _urls_from_context(context: dict[str, Any] | None) -> list[str]:
    ctx = dict(context or {})
    u = ctx.get("monitored_urls") or ctx.get("affected_urls")
    if isinstance(u, list):
        return [str(x).strip() for x in u if str(x).strip()][:40]
    su = str(ctx.get("start_url") or "").strip()
    return [su] if su else []


def detect_issues(
    core_v3: dict[str, Any],
    ground_truth_bundle: dict[str, Any] | None,
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Returns ``[{ issue_type, severity, affected_urls, root_cause, signals }]``.
    """
    issues: list[dict[str, Any]] = []
    urls = _urls_from_context(context)
    gt = dict(ground_truth_bundle or {})

    rd = dict(core_v3.get("ranking_decision") or {})
    comps = dict(rd.get("components") or {})
    penalties = list(core_v3.get("penalties") or [])
    idx = dict(core_v3.get("indexability") or {})
    topical = list(core_v3.get("topical_authority") or [])
    val = dict((gt.get("validation") or {}))
    intent_gt = dict(gt.get("intent_truth") or {})
    vol = dict(gt.get("volatility") or {})
    dt = dict(gt.get("data_trust") or {})

    # Intent: model vs SERP-derived dominant
    if topical:
        row0 = dict(topical[0])
        si = str((row0.get("serp_intent") or {}).get("serp_intent") or "")
        ci = str((row0.get("intent_analysis") or {}).get("dominant_intent") or "")
        dom_serp = str(intent_gt.get("dominant_intent") or "")
        if si and ci and si != ci and "navigational" not in (si, ci):
            issues.append(
                {
                    "issue_type": "intent_mismatch",
                    "severity": round(0.55 + 0.15 * float(intent_gt.get("intent_stability_score") or 0), 3),
                    "affected_urls": urls or ["site:cluster_primary"],
                    "root_cause": (
                        f"Cluster/page intent «{ci}» differs from SERP row classifier «{si}» "
                        f"(ground-truth dominant «{dom_serp or 'n/a'}»)."
                    ),
                    "signals": {"cluster_serp_intent": si, "cluster_page_intent": ci, "serp_truth_intent": dom_serp},
                }
            )

    align = float(comps.get("mean_serp_alignment") or 0.0)
    if align < 0.45:
        issues.append(
            {
                "issue_type": "serp_misalignment",
                "severity": round(min(0.95, 0.4 + (0.45 - align)), 3),
                "affected_urls": urls or ["site:topical_cluster"],
                "root_cause": (
                    f"Mean SERP alignment component = {align:.3f} (<0.45) — content/format vs SERP winners."
                ),
                "signals": {"mean_serp_alignment": align},
            }
        )

    for p in penalties:
        t = str(p.get("type") or "")
        if t in ("serp_misalignment", "intent_mismatch"):
            continue
        imp = abs(float(p.get("impact") or 0))
        if imp >= 0.06:
            issues.append(
                {
                    "issue_type": t or "penalty_signal",
                    "severity": round(min(0.95, 0.35 + imp), 3),
                    "affected_urls": urls or ["site:aggregate"],
                    "root_cause": str(p.get("reason") or t),
                    "signals": {"penalty_type": t, "penalty_impact": float(p.get("impact") or 0)},
                }
            )

    mean_top = float(comps.get("mean_topical_authority") or 0.0)
    if mean_top < 0.42:
        issues.append(
            {
                "issue_type": "weak_topical_authority",
                "severity": round(0.5 + (0.42 - mean_top), 3),
                "affected_urls": urls or ["site:topical_cluster"],
                "root_cause": f"Mean topical authority composite = {mean_top:.3f} (v3 ranking component).",
                "signals": {"mean_topical_authority": mean_top},
            }
        )

    for row in topical[:3]:
        gap = dict(row.get("gap_analysis") or {})
        flow = float(row.get("authority_flow_score") or 0.0)
        if flow < 0.4:
            issues.append(
                {
                    "issue_type": "internal_linking_gap",
                    "severity": round(0.45 + (0.4 - flow), 3),
                    "affected_urls": urls or [str(row.get("topic") or "cluster")],
                    "root_cause": (
                        f"Authority flow score = {flow:.3f} for topic «{row.get('topic')}» — weak internal PageRank paths."
                    ),
                    "signals": {"authority_flow_score": flow, "gap_score": gap.get("gap_score")},
                }
            )
        ywc = int(gap.get("your_avg_word_count") or 0)
        swc = int(gap.get("competitor_proxy_word_count") or 0)
        if swc > 400 and ywc > 0 and ywc < int(0.55 * swc):
            issues.append(
                {
                    "issue_type": "content_depth_gap",
                    "severity": round(min(0.9, 0.35 + (swc - ywc) / max(swc, 1)), 3),
                    "affected_urls": urls or ["site:cluster_pages"],
                    "root_cause": (
                        f"Cluster crawl avg word_count ({ywc}) materially below competitor_proxy_word_count ({swc}) in gap_analysis."
                    ),
                    "signals": {"your_avg_word_count": ywc, "competitor_proxy_word_count": swc},
                }
            )

    ir = float(idx.get("indexable_ratio") or 1.0)
    if ir < 0.55:
        issues.append(
            {
                "issue_type": "technical_indexability_blocker",
                "severity": round(0.55 + (0.55 - ir), 3),
                "affected_urls": [str(u) for u in (idx.get("primary_blockers") or [])[:8]] or urls or ["site:crawl"],
                "root_cause": f"Indexable ratio = {ir:.3f} from page_audits aggregation (v3 indexability).",
                "signals": {"indexable_ratio": ir, "blockers_sample": (idx.get("primary_blockers") or [])[:4]},
            }
        )

    # Ground truth: validator misalignment + volatility + trust
    for r in (val.get("misalignment_reasons") or [])[:4]:
        if isinstance(r, str) and r and r != "no_material_misalignment_detected":
            issues.append(
                {
                    "issue_type": "prediction_serp_misalignment",
                    "severity": 0.62,
                    "affected_urls": urls,
                    "root_cause": f"Ground-truth validator: {r}",
                    "signals": {
                        "prediction_error": val.get("prediction_error"),
                        "actual_best_rank": val.get("actual_best_rank"),
                    },
                }
            )

    nv = float(vol.get("normalized_volatility") or 0.0)
    if nv > 0.55:
        issues.append(
            {
                "issue_type": "high_serp_volatility",
                "severity": round(min(0.85, nv), 3),
                "affected_urls": urls or ["query:serp"],
                "root_cause": (
                    f"SERP slot entropy volatility = {nv:.3f} — rankings for this query are unstable in snapshots."
                ),
                "signals": {"normalized_volatility": nv},
            }
        )

    dup = float(dt.get("duplication_rate") or 0.0)
    fs = float(dt.get("fetch_success_rate") or 1.0)
    if dup > 0.45 or fs < 0.55:
        issues.append(
            {
                "issue_type": "low_ground_truth_trust",
                "severity": round(0.4 + 0.5 * dup + 0.35 * max(0, 0.7 - fs), 3),
                "affected_urls": [],
                "root_cause": (
                    f"SERP data_trust: duplication_rate={dup:.3f}, fetch_success_rate={fs:.3f} — validate cautiously."
                ),
                "signals": dict(dt),
            }
        )

    rk = float(comps.get("mean_ranking_score") or 0.0)
    if rk < 0.44 and not any(i["issue_type"] == "weak_topical_authority" for i in issues):
        issues.append(
            {
                "issue_type": "weak_on_page_ranking_signals",
                "severity": round(0.45 + (0.44 - rk), 3),
                "affected_urls": urls or ["site:pages"],
                "root_cause": f"Mean page ranking_score component = {rk:.3f} (from v3 components).",
                "signals": {"mean_ranking_score": rk},
            }
        )

    merged: dict[str, dict[str, Any]] = {}
    for i in issues:
        it = str(i.get("issue_type") or "")
        prev = merged.get(it)
        if prev is None or float(i.get("severity") or 0) > float(prev.get("severity") or 0):
            merged[it] = i
    return list(merged.values())[:25]
