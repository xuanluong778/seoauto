"""
SEO Autopilot: detect → act → prioritize → roadmap → validate → learn.

Integrates ``build_seo_intelligence_core_v3`` output with ``build_seo_ground_truth_bundle`` slices.
"""

from __future__ import annotations

from typing import Any

from app.services.action_generator import generate_actions
from app.services.execution_planner import build_execution_roadmap
from app.services.issue_detection_engine import detect_issues
from app.services.learning_engine import build_learning_feedback
from app.services.prioritization_engine import prioritize_actions
from app.services.validation_engine import build_validation_plan, evaluate_action_outcome


def build_seo_autopilot_bundle(
    *,
    core_v3: dict[str, Any],
    ground_truth_bundle: dict[str, Any] | None,
    queries: list[str],
    monitored_url: str,
    context: dict[str, Any] | None = None,
    include_validation_sample: bool = True,
) -> dict[str, Any]:
    """
    ``queries``: GSC / cluster queries used for SERP ground truth (first drives validation plan).

    ``context``: optional ``start_url``, ``monitored_urls`` list for ``issue_detection_engine``.

    Returns keys: ``issues``, ``top_actions``, ``roadmap``, ``validation_plan``, ``learning_feedback``.
    """
    ctx = dict(context or {})
    if monitored_url and not ctx.get("start_url"):
        ctx["start_url"] = monitored_url
    if monitored_url and not ctx.get("monitored_urls"):
        ctx["monitored_urls"] = [monitored_url]

    issues = detect_issues(core_v3, ground_truth_bundle, context=ctx)
    raw_actions = generate_actions(issues, core_v3=core_v3, ground_truth_bundle=ground_truth_bundle, context=ctx)
    prioritized = prioritize_actions(raw_actions)
    roadmap = build_execution_roadmap(prioritized)
    vplan = build_validation_plan(
        prioritized,
        queries=queries,
        monitored_url=monitored_url,
        ground_truth_bundle=ground_truth_bundle,
    )

    sample_val: dict[str, Any] | None = None
    if include_validation_sample and prioritized and queries and monitored_url:
        top = prioritized[0]
        sample_val = evaluate_action_outcome(
            query=str(queries[0]).strip(),
            monitored_url=monitored_url,
            predicted_impact_delta_prob=float(top.get("expected_impact_delta_prob") or 0.0),
        )
        sample_val["action_id"] = top.get("action_id")

    learning_feedback = build_learning_feedback()
    if sample_val:
        learning_feedback = [
            {
                "type": "live_validation_sample",
                "detail": sample_val,
                "explain": "Uses first prioritized action + oldest/newest snapshots only (not causally attributed).",
            },
            *learning_feedback,
        ]

    return {
        "issues": issues,
        "top_actions": prioritized[:20],
        "roadmap": roadmap,
        "validation_plan": vplan,
        "learning_feedback": learning_feedback,
        "meta": {
            "queries_used": [str(q).strip() for q in queries[:8] if str(q).strip()],
            "monitored_url": monitored_url,
            "core_version": core_v3.get("version"),
        },
    }
