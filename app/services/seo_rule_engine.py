"""
Production-oriented SEO decision layer: crawl + parse signals → contextual issues.

Each rule returns a structured issue dict or None. Rules are registered in RULES and executed
via ``run_rules`` → dedupe/sort → page score (100 minus severity weights).
"""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlparse

from app.services.seo_normalize import normalize_url_safe

IssueFn = Callable[[dict[str, Any]], dict[str, Any] | None]


def _policy_like_url(url: str) -> bool:
    """
    Regex policy/contact matcher used to soften indexability severity.
    """
    return bool(
        re.search(
            r"(policy|privacy|terms|contact|chinh-sach|bao-mat|lien-he)",
            url or "",
            flags=re.I,
        )
    )


RULE_CHECKLIST: dict[str, str] = {
    "indexability_blocked": "GSC",
    "indexability_signal_conflict": "GSC",
    "canonical_cross_host": "Onpage",
    "canonical_self_mismatch": "Onpage",
    "canonical_missing_high_value": "Onpage",
    "js_seo_risk_high": "Onpage",
    "js_seo_risk_medium": "Onpage",
    "js_shell_missing_critical": "Onpage",
    "cloaking_heuristic": "GSC",
    "robots_meta_noindex_contradiction": "GSC",
    "meta_robots_noindex": "GSC",
    "x_robots_tag_noindex": "GSC",
    "canonical_scheme_mismatch": "Onpage",
    "canonical_trailing_slash_mismatch": "Onpage",
    "canonical_points_to_bad_status": "GSC",
    "http_status_non_200": "GSC",
    "missing_title": "Onpage",
    "title_too_long": "Onpage",
    "missing_meta_description": "Onpage",
    "missing_h1": "Onpage",
    "multiple_h1": "Onpage",
    "thin_content": "Onpage",
    "images_missing_alt": "Images",
    "title_too_short": "Onpage",
    "meta_description_too_long": "Onpage",
    "missing_viewport": "Onpage",
    "images_broken_src": "Images",
    "duplicate_h1": "Onpage",
    "duplicate_meta_description": "Onpage",
    "hreflang_invalid_code": "International",
    "hreflang_missing_self": "International",
    "hreflang_missing_href": "International",
    "internal_link_redirect": "GSC",
    "orphan_page": "GSC",
    "crawl_depth_deep": "GSC",
    "soft_404_heuristic": "GSC",
    "weak_heading_structure": "Onpage",
    "canonical_points_to_non_indexable": "GSC",
    "canonical_low_similarity_mismatch": "Onpage",
    "google_may_ignore_canonical": "GSC",
    "page_unlikely_indexed": "GSC",
    "cloaking_risk_advanced": "GSC",
    "serp_gap_thin_content": "Onpage",
    "serp_gap_heading_structure": "Onpage",
    "serp_gap_internal_links": "Onpage",
    "serp_gap_keyword_coverage": "Onpage",
    "serp_gap_semantic_depth": "Onpage",
    "serp_gap_generic": "Onpage",
    "crawl_http_3xx": "GSC",
    "crawl_http_4xx": "GSC",
    "crawl_http_5xx": "GSC",
    "crawl_timeout": "GSC",
    "crawl_connection_error": "GSC",
    "redirect_loop": "GSC",
    "crawled_url_robots_blocked": "Robots",
}

SOFT_404_PATTERNS: tuple[str, ...] = (
    "not found",
    "khong tim thay",
    "không tìm thấy",
    "404",
    "page not available",
)


def _is_soft_404_text(visible_text: str, title: str) -> bool:
    return _soft_404_matched_pattern(visible_text, title) is not None


def _soft_404_matched_pattern(visible_text: str, title: str) -> str | None:
    content = f"{visible_text or ''} {title or ''}".lower()
    for p in SOFT_404_PATTERNS:
        if p in content:
            return p
    return None


