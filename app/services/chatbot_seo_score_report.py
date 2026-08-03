"""Chuẩn hóa kết quả SEO Score cho panel Chatbot (URL / nội dung)."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

_PASS_GRADE_TIERS = frozenset({"excellent", "good"})


def _grade_passed(grade_tier: str, score: int) -> bool:
    tier = str(grade_tier or "").strip().lower()
    if tier in _PASS_GRADE_TIERS:
        return True
    return int(score or 0) >= 60


def _density_for_keyword(text: str, keyword: str) -> dict[str, Any]:
    kw = str(keyword or "").strip().lower()
    if not kw:
        return {"primary_keyword": "", "count": 0, "density_pct": 0.0, "word_count": 0}
    words = re.findall(r"[\wà-ỹ]+", str(text or ""), re.I)
    wc = len(words)
    if not wc:
        return {"primary_keyword": keyword, "count": 0, "density_pct": 0.0, "word_count": 0}
    body_l = " ".join(words).lower()
    count = body_l.count(kw)
    if count == 0 and " " in kw:
        parts = [p for p in kw.split() if len(p) > 2]
        if parts:
            count = sum(body_l.count(p) for p in parts[:3])
    density = round((count / wc) * 100, 2) if wc else 0.0
    return {
        "primary_keyword": keyword,
        "count": count,
        "density_pct": density,
        "word_count": wc,
    }


def _extract_headings(html: str) -> dict[str, list[str]]:
    try:
        soup = BeautifulSoup(str(html or "")[:800_000], "html.parser")
    except Exception:
        return {"h1": [], "h2": [], "h3": []}
    return {
        "h1": [t.get_text(" ", strip=True) for t in soup.find_all("h1") if t.get_text(strip=True)][:6],
        "h2": [t.get_text(" ", strip=True) for t in soup.find_all("h2") if t.get_text(strip=True)][:12],
        "h3": [t.get_text(" ", strip=True) for t in soup.find_all("h3") if t.get_text(strip=True)][:12],
    }


def _bucket_issues_from_factors(factors: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    critical: list[dict[str, str]] = []
    warning: list[dict[str, str]] = []
    suggestion: list[dict[str, str]] = []
    for f in factors or []:
        st = str(f.get("status") or "")
        item = {
            "id": str(f.get("id") or ""),
            "title": str(f.get("label") or f.get("title") or ""),
            "message": str(f.get("message") or f.get("problem") or ""),
            "suggestion": str(f.get("suggestion") or f.get("fix") or ""),
        }
        if st == "failed":
            critical.append(item)
        elif st == "warning":
            warning.append(item)
        elif st == "passed" and item["suggestion"]:
            suggestion.append(item)
    return {
        "critical": critical[:20],
        "warning": warning[:20],
        "suggestion": suggestion[:12],
    }


def _bucket_issues_from_url_checks(groups: list[dict[str, Any]], legacy_issues: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, str]]]:
    critical: list[dict[str, str]] = []
    warning: list[dict[str, str]] = []
    suggestion: list[dict[str, str]] = []
    for g in groups or []:
        for c in g.get("checks") or []:
            st = str(c.get("status") or "")
            item = {
                "id": str(c.get("id") or ""),
                "title": str(c.get("title") or ""),
                "message": str(c.get("problem") or ""),
                "suggestion": str(c.get("fix") or ""),
            }
            if st == "failed":
                critical.append(item)
            elif st == "warning":
                warning.append(item)
    for iss in legacy_issues or []:
        pri = str(iss.get("priority") or "P2")
        item = {
            "id": str(iss.get("id") or iss.get("code") or ""),
            "title": str(iss.get("title") or iss.get("message") or "Vấn đề SEO"),
            "message": str(iss.get("message") or iss.get("detail") or ""),
            "suggestion": str(iss.get("fix") or iss.get("recommendation") or ""),
        }
        if pri in ("P0", "P1"):
            critical.append(item)
        elif pri == "P2":
            warning.append(item)
        else:
            suggestion.append(item)
    return {
        "critical": critical[:20],
        "warning": warning[:20],
        "suggestion": suggestion[:12],
    }


def _metric_from_factor(factors: list[dict[str, Any]], factor_id: str) -> dict[str, Any]:
    for f in factors or []:
        if str(f.get("id") or "") == factor_id:
            return {
                "status": f.get("status"),
                "status_label": f.get("status_label"),
                "message": f.get("message"),
                "score": f.get("score"),
                "max_score": f.get("max_score"),
            }
    return {}


def build_chatbot_seo_report_from_content(
    checklist: dict[str, Any],
    *,
    primary_keyword: str,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
) -> dict[str, Any]:
    """Báo cáo SEO nội dung (30 yếu tố) cho chatbot."""
    score = int(checklist.get("score") or 0)
    grade_tier = str(checklist.get("grade_tier") or "")
    grade_label = str(checklist.get("grade_label") or "")
    factors = list(checklist.get("factors") or [])
    groups = list(checklist.get("groups") or [])
    headings = _extract_headings(content_html)
    body_text = BeautifulSoup(str(content_html or "")[:800_000], "html.parser").get_text(" ", strip=True)

    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        imgs = soup.find_all("img")
        imgs_no_alt = sum(
            1 for img in imgs if not str(img.get("alt") or "").strip()
        )
        internal = len([a for a in soup.find_all("a", href=True) if str(a.get("href") or "").startswith(("/", "#"))])
        external = len([
            a for a in soup.find_all("a", href=True)
            if str(a.get("href") or "").startswith("http")
        ])
    except Exception:
        imgs = []
        imgs_no_alt = 0
        internal = 0
        external = 0

    sec_raw = _metric_from_factor(factors, "semantic_keywords")
    intent_raw = _metric_from_factor(factors, "intent_title_match")
    faq_raw = _metric_from_factor(factors, "helpful_faq_conclusion")
    schema_raw = _metric_from_factor(factors, "media_schema_blockquote")
    cta_raw = _metric_from_factor(factors, "helpful_faq_conclusion")
    eeat_raw = _metric_from_factor(factors, "eeat_trust_signals")

    group_scores = [
        {"id": g.get("id"), "label": g.get("label"), "score": g.get("score"), "max_score": g.get("max_score")}
        for g in groups
    ]

    return {
        "mode": "content",
        "total_score": score,
        "passed": _grade_passed(grade_tier, score),
        "grade_tier": grade_tier,
        "grade_label": grade_label,
        "primary_keyword": primary_keyword,
        "metrics": {
            "title": title or (headings.get("h1") or [""])[0],
            "meta_description": meta_description,
            "headings": headings,
            "keyword_density": _density_for_keyword(body_text, primary_keyword),
            "secondary_keywords": sec_raw.get("message") or "",
            "search_intent": intent_raw.get("message") or intent_raw.get("status_label") or "",
            "internal_links": {"count": internal, **_metric_from_factor(factors, "links_internal")},
            "external_links": {"count": external, **_metric_from_factor(factors, "links_external")},
            "images": {
                "total": len(imgs),
                "missing_alt": imgs_no_alt,
                **_metric_from_factor(factors, "media_alt_text"),
            },
            "readability": _metric_from_factor(factors, "readability_formatting") or _metric_from_factor(factors, "readability_sentence_length"),
            "faq": faq_raw,
            "schema": schema_raw,
            "cta": cta_raw,
            "eeat": eeat_raw,
            "word_count": int(checklist.get("word_count") or 0),
        },
        "group_scores": group_scores,
        "issues": _bucket_issues_from_factors(factors),
        "summary_counts": checklist.get("summary") or {},
    }


def build_chatbot_seo_report_from_url(
    raw: dict[str, Any],
    *,
    keyword: str,
    html: str = "",
) -> dict[str, Any]:
    """Báo cáo SEO URL cho chatbot."""
    ten = dict(raw.get("ten_group_scoreboard") or {})
    scores = dict(raw.get("scores") or {})
    total = int(ten.get("total_score") or scores.get("ten_group_total") or scores.get("total") or 0)
    page = dict(raw.get("page_snapshot") or {})
    breakdown = dict(raw.get("breakdown") or {})
    serp = dict(raw.get("serp") or {})
    groups = list(ten.get("groups") or [])
    legacy_issues = list(raw.get("issues") or [])

    title = str(page.get("title") or "")
    meta = str(page.get("meta_description") or "")
    headings = _extract_headings(html)
    if not headings.get("h1") and title:
        headings["h1"] = [title]
    h1c = int(page.get("h1_count") or len(headings.get("h1") or []))
    if h1c and not headings.get("h1"):
        headings["h1"] = [f"({h1c} H1 trên trang)"]
    body_text = ""
    try:
        body_text = BeautifulSoup(str(html or "")[:800_000], "html.parser").get_text(" ", strip=True)
    except Exception:
        pass

    links_meta = (breakdown.get("links") or {}) if isinstance(breakdown.get("links"), dict) else {}
    schema_meta = (breakdown.get("schema") or {}) if isinstance(breakdown.get("schema"), dict) else {}
    ux_meta = (breakdown.get("ux_readability") or {}) if isinstance(breakdown.get("ux_readability"), dict) else {}
    intent_meta = (breakdown.get("intent") or {}) if isinstance(breakdown.get("intent"), dict) else {}
    eeat_meta = (breakdown.get("eeat") or {}) if isinstance(breakdown.get("eeat"), dict) else {}

    grade_tier = "excellent" if total >= 90 else "good" if total >= 75 else "needs_work" if total >= 60 else "not_ready"
    grade_label = {90: "Xuất sắc", 75: "Tốt", 60: "Cần tối ưu"}.get(
        90 if total >= 90 else 75 if total >= 75 else 60 if total >= 60 else 0,
        "Không nên publish" if total < 60 else "Cần tối ưu",
    )
    if total >= 90:
        grade_label = "Xuất sắc"
    elif total >= 75:
        grade_label = "Tốt"
    elif total >= 60:
        grade_label = "Cần tối ưu"
    else:
        grade_label = "Chưa đạt"

    group_scores = [
        {"id": g.get("id"), "label": g.get("label"), "score": g.get("score"), "max_score": 100}
        for g in groups
    ]

    return {
        "mode": "url",
        "url": str(raw.get("url") or ""),
        "total_score": total,
        "passed": total >= 60,
        "grade_tier": grade_tier,
        "grade_label": grade_label,
        "primary_keyword": keyword,
        "metrics": {
            "title": title,
            "meta_description": meta,
            "headings": headings,
            "keyword_density": _density_for_keyword(body_text, keyword),
            "secondary_keywords": ", ".join(ten.get("secondary_keywords") or []),
            "search_intent": str(serp.get("serp_intent") or intent_meta.get("serp_intent") or intent_meta.get("intent") or "—"),
            "internal_links": {
                "count": int(links_meta.get("internal_count") or links_meta.get("internal") or 0),
                "message": str(links_meta.get("note") or ""),
            },
            "external_links": {
                "count": int(links_meta.get("external_count") or links_meta.get("external") or 0),
                "message": str(links_meta.get("external_note") or ""),
            },
            "images": {
                "total": int(ux_meta.get("images_total") or 0),
                "missing_alt": int(ux_meta.get("images_missing_alt") or 0),
                "message": str(ux_meta.get("alt_note") or ""),
            },
            "readability": {
                "score": breakdown.get("ux_readability", {}).get("score") if isinstance(breakdown.get("ux_readability"), dict) else None,
                "message": str(ux_meta.get("readability") or ""),
            },
            "faq": {"message": str((breakdown.get("helpful_content") or {}).get("faq") or "")},
            "schema": {
                "has_schema": bool(schema_meta.get("ld_count") or schema_meta.get("has_json_ld")),
                "message": str(schema_meta.get("note") or ""),
            },
            "cta": {"message": str((breakdown.get("helpful_content") or {}).get("cta") or "")},
            "eeat": {
                "score": eeat_meta.get("score"),
                "message": str(eeat_meta.get("note") or ""),
            },
            "word_count": int((breakdown.get("content_depth") or {}).get("word_count") or 0),
        },
        "group_scores": group_scores,
        "issues": _bucket_issues_from_url_checks(groups, legacy_issues),
        "priority_fixes": list(ten.get("priority_fixes") or [])[:10],
        "ai_suggestions": list(ten.get("ai_suggestions") or [])[:6],
    }
