"""
Advanced SEO decision engine (v2): multi-signal truth, suppression, dependencies, dynamic scoring.

Pipeline:
  1. resolve_seo_truth
  2. build context (from seo_rule_engine.build_page_rule_context)
  3. filter rules (suppression + dependencies)
  4. run rules
  5. dedupe / sort
  6. refine confidence + weighted score impact
  7. aggregate summary score
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.canonical_crawler import crawl_canonical_target
from app.services.js_analysis import compute_advanced_cloaking_analysis
from app.services.search_behavior import flatten_for_resolved_signals, resolve_search_engine_decision
from app.services.search_engine_simulator import simulate_google_indexing
from app.services.seo_normalize import normalize_url_safe
from app.services.seo_rule_engine import (
    RULES,
    build_page_rule_context,
    dedupe_and_prioritize_issues,
)

IssueFn = Callable[[dict[str, Any]], dict[str, Any] | None]


def _header_ci(headers: dict[str, Any] | None, name: str) -> str:
    if not headers:
        return ""
    want = name.lower()
    for k, v in headers.items():
        if str(k).lower() == want:
            return str(v).strip()
    return ""


def _has_noindex_none(text: str) -> bool:
    t = (text or "").lower()
    return "noindex" in t or "none" in t


def _norm_url_key(url: str) -> str:
    try:
        return (normalize_url_safe(url) if url else "").strip().lower().rstrip("/")
    except Exception:
        return (url or "").strip().lower().rstrip("/")


def _norm_host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        h = (urlparse(url or "").hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def resolve_seo_truth(data: dict[str, Any]) -> dict[str, Any]:
    """
    Merge HTTP, X-Robots-Tag (document), and meta robots into a single indexability verdict.

    Precedence: HTTP non-2xx → not indexable; then X-Robots-Tag on **final document** response;
    then meta robots on rendered HTML; then crawler ``indexability`` object as tie-breaker.
    """
    status = int(data.get("status") or 0)
    parsed = dict(data.get("parsed") or {})
    idx_layer = dict(data.get("indexability") or {})
    pw_h = dict(data.get("playwright_headers") or {})
    raw_h = dict(data.get("raw_headers") or {})
    cr = dict(data.get("canonical_resolution") or {})
    rvr = dict(data.get("raw_vs_rendered") or {})
    fe = (cr.get("final_effective_url") or data.get("url") or "").strip()

    xr_doc = _header_ci(pw_h, "x-robots-tag")
    xr_raw = _header_ci(raw_h, "x-robots-tag")
    meta_txt = (parsed.get("robots_meta") or "").strip()

    final_indexability = True
    indexability_source = "http"
    if status == 0 or status >= 400 or status < 200:
        final_indexability = False
        indexability_source = "http"
    elif _has_noindex_none(xr_doc):
        final_indexability = False
        indexability_source = "header"
    elif _has_noindex_none(meta_txt):
        final_indexability = False
        indexability_source = "meta"
    elif _has_noindex_none(xr_raw) and not _has_noindex_none(xr_doc):
        # Raw hop saw X-Robots noindex but final document headers differ — conservative: treat as blocked.
        final_indexability = False
        indexability_source = "header"
    else:
        final_indexability = bool(idx_layer.get("indexable", True))
        indexability_source = "meta" if meta_txt else "http"

    canon_resolved = (
        (cr.get("canonical_url") or "").strip()
        or (parsed.get("canonical") or "").strip()
        or fe
    )
    fe_host = _norm_host(fe)
    chost = _norm_host(canon_resolved)
    if not canon_resolved or canon_resolved == fe:
        canonical_type = "self"
    elif chost and fe_host and chost != fe_host:
        canonical_type = "cross-domain"
    else:
        canonical_type = "cross-url"

    if not final_indexability:
        canonical_valid = False
    else:
        canonical_valid = canonical_type in ("self", "cross-url", "cross-domain")

    jsl = str(data.get("js_seo_risk_level") or "low").lower()
    if jsl not in ("low", "medium", "high"):
        jsl = "low"
    if data.get("js_dependency") and jsl == "low":
        ratio = float(rvr.get("content_length_ratio") or 1.0)
        if ratio > 1.35 or ratio < 0.72:
            jsl = "medium"

    identical = bool(rvr.get("identical", True))
    ratio = float(rvr.get("content_length_ratio") or 1.0)
    len_r = int(rvr.get("raw_length") or 0)
    len_e = int(rvr.get("rendered_length") or 0)
    if identical and abs(ratio - 1.0) < 0.03:
        content_reliability = "raw"
    elif (not identical and max(len_r, len_e) > 800 and (ratio > 1.22 or ratio < 0.78)) or (
        not identical and len_e > len_r * 1.15
    ):
        content_reliability = "rendered"
    else:
        content_reliability = "mixed"

    return {
        "final_indexability": final_indexability,
        "indexability_source": indexability_source,
        "canonical_truth": canon_resolved or None,
        "canonical_type": canonical_type,
        "canonical_valid": canonical_valid,
        "js_dependency_level": jsl,
        "content_reliability": content_reliability,
        "x_robots_tag_document": xr_doc or None,
        "meta_robots_rendered": meta_txt or None,
    }


RULE_ID_BY_FN: dict[str, str] = {fn.__name__: fn.__name__.replace("evaluate_", "") for fn in RULES}

INDEX_CORE_RULES = frozenset(
    {
        "indexability_blocked",
        "indexability_signal_conflict",
        "http_status_non_200",
        "robots_meta_noindex_contradiction",
        "cloaking_heuristic",
        "js_seo_risk_high",
        "js_seo_risk_medium",
        "js_shell_missing_critical",
        "canonical_points_to_non_indexable",
        "canonical_low_similarity_mismatch",
        "google_may_ignore_canonical",
        "page_unlikely_indexed",
        "cloaking_risk_advanced",
    }
)
CONTENT_RULES = frozenset(
    {
        "missing_title",
        "title_too_long",
        "missing_meta_description",
        "thin_content",
        "images_missing_alt",
    }
)
STRUCTURE_RULES = frozenset({"missing_h1", "multiple_h1", "weak_heading_structure"})
CANONICAL_RULES = frozenset(
    {
        "canonical_cross_host",
        "canonical_self_mismatch",
        "canonical_missing_high_value",
        "canonical_points_to_non_indexable",
        "canonical_low_similarity_mismatch",
        "google_may_ignore_canonical",
    }
)


def _redirect_detected(data: dict[str, Any]) -> bool:
    rh = data.get("redirect_history") or []
    return isinstance(rh, list) and len(rh) >= 2


def should_run_rule(rule_id: str, resolved_signals: dict[str, Any], context: dict[str, Any]) -> bool:
    """Return False to suppress a rule for this URL (irrelevant or overridden by stronger signals)."""
    st = int(context.get("status") or 0)
    fin = bool(resolved_signals.get("final_indexability"))

    if not fin:
        return rule_id in INDEX_CORE_RULES

    if st != 200:
        if rule_id in CONTENT_RULES | STRUCTURE_RULES | CANONICAL_RULES:
            return False

    if _redirect_detected(context):
        if rule_id in CONTENT_RULES | STRUCTURE_RULES:
            return False

    return True


RULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "canonical_cross_host": ("canonical_truth",),
    "canonical_self_mismatch": ("canonical_truth",),
}


def _dependencies_satisfied(rule_id: str, resolved_signals: dict[str, Any]) -> bool:
    deps = RULE_DEPENDENCIES.get(rule_id, ())
    for key in deps:
        val = resolved_signals.get(key)
        if key == "canonical_truth" and not (val or "").strip():
            return False
    return True


BUSINESS_IMPACT_WEIGHT: dict[str, float] = {
    "indexability": 1.5,
    "technical": 1.22,
    "content": 1.0,
    "structure": 0.95,
}

SEVERITY_BASE: dict[str, float] = {"high": 15.0, "medium": 8.0, "low": 3.0}


def _refine_confidence(
    issue: dict[str, Any],
    context: dict[str, Any],
    resolved_signals: dict[str, Any],
) -> float:
    c = float(issue.get("confidence") or 0.72)
    boost = 0.0
    detected = issue.get("detected_from") or []
    if isinstance(detected, list):
        boost += min(0.06, 0.012 * len(detected))

    if resolved_signals.get("content_reliability") == "rendered" and issue.get("category") == "content":
        boost += 0.035

    rid = str(issue.get("rule_id") or "")
    if rid == "indexability_blocked" and not resolved_signals.get("final_indexability"):
        boost += 0.04

    cr = context.get("crawl_record") or {}
    completeness = sum(
        1
        for k in (
            "indexability",
            "canonical_resolution",
            "raw_vs_rendered",
            "seo_signals",
            "response_headers",
        )
        if cr.get(k) is not None
    )
    boost += min(0.04, 0.008 * completeness)

    if resolved_signals.get("js_dependency_level") == "high" and issue.get("category") in ("content", "structure"):
        c *= 0.86

    if resolved_signals.get("indexability_source") == "header" and rid.startswith("indexability"):
        boost += 0.02

    return round(min(0.98, max(0.11, c + boost)), 3)


def _weighted_score_impact(
    issue: dict[str, Any],
    context: dict[str, Any],
    resolved_signals: dict[str, Any],
    refined_confidence: float,
) -> float:
    sev = str(issue.get("severity") or "low").lower()
    base = float(SEVERITY_BASE.get(sev, 3.0))
    cat = str(issue.get("category") or "content")
    w = float(BUSINESS_IMPACT_WEIGHT.get(cat, 1.0))
    imp = base * w
    if str(context.get("page_type") or "") == "homepage":
        imp *= 1.5
    if refined_confidence < 0.6:
        imp *= 0.35 + 0.65 * refined_confidence
    else:
        imp *= 0.88 + 0.12 * refined_confidence
    return round(max(0.0, imp), 2)


def run_decision_engine_v2(
    url: str,
    parsed: dict[str, Any],
    page_type: str,
    crawl_record: dict[str, Any] | None,
) -> dict[str, Any]:
    status = int(parsed.get("status") or 0)
    data = build_page_rule_context(
        url=url, status=status, parsed=parsed, page_type=page_type, crawl_record=crawl_record
    )
    data["crawl_record"] = dict(crawl_record or {})

    pre_signals = resolve_seo_truth(data)

    cr = dict(data.get("crawl_record") or {})
    raw_html = str(data.get("raw_html") or cr.get("raw_html") or "")
    rendered_html = str(data.get("rendered_html") or cr.get("rendered_html") or cr.get("html") or "")
    cloaking_advanced = compute_advanced_cloaking_analysis(
        raw_html,
        rendered_html,
        html_compare=dict(data.get("raw_vs_rendered") or {}),
        parsed=parsed,
    )
    data["cloaking_advanced"] = cloaking_advanced

    canon_truth = (pre_signals.get("canonical_truth") or "").strip()
    fe_url = (data.get("canonical_resolution") or {}).get("final_effective_url") or url
    fe_url = str(fe_url or "").strip()
    cta: dict[str, Any]
    if int(status or 0) == 200 and canon_truth and _norm_url_key(canon_truth) != _norm_url_key(fe_url):
        cta = crawl_canonical_target(
            fe_url,
            canon_truth,
            source_html=rendered_html or raw_html,
            timeout_seconds=12.0,
        )
    else:
        cta = {
            "fetched": False,
            "target_status": None,
            "target_indexable": True,
            "target_title": "",
            "similarity_score": None,
            "canonical_chain_valid": True,
            "target_canonical_href": None,
            "canonical_points_back_to_source": False,
            "fetch_error": None,
        }
    data["canonical_target_analysis"] = cta

    search_decision = resolve_search_engine_decision(data)
    data["search_engine_decision"] = search_decision
    resolved_signals = {**pre_signals, **flatten_for_resolved_signals(search_decision, data)}
    data["final_indexability_resolved"] = resolved_signals["final_indexability"]

    sim_payload = dict(data)
    sim_payload["resolved_signals"] = resolved_signals
    sim_payload["canonical_target_analysis"] = cta
    sim_payload["cloaking_advanced"] = cloaking_advanced
    google_simulation = simulate_google_indexing(sim_payload)
    sb_sim = dict(search_decision.get("indexing_simulation") or {})
    if "will_index" in sb_sim:
        google_simulation["will_index"] = bool(sb_sim["will_index"])
    if sb_sim.get("indexation_reason"):
        google_simulation["index_decision_reason"] = str(sb_sim["indexation_reason"])
    if sb_sim.get("trust_score") is not None:
        google_simulation["trust_score"] = float(sb_sim["trust_score"])
    if "duplicate_cluster" in sb_sim:
        google_simulation["duplicate_cluster"] = list(sb_sim.get("duplicate_cluster") or [])
    data["google_simulation"] = google_simulation

    resolved_signals = {
        **resolved_signals,
        "google_simulation": google_simulation,
        "canonical_target_analysis": cta,
        "cloaking_advanced": cloaking_advanced,
    }
    data["resolved_signals"] = resolved_signals

    raw_issues: list[dict[str, Any]] = []
    for fn in RULES:
        rid = RULE_ID_BY_FN.get(fn.__name__, "")
        if not rid:
            continue
        if not should_run_rule(rid, resolved_signals, data):
            continue
        if not _dependencies_satisfied(rid, resolved_signals):
            continue
        try:
            issue = fn(data)
        except Exception:
            issue = None
        if not issue:
            continue
        issue = dict(issue)
        issue["rule_id"] = rid
        issue["suppressed"] = False
        issue["suppression_reason"] = None
        issue["decision_source"] = "multi_signal_v2"
        rc = _refine_confidence(issue, data, resolved_signals)
        issue["confidence"] = rc
        issue["adjusted_score_impact"] = _weighted_score_impact(issue, data, resolved_signals, rc)
        raw_issues.append(issue)

    serp_extra = list((cr or {}).get("serp_synthetic_issues") or [])
    for issue in serp_extra:
        if not isinstance(issue, dict):
            continue
        issue = dict(issue)
        if not str(issue.get("rule_id") or "").strip():
            continue
        issue.setdefault("suppressed", False)
        issue.setdefault("suppression_reason", None)
        issue.setdefault("decision_source", "serp_competitor_intelligence")
        rc = _refine_confidence(issue, data, resolved_signals)
        issue["confidence"] = rc
        issue["adjusted_score_impact"] = _weighted_score_impact(issue, data, resolved_signals, rc)
        raw_issues.append(issue)

    issues = dedupe_and_prioritize_issues(raw_issues)
    total_impact = sum(float(i.get("adjusted_score_impact") or 0) for i in issues)
    score = max(0.0, min(100.0, round(100.0 - total_impact, 1)))
    critical_count = sum(1 for i in issues if str(i.get("severity")) == "high")

    post_cap = 100.0
    if google_simulation.get("will_index") is False:
        post_cap = min(post_cap, 50.0)
    if not bool(cta.get("canonical_chain_valid", True)) and cta.get("fetched"):
        post_cap = min(post_cap, 44.0)
    elif cta.get("fetched") and not bool(cta.get("target_indexable", True)):
        post_cap = min(post_cap, 46.0)
    if str(cloaking_advanced.get("cloaking_risk_level") or "").lower() == "high":
        post_cap = min(post_cap, 40.0)
    score = min(score, post_cap)

    return {
        "url": url,
        "resolved_signals": resolved_signals,
        "search_engine_decision": search_decision,
        "simulation": google_simulation,
        "canonical_target": cta,
        "cloaking_analysis": cloaking_advanced,
        "summary": {
            "score": score,
            "total_issues": len(issues),
            "critical_count": critical_count,
            "total_weighted_impact": round(total_impact, 2),
        },
        "issues": issues,
    }


def run_seo_decision_layer_v2(
    url: str,
    parsed: dict[str, Any],
    page_type: str,
    crawl_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Public entry used by ``seo_rule_engine.run_seo_decision_layer``."""
    return run_decision_engine_v2(url, parsed, page_type, crawl_record)