def _norm_host(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _norm_url(u: str) -> str:
    try:
        return (normalize_url_safe(u) if u else "").strip().lower().rstrip("/")
    except Exception:
        return (u or "").strip().lower().rstrip("/")


def _issue(
    rule_id: str,
    issue: str,
    severity: str,
    confidence: float,
    category: str,
    *,
    why: str,
    detected_from: list[str],
    causes: list[str],
    fixes: list[str],
    validation: list[str],
    url: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ev: list[dict[str, Any]] = [dict(x) for x in (evidence or []) if isinstance(x, dict)]
    page_url = str(url or "").strip()
    if page_url and not any(e.get("url") == page_url for e in ev):
        ev.append({"kind": "url", "url": page_url})
    if not ev:
        for field in detected_from or []:
            if field:
                ev.append({"kind": "detected_from", "text": str(field)})
    out: dict[str, Any] = {
        "rule_id": rule_id,
        "issue": issue,
        "severity": severity,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "category": category,
        "why_it_matters": why,
        "detected_from": detected_from,
        "possible_causes": causes,
        "how_to_fix": fixes,
        "validation_steps": validation,
        "evidence": ev,
    }
    if page_url:
        out["url"] = page_url
        out["affected_urls"] = [page_url]
    return out


def build_page_rule_context(
    *,
    url: str,
    status: int,
    parsed: dict[str, Any],
    page_type: str,
    crawl_record: dict[str, Any] | None,
) -> dict[str, Any]:
    wc = int(parsed.get("word_count") or 0)
    if wc < 300:
        content_depth = "thin"
    elif wc < 900:
        content_depth = "normal"
    else:
        content_depth = "deep"

    cr = dict(crawl_record or {})
    ss = dict(cr.get("seo_signals") or {})
    idx = dict(cr.get("indexability") or {})
    if not idx and status:
        idx = {
            "indexable": 200 <= int(status) < 400,
            "indexability_reason": "Không có object indexability từ crawler; suy luận từ HTTP.",
            "indexability_confidence": 0.45,
            "meta_robots_text": None,
            "x_robots_tag": None,
            "x_robots_tag_raw": None,
        }

    return {
        "url": url,
        "status": int(status or 0),
        "parsed": parsed,
        "page_type": page_type,
        "content_depth": content_depth,
        "js_dependency": bool(ss.get("js_dependency")),
        "render_difference": bool(ss.get("render_difference")),
        "seo_signals": ss,
        "canonical_resolution": dict(cr.get("canonical_resolution") or {}),
        "indexability": idx,
        "raw_vs_rendered": dict(cr.get("raw_vs_rendered") or {}),
        "js_seo_risk_score": float(cr.get("js_seo_risk_score") or 0.0),
        "js_seo_risk_level": str(cr.get("js_seo_risk_level") or "low"),
        "cloaking_risk": bool(cr.get("cloaking_risk")),
        "cloaking_reason": str(cr.get("cloaking_reason") or ""),
        "playwright_headers": dict(cr.get("response_headers") or {}),
        "raw_headers": dict(cr.get("raw_response_headers") or {}),
        "redirect_history": list(cr.get("redirect_history") or []),
        "raw_redirect_history": list(cr.get("raw_redirect_history") or []),
        "rendered_html": str(cr.get("rendered_html") or cr.get("html") or ""),
        "raw_html": str(cr.get("raw_html") or ""),
    }


def _has_noindex_directive(text: str) -> bool:
    t = (text or "").lower()
    return "noindex" in t or "none" in t


def evaluate_indexability_blocked(d: dict[str, Any]) -> dict[str, Any] | None:
    idx = d["indexability"]
    fin = d.get("final_indexability_resolved")
    if fin is None:
        blocked = not idx.get("indexable", True)
    else:
        blocked = not bool(fin)
    if not blocked:
        return None
    url = str(d.get("url") or "")
    parsed_robots = str((d.get("parsed") or {}).get("robots_meta") or "").lower()
    rs = d.get("resolved_signals")
    xr_doc = ""
    if isinstance(rs, dict):
        xr_doc = str(rs.get("x_robots_tag_document") or "").lower()
    meta_txt = str(idx.get("meta_robots_text") or parsed_robots or "")
    xr_txt = str(idx.get("x_robots_tag") or xr_doc or "")
    # noindex cụ thể do rule meta_robots_noindex / x_robots_tag_noindex xử lý
    if _has_noindex_directive(meta_txt) or _has_noindex_directive(xr_txt):
        return None
    page_type = str(d.get("page_type") or "").lower()
    severity = "high"
    if _policy_like_url(url):
        severity = "low"
    conf = float(idx.get("indexability_confidence") or 0.85)
    reason = str(idx.get("indexability_reason") or "")
    return _issue(
        "indexability_blocked",
        "URL không được đánh giá là có thể index (indexable = false).",
        severity,
        conf,
        "indexability",
        why="Google thường không đưa URL vào index khi HTTP lỗi hoặc tín hiệu chặn index khác noindex — mất traffic tìm kiếm có chủ đích.",
        detected_from=[
            "resolved.final_indexability",
            "indexability.indexability_reason",
            "status",
        ],
        causes=[
            "Mã HTTP không phải 2xx.",
            "Tín hiệu chặn index khác noindex (header/meta đặc biệt).",
        ],
        fixes=[
            "Xác nhận trong GSC → Page indexing: URL có bị 'Excluded' không.",
            "Sửa HTTP status hoặc tín hiệu chặn index theo intent (staging vs production).",
        ],
        validation=[
            "Mở URL với Googlebot UA (hoặc GSC URL Inspection) và kiểm tra HTML + response headers.",
            "So khớp bản raw vs rendered trong audit debug.",
        ],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "http_status", "value": int(d.get("status") or 0)},
            {"kind": "indexability_reason", "value": reason[:300]},
            {"kind": "indexable", "value": False},
        ],
    )


def evaluate_meta_robots_noindex(d: dict[str, Any]) -> dict[str, Any] | None:
    idx = d["indexability"]
    meta = str(idx.get("meta_robots_text") or (d.get("parsed") or {}).get("robots_meta") or "")
    if not _has_noindex_directive(meta):
        return None
    fin = d.get("final_indexability_resolved", idx.get("indexable", True))
    if fin is True and not _has_noindex_directive(meta):
        return None
    url = str(d.get("url") or "")
    severity = "high"
    if _policy_like_url(url):
        severity = "low"
    conf = float(idx.get("indexability_confidence") or 0.93)
    return _issue(
        "meta_robots_noindex",
        f"Meta robots/googlebot chứa noindex/none — URL không được index: {url}",
        severity,
        conf,
        "indexability",
        why="Thẻ meta robots noindex là tín hiệu mạnh khiến Google thường loại URL khỏi index.",
        detected_from=["indexability.meta_robots_text", "parsed.robots_meta"],
        causes=["CMS staging", "Plugin SEO bật noindex nhầm", "Template <head> copy nhầm"],
        fixes=["Gỡ noindex/none khỏi meta robots nếu URL cần index.", "Kiểm tra plugin SEO và môi trường production."],
        validation=["View source / rendered HTML <head>.", "GSC URL Inspection → Indexing allowed?"],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "meta_robots", "value": meta},
        ],
    )


def evaluate_x_robots_tag_noindex(d: dict[str, Any]) -> dict[str, Any] | None:
    idx = d["indexability"]
    rs = d.get("resolved_signals") or {}
    xr = str(
        rs.get("x_robots_tag_document")
        or idx.get("x_robots_tag")
        or idx.get("x_robots_tag_raw")
        or ""
    )
    hdrs = dict(d.get("playwright_headers") or d.get("raw_headers") or {})
    if not xr:
        for k, v in hdrs.items():
            if str(k).lower() == "x-robots-tag" and v:
                xr = str(v)
                break
    if not _has_noindex_directive(xr):
        return None
    url = str(d.get("url") or "")
    severity = "high"
    if _policy_like_url(url):
        severity = "low"
    conf = float(idx.get("indexability_confidence") or 0.94)
    return _issue(
        "x_robots_tag_noindex",
        f"HTTP header X-Robots-Tag chứa noindex/none — URL không được index: {url}",
        severity,
        conf,
        "indexability",
        why="X-Robots-Tag trên response HTTP được Google ưu tiên — chặn index ngay cả khi meta cho phép.",
        detected_from=["indexability.x_robots_tag", "response_headers.x-robots-tag"],
        causes=["CDN/WAF header", "Server config Apache/Nginx", "Plugin cache header"],
        fixes=["Gỡ noindex khỏi X-Robots-Tag trên response 200.", "Đồng bộ header với meta robots intent."],
        validation=["curl -I URL và kiểm tra X-Robots-Tag.", "GSC Live test."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "x_robots_tag", "value": xr},
        ],
    )


