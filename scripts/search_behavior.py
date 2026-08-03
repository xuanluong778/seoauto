"""
Single source of truth for Google-like resolution: indexability, canonical, primary URL,
indexing simulation, signal reliability, and conflicts.

``data`` matches ``build_page_rule_context`` output (+ ``canonical_target_analysis`` when available).
"""

from __future__ import annotations

from typing import Any

from app.services.seo_normalize import normalize_url_safe


def _norm(u: str) -> str:
    return (normalize_url_safe(u) if u else "").strip().lower().rstrip("/")


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


def _norm_host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        h = (urlparse(url or "").hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def resolve_final_indexability(data: dict[str, Any]) -> dict[str, Any]:
    """
    Strict precedence:
    1) HTTP status
    2) X-Robots-Tag (final document response — Playwright headers)
    3) meta robots (rendered parsed)
    4) crawler indexability fallback
    """
    status = int(data.get("status") or 0)
    parsed = dict(data.get("parsed") or {})
    idx = dict(data.get("indexability") or {})
    pw_h = dict(data.get("playwright_headers") or {})
    raw_h = dict(data.get("raw_headers") or {})
    meta_txt = (parsed.get("robots_meta") or "").strip()

    xr_doc = _header_ci(pw_h, "x-robots-tag")
    xr_raw = _header_ci(raw_h, "x-robots-tag")

    conflict = False
    crawl_idx = bool(idx.get("indexable", True))
    meta_blocks = _has_noindex_none(meta_txt)
    header_doc_blocks = _has_noindex_none(xr_doc)
    header_raw_blocks = _has_noindex_none(xr_raw)

    if meta_blocks and not header_doc_blocks and crawl_idx:
        conflict = True
    if header_raw_blocks != header_doc_blocks and (header_raw_blocks or header_doc_blocks):
        conflict = True

    final = True
    source = "fallback"
    confidence = 0.88

    if status == 0 or status >= 400 or status < 200:
        final = False
        source = "http"
        confidence = 0.98
    elif header_doc_blocks:
        final = False
        source = "header"
        confidence = 0.96
        if meta_blocks and not conflict:
            conflict = True
    elif meta_blocks:
        final = False
        source = "meta"
        confidence = 0.9
    elif header_raw_blocks and not header_doc_blocks:
        final = False
        source = "header"
        confidence = 0.82
        conflict = True
    else:
        final = crawl_idx
        source = "fallback"
        confidence = float(idx.get("indexability_confidence") or 0.75)
        if not crawl_idx and (not meta_txt and not xr_doc):
            confidence = min(confidence, 0.55)

    if conflict:
        confidence = max(0.35, confidence - 0.12)

    return {
        "final_indexable": bool(final),
        "decision_source": source,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "conflict_detected": bool(conflict),
    }


def compute_signal_reliability(data: dict[str, Any]) -> dict[str, Any]:
    """Heuristic reliability tiers for signal classes."""
    status = int(data.get("status") or 0)
    rvr = dict(data.get("raw_vs_rendered") or {})
    identical = bool(rvr.get("identical", True))
    ratio = float(rvr.get("content_length_ratio") or 1.0)

    http_rel = 1.0 if 200 <= status < 400 else 0.55 if status else 0.5

    pw_h = dict(data.get("playwright_headers") or {})
    header_rel = 0.95 if _header_ci(pw_h, "x-robots-tag") or _header_ci(pw_h, "content-type") else 0.72

    meta_rel = 0.88 if (dict(data.get("parsed") or {}).get("robots_meta") or "").strip() else 0.55

    if identical and abs(ratio - 1.0) < 0.04:
        dom_rel = 0.92
    elif float(rvr.get("raw_length") or 0) > 400 and (ratio > 1.2 or ratio < 0.78):
        dom_rel = 0.58
    else:
        dom_rel = 0.72

    overall = round(
        http_rel * 0.28 + header_rel * 0.24 + meta_rel * 0.22 + dom_rel * 0.26,
        3,
    )
    overall = max(0.0, min(1.0, overall))
    return {
        "http_reliability": round(http_rel, 3),
        "header_reliability": round(header_rel, 3),
        "meta_reliability": round(meta_rel, 3),
        "dom_reliability": round(dom_rel, 3),
        "overall_reliability": overall,
    }


def detect_signal_conflicts(data: dict[str, Any], idx_res: dict[str, Any] | None = None) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    parsed = dict(data.get("parsed") or {})
    rvr = dict(data.get("raw_vs_rendered") or {})
    cr = dict(data.get("canonical_resolution") or {})
    pw_h = dict(data.get("playwright_headers") or {})
    raw_h = dict(data.get("raw_headers") or {})

    xr_doc = _header_ci(pw_h, "x-robots-tag").lower()
    meta = (parsed.get("robots_meta") or "").lower()
    if meta and xr_doc and _has_noindex_none(meta) != _has_noindex_none(xr_doc):
        conflicts.append(
            {
                "type": "header_vs_meta_robots",
                "detail": "X-Robots-Tag and meta robots disagree on noindex/none semantics.",
            }
        )

    rc = (rvr.get("canonical_raw_normalized") or "").strip()
    rr = (rvr.get("canonical_rendered_normalized") or "").strip()
    if rc and rr and rc != rr:
        conflicts.append(
            {
                "type": "raw_vs_rendered_canonical",
                "detail": f"raw={rc[:120]} rendered={rr[:120]}",
            }
        )

    fe = (cr.get("final_effective_url") or data.get("url") or "").strip()
    rh = list(data.get("redirect_history") or [])
    if isinstance(rh, list) and len(rh) >= 2 and fe:
        last = str(rh[-1].get("url") if isinstance(rh[-1], dict) else rh[-1] or "")
        if last and _norm(last) != _norm(fe):
            conflicts.append(
                {
                    "type": "canonical_vs_redirect_final",
                    "detail": "Redirect chain terminal differs from canonical_resolution.final_effective_url.",
                }
            )

    idx_res = idx_res or {}
    if idx_res.get("conflict_detected"):
        conflicts.append({"type": "indexability_signal_mix", "detail": "Indexability sources partially disagree."})

    sev = "low"
    if any(c["type"] in ("header_vs_meta_robots", "raw_vs_rendered_canonical") for c in conflicts):
        sev = "high" if len(conflicts) >= 2 else "medium"

    return {"conflicts": conflicts, "severity": sev}


def resolve_canonical_behavior(data: dict[str, Any], idx: dict[str, Any]) -> dict[str, Any]:
    """
    Google-like canonical handling using declared canonical, final URL, raw vs rendered,
    canonical_target_analysis (similarity, chain, target indexability).
    """
    url = str(data.get("url") or "").strip()
    parsed = dict(data.get("parsed") or {})
    cr = dict(data.get("canonical_resolution") or {})
    rvr = dict(data.get("raw_vs_rendered") or {})
    cta = dict(data.get("canonical_target_analysis") or {})

    fe = (cr.get("final_effective_url") or url).strip()
    declared = (parsed.get("canonical") or cr.get("canonical_url") or "").strip()
    ren_c = (rvr.get("canonical_rendered_normalized") or "").strip()
    if declared:
        canon_candidate = declared
    elif ren_c:
        canon_candidate = ren_c
    else:
        canon_candidate = fe

    if not idx.get("final_indexable", True):
        return {
            "canonical_chosen": fe or url,
            "canonical_source": "self",
            "canonical_valid": False,
            "canonical_reason": "Page not indexable — canonical consolidation is irrelevant for indexing.",
        }

    if not canon_candidate or _norm(canon_candidate) == _norm(fe):
        return {
            "canonical_chosen": fe or url,
            "canonical_source": "self",
            "canonical_valid": True,
            "canonical_reason": "Self URL or no alternate canonical; effective URL is the primary document.",
        }

    sim = cta.get("similarity_score")
    sim_f = float(sim) if isinstance(sim, (int, float)) else None
    fetched = bool(cta.get("fetched"))
    chain_ok = bool(cta.get("canonical_chain_valid", True))
    target_ok = bool(cta.get("target_indexable", True))

    if not chain_ok:
        return {
            "canonical_chosen": fe or url,
            "canonical_source": "google_selected",
            "canonical_valid": False,
            "canonical_reason": "Canonical loop or contradictory chain — ignore declared canonical.",
        }
    if fetched and not target_ok:
        return {
            "canonical_chosen": fe or url,
            "canonical_source": "google_selected",
            "canonical_valid": False,
            "canonical_reason": "Canonical target is not indexable — model ignores consolidation to that URL.",
        }
    if sim_f is not None and sim_f < 0.38:
        return {
            "canonical_chosen": fe or url,
            "canonical_source": "google_selected",
            "canonical_valid": False,
            "canonical_reason": "Low similarity to canonical target — likely alternate URL; Google may pick crawled URL.",
        }
    if not fetched:
        return {
            "canonical_chosen": canon_candidate,
            "canonical_source": "declared",
            "canonical_valid": False,
            "canonical_reason": "Declared canonical points away but target not probed — conservative: invalid for consolidation.",
        }

    return {
        "canonical_chosen": canon_candidate,
        "canonical_source": "declared",
        "canonical_valid": True,
        "canonical_reason": "Declared canonical to probed, indexable target with acceptable similarity and valid chain.",
    }


def resolve_primary_url(data: dict[str, Any], canon: dict[str, Any]) -> dict[str, Any]:
    cr = dict(data.get("canonical_resolution") or {})
    url = str(data.get("url") or "").strip()
    fe = (cr.get("final_effective_url") or url).strip()
    if canon.get("canonical_valid") and canon.get("canonical_source") == "declared":
        pu = str(canon.get("canonical_chosen") or fe).strip()
        is_primary = _norm(pu) == _norm(fe)
        return {"primary_url": pu, "is_primary": is_primary}
    pu = fe or url
    return {"primary_url": pu, "is_primary": True}


def simulate_indexing_behavior(
    data: dict[str, Any],
    idx: dict[str, Any],
    canon: dict[str, Any],
    primary: dict[str, Any],
    reliability: dict[str, Any],
) -> dict[str, Any]:
    """Simulate index vs duplicate consolidation with trust score."""
    status = int(data.get("status") or 0)
    cloak = dict(data.get("cloaking_advanced") or {})
    cta = dict(data.get("canonical_target_analysis") or {})
    fe = str(dict(data.get("canonical_resolution") or {}).get("final_effective_url") or data.get("url") or "").strip()
    chosen = str(canon.get("canonical_chosen") or fe).strip()

    duplicate_cluster: list[str] = []
    reasons: list[str] = []
    will_index = True
    trust = float(reliability.get("overall_reliability") or 0.75)

    if status >= 400 or status < 200:
        will_index = False
        reasons.append("HTTP not in 2xx success range.")
    elif not idx.get("final_indexable", True):
        will_index = False
        reasons.append("Resolved indexability is false.")
    elif canon.get("canonical_valid") and canon.get("canonical_source") == "declared" and _norm(chosen) != _norm(fe):
        will_index = False
        duplicate_cluster = sorted({_norm(fe), _norm(chosen)})
        reasons.append("Valid declared canonical to another URL — this URL modeled as duplicate/non-primary.")
    elif str(canon.get("canonical_source")) == "google_selected" and _norm(chosen) == _norm(fe):
        reasons.append("Google-selected effective URL retained as primary document surface.")
        will_index = True

    cloak_lvl = str(cloak.get("cloaking_risk_level") or "low").lower()
    if bool(data.get("cloaking_risk")) or cloak_lvl == "high":
        trust *= 0.62
        reasons.append("Cloaking heuristic / advanced risk lowers trust.")
    elif cloak_lvl == "medium":
        trust *= 0.82
        reasons.append("Medium cloaking divergence — trust reduced.")

    if not reasons:
        reasons.append("Signals consistent with normal indexing for this URL.")

    return {
        "will_index": bool(will_index),
        "indexation_reason": " ".join(reasons).strip(),
        "duplicate_cluster": duplicate_cluster,
        "trust_score": round(max(0.0, min(1.0, trust)), 3),
    }


def _signals_snapshot(
    data: dict[str, Any],
    idx: dict[str, Any],
    canon: dict[str, Any],
    primary: dict[str, Any],
    sim: dict[str, Any],
    rel: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    parsed = dict(data.get("parsed") or {})
    return {
        "http_status": int(data.get("status") or 0),
        "x_robots_playwright": _header_ci(dict(data.get("playwright_headers") or {}), "x-robots-tag") or None,
        "x_robots_raw": _header_ci(dict(data.get("raw_headers") or {}), "x-robots-tag") or None,
        "meta_robots_rendered": (parsed.get("robots_meta") or "")[:500] or None,
        "crawler_indexable": dict(data.get("indexability") or {}).get("indexable"),
        "canonical_resolution": dict(data.get("canonical_resolution") or {}),
        "raw_vs_rendered_canonical": {
            "raw": (dict(data.get("raw_vs_rendered") or {}).get("canonical_raw_normalized") or ""),
            "rendered": (dict(data.get("raw_vs_rendered") or {}).get("canonical_rendered_normalized") or ""),
        },
        "canonical_target_analysis": dict(data.get("canonical_target_analysis") or {}),
        "resolved": {
            "final_indexability": idx,
            "canonical_behavior": canon,
            "primary_url": primary,
            "indexing_simulation": sim,
            "signal_reliability": rel,
            "conflicts": conf,
        },
    }


def compute_rendering_signals(data: dict[str, Any]) -> dict[str, str]:
    """JS / raw-vs-rendered reliability (same heuristics as legacy ``resolve_seo_truth``)."""
    rvr = dict(data.get("raw_vs_rendered") or {})
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

    return {"js_dependency_level": jsl, "content_reliability": content_reliability}


def resolve_search_engine_decision(data: dict[str, Any]) -> dict[str, Any]:
    """
    Full merge: indexability → reliability → conflicts → canonical → primary → indexing.

    Requires ``canonical_target_analysis`` on ``data`` for best canonical verdict (caller adds after probe).
    """
    url = str(data.get("url") or "").strip()
    idx = resolve_final_indexability(data)
    rel = compute_signal_reliability(data)
    conf = detect_signal_conflicts(data, idx)
    canon = resolve_canonical_behavior(data, idx)
    primary = resolve_primary_url(data, canon)
    sim = simulate_indexing_behavior(data, idx, canon, primary, rel)
    snap = _signals_snapshot(data, idx, canon, primary, sim, rel, conf)

    return {
        "url": url,
        "final_indexability": idx,
        "canonical_behavior": canon,
        "primary_url": primary,
        "indexing_simulation": sim,
        "signal_reliability": rel,
        "conflicts": conf,
        "signals_snapshot": snap,
    }


def flatten_for_resolved_signals(decision: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Map search_behavior output to keys consumed by ``simulate_google_indexing`` / rules."""
    idx = dict(decision.get("final_indexability") or {})
    canon = dict(decision.get("canonical_behavior") or {})
    fe = (dict(data.get("canonical_resolution") or {}).get("final_effective_url") or data.get("url") or "").strip()
    chosen = str(canon.get("canonical_chosen") or fe).strip()
    ctype = "self"
    if chosen and fe and _norm(chosen) != _norm(fe):
        if _norm_host(chosen) == _norm_host(fe):
            ctype = "cross-url"
        else:
            ctype = "cross-domain"

    render = compute_rendering_signals(data)
    return {
        "final_indexability": bool(idx.get("final_indexable")),
        "indexability_source": str(idx.get("decision_source") or "fallback"),
        "indexability_confidence": float(idx.get("confidence") or 0.8),
        "canonical_truth": chosen,
        "canonical_type": ctype,
        "canonical_valid": bool(canon.get("canonical_valid")),
        "js_dependency_level": render["js_dependency_level"],
        "content_reliability": render["content_reliability"],
        "search_engine_decision": decision,
    }
