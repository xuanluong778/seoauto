"""
JS SEO risk and cloaking-style heuristics from raw vs rendered snapshots.

Scores are conservative heuristics for triage, not proof of malicious cloaking.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_js_seo_risk(html_compare: dict[str, Any]) -> dict[str, Any]:
    """
    Rules (additive, capped at 1.0):
      - DOM materially different: +0.3
      - Title mismatch: +0.3
      - H1 present only after render (in missing_elements_in_raw as H1): +0.4
    """
    score = 0.0
    if not html_compare.get("identical", True):
        score += 0.3
    if not html_compare.get("title_match", True):
        score += 0.3
    miss_raw = html_compare.get("missing_elements_in_raw") or []
    if isinstance(miss_raw, list) and "H1" in miss_raw:
        score += 0.4
    score = _clamp01(score)
    if score < 0.35:
        level = "low"
    elif score < 0.65:
        level = "medium"
    else:
        level = "high"
    return {"js_seo_risk_score": round(score, 3), "js_seo_risk_level": level}


def _strip_boilerplate_html(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")


def _tokenize_words(text: str, limit: int = 12_000) -> list[str]:
    return re.findall(r"[a-z0-9\u00c0-\u024f]+", (text or "").lower())[:limit]


def _cosine_from_counters(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    vocab = set(a) | set(b)
    dot = 0.0
    na = 0.0
    nb = 0.0
    for w in vocab:
        va = 1.0 + math.log(a[w]) if w in a else 0.0
        vb = 1.0 + math.log(b[w]) if w in b else 0.0
        dot += va * vb
        na += va * va
        nb += vb * vb
    if na <= 0 or nb <= 0:
        return 0.0
    return _clamp01(dot / (math.sqrt(na) * math.sqrt(nb)))


def _dom_tag_similarity(raw_html: str, rendered_html: str, cap: int = 4000) -> float:
    """Jaccard-like overlap on tag-name multiset (structure proxy)."""

    def tags(h: str) -> Counter[str]:
        if not h:
            return Counter()
        try:
            soup = BeautifulSoup(h, "html.parser")
            names: list[str] = []
            for el in soup.find_all(True):
                n = el.name
                if isinstance(n, str) and n:
                    names.append(n.lower())
                if len(names) >= cap:
                    break
            return Counter(names)
        except Exception:
            return Counter()

    cr, ce = tags(raw_html), tags(rendered_html)
    if not cr and not ce:
        return 1.0
    inter = sum(min(cr[t], ce[t]) for t in set(cr) | set(ce))
    union = sum(max(cr[t], ce[t]) for t in set(cr) | set(ce))
    if union <= 0:
        return 0.0
    return _clamp01(inter / union)


def compute_text_similarity(raw_html: str, rendered_html: str) -> dict[str, Any]:
    """
    Lexical similarity between raw HTTP HTML and rendered DOM HTML.

    Combines log-weighted cosine on word bags with a lightweight DOM tag overlap score.
    """
    tr = _strip_boilerplate_html(raw_html or "")
    te = _strip_boilerplate_html(rendered_html or "")
    wa = Counter(_tokenize_words(tr))
    wb = Counter(_tokenize_words(te))
    text_sim = _cosine_from_counters(wa, wb) if (tr.strip() and te.strip()) else 0.0
    dom_sim = _dom_tag_similarity(raw_html or "", rendered_html or "")
    return {
        "text_similarity_score": round(float(text_sim), 4),
        "dom_similarity_score": round(float(dom_sim), 4),
    }


def compute_advanced_cloaking_analysis(
    raw_html: str,
    rendered_html: str,
    *,
    html_compare: dict[str, Any] | None = None,
    parsed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Text/DOM similarity plus title/canonical agreement from ``html_compare``.

    ``cloaking_risk_level``: high if text_similarity < 0.5, medium in [0.5, 0.75), else low,
    then optionally upgraded when title or canonical mismatch between trees.
    """
    hc = dict(html_compare or {})
    parsed = dict(parsed or {})

    pack = compute_text_similarity(raw_html, rendered_html)
    text_sim = float(pack.get("text_similarity_score") or 0.0)
    dom_sim = float(pack.get("dom_similarity_score") or 0.0)

    raw_short = len((raw_html or "").strip()) < 120
    ren_short = len((rendered_html or "").strip()) < 120
    if raw_short or ren_short:
        level = "low"
        notes = "insufficient_html_for_similarity"
    elif text_sim < 0.5:
        level = "high"
        notes = "text_body_divergence"
    elif text_sim < 0.75:
        level = "medium"
        notes = "text_body_moderate_divergence"
    else:
        level = "low"
        notes = "text_body_similar"

    title_mismatch = not bool(hc.get("title_match", True))
    raw_c = (hc.get("canonical_raw_normalized") or "").strip()
    ren_c = (hc.get("canonical_rendered_normalized") or "").strip()
    canonical_mismatch = bool(raw_c and ren_c and raw_c != ren_c)

    if title_mismatch and level == "low":
        level = "medium"
        notes = "title_mismatch_escalation"
    if canonical_mismatch and level == "low":
        level = "medium"
        notes = "canonical_mismatch_escalation"
    if title_mismatch and canonical_mismatch and level == "medium":
        level = "high"
        notes = "title_and_canonical_mismatch"

    raw_title = (hc.get("title_raw") or "").strip()
    ren_title = (hc.get("title_rendered") or parsed.get("title") or "").strip()
    if not raw_title and title_mismatch and ren_title:
        notes = (notes + ";parsed_title_only_rendered").strip(";")

    return {
        **pack,
        "cloaking_risk_level": level,
        "title_mismatch": title_mismatch,
        "canonical_mismatch": canonical_mismatch,
        "notes": notes,
    }