def evaluate_indexability_signal_conflict(d: dict[str, Any]) -> dict[str, Any] | None:
    idx = d["indexability"]
    fin = d.get("final_indexability_resolved", idx.get("indexable", True))
    if not fin:
        return None
    meta = str(idx.get("meta_robots_text") or (d.get("parsed") or {}).get("robots_meta") or "")
    rs = d.get("resolved_signals") or {}
    xr = str(rs.get("x_robots_tag_document") or idx.get("x_robots_tag") or "")
    meta_ni = _has_noindex_directive(meta)
    xr_ni = _has_noindex_directive(xr)
    # Chỉ báo khi có bằng chứng mâu thuẫn cụ thể (meta vs header), không đoán từ confidence thấp.
    if meta_ni == xr_ni:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "indexability_signal_conflict",
        "Tín hiệu indexability không nhất quán (meta vs X-Robots-Tag).",
        "medium",
        0.82,
        "indexability",
        why="Tín hiệu mơ hồ làm khó Google — meta và header phải cùng intent index/noindex.",
        detected_from=["indexability.meta_robots_text", "indexability.x_robots_tag"],
        causes=["CDN trả header khác theo path", "Plugin SEO ghi meta, server còn header cũ"],
        fixes=["Chuẩn hóa một nguồn sự thật: meta và X-Robots-Tag cùng cho phép hoặc cùng noindex."],
        validation=["So sánh response headers và <meta name=robots> trên cùng URL."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "meta_robots", "value": meta or ""},
            {"kind": "x_robots_tag", "value": xr or ""},
        ],
    )


def evaluate_http_status_non_200(d: dict[str, Any]) -> dict[str, Any] | None:
    st = int(d["status"] or 0)
    if st == 200 or st == 0:
        return None
    fin = d.get("final_indexability_resolved", d["indexability"].get("indexable", True))
    if not fin:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "http_status_non_200",
        f"Tài liệu trả HTTP {st} nhưng indexability vẫn true — kiểm tra logic indexability.",
        "high",
        0.55,
        "technical",
        why="Trạng thái không 200 thường không được index như nội dung ổn định.",
        detected_from=["status", "indexability.indexable"],
        causes=["Dữ liệu indexability thiếu hoặc lỗi pipeline.", "Redirect trung gian không được ghi nhận."],
        fixes=["Rà lại crawler và indexability engine cho URL này."],
        validation=["Kiểm tra chain redirect và status cuối trong crawl record."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "http_status", "value": st},
            {"kind": "indexable", "value": True},
        ],
    )


def evaluate_canonical_cross_host(d: dict[str, Any]) -> dict[str, Any] | None:
    cr = d["canonical_resolution"]
    c = cr.get("canonical_url")
    fe = cr.get("final_effective_url") or d["url"]
    if not c:
        return None
    if _norm_host(str(c)) == _norm_host(str(fe)):
        return None
    url = str(d.get("url") or "")
    return _issue(
        "canonical_cross_host",
        "Canonical trỏ sang host khác với URL hiệu dụng (cross-domain / property khác).",
        "medium",
        0.88,
        "technical",
        why="Hợp lệ khi chuyển tài sản hoặc syndication, nhưng sai cấu hình sẽ làm Google chọn URL không mong muốn.",
        detected_from=["canonical_resolution.canonical_url", "canonical_resolution.final_effective_url"],
        causes=["CDN mirror", "Sai domain trong CMS", "Href tuyệt đối copy nhầm"],
        fixes=["Nếu đây là bản chính thức của nội dung, canonical nên trỏ về cùng host hoặc URL được chọn rõ ràng trong GSC."],
        validation=["URL Inspection với user-declared canonical trong GSC.", "So sánh host sau www-strip."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "canonical_url", "url": str(c)},
            {"kind": "final_effective_url", "url": str(fe)},
        ],
    )


def evaluate_canonical_self_mismatch(d: dict[str, Any]) -> dict[str, Any] | None:
    cr = d["canonical_resolution"]
    if not cr.get("canonical_mismatch"):
        return None
    c, fe = cr.get("canonical_url"), cr.get("final_effective_url") or d["url"]
    if not c or _norm_host(str(c)) != _norm_host(str(fe)):
        return None
    return _issue(
        "canonical_self_mismatch",
        "Canonical trỏ tới URL khác trên cùng site (không trùng URL hiệu dụng).",
        "medium",
        0.82,
        "technical",
        why="Google thường tôn trọng canonical mạnh; self-canonical sai có thể gom tín hiệu sang URL khác.",
        detected_from=["canonical_resolution.canonical_mismatch", "canonical_resolution.canonical_url"],
        causes=["Tham số tracking", "Slug cũ / www vs non-www đã chuẩn hóa khác parser"],
        fixes=["Chuẩn hóa canonical về URL ưu tiên (thường self sau redirect 301)."],
        validation=["Kiểm tra URL sau redirect == canonical không.", "Screaming Frog Canonicals report."],
        url=str(d.get("url") or ""),
        evidence=[
            {"kind": "url", "url": str(d.get("url") or "")},
            {"kind": "canonical_url", "url": str(c)},
            {"kind": "final_effective_url", "url": str(fe)},
        ],
    )


def evaluate_canonical_missing_high_value(d: dict[str, Any]) -> dict[str, Any] | None:
    if d["page_type"] not in ("article", "homepage", "landing"):
        return None
    cr = d["canonical_resolution"]
    if cr.get("canonical_url"):
        return None
    parsed_c = (d["parsed"].get("canonical") or "").strip()
    if parsed_c:
        return None
    return _issue(
        "canonical_missing_high_value",
        "Trang quan trọng (article/homepage/landing) không có canonical tuyệt đối rõ ràng.",
        "low",
        0.62 if d["page_type"] == "homepage" else 0.74,
        "technical",
        why="Self-canonical giúp hợp nhất tín hiệu khi có tham số, bản in, hoặc A/B — GSC dễ đối chiếu.",
        detected_from=["page_type", "canonical_resolution.canonical_url", "parsed.canonical"],
        causes=["Theme không in canonical", "SPA inject sau render — parser đã dùng rendered HTML"],
        fixes=["Thêm <link rel=\"canonical\" href=\"URL ưu tiên\"> trong HTML ổn định (không chỉ client-only)."],
        validation=["Xem canonical.json trong debug run.", "So với URL Inspection."],
        url=str(d.get("url") or ""),
        evidence=[
            {"kind": "url", "url": str(d.get("url") or "")},
            {"kind": "canonical_url", "value": ""},
            {"kind": "page_type", "value": d["page_type"]},
        ],
    )


def evaluate_js_seo_risk_high(d: dict[str, Any]) -> dict[str, Any] | None:
    if d["js_seo_risk_level"] != "high":
        return None
    return _issue(
        "js_seo_risk_high",
        "Rủi ro SEO phụ thuộc JavaScript cao (DOM/title/H1 khác biệt mạnh giữa raw và rendered).",
        "high",
        min(0.92, 0.65 + d["js_seo_risk_score"] * 0.25),
        "technical",
        why="Google render JS nhưng crawl budget và độ trễ render có thể làm nội dung quan trọng bị thấy muộn hoặc không đầy đủ.",
        detected_from=["js_seo_risk_level", "js_seo_risk_score", "raw_vs_rendered"],
        causes=["CSR shell", "A/B inject title", "Lazy H1"],
        fixes=["SSR hoặc hybrid cho title/H1/canonical; kiểm tra source HTML ban đầu có đủ tín hiệu SEO cốt lõi."],
        validation=["So raw.html vs rendered.html trong debug.", "GSC View crawled page."],
    )


