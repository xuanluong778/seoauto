"""
Turn detected issues into quantified, URL-targeted actions (no generic tips).
"""

from __future__ import annotations

from typing import Any

_EFFORT = ("low", "medium", "high")


def _pick_target_url(issue: dict[str, Any], context: dict[str, Any] | None) -> str:
    ctx = dict(context or {})
    urls = list(issue.get("affected_urls") or [])
    for u in urls:
        if u and not str(u).startswith("site:") and not str(u).startswith("query:"):
            return str(u)
    return str(ctx.get("start_url") or ctx.get("primary_url") or "").strip()


def _base_confidence(ground_truth_bundle: dict[str, Any] | None) -> float:
    gt = dict(ground_truth_bundle or {})
    dt = dict(gt.get("data_trust") or {})
    vol = float((gt.get("volatility") or {}).get("normalized_volatility") or 0.0)
    fs = float(dt.get("fetch_success_rate") or 0.8)
    rc = float(dt.get("render_completeness") or 0.85)
    dup = float(dt.get("duplication_rate") or 0.2)
    c = max(0.25, min(0.92, fs * rc * (1.0 - 0.45 * dup) * (1.0 - 0.35 * vol)))
    return round(c, 4)


def generate_actions(
    issues: list[dict[str, Any]],
    *,
    core_v3: dict[str, Any],
    ground_truth_bundle: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Each action: ``action``, ``action_id``, ``target_url``, ``issue_type``,
    ``expected_impact_delta_prob``, ``effort``, ``ranking_signal``, ``confidence``, ``evidence``.
    """
    base_c = _base_confidence(ground_truth_bundle)
    actions: list[dict[str, Any]] = []

    for i, issue in enumerate(issues):
        it = str(issue.get("issue_type") or "")
        tgt = _pick_target_url(issue, context)
        sev = float(issue.get("severity") or 0.5)
        sig = dict(issue.get("signals") or {})

        if it == "intent_mismatch":
            actions.append(
                {
                    "action_id": f"act_{i}_intent_align",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Rewrite H1 + lead paragraph so primary entity + intent match SERP dominant intent "
                        f"({sig.get('cluster_serp_intent') or sig.get('serp_truth_intent')}); align H2s to SERP formats."
                    ),
                    "expected_impact_delta_prob": round(min(0.22, 0.08 + 0.12 * sev), 4),
                    "effort": "medium",
                    "ranking_signal": "mean_serp_alignment + intent_match (v3 penalties relief)",
                    "confidence": round(base_c * 0.95, 4),
                    "evidence": sig,
                }
            )
        elif it == "serp_misalignment":
            actions.append(
                {
                    "action_id": f"act_{i}_serp_format",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Add SERP-shaped module (FAQ schema block + comparison table) using gap.missing_content_types "
                        "from topical_gap_analysis for this cluster."
                    ),
                    "expected_impact_delta_prob": round(min(0.2, 0.07 + 0.12 * sev), 4),
                    "effort": "medium",
                    "ranking_signal": "serp_alignment_score, mean_serp_alignment component",
                    "confidence": round(base_c * 0.9, 4),
                    "evidence": sig,
                }
            )
        elif it == "weak_topical_authority":
            actions.append(
                {
                    "action_id": f"act_{i}_topical_support",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Publish 2–4 supporting URLs in the same cluster_id with internal links to the money URL; "
                        "cover missing_subtopics from coverage engine when present."
                    ),
                    "expected_impact_delta_prob": round(min(0.18, 0.05 + 0.12 * sev), 4),
                    "effort": "high",
                    "ranking_signal": "mean_topical_authority + cluster coverage_score",
                    "confidence": round(base_c * 0.82, 4),
                    "evidence": sig,
                }
            )
        elif it == "internal_linking_gap":
            actions.append(
                {
                    "action_id": f"act_{i}_internal_links",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Add contextual inbound links from highest in-degree hub pages in the same cluster to this URL; "
                        "target authority_flow_score lift >0.08 vs baseline in next crawl."
                    ),
                    "expected_impact_delta_prob": round(min(0.14, 0.04 + 0.1 * sev), 4),
                    "effort": "low",
                    "ranking_signal": "internal PageRank / authority_flow_score",
                    "confidence": round(base_c * 0.88, 4),
                    "evidence": sig,
                }
            )
        elif it == "content_depth_gap":
            actions.append(
                {
                    "action_id": f"act_{i}_depth",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        f"Expand body to close gap vs competitor_proxy_word_count: "
                        f"current {sig.get('your_avg_word_count')} vs proxy {sig.get('competitor_proxy_word_count')} words."
                    ),
                    "expected_impact_delta_prob": round(min(0.16, 0.05 + 0.09 * sev), 4),
                    "effort": "medium",
                    "ranking_signal": "mean_ranking_score (content depth bucket) + gap_analysis",
                    "confidence": round(base_c * 0.85, 4),
                    "evidence": sig,
                }
            )
        elif it == "technical_indexability_blocker":
            actions.append(
                {
                    "action_id": f"act_{i}_indexability",
                    "issue_type": it,
                    "target_url": tgt or (sig.get("blockers_sample") or [""])[0],
                    "action": (
                        "Resolve final_indexability / simulation.will_index blockers on listed URLs; "
                        "re-run crawl to confirm indexable_ratio ≥0.58."
                    ),
                    "expected_impact_delta_prob": round(min(0.25, 0.1 + 0.12 * sev), 4),
                    "effort": "medium",
                    "ranking_signal": "indexable_ratio (v3 ranking_decision input)",
                    "confidence": round(base_c * 0.92, 4),
                    "evidence": sig,
                }
            )
        elif it == "prediction_serp_misalignment":
            actions.append(
                {
                    "action_id": f"act_{i}_gt_reconcile",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Reconcile model vs SERP: verify canonical URL matches monitored URL; "
                        "collect redundant SERP pass and re-check intent_truth vs topical row."
                    ),
                    "expected_impact_delta_prob": round(0.06 + 0.05 * sev, 4),
                    "effort": "low",
                    "ranking_signal": "ground_truth validation + ranking_probability calibration",
                    "confidence": round(base_c * 0.75, 4),
                    "evidence": sig,
                }
            )
        elif it == "high_serp_volatility":
            actions.append(
                {
                    "action_id": f"act_{i}_stabilize_sampling",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Increase SERP snapshot cadence + keep query/geo/provider constant; "
                        "delay major content rewrites until volatility <0.45 to avoid false positives."
                    ),
                    "expected_impact_delta_prob": 0.03,
                    "effort": "low",
                    "ranking_signal": "measurement quality (reduces false validation)",
                    "confidence": round(base_c * 0.7, 4),
                    "evidence": sig,
                }
            )
        elif it == "low_ground_truth_trust":
            actions.append(
                {
                    "action_id": f"act_{i}_serp_source",
                    "issue_type": it,
                    "target_url": "",
                    "action": (
                        "Fix SERP provider reliability (CSE/SerpAPI keys, pagination completeness) before scaling actions; "
                        "targets data_trust.fetch_success_rate and duplication_rate."
                    ),
                    "expected_impact_delta_prob": 0.02,
                    "effort": "low",
                    "ranking_signal": "trust in validation pipeline (indirect)",
                    "confidence": 0.55,
                    "evidence": sig,
                }
            )
        elif it in ("js_dependency_risk", "cloaking_signal", "low_trust_data", "serp_volatility_penalty"):
            actions.append(
                {
                    "action_id": f"act_{i}_penalty_{it}",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        f"Mitigate penalty «{it}» per v3 penalty engine — tie technical fix to resolved_signals "
                        f"(JS render parity / cloaking heuristics / trust inputs)."
                    ),
                    "expected_impact_delta_prob": round(min(0.2, abs(float(sig.get("penalty_impact", -0.12))) * 0.55), 4),
                    "effort": "high" if it == "cloaking_signal" else "medium",
                    "ranking_signal": "penalty_sum in ranking_decision_v3",
                    "confidence": round(base_c * 0.8, 4),
                    "evidence": sig,
                }
            )
        elif it == "weak_on_page_ranking_signals":
            actions.append(
                {
                    "action_id": f"act_{i}_onpage",
                    "issue_type": it,
                    "target_url": tgt or "",
                    "action": (
                        "Address limiting_factors from page ranking bundle: headings, orphan, JS, thin_content — "
                        "pick top 2 by frequency across page_audits."
                    ),
                    "expected_impact_delta_prob": round(min(0.15, 0.05 + 0.1 * sev), 4),
                    "effort": "medium",
                    "ranking_signal": "mean_ranking_score (compute_ranking_score stack)",
                    "confidence": round(base_c * 0.86, 4),
                    "evidence": sig,
                }
            )

    # Dedupe action_id collisions
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for a in actions:
        aid = str(a.get("action_id") or "")
        if aid in seen:
            continue
        seen.add(aid)
        deduped.append(a)
    return deduped[:30]