def detect_cloaking_risk(html_compare: dict[str, Any]) -> dict[str, Any]:
    """
    Heuristic: large body delta OR title mismatch OR canonical string differs between trees.
    """
    reasons: list[str] = []
    ratio = float(html_compare.get("content_length_ratio") or 1.0)
    sig_len = ratio > 1.35 or ratio < 0.74
    if not html_compare.get("identical", True) and sig_len and max(
        int(html_compare.get("raw_length") or 0),
        int(html_compare.get("rendered_length") or 0),
    ) > 400:
        reasons.append("Chênh lệnh độ dài HTML đáng kể giữa raw và rendered.")

    if not html_compare.get("title_match", True):
        reasons.append("Khác title giữa raw và rendered.")

    raw_c = (html_compare.get("canonical_raw_normalized") or "").strip()
    ren_c = (html_compare.get("canonical_rendered_normalized") or "").strip()
    if raw_c and ren_c and raw_c != ren_c:
        reasons.append("Khác canonical tuyệt đối giữa raw HTTP body và DOM sau JS.")

    risk = bool(reasons)
    return {
        "cloaking_risk": risk,
        "cloaking_reason": "; ".join(reasons) if reasons else "Không bật quy tắc cloaking heuristic.",
    }


def build_seo_signals(
    *,
    html_compare: dict[str, Any],
    indexability: dict[str, Any],
    js_risk: dict[str, Any],
    cloaking: dict[str, Any],
) -> dict[str, Any]:
    render_diff = not bool(html_compare.get("identical", True))
    js_dep = bool(
        render_diff
        or html_compare.get("js_likely_changed_dom")
        or bool(html_compare.get("missing_elements_in_raw"))
    )
    return {
        "js_dependency": js_dep,
        "js_seo_risk_level": js_risk.get("js_seo_risk_level", "low"),
        "cloaking_risk": bool(cloaking.get("cloaking_risk")),
        "render_difference": render_diff,
        "indexable": bool(indexability.get("indexable")),
    }