def evaluate_js_seo_risk_medium(d: dict[str, Any]) -> dict[str, Any] | None:
    if d["js_seo_risk_level"] != "medium":
        return None
    return _issue(
        "js_seo_risk_medium",
        "Mức rủi ro JS trung bình — nên rà soát nội dung quan trọng trong HTML tĩnh.",
        "medium",
        0.72,
        "technical",
        why="Giảm phụ thuộc JS giúp ổn định snippet và indexing khi render chậm.",
        detected_from=["js_seo_risk_level", "js_seo_risk_score", "seo_signals.js_dependency"],
        causes=["Hydration thay đổi text", "Component mount muộn"],
        fixes=["Đưa title, meta description, H1 chính vào HTML server hoặc pre-render."],
        validation=["Kiểm tra missing_elements_in_raw trong raw_vs_rendered.json."],
    )


def evaluate_js_shell_missing_critical(d: dict[str, Any]) -> dict[str, Any] | None:
    miss = d["raw_vs_rendered"].get("missing_elements_in_raw") or []
    if not isinstance(miss, list) or not miss:
        return None
    critical = {"title", "meta_description", "H1"} & set(miss)
    if not critical:
        return None
    if not d["js_dependency"]:
        return None
    return _issue(
        "js_shell_missing_critical",
        f"HTML thô thiếu thành phần SEO quan trọng sau render: {', '.join(sorted(critical))}.",
        "high" if "title" in critical else "medium",
        0.78 if "title" in critical else 0.7,
        "structure",
        why="Nếu bot thấy shell trống, snippet và ranking có thể không phản ánh UX người dùng.",
        detected_from=["raw_vs_rendered.missing_elements_in_raw", "seo_signals.js_dependency"],
        causes=["SPA shell", "SSR tắt cho bot", "A/B framework"],
        fixes=["SSR/prerender cho title/meta/H1 hoặc static HTML fallback."],
        validation=["So sánh title trong raw vs rendered.", "Rich Results / Mobile-friendly test."],
    )


def evaluate_cloaking_heuristic(d: dict[str, Any]) -> dict[str, Any] | None:
    if not d["cloaking_risk"]:
        return None
    return _issue(
        "cloaking_heuristic",
        "Heuristic phát hiện chênh lệch đáng ngờ giữa raw và rendered (không kết luận cloaking ác ý).",
        "high",
        0.68,
        "technical",
        why="Chênh lệch lớn title/canonical/body có thể là A/B, CDN, hoặc rủi ro chính sách — cần rà soát thủ công.",
        detected_from=["cloaking_risk", "cloaking_reason", "raw_vs_rendered"],
        causes=[d["cloaking_reason"] or "Khác biệt DOM/title/canonical."],
        fixes=["Đảm bảo Googlebot nhận cùng business logic với user; gỡ A/B trên bot nếu vi phạm policy."],
        validation=["Search Console URL Inspection vs curl Googlebot.", "Log server theo UA."],
    )


def evaluate_robots_meta_noindex_contradiction(d: dict[str, Any]) -> dict[str, Any] | None:
    robots = (d["parsed"].get("robots_meta") or "").lower()
    if "noindex" not in robots and "none" not in robots:
        return None
    fin = d.get("final_indexability_resolved", d["indexability"].get("indexable", True))
    if not fin:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "robots_meta_noindex_contradiction",
        "Meta robots có noindex/none nhưng layer indexability vẫn đánh dấu indexable — mâu thuẫn tín hiệu.",
        "medium",
        0.6,
        "indexability",
        why="Mâu thuẫn làm khó debug coverage và có thể che giấu hành vi thật sau redirect/header.",
        detected_from=["parsed.robots_meta", "indexability.indexable"],
        causes=["Indexability chỉ đọc header, meta ở trang con iframe", "Lỗi parse hoặc cache"],
        fixes=["Đồng bộ meta robots với X-Robots-Tag và HTTP; kiểm tra canonical chain."],
        validation=["Đọc rendered.html toàn bộ <head>.", "GSC live test."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "meta_robots", "value": robots},
            {"kind": "indexable", "value": True},
        ],
    )


def evaluate_missing_title(d: dict[str, Any]) -> dict[str, Any] | None:
    if (d["parsed"].get("title") or "").strip():
        return None
    if int(d["status"] or 0) != 200:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "missing_title",
        "Thiếu thẻ <title> sau render.",
        "high",
        0.97,
        "content",
        why="Title là tín hiệu mạnh cho SERP và tab trình duyệt.",
        detected_from=["parsed.title"],
        causes=["Xóa nhầm", "JS chưa hydrate"],
        fixes=["Thêm <title> duy nhất, mô tả rõ trang."],
        validation=["Kiểm tra rendered.html.", "GSC Enhancement."],
        url=url,
        evidence=[{"kind": "url", "url": url}, {"kind": "title", "value": ""}],
    )


def evaluate_title_too_long(d: dict[str, Any]) -> dict[str, Any] | None:
    t = (d["parsed"].get("title") or "").strip()
    if not t or len(t) <= 60:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "title_too_long",
        f"Title dài {len(t)} ký tự — SERP thường cắt ~60 ký tự hiển thị.",
        "medium",
        0.52,
        "content",
        why="Snippet có thể mất phần thương hiệu hoặc CTA phía sau.",
        detected_from=["parsed.title"],
        causes=["CMS auto-append", "A/B dài"],
        fixes=["Rút gọn; đặt từ khóa chính phía trước."],
        validation=["SERP simulator / GSC preview."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "title", "value": t[:180]},
            {"kind": "title_length", "value": len(t)},
        ],
    )


def evaluate_missing_meta_description(d: dict[str, Any]) -> dict[str, Any] | None:
    if (d["parsed"].get("meta_description") or "").strip():
        return None
    if int(d["status"] or 0) != 200:
        return None
    sev = "high" if d["page_type"] in ("article", "homepage", "landing") else "medium"
    conf = 0.86 if sev == "high" else 0.48
    url = str(d.get("url") or "")
    return _issue(
        "missing_meta_description",
        "Thiếu meta description (hoặc og:description).",
        sev,
        conf,
        "content",
        why="Snippet organic thường lấy từ description; thiếu thì Google tự trích — kém kiểm soát.",
        detected_from=["parsed.meta_description", "page_type"],
        causes=["Theme thiếu field", "SPA"],
        fixes=["Thêm meta description độc nhất, phản ánh intent trang."],
        validation=["Kiểm tra parsed.json."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "meta_description", "value": ""},
            {"kind": "page_type", "value": d["page_type"]},
        ],
    )


