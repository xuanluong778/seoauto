"""
Google-like indexing *simulation* for audits: consolidation, noindex, HTTP gates, JS/cloaking trust.

This is a behavioral model for prioritization — not a guarantee of live Google behavior.
"""

from __future__ import annotations

from typing import Any

from app.services.seo_normalize import normalize_url_safe


def _norm(u: str) -> str:
    return (normalize_url_safe(u) if u else "").strip().lower().rstrip("/")


def simulate_google_indexing(data: dict[str, Any]) -> dict[str, Any]:
    """
    Merge crawl + resolved truth + optional canonical-target crawl into a single verdict.

    ``data`` should include at least: ``url``, ``status``, ``parsed``, ``canonical_resolution``,
    ``raw_vs_rendered``, ``resolved_signals`` (from ``resolve_seo_truth``), optional
    ``canonical_target_analysis``, ``cloaking_advanced``, and boolean ``cloaking_risk``.
    """
    status = int(data.get("status") or 0)
    url = (data.get("url") or "").strip()
    parsed = dict(data.get("parsed") or {})
    cr = dict(data.get("canonical_resolution") or {})
    rs = dict(data.get("resolved_signals") or {})
    rvr = dict(data.get("raw_vs_rendered") or {})
    cta = dict(data.get("canonical_target_analysis") or {})
    cloak_adv = dict(data.get("cloaking_advanced") or {})

    fe = (cr.get("final_effective_url") or url).strip()
    canon = (rs.get("canonical_truth") or parsed.get("canonical") or fe or "").strip()
    fin = bool(rs.get("final_indexability", True))
    ctype = str(rs.get("canonical_type") or "self")

    ignored_signals: list[str] = []
    reason_parts: list[str] = []

    will_index = True
    if status >= 400:
        will_index = False
        reason_parts.append(
            "HTTP status is 4xx/5xx — Google typically does not treat the response as a normal indexable document."
        )
    elif status > 0 and status < 200:
        will_index = False
        reason_parts.append("Non-success HTTP status before 200 — indexing as a stable document is unlikely.")

    if not fin:
        will_index = False
        reason_parts.append(
            "Resolved indexability is false (noindex/none, blocking headers, or failed fetch) — URL should not enter the index as intended."
        )

    primary_url = fe or url
    canonical_chosen = canon or fe or url
    canonical_source: str = "declared"

    external = bool(canon) and _norm(canon) != _norm(fe) and status < 400 and fin
    sim_score = cta.get("similarity_score")
    sim_f = float(sim_score) if isinstance(sim_score, (int, float)) else None
    fetched = bool(cta.get("fetched"))
    target_ok = bool(cta.get("target_indexable", True))
    chain_ok = bool(cta.get("canonical_chain_valid", True))

    raw_canon = (rvr.get("canonical_raw_normalized") or "").strip()
    ren_canon = (rvr.get("canonical_rendered_normalized") or "").strip()
    canon_dom_conflict = bool(raw_canon and ren_canon and raw_canon != ren_canon)

    if external:
        canonical_chosen = canon
        if not fetched:
            primary_url = canon
            will_index = False
            reason_parts.append(
                "Declared canonical points to a different URL — this URL is modeled as a non-primary duplicate (canonical target treated as primary consolidation URL)."
            )
            ignored_signals.append("canonical_target_not_probed")
        elif not chain_ok:
            will_index = False
            canonical_source = "google_selected"
            primary_url = fe or url
            reason_parts.append(
                "Canonical chain looks cyclic or contradictory (e.g. target declares canonical back here) — model treats consolidation as unreliable; this URL may be dropped or handled conservatively."
            )
            ignored_signals.append("declared_canonical_hierarchy")
        elif not target_ok:
            will_index = False
            primary_url = fe or url
            canonical_chosen = fe or url
            canonical_source = "google_selected"
            reason_parts.append(
                "Canonical target is not indexable — Google is unlikely to honor consolidation to that URL; this URL may be orphaned or excluded."
            )
            ignored_signals.append("canonical_target_not_indexable")
        elif sim_f is not None and sim_f < 0.40:
            canonical_source = "google_selected"
            primary_url = fe or url
            canonical_chosen = fe or url
            reason_parts.append(
                "Low lexical/content similarity vs canonical target with conflicting consolidation signals — behaviorally similar to cases where Google keeps the crawled URL or picks its own cluster primary."
            )
            ignored_signals.append("declared_canonical_low_similarity")
            if canon_dom_conflict:
                ignored_signals.append("raw_vs_rendered_canonical_disagreement")
        else:
            primary_url = canon
            reason_parts.append(
                "Strong declared canonical to an indexable target with acceptable similarity — model expects this URL to consolidate away from the index as a standalone document."
            )
            will_index = False

    if external and ctype == "cross-domain" and fetched and target_ok and chain_ok and (sim_f is None or sim_f >= 0.40):
        ignored_signals.append("cross_domain_canonical_property_boundary")

    ranking_eligibility: str = "high"
    cloak_level = str(cloak_adv.get("cloaking_risk_level") or "low").lower()
    if bool(data.get("cloaking_risk")) or cloak_level == "high":
        ranking_eligibility = "low"
        reason_parts.append("Cloaking-style divergence (heuristic + text/DOM similarity) lowers ranking eligibility.")
    elif cloak_level == "medium":
        ranking_eligibility = "medium"

    miss_raw = rvr.get("missing_elements_in_raw") or []
    critical_missing = isinstance(miss_raw, list) and (
        "title" in miss_raw or "H1" in miss_raw or "meta_description" in miss_raw
    )
    js_dep = str(rs.get("js_dependency_level") or "low").lower()
    content_rel = str(rs.get("content_reliability") or "raw").lower()

    if critical_missing and (js_dep in ("medium", "high") or content_rel == "rendered"):
        if ranking_eligibility == "high":
            ranking_eligibility = "medium"
        reason_parts.append(
            "Meaningful body/title/meta signals appear only after JS — ranking signals may be delayed or weaker in early crawl stages."
        )
        ignored_signals.append("raw_document_incomplete_for_primary_signals")

    if not reason_parts:
        reason_parts.append(
            "Signals are broadly consistent with a normal indexable URL and predictable canonical handling."
        )

    return {
        "will_index": bool(will_index),
        "primary_url": primary_url,
        "index_decision_reason": " ".join(reason_parts).strip(),
        "canonical_chosen": canonical_chosen,
        "canonical_source": canonical_source if canonical_source in ("declared", "google_selected") else "declared",
        "ignored_signals": sorted(set(ignored_signals)),
        "ranking_eligibility": ranking_eligibility,
    }