def evaluate_missing_h1(d: dict[str, Any]) -> dict[str, Any] | None:
    h1_rendered = int(d["parsed"].get("h1_count") or 0)
    if h1_rendered > 0:
        return None
    if int(d["status"] or 0) != 200:
        return None
    raw_html = str(d.get("raw_html") or "")
    h1_raw = len(re.findall(r"<h1\b", raw_html, flags=re.I))
    js_dependency = bool(d.get("js_dependency"))
    if not (h1_raw == 0 and h1_rendered == 0 and not js_dependency):
        return None
    if d["page_type"] in ("article", "landing"):
        sev, conf = "high", 0.9
    elif d["page_type"] == "homepage":
        sev, conf = "medium", 0.55
    else:
        sev, conf = "low", 0.38
    url = str(d.get("url") or "")
    return _issue(
        "missing_h1",
        "Không có H1 sau render.",
        sev,
        conf,
        "structure",
        why="H1 giúp phân cấp chủ đề; với bài viết/landing thường kỳ vọng một H1 rõ.",
        detected_from=["parsed.h1_count", "page_type"],
        causes=["Hero dùng div", "H1 inject JS"],
        fixes=["Một H1 mô tả chủ đề chính; các mục dùng H2."],
        validation=["Outline heading trong SF.", "Accessibility tree."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "h1_count", "value": h1_rendered},
            {"kind": "page_type", "value": d["page_type"]},
        ],
    )


def evaluate_multiple_h1(d: dict[str, Any]) -> dict[str, Any] | None:
    h1c = int(d["parsed"].get("h1_count") or 0)
    if h1c <= 1:
        return None
    if int(d["status"] or 0) != 200:
        return None
    url = str(d.get("url") or "")
    h1_texts = d["parsed"].get("h1") or []
    return _issue(
        "multiple_h1",
        f"Có {h1c} thẻ H1 — dễ làm loãng tín hiệu heading.",
        "medium",
        0.78,
        "structure",
        why="Nhiều H1 có thể gây nhiễu; không luôn sai (ví dụ accessibility pattern) nhưng cần rà.",
        detected_from=["parsed.h1_count"],
        causes=["Component lặp", "Template"],
        fixes=["Giữ một H1 chính; đổi phần còn lại sang H2."],
        validation=["Kiểm tra DOM sau render."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "h1_count", "value": h1c},
            {"kind": "h1_texts", "value": list(h1_texts)[:6]},
        ],
    )


def evaluate_thin_content(d: dict[str, Any]) -> dict[str, Any] | None:
    wc = int(d["parsed"].get("word_count") or 0)
    if wc >= 300:
        return None
    if d["page_type"] == "category":
        sev, conf = "low", 0.35
    elif d["page_type"] in ("article", "landing"):
        sev, conf = "medium", 0.65
    else:
        sev, conf = "low", 0.45
    return _issue(
        "thin_content",
        f"Nội dung text ~{wc} từ (dưới 300).",
        sev,
        conf,
        "content",
        why="Trang mỏng khó cạnh tranh cho truy vấn thông tin; category có thể chấp nhận được.",
        detected_from=["parsed.word_count", "page_type", "content_depth"],
        causes=["Listing ít mô tả", "Chỉ widget"],
        fixes=["Bổ sung copy có giá trị hoặc hợp nhất URL trùng lặp."],
        validation=["So với top SERP cho intent tương tự."],
    )


def evaluate_images_missing_alt(d: dict[str, Any]) -> dict[str, Any] | None:
    n = int(d["parsed"].get("images_missing_alt") or 0)
    if n <= 0:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "images_missing_alt",
        f"{n} ảnh thiếu alt (hoặc alt rỗng không decorative).",
        "low",
        0.82,
        "content",
        why="Alt hỗ trợ Image Search và a11y; decorative nên alt rỗng có chủ đích.",
        detected_from=["parsed.images_missing_alt"],
        causes=["CMS không bắt buộc alt", "Lấy ảnh ngoài không map"],
        fixes=["Thêm alt mô tả; alt=\"\" cho trang trí."],
        validation=["Lighthouse / axe."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "images_missing_alt", "value": n},
            {"kind": "images_total", "value": int(d["parsed"].get("images_total") or 0)},
        ],
    )


def evaluate_title_too_short(d: dict[str, Any]) -> dict[str, Any] | None:
    t = (d["parsed"].get("title") or "").strip()
    if not t or len(t) >= 20:
        return None
    if int(d["status"] or 0) != 200:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "title_too_short",
        f"Title ngắn {len(t)} ký tự — khó mô tả chủ đề trên SERP: {t}",
        "low",
        0.62,
        "content",
        why="Title quá ngắn thường thiếu ngữ cảnh và dễ trùng thương hiệu suông.",
        detected_from=["parsed.title"],
        causes=["Chỉ tên brand", "CMS cắt title"],
        fixes=["Mở rộng title (thường 20–60 ký tự) với chủ đề trang."],
        validation=["Xem SERP preview."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "title", "value": t},
            {"kind": "title_length", "value": len(t)},
        ],
    )


def evaluate_meta_description_too_long(d: dict[str, Any]) -> dict[str, Any] | None:
    m = (d["parsed"].get("meta_description") or "").strip()
    if not m or len(m) <= 160:
        return None
    if int(d["status"] or 0) != 200:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "meta_description_too_long",
        f"Meta description dài {len(m)} ký tự — snippet thường cắt ~155–160 ký tự.",
        "low",
        0.58,
        "content",
        why="Phần cuối description có thể không hiện trên SERP.",
        detected_from=["parsed.meta_description"],
        causes=["Template dài", "Nhồi keyword"],
        fixes=["Rút còn khoảng 120–160 ký tự, CTA rõ ở đầu."],
        validation=["SERP simulator."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "meta_description", "value": m[:200]},
            {"kind": "meta_length", "value": len(m)},
        ],
    )


def evaluate_missing_viewport(d: dict[str, Any]) -> dict[str, Any] | None:
    if int(d["status"] or 0) != 200:
        return None
    vp = str((d["parsed"] or {}).get("viewport") or "").strip()
    if vp:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "missing_viewport",
        f"Thiếu meta viewport — ảnh hưởng mobile: {url}",
        "medium",
        0.9,
        "technical",
        why="Không có viewport khiến Google/mobile render sai chiều rộng.",
        detected_from=["parsed.viewport"],
        causes=["Theme thiếu", "AMP/SPA không in meta"],
        fixes=['Thêm <meta name="viewport" content="width=device-width, initial-scale=1">.'],
        validation=["View source <head>.", "Mobile-Friendly Test."],
        url=url,
        evidence=[{"kind": "url", "url": url}, {"kind": "viewport", "value": ""}],
    )


def evaluate_images_broken_src(d: dict[str, Any]) -> dict[str, Any] | None:
    n = int((d["parsed"] or {}).get("images_broken_src") or 0)
    if n <= 0:
        return None
    if int(d["status"] or 0) != 200:
        return None
    url = str(d.get("url") or "")
    samples = list((d["parsed"] or {}).get("images_broken_samples") or [])[:8]
    return _issue(
        "images_broken_src",
        f"{n} ảnh có src trống hoặc không hợp lệ trên {url}",
        "medium",
        0.86,
        "content",
        why="src rỗng/javascript: làm ảnh lỗi và tốn crawl tới resource vô nghĩa.",
        detected_from=["parsed.images_broken_src"],
        causes=["Placeholder chưa thay", "JS gắn src muộn nhưng crawler thấy trống"],
        fixes=["Gán URL ảnh tĩnh hợp lệ hoặc xóa thẻ img hỏng."],
        validation=["Kiểm tra DOM img[src]."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "images_broken_src", "value": n},
            {"kind": "broken_src_samples", "value": samples},
        ],
    )


def evaluate_soft_404_heuristic(d: dict[str, Any]) -> dict[str, Any] | None:
    status = int(d.get("status") or 0)
    if status != 200:
        return None
    wc = int(d["parsed"].get("word_count") or 0)
    if wc >= 150:
        return None
    title = str(d["parsed"].get("title") or "")
    visible_text = str(d["parsed"].get("visible_text") or "")
    matched = _soft_404_matched_pattern(visible_text, title)
    if not matched:
        return None
    return _issue(
        "soft_404_heuristic",
        "Trang trả 200 nhưng có dấu hiệu soft 404 (nội dung mỏng + mẫu 'not found/404').",
        "high",
        0.82,
        "indexability",
        why="Soft 404 làm URL khó được index hoặc bị loại khỏi kết quả dù HTTP 200.",
        detected_from=["status", "parsed.word_count", "parsed.visible_text", "parsed.title"],
        causes=["Template lỗi trả 200", "Trang không tồn tại nhưng không trả 404/410 thật"],
        fixes=["Trả 404/410 cho trang không tồn tại; hoặc bổ sung nội dung thực sự hữu ích nếu trang cần index."],
        validation=["URL Inspection trong GSC.", "Kiểm tra response thật bằng curl và nội dung visible text."],
        url=str(d.get("url") or ""),
        evidence=[
            {"kind": "url", "url": str(d.get("url") or "")},
            {"kind": "http_status", "value": status},
            {"kind": "word_count", "value": wc},
            {"kind": "title", "value": title[:180]},
            {"kind": "soft_404_pattern", "value": matched},
        ],
    )


def evaluate_canonical_points_to_non_indexable(d: dict[str, Any]) -> dict[str, Any] | None:
    cta = d.get("canonical_target_analysis") or {}
    if not cta.get("fetched"):
        return None
    st = int(cta.get("target_status") or 0)
    if 300 <= st < 600:
        return None  # canonical_points_to_bad_status xử lý
    if cta.get("target_indexable", True):
        return None
    url = str(d.get("url") or "")
    canonical = str((d.get("canonical_resolution") or {}).get("canonical_url") or (d.get("parsed") or {}).get("canonical") or "")
    return _issue(
        "canonical_points_to_non_indexable",
        "Canonical trỏ tới URL đích không indexable (HTTP/robots/meta) — Google khó hợp nhất cluster theo canonical này.",
        "high",
        0.86,
        "technical",
        why="Canonical sang trang chặn index thường bị bỏ qua hoặc gây cluster lỗi — URL hiện tại có thể bị loại hoặc chọn sai primary.",
        detected_from=[
            "canonical_target_analysis.target_indexable",
            "canonical_target_analysis.target_status",
            "resolved_signals.canonical_truth",
        ],
        causes=["Sai URL trong CMS", "Staging/noindex trên bản đích", "Soft-404 trên canonical"],
        fixes=["Sửa canonical về URL indexable thật hoặc self-canonical đúng intent.", "Kiểm tra robots + status đích."],
        validation=["Mở canonical đích bằng Googlebot UA.", "URL Inspection cho URL đích."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "canonical_url", "url": canonical},
            {"kind": "target_indexable", "value": False},
            {"kind": "http_status", "value": st},
        ],
    )


def evaluate_canonical_points_to_bad_status(d: dict[str, Any]) -> dict[str, Any] | None:
    cta = d.get("canonical_target_analysis") or {}
    if not cta.get("fetched"):
        return None
    st = int(cta.get("target_status") or 0)
    if st == 200 or st == 0:
        return None
    cr = d["canonical_resolution"]
    canonical = str(cr.get("canonical_url") or d["parsed"].get("canonical") or "")
    if not canonical:
        return None
    if 300 <= st < 400:
        sev = "medium"
        label = f"redirect HTTP {st}"
    elif 400 <= st < 500:
        sev = "high"
        label = f"lỗi client HTTP {st}"
    else:
        sev = "high"
        label = f"lỗi server HTTP {st}"
    return _issue(
        "canonical_points_to_bad_status",
        f"Canonical trỏ tới URL đích trả {label}: {canonical}",
        sev,
        0.9,
        "indexability",
        why="Canonical sang URL redirect/lỗi khiến Google khó hợp nhất cluster và có thể bỏ qua canonical.",
        detected_from=[
            "canonical_target_analysis.target_status",
            "canonical_resolution.canonical_url",
        ],
        causes=["URL đích đã xóa/redirect", "Staging URL trong canonical", "Sai slug trong CMS"],
        fixes=["Sửa canonical về URL trả 200 indexable.", "Redirect 301 đích cũ về URL chính thức trước khi canonical."],
        validation=["Fetch canonical đích bằng curl.", "GSC URL Inspection canonical đích."],
        url=str(d.get("url") or ""),
        evidence=[
            {"kind": "url", "url": str(d.get("url") or "")},
            {"kind": "canonical_url", "url": canonical},
            {"kind": "http_status", "value": st},
        ],
    )


def evaluate_canonical_scheme_mismatch(d: dict[str, Any]) -> dict[str, Any] | None:
    cr = d["canonical_resolution"]
    c = str(cr.get("canonical_url") or "").strip()
    fe = str(cr.get("final_effective_url") or d["url"] or "").strip()
    if not c or not fe:
        return None
    pc, pf = urlparse(c), urlparse(fe)
    if pc.path.rstrip("/") != pf.path.rstrip("/"):
        return None
    if (pc.hostname or "").lower().replace("www.", "") != (pf.hostname or "").lower().replace("www.", ""):
        return None
    if pc.scheme.lower() == pf.scheme.lower():
        return None
    url = str(d.get("url") or "")
    return _issue(
        "canonical_scheme_mismatch",
        f"Canonical dùng scheme khác URL hiệu dụng ({pc.scheme} vs {pf.scheme}): {c}",
        "medium",
        0.87,
        "indexability",
        why="http vs https là hai URL khác nhau — Google có thể chọn bản không mong muốn nếu canonical không nhất quán.",
        detected_from=["canonical_resolution.canonical_url", "canonical_resolution.final_effective_url"],
        causes=["Mixed content redirect chưa hoàn tất", "CMS hard-code http trong canonical"],
        fixes=["Chuẩn hóa canonical về https (hoặc scheme chính thức).", "301 toàn site sang HTTPS."],
        validation=["So sánh scheme sau redirect cuối.", "GSC property http vs https."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "canonical_url", "url": c},
            {"kind": "final_effective_url", "url": fe},
            {"kind": "scheme_mismatch", "value": f"{pc.scheme} vs {pf.scheme}"},
        ],
    )


def evaluate_canonical_trailing_slash_mismatch(d: dict[str, Any]) -> dict[str, Any] | None:
    cr = d["canonical_resolution"]
    c = str(cr.get("canonical_url") or "").strip()
    fe = str(cr.get("final_effective_url") or d["url"] or "").strip()
    if not c or not fe:
        return None
    pc, pf = urlparse(c), urlparse(fe)
    if pc.scheme.lower() != pf.scheme.lower():
        return None
    if (pc.hostname or "").lower() != (pf.hostname or "").lower():
        return None
    if pc.path.rstrip("/") != pf.path.rstrip("/"):
        return None
    if pc.path == pf.path:
        return None
    url = str(d.get("url") or "")
    return _issue(
        "canonical_trailing_slash_mismatch",
        f"Canonical khác trailing slash so với URL hiệu dụng: {c} vs {fe}",
        "medium",
        0.84,
        "indexability",
        why="Hai biến thể slash có thể tách tín hiệu index nếu không redirect/canonical nhất quán.",
        detected_from=["canonical_resolution.canonical_url", "canonical_resolution.final_effective_url"],
        causes=["CMS thêm/bỏ slash", "Server rewrite không thống nhất"],
        fixes=["Chọn một convention (có hoặc không slash) và 301 + canonical thống nhất."],
        validation=["curl -I cả hai biến thể slash.", "Screaming Frog canonical report."],
        url=url,
        evidence=[
            {"kind": "url", "url": url},
            {"kind": "canonical_url", "url": c},
            {"kind": "final_effective_url", "url": fe},
        ],
    )


def evaluate_canonical_low_similarity_mismatch(d: dict[str, Any]) -> dict[str, Any] | None:
    cta = d.get("canonical_target_analysis") or {}
    if not cta.get("fetched"):
        return None
    sim = cta.get("similarity_score")
    if sim is None:
        return None
    if float(sim) >= 0.35:
        return None
    cr = d["canonical_resolution"]
    fe = (cr.get("final_effective_url") or d["url"] or "").strip()
    c = (cr.get("canonical_url") or d["parsed"].get("canonical") or "").strip()
    if not c or _norm_url(str(c)) == _norm_url(str(fe)):
        return None
    return _issue(
        "canonical_low_similarity_mismatch",
        "Canonical trỏ URL khác nhưng độ tương đồng nội dung với đích rất thấp — có thể canonical sai hoặc Google bỏ qua.",
        "medium",
        0.78,
        "technical",
        why="Google dùng nhiều tín hiệu ngoài thẻ canonical; nội dung khác hẳn làm giảm xác suất consolidation.",
        detected_from=["canonical_target_analysis.similarity_score", "canonical_resolution.canonical_url"],
        causes=["Template khác", "Canonical copy nhầm", "A/B hoặc tham số sai", "Cross-domain syndication không duplicate"],
        fixes=["Đảm bảo canonical trỏ tới URL thực sự duplicate hoặc gần duplicate.", "Kiểm tra body chính vs đích."],
        validation=["So sánh text chính (main content) giữa hai URL.", "GSC Duplicate cluster nếu có."],
    )


def evaluate_google_may_ignore_canonical(d: dict[str, Any]) -> dict[str, Any] | None:
    sim = d.get("google_simulation") or {}
    if str(sim.get("canonical_source") or "") != "google_selected":
        return None
    return _issue(
        "google_may_ignore_canonical",
        "Mô phỏng: Google có thể không tôn trọng canonical đã khai báo (chuỗi hoặc similarity bất thường).",
        "medium",
        0.72,
        "technical",
        why="Khi canonical mâu thuẫn hoặc đích không tin cậy, URL hiển thị có thể khác cluster bạn kỳ vọng.",
        detected_from=["google_simulation.canonical_source", "google_simulation.ignored_signals"],
        causes=["Vòng canonical", "Đích noindex", "Nội dung không duplicate thực sự"],
        fixes=["Chuẩn hóa canonical chain một chiều.", "Đồng bộ nội dung duplicate hoặc bỏ canonical sai."],
        validation=["URL Inspection + xem user-declared vs Google-selected.", "Fetch đích canonical trong audit."],
    )


def evaluate_page_unlikely_indexed(d: dict[str, Any]) -> dict[str, Any] | None:
    sim = d.get("google_simulation") or {}
    if sim.get("will_index") is not False:
        return None
    fin = bool(d.get("final_indexability_resolved", d["indexability"].get("indexable", True)))
    if not fin:
        return None
    return _issue(
        "page_unlikely_indexed",
        "Mô phỏng hành vi Google: URL này khó là bản primary được index (duplicate/consolidation hoặc canonical bị hủy).",
        "high",
        0.74,
        "indexability",
        why="Kể cả khi HTTP 200 và meta cho phép index, canonical/duplicate modeling cho thấy URL có thể không xuất hiện như tài liệu độc lập.",
        detected_from=["google_simulation.will_index", "google_simulation.primary_url"],
        causes=["Self URL là bản duplicate của canonical khác", "Canonical đích không hợp lệ", "Chuỗi canonical lỗi"],
        fixes=["Xác định URL primary thật và self-canonical đúng.", "Sửa duplicate hoặc redirect 301 nếu intent là gộp."],
        validation=["GSC Coverage + URL Inspection (Google-selected canonical).", "So audit simulation vs thực tế GSC."],
    )


def evaluate_cloaking_risk_advanced(d: dict[str, Any]) -> dict[str, Any] | None:
    adv = d.get("cloaking_advanced") or {}
    if str(adv.get("cloaking_risk_level") or "").lower() != "high":
        return None
    return _issue(
        "cloaking_risk_advanced",
        "Cloaking risk (advanced): raw vs rendered khác biệt mạnh (text/DOM) hoặc kết hợp mismatch title/canonical.",
        "high",
        min(0.9, 0.55 + float(adv.get("text_similarity_score") or 0) * 0.15),
        "technical",
        why="Chênh lệch lớn giữa HTML tĩnh và DOM sau JS làm giảm tin cậy và có thể trùng với pattern rủi ro chính sách — cần review thủ công.",
        detected_from=[
            "cloaking_advanced.text_similarity_score",
            "cloaking_advanced.dom_similarity_score",
            "cloaking_advanced.title_mismatch",
            "cloaking_advanced.canonical_mismatch",
        ],
        causes=["CSR shell", "A/B theo UA", "Inject title/canonical sau render"],
        fixes=["SSR/hybrid cho phần quan trọng; đồng nhất raw vs rendered cho bot và user.", "Log UA theo policy."],
        validation=["So raw.html vs rendered.html.", "Rich Results / URL Inspection."],
    )


def evaluate_weak_heading_structure(d: dict[str, Any]) -> dict[str, Any] | None:
    h2 = d["parsed"].get("h2") or []
    wc = int(d["parsed"].get("word_count") or 0)
    h1c = int(d["parsed"].get("h1_count") or 0)
    if wc < 450 or h1c == 0:
        return None
    if isinstance(h2, list) and len(h2) >= 2:
        return None
    return _issue(
        "weak_heading_structure",
        "Nội dung dài nhưng ít H2 — cấu trúc heading có thể yếu cho phân mục.",
        "low",
        0.55,
        "structure",
        why="H2 giúp Google và người dùng quét chủ đề phụ; tránh 'tường text'.",
        detected_from=["parsed.h2", "parsed.word_count", "parsed.h1_count"],
        causes=["Một khối prose", "Editor không dùng heading"],
        fixes=["Chia section với H2/H3 logic."],
        validation=["Outline trong SF hoặc HeadingsMap."],
    )


RULES: list[IssueFn] = [
    evaluate_meta_robots_noindex,
    evaluate_x_robots_tag_noindex,
    evaluate_indexability_blocked,
    evaluate_http_status_non_200,
    evaluate_indexability_signal_conflict,
    evaluate_canonical_cross_host,
    evaluate_canonical_self_mismatch,
    evaluate_canonical_scheme_mismatch,
    evaluate_canonical_trailing_slash_mismatch,
    evaluate_canonical_missing_high_value,
    evaluate_canonical_points_to_bad_status,
    evaluate_canonical_points_to_non_indexable,
    evaluate_canonical_low_similarity_mismatch,
    evaluate_google_may_ignore_canonical,
    evaluate_page_unlikely_indexed,
    evaluate_cloaking_risk_advanced,
    evaluate_cloaking_heuristic,
    evaluate_js_seo_risk_high,
    evaluate_js_seo_risk_medium,
    evaluate_js_shell_missing_critical,
    evaluate_robots_meta_noindex_contradiction,
    evaluate_missing_title,
    evaluate_title_too_long,
    evaluate_title_too_short,
    evaluate_missing_meta_description,
    evaluate_meta_description_too_long,
    evaluate_missing_h1,
    evaluate_multiple_h1,
    evaluate_thin_content,
    evaluate_images_missing_alt,
    evaluate_images_broken_src,
    evaluate_missing_viewport,
    evaluate_soft_404_heuristic,
    evaluate_weak_heading_structure,
]


def run_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fn in RULES:
        try:
            issue = fn(data)
        except Exception:
            issue = None
        if issue:
            out.append(issue)
    return dedupe_and_prioritize_issues(out)


def _sev_rank(s: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(s).lower(), 0)


def dedupe_and_prioritize_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One issue per rule_id; prefer higher severity then confidence."""
    by_id: dict[str, dict[str, Any]] = {}
    for it in issues:
        rid = str(it.get("rule_id") or "")
        if not rid:
            continue
        cur = by_id.get(rid)
        if cur is None:
            by_id[rid] = it
            continue
        if _sev_rank(it["severity"]) > _sev_rank(cur["severity"]):
            by_id[rid] = it
        elif _sev_rank(it["severity"]) == _sev_rank(cur["severity"]) and float(it.get("confidence") or 0) > float(
            cur.get("confidence") or 0
        ):
            by_id[rid] = it
    merged = list(by_id.values())
    merged.sort(key=lambda x: (-_sev_rank(x.get("severity", "")), -float(x.get("confidence") or 0)))
    return merged


def compute_decision_score(issues: list[dict[str, Any]]) -> float:
    score = 100.0
    for it in issues:
        sev = str(it.get("severity") or "low").lower()
        if sev == "high":
            score -= 15
        elif sev == "medium":
            score -= 8
        else:
            score -= 3
    return max(0.0, min(100.0, round(score, 1)))


def run_seo_decision_layer(
    url: str,
    parsed: dict[str, Any],
    page_type: str,
    crawl_record: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.services.decision_engine_v2 import run_decision_engine_v2

    return run_decision_engine_v2(url, parsed, page_type, crawl_record)


def issues_to_legacy_api_issues(issues: list[dict[str, Any]], page_type: str) -> list[dict[str, Any]]:
    """Map rich decision issues to existing analyzer / formatter dict shape."""
    legacy: list[dict[str, Any]] = []
    for it in issues:
        rid = str(it.get("rule_id") or "decision")
        fixes = it.get("how_to_fix") or []
        evidence = list(it.get("evidence") or [])
        if not evidence:
            for field in it.get("detected_from") or []:
                if field:
                    evidence.append({"kind": "detected_from", "text": str(field)})
        row = {
                "type": rid,
                "severity": it.get("severity"),
                "message": it.get("issue"),
                "checklist_group": RULE_CHECKLIST.get(rid, "General"),
                "confidence": it.get("confidence"),
                "explanation": it.get("why_it_matters"),
                "remediation": "\n".join(fixes) if fixes else None,
                "page_type": page_type,
                "detected_from": it.get("detected_from"),
                "possible_causes": it.get("possible_causes"),
                "validation_steps": it.get("validation_steps"),
                "issue_category": it.get("category"),
                "adjusted_score_impact": it.get("adjusted_score_impact"),
                "decision_source": it.get("decision_source"),
                "suppressed": it.get("suppressed", False),
                "suppression_reason": it.get("suppression_reason"),
        }
        if evidence:
            row["evidence"] = evidence
        if it.get("url"):
            row["url"] = it.get("url")
        if it.get("affected_urls"):
            row["affected_urls"] = list(it.get("affected_urls") or [])
        elif it.get("url"):
            row["affected_urls"] = [it.get("url")]
        legacy.append(row)
    return legacy
