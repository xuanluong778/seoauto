"""
Chấm điểm SEO 1 URL theo 10 nhóm (tổng 100 điểm).
Bổ sung cho url_seo_scoreboard — không thay thế 12 trụ legacy.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

GROUP_WEIGHTS: dict[str, float] = {
    "indexability": 15.0,
    "title_meta_slug": 12.0,
    "heading": 8.0,
    "keyword_semantic": 12.0,
    "search_intent": 12.0,
    "content_quality": 12.0,
    "links": 8.0,
    "image_seo": 6.0,
    "schema": 7.0,
    "ux_mobile_speed": 8.0,
}

GROUP_LABELS: dict[str, str] = {
    "indexability": "Indexability",
    "title_meta_slug": "Title / Meta / Slug",
    "heading": "Heading",
    "keyword_semantic": "Keyword / Semantic",
    "search_intent": "Search Intent",
    "content_quality": "Content Quality",
    "links": "Internal / External Link",
    "image_seo": "Image SEO",
    "schema": "Schema",
    "ux_mobile_speed": "UX / Mobile / Speed",
}

PENALTY_CAPS: dict[str, float] = {
    "http_404_500": 40.0,
    "noindex": 50.0,
    "robots_blocked": 50.0,
    "canonical_wrong": 70.0,
    "thin_content": 75.0,
    "spam": 30.0,
}


def _check(
    *,
    check_id: str,
    title: str,
    status: str,
    score: float,
    max_score: float,
    problem: str = "",
    impact: str = "",
    fix: str = "",
) -> dict[str, Any]:
    st = status if status in ("passed", "warning", "failed") else "warning"
    return {
        "id": check_id,
        "title": title,
        "status": st,
        "score": round(max(0.0, min(max_score, float(score))), 1),
        "max_score": round(float(max_score), 1),
        "problem": problem or "—",
        "impact": impact or "—",
        "fix": fix or "—",
    }


def _group_score_from_checks(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 0.0
    earned = sum(float(c.get("score") or 0) for c in checks)
    max_total = sum(float(c.get("max_score") or 0) for c in checks)
    if max_total <= 0:
        return 0.0
    return round(min(100.0, earned / max_total * 100.0), 1)


def _slug_from_url(url: str) -> str:
    try:
        path = urlparse(url).path.strip("/")
        return path.split("/")[-1] if path else ""
    except Exception:
        return ""


def _has_noindex(html: str, headers: dict[str, Any]) -> bool:
    h = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if "x-robots-tag" in h and "noindex" in h["x-robots-tag"]:
        return True
    if not html:
        return False
    m = re.search(
        r'<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']+)["\']',
        html[:120_000],
        re.I,
    )
    if m and "noindex" in m.group(1).lower():
        return True
    return bool(re.search(r'<meta[^>]+content=["\'][^"\']*noindex', html[:120_000], re.I))


def _keyword_in_text(kw: str, text: str) -> bool:
    if not kw or not text:
        return False
    return kw.strip().lower() in text.lower()


def _token_overlap(keywords: list[str], text: str) -> float:
    if not keywords or not text:
        return 0.0
    t = text.lower()
    hits = sum(1 for k in keywords if k and k.strip().lower() in t)
    return hits / max(1, len(keywords))


def build_ten_group_scoreboard(
    *,
    url: str,
    normalized_url: str,
    fetch: dict[str, Any],
    page_data: dict[str, Any],
    content_pkg: dict[str, Any],
    html: str,
    headers: dict[str, Any],
    ld_blocks: list[dict[str, Any]],
    soup: BeautifulSoup | None,
    primary_keyword: str | None,
    secondary_keywords: list[str] | None,
    page_type: str | None,
    breakdown: dict[str, Any],
    legacy_issues: list[dict[str, Any]],
    serp_intent_pkg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build 10-group score payload for API + UI."""
    status = int(fetch.get("status") or 0)
    ok = bool(fetch.get("ok"))
    final_url = str(fetch.get("final_url") or normalized_url or url)
    title = str(page_data.get("title") or "")
    meta = str(page_data.get("meta_description") or "")
    canonical = str(page_data.get("canonical") or "")
    h1c = int(page_data.get("h1_count") or 0)
    h2c = int(page_data.get("h2_count") or 0)
    wc = int(content_pkg.get("word_count") or page_data.get("word_count") or 0)
    imgs = int(page_data.get("images_total") or 0)
    imgs_no_alt = int(page_data.get("images_missing_alt") or 0)
    depth = str(content_pkg.get("content_depth") or "thin")

    pk = (primary_keyword or "").strip()
    sec = [s.strip() for s in (secondary_keywords or []) if s and str(s).strip()]
    all_kw = ([pk] if pk else []) + sec
    ptype = (page_type or "unknown").strip().lower() or "unknown"
    slug = _slug_from_url(normalized_url or url)

    if soup is None:
        soup = BeautifulSoup((html or "")[:400_000], "html.parser")

    internal_links = len(soup.find_all("a", href=True))
    external_links = 0
    host = (urlparse(normalized_url or url).netloc or "").lower().lstrip("www.")
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        if href.startswith("http") and host and host not in href.lower():
            external_links += 1

    # --- Indexability ---
    idx_checks: list[dict[str, Any]] = []
    if status in (404, 410):
        idx_checks.append(
            _check(
                check_id="http_404",
                title="HTTP status 404/410",
                status="failed",
                score=0,
                max_score=25,
                problem=f"Trang trả HTTP {status}.",
                impact="Google không index trang lỗi — mất traffic.",
                fix="Sửa URL, redirect 301 tới trang thay thế hoặc khôi phục nội dung.",
            )
        )
    elif status >= 500:
        idx_checks.append(
            _check(
                check_id="http_5xx",
                title="Lỗi máy chủ 5xx",
                status="failed",
                score=0,
                max_score=25,
                problem=f"HTTP {status}.",
                impact="Bot không crawl ổn định — index bị gián đoạn.",
                fix="Khắc phục server/backend; kiểm tra log và CDN.",
            )
        )
    elif status == 200:
        idx_checks.append(
            _check(
                check_id="http_200",
                title="HTTP 200 OK",
                status="passed",
                score=25,
                max_score=25,
                problem="",
                impact="Trang phản hồi thành công.",
                fix="—",
            )
        )
    else:
        idx_checks.append(
            _check(
                check_id="http_other",
                title=f"HTTP {status}",
                status="warning",
                score=12,
                max_score=25,
                problem=f"Status {status} không phải 200.",
                impact="Có thể ảnh hưởng crawl/index.",
                fix="Đảm bảo URL chính trả 200 sau redirect.",
            )
        )

    noindex = _has_noindex(html, headers)
    idx_checks.append(
        _check(
            check_id="noindex",
            title="Không chặn noindex",
            status="failed" if noindex else "passed",
            score=0 if noindex else 20,
            max_score=20,
            problem="Phát hiện noindex." if noindex else "",
            impact="Trang sẽ không được index." if noindex else "Cho phép index.",
            fix="Gỡ noindex trên meta robots / HTTP header nếu muốn index." if noindex else "—",
        )
    )

    canon_ok = True
    canon_problem = ""
    if canonical:
        c_norm = canonical.rstrip("/").lower()
        u_norm = final_url.rstrip("/").lower()
        if c_norm != u_norm and normalized_url.rstrip("/").lower() not in c_norm:
            canon_ok = False
            canon_problem = f"Canonical ({canonical}) khác URL đích ({final_url})."
    idx_checks.append(
        _check(
            check_id="canonical",
            title="Canonical hợp lệ",
            status="passed" if canon_ok else "failed",
            score=20 if canon_ok else 0,
            max_score=20,
            problem=canon_problem,
            impact="Canonical sai gây trùng lặp / mất equity." if not canon_ok else "Chuẩn hóa URL index.",
            fix="Đặt self-referencing canonical trỏ đúng URL chính." if not canon_ok else "—",
        )
    )

    https_ok = final_url.lower().startswith("https://")
    idx_checks.append(
        _check(
            check_id="https",
            title="HTTPS",
            status="passed" if https_ok else "warning",
            score=15 if https_ok else 5,
            max_score=15,
            problem="" if https_ok else "URL không dùng HTTPS.",
            impact="Tín hiệu bảo mật & ranking." if not https_ok else "—",
            fix="Chuyển site sang HTTPS + redirect 301." if not https_ok else "—",
        )
    )

    robots_blocked = any(
        str(i.get("type") or "").startswith("robots_") and str(i.get("severity")) == "high"
        for i in legacy_issues
    )
    idx_checks.append(
        _check(
            check_id="robots_txt",
            title="Không bị chặn robots.txt",
            status="failed" if robots_blocked else "passed",
            score=0 if robots_blocked else 20,
            max_score=20,
            problem="Có tín hiệu bị chặn robots." if robots_blocked else "",
            impact="Google không crawl được trang." if robots_blocked else "—",
            fix="Sửa Disallow trong robots.txt." if robots_blocked else "—",
        )
    )

    # --- Title / Meta / Slug ---
    tms_checks: list[dict[str, Any]] = []
    tl = len(title)
    if not title.strip():
        tms_checks.append(
            _check(
                check_id="title_missing",
                title="Có thẻ Title",
                status="failed",
                score=0,
                max_score=30,
                problem="Thiếu title.",
                impact="CTR và relevance giảm mạnh.",
                fix="Thêm title duy nhất, chứa keyword chính.",
            )
        )
    elif 30 <= tl <= 60:
        tms_checks.append(
            _check(
                check_id="title_length",
                title="Độ dài Title",
                status="passed",
                score=30,
                max_score=30,
                problem="",
                impact=f"Title {tl} ký tự — trong khoảng tối ưu.",
                fix="—",
            )
        )
    else:
        tms_checks.append(
            _check(
                check_id="title_length",
                title="Độ dài Title",
                status="warning",
                score=18,
                max_score=30,
                problem=f"Title {tl} ký tự (khuyến nghị 30–60).",
                impact="CTR có thể bị cắt trên SERP.",
                fix="Rút gọn hoặc mở rộng title trong giới hạn.",
            )
        )

    ml = len(meta)
    if not meta.strip():
        tms_checks.append(
            _check(
                check_id="meta_missing",
                title="Meta description",
                status="warning",
                score=10,
                max_score=25,
                problem="Thiếu meta description.",
                impact="Google tự tạo snippet — CTR không kiểm soát.",
                fix="Viết meta 120–160 ký tự, có CTA.",
            )
        )
    elif 120 <= ml <= 160:
        tms_checks.append(
            _check(
                check_id="meta_length",
                title="Meta description",
                status="passed",
                score=25,
                max_score=25,
                problem="",
                impact="Snippet tối ưu.",
                fix="—",
            )
        )
    else:
        tms_checks.append(
            _check(
                check_id="meta_length",
                title="Meta description",
                status="warning",
                score=15,
                max_score=25,
                problem=f"Meta {ml} ký tự.",
                impact="Snippet có thể bị cắt.",
                fix="Chỉnh meta về 120–160 ký tự.",
            )
        )

    slug_ok = bool(slug) and len(slug) <= 80 and " " not in slug
    kw_in_slug = _keyword_in_text(pk, slug.replace("-", " ")) if pk and slug else False
    tms_checks.append(
        _check(
            check_id="slug",
            title="URL slug thân thiện",
            status="passed" if slug_ok and (not pk or kw_in_slug) else "warning",
            score=25 if slug_ok and (not pk or kw_in_slug) else 12,
            max_score=25,
            problem="" if slug_ok else "Slug dài hoặc thiếu.",
            impact="URL sạch giúp relevance & CTR.",
            fix="Dùng slug ngắn, có keyword, dấu gạch ngang." if not slug_ok or (pk and not kw_in_slug) else "—",
        )
    )

    if pk:
        in_title = _keyword_in_text(pk, title)
        tms_checks.append(
            _check(
                check_id="kw_in_title",
                title="Keyword chính trong Title",
                status="passed" if in_title else "warning",
                score=20 if in_title else 8,
                max_score=20,
                problem="" if in_title else f"Không thấy «{pk}» trong title.",
                impact="Liên quan chủ đề trên SERP.",
                fix="Đưa keyword tự nhiên vào đầu title." if not in_title else "—",
            )
        )

    # --- Heading ---
    hd_checks: list[dict[str, Any]] = []
    if h1c == 1:
        hd_checks.append(
            _check(
                check_id="h1_single",
                title="Một H1 duy nhất",
                status="passed",
                score=40,
                max_score=40,
                problem="",
                impact="Cấu trúc heading rõ.",
                fix="—",
            )
        )
    elif h1c == 0:
        hd_checks.append(
            _check(
                check_id="h1_missing",
                title="Có H1",
                status="failed",
                score=0,
                max_score=40,
                problem="Thiếu H1.",
                impact="Khó hiểu chủ đề trang.",
                fix="Thêm một H1 chứa keyword chính.",
            )
        )
    else:
        hd_checks.append(
            _check(
                check_id="h1_multiple",
                title="Một H1 duy nhất",
                status="warning",
                score=20,
                max_score=40,
                problem=f"Có {h1c} thẻ H1.",
                impact="Phân tán relevance.",
                fix="Gộp còn 1 H1.",
            )
        )

    if h2c >= 2:
        hd_checks.append(
            _check(
                check_id="h2_structure",
                title="Cấu trúc H2",
                status="passed",
                score=35,
                max_score=35,
                problem="",
                impact=f"{h2c} H2 hỗ trợ scan nội dung.",
                fix="—",
            )
        )
    else:
        hd_checks.append(
            _check(
                check_id="h2_structure",
                title="Cấu trúc H2",
                status="warning",
                score=15,
                max_score=35,
                problem="Ít hoặc không có H2.",
                impact="Nội dung khó đọc / thiếu hierarchy.",
                fix="Chia section bằng H2 theo outline.",
            )
        )

    heading_score_legacy = float((breakdown.get("structure") or {}).get("heading_structure_score") or 0)
    if heading_score_legacy >= 0.6:
        hd_checks.append(
            _check(
                check_id="heading_hierarchy",
                title="Thứ bậc heading",
                status="passed",
                score=25,
                max_score=25,
                problem="",
                impact="Outline logic.",
                fix="—",
            )
        )
    else:
        hd_checks.append(
            _check(
                check_id="heading_hierarchy",
                title="Thứ bậc heading",
                status="warning",
                score=12,
                max_score=25,
                problem="Thứ bậc heading chưa tối ưu.",
                impact="UX & featured snippet.",
                fix="Không nhảy cấp H1→H4; dùng H2/H3 tuần tự.",
            )
        )

    # --- Keyword / Semantic ---
    ks_checks: list[dict[str, Any]] = []
    body_text = soup.get_text(" ", strip=True)[:50_000] if soup else ""
    if pk:
        in_body = _keyword_in_text(pk, body_text)
        ks_checks.append(
            _check(
                check_id="primary_in_body",
                title="Keyword chính trong nội dung",
                status="passed" if in_body else "failed",
                score=35 if in_body else 0,
                max_score=35,
                problem="" if in_body else f"Không thấy «{pk}» trong body.",
                impact="Relevance chủ đề.",
                fix="Dùng keyword tự nhiên trong intro và H2." if not in_body else "—",
            )
        )
    else:
        ks_checks.append(
            _check(
                check_id="primary_kw",
                title="Keyword chính",
                status="warning",
                score=15,
                max_score=35,
                problem="Chưa nhập keyword chính.",
                impact="Không đánh giá semantic đầy đủ.",
                fix="Nhập primary keyword khi chấm điểm.",
            )
        )

    sec_overlap = _token_overlap(sec, body_text)
    ks_checks.append(
        _check(
            check_id="secondary_keywords",
            title="Secondary keywords",
            status="passed" if sec_overlap >= 0.5 or not sec else "warning",
            score=25 if sec_overlap >= 0.5 else (15 if sec else 20),
            max_score=25,
            problem="" if sec_overlap >= 0.5 or not sec else "Một số secondary chưa xuất hiện.",
            impact="Phủ semantic chủ đề.",
            fix="Bổ sung LSI/secondary vào H2 và đoạn văn." if sec and sec_overlap < 0.5 else "—",
        )
    )

    kw_comp = float((breakdown.get("keyword_semantic") or {}).get("keyword_in_title") or 0)
    ks_checks.append(
        _check(
            check_id="semantic_coverage",
            title="Semantic coverage",
            status="passed" if kw_comp or _token_overlap(all_kw, title + " " + meta) >= 0.3 else "warning",
            score=20,
            max_score=20,
            problem="",
            impact="Title/meta phủ chủ đề.",
            fix="Mở rộng từ đồng nghĩa quanh keyword.",
        )
    )

    density = float((content_pkg.get("keyword_density_estimate") or {}).get(pk, 0) if pk else 0)
    spam = density > 0.035 if pk else False
    ks_checks.append(
        _check(
            check_id="keyword_density",
            title="Mật độ keyword",
            status="failed" if spam else "passed",
            score=0 if spam else 20,
            max_score=20,
            problem=f"Mật độ ~{density:.2%} — có thể spam." if spam else "",
            impact="Penalty spam / quality." if spam else "Mật độ ổn.",
            fix="Giảm lặp keyword; viết tự nhiên." if spam else "—",
        )
    )

    # --- Search Intent ---
    si_checks: list[dict[str, Any]] = []
    page_intent = (breakdown.get("intent") or {}).get("page_intent") or {}
    pi = str(page_intent.get("intent") or "unknown")
    serp_i = str((serp_intent_pkg or {}).get("serp_intent") or "unknown")
    match = pi == serp_i or pi == "unknown" or serp_i == "unknown"
    if pk and serp_intent_pkg:
        si_checks.append(
            _check(
                check_id="intent_match",
                title="Khớp intent SERP",
                status="passed" if match else "failed",
                score=50 if match else 10,
                max_score=50,
                problem="" if match else f"Trang {pi} vs SERP {serp_i}.",
                impact="Không khớp intent → khó top 10.",
                fix="Điều chỉnh format nội dung theo SERP (blog/landing/list)." if not match else "—",
            )
        )
    elif pk:
        si_checks.append(
            _check(
                check_id="intent_match",
                title="Khớp intent SERP",
                status="warning",
                score=25,
                max_score=50,
                problem="Chưa có dữ liệu SERP.",
                impact="Không xác nhận intent.",
                fix="Bật phân tích SERP (API key).",
            )
        )
    else:
        si_checks.append(
            _check(
                check_id="intent_match",
                title="Search intent",
                status="warning",
                score=20,
                max_score=50,
                problem="Chưa có keyword → không phân loại intent.",
                impact="—",
                fix="Nhập keyword chính.",
            )
        )

    if ptype != "unknown":
        si_checks.append(
            _check(
                check_id="page_type",
                title=f"Page type: {ptype}",
                status="passed",
                score=25,
                max_score=25,
                problem="",
                impact="Đối chiếu checklist theo loại trang.",
                fix="—",
            )
        )

    si_checks.append(
        _check(
            check_id="cta_intent",
            title="CTA / conversion signals",
            status="passed" if re.search(r"(mua|đăng ký|liên hệ|contact|buy|order)", body_text, re.I) else "warning",
            score=25,
            max_score=25,
            problem="",
            impact="Phù hợp commercial intent.",
            fix="Thêm CTA rõ nếu landing/commercial.",
        )
    )

    # --- Content Quality ---
    cq_checks: list[dict[str, Any]] = []
    thin = wc < 300 or depth == "thin"
    if thin:
        cq_checks.append(
            _check(
                check_id="word_count",
                title="Độ dài nội dung",
                status="failed" if wc < 150 else "warning",
                score=10 if wc >= 150 else 0,
                max_score=40,
                problem=f"~{wc} từ — thin content.",
                impact="Khó cạnh tranh informational queries.",
                fix="Mở rộng nội dung có giá trị (FAQ, ví dụ, data).",
            )
        )
    else:
        cq_checks.append(
            _check(
                check_id="word_count",
                title="Độ dài nội dung",
                status="passed",
                score=40,
                max_score=40,
                problem="",
                impact=f"~{wc} từ.",
                fix="—",
            )
        )

    helpful = float((breakdown.get("helpful_content") or {}).get("score") or content_pkg.get("heading_structure_score") or 0.5)
    cq_checks.append(
        _check(
            check_id="helpful_content",
            title="Helpful content signals",
            status="passed" if helpful >= 0.55 else "warning",
            score=30 if helpful >= 0.55 else 15,
            max_score=30,
            problem="" if helpful >= 0.55 else "Thiếu format helpful (list, FAQ).",
            impact="Quality rater guidelines.",
            fix="Thêm FAQ, bullet, ví dụ thực tế.",
        )
    )

    cq_checks.append(
        _check(
            check_id="uniqueness",
            title="Nội dung độc đáo",
            status="warning",
            score=15,
            max_score=30,
            problem="Chưa so sánh duplicate (cần crawl đối thủ).",
            impact="—",
            fix="Tránh copy; bổ sung insight riêng.",
        )
    )

    # --- Links ---
    lk_checks: list[dict[str, Any]] = []
    if internal_links >= 5:
        lk_checks.append(
            _check(
                check_id="internal_links",
                title="Internal links",
                status="passed",
                score=50,
                max_score=50,
                problem="",
                impact=f"~{internal_links} link nội bộ.",
                fix="—",
            )
        )
    else:
        lk_checks.append(
            _check(
                check_id="internal_links",
                title="Internal links",
                status="warning",
                score=20,
                max_score=50,
                problem="Ít liên kết nội bộ.",
                impact="PageRank nội bộ yếu.",
                fix="Link tới pillar/cluster liên quan.",
            )
        )

    if external_links >= 1:
        lk_checks.append(
            _check(
                check_id="external_links",
                title="External links",
                status="passed",
                score=25,
                max_score=25,
                problem="",
                impact="Trích dẫn nguồn uy tín.",
                fix="—",
            )
        )
    else:
        lk_checks.append(
            _check(
                check_id="external_links",
                title="External links",
                status="warning",
                score=10,
                max_score=25,
                problem="Không có outlink.",
                impact="Thiếu tín hiệu E-E-A-T.",
                fix="Link nguồn tham khảo chất lượng.",
            )
        )

    lk_checks.append(
        _check(
            check_id="anchor_diversity",
            title="Anchor text đa dạng",
            status="passed",
            score=25,
            max_score=25,
            problem="",
            impact="Tránh over-optimize.",
            fix="—",
        )
    )

    # --- Image SEO ---
    im_checks: list[dict[str, Any]] = []
    if imgs == 0:
        im_checks.append(
            _check(
                check_id="images_present",
                title="Hình ảnh trên trang",
                status="warning",
                score=20,
                max_score=40,
                problem="Không có ảnh.",
                impact="UX & image search.",
                fix="Thêm ảnh minh họa có alt.",
            )
        )
    elif imgs_no_alt == 0:
        im_checks.append(
            _check(
                check_id="alt_text",
                title="Alt text",
                status="passed",
                score=40,
                max_score=40,
                problem="",
                impact=f"{imgs} ảnh có alt.",
                fix="—",
            )
        )
    else:
        im_checks.append(
            _check(
                check_id="alt_text",
                title="Alt text",
                status="failed" if imgs_no_alt > imgs // 2 else "warning",
                score=15,
                max_score=40,
                problem=f"{imgs_no_alt}/{imgs} ảnh thiếu alt.",
                impact="Image SEO & accessibility.",
                fix="Bổ sung alt mô tả, có keyword khi phù hợp.",
            )
        )

    im_checks.append(
        _check(
            check_id="image_optimization",
            title="Tối ưu kích thước ảnh",
            status="warning",
            score=30,
            max_score=30,
            problem="Chưa đo dung lượng ảnh (cần lab).",
            impact="—",
            fix="Nén WebP/AVIF, lazy-load.",
        )
    )

    im_checks.append(
        _check(
            check_id="image_sitemap",
            title="Image sitemap",
            status="warning",
            score=15,
            max_score=30,
            problem="Chưa xác minh image sitemap.",
            impact="Image discovery.",
            fix="Thêm URL ảnh vào sitemap hoặc image sitemap riêng.",
        )
    )

    # --- Schema ---
    sch_checks: list[dict[str, Any]] = []
    if ld_blocks:
        types = []
        for b in ld_blocks:
            t = b.get("@type")
            if isinstance(t, list):
                types.extend(t)
            elif t:
                types.append(str(t))
        sch_checks.append(
            _check(
                check_id="structured_data",
                title="Structured data",
                status="passed",
                score=50,
                max_score=50,
                problem="",
                impact=f"Types: {', '.join(types[:5]) or 'JSON-LD'}.",
                fix="—",
            )
        )
        sch_checks.append(
            _check(
                check_id="schema_valid",
                title="Schema hợp lệ",
                status="passed",
                score=30,
                max_score=30,
                problem="",
                impact="Rich results eligibility.",
                fix="—",
            )
        )
    else:
        sch_checks.append(
            _check(
                check_id="structured_data",
                title="Structured data",
                status="failed",
                score=0,
                max_score=50,
                problem="Không có JSON-LD.",
                impact="Mất rich results.",
                fix="Thêm Article/Product/Organization schema.",
            )
        )
        sch_checks.append(
            _check(
                check_id="schema_valid",
                title="Schema hợp lệ",
                status="failed",
                score=0,
                max_score=30,
                problem="—",
                impact="—",
                fix="—",
            )
        )

    sch_checks.append(
        _check(
            check_id="local_business",
            title="Local Business (nếu cần)",
            status="warning",
            score=20,
            max_score=20,
            problem="Chưa xác minh LocalBusiness.",
            impact="Local pack.",
            fix="Thêm LocalBusiness nếu có địa chỉ.",
        )
    )

    # --- UX / Mobile / Speed ---
    ux_checks: list[dict[str, Any]] = []
    viewport = bool(soup.find("meta", attrs={"name": "viewport"})) if soup else False
    ux_checks.append(
        _check(
            check_id="viewport",
            title="Mobile viewport",
            status="passed" if viewport else "failed",
            score=30 if viewport else 0,
            max_score=30,
            problem="" if viewport else "Thiếu meta viewport.",
            impact="Mobile-friendly.",
            fix='Thêm <meta name="viewport" content="width=device-width, initial-scale=1">.' if not viewport else "—",
        )
    )

    speed_proxy = float((breakdown.get("speed_mobile") or {}).get("score") or 70)
    if speed_proxy >= 70:
        ux_checks.append(
            _check(
                check_id="speed_proxy",
                title="Tốc độ (proxy)",
                status="passed",
                score=35,
                max_score=35,
                problem="",
                impact="HTML weight / HTTPS OK.",
                fix="—",
            )
        )
    else:
        ux_checks.append(
            _check(
                check_id="speed_proxy",
                title="Tốc độ (proxy)",
                status="warning",
                score=18,
                max_score=35,
                problem="HTML nặng hoặc tài nguyên chặn.",
                impact="CWV & ranking mobile.",
                fix="Giảm JS/CSS, bật cache, CDN.",
            )
        )

    ux_checks.append(
        _check(
            check_id="readability",
            title="Khả năng đọc",
            status="passed",
            score=20,
            max_score=20,
            problem="",
            impact="UX engagement.",
            fix="—",
        )
    )

    ux_checks.append(
        _check(
            check_id="cwv_lab",
            title="Core Web Vitals",
            status="warning",
            score=15,
            max_score=15,
            problem="Cần PageSpeed/Lighthouse để đo LCP/CLS.",
            impact="—",
            fix="Chạy PSI cho URL.",
        )
    )

    groups_raw: dict[str, list[dict[str, Any]]] = {
        "indexability": idx_checks,
        "title_meta_slug": tms_checks,
        "heading": hd_checks,
        "keyword_semantic": ks_checks,
        "search_intent": si_checks,
        "content_quality": cq_checks,
        "links": lk_checks,
        "image_seo": im_checks,
        "schema": sch_checks,
        "ux_mobile_speed": ux_checks,
    }

    groups: list[dict[str, Any]] = []
    group_scores: dict[str, float] = {}
    weighted_total = 0.0
    weight_sum = sum(GROUP_WEIGHTS.values())

    for gid, checks in groups_raw.items():
        gscore = _group_score_from_checks(checks)
        w = GROUP_WEIGHTS.get(gid, 0.0)
        wp = round(gscore * w / 100.0, 2)
        weighted_total += wp
        group_scores[gid] = gscore
        groups.append(
            {
                "id": gid,
                "label": GROUP_LABELS.get(gid, gid),
                "weight": w,
                "weight_percent": round(w / weight_sum * 100, 1),
                "score": gscore,
                "weighted_points": wp,
                "checks": checks,
                "checks_passed": sum(1 for c in checks if c["status"] == "passed"),
                "checks_warning": sum(1 for c in checks if c["status"] == "warning"),
                "checks_failed": sum(1 for c in checks if c["status"] == "failed"),
            }
        )

    total_score = round(weighted_total, 1)
    penalties_applied: list[dict[str, Any]] = []

    if status in (404, 410, 500, 502, 503):
        cap = PENALTY_CAPS["http_404_500"]
        if total_score > cap:
            penalties_applied.append({"code": "http_404_500", "cap": cap, "reason": f"HTTP {status}"})
            total_score = cap
    if noindex:
        cap = PENALTY_CAPS["noindex"]
        if total_score > cap:
            penalties_applied.append({"code": "noindex", "cap": cap, "reason": "noindex detected"})
            total_score = cap
    if robots_blocked:
        cap = PENALTY_CAPS["robots_blocked"]
        if total_score > cap:
            penalties_applied.append({"code": "robots_blocked", "cap": cap, "reason": "robots block"})
            total_score = cap
    if not canon_ok and canonical:
        cap = PENALTY_CAPS["canonical_wrong"]
        if total_score > cap:
            penalties_applied.append({"code": "canonical_wrong", "cap": cap, "reason": "canonical mismatch"})
            total_score = cap
    if thin:
        cap = PENALTY_CAPS["thin_content"]
        if total_score > cap:
            penalties_applied.append({"code": "thin_content", "cap": cap, "reason": f"thin content ({wc} words)"})
            total_score = cap
    if spam:
        cap = PENALTY_CAPS["spam"]
        if total_score > cap:
            penalties_applied.append({"code": "spam", "cap": cap, "reason": "keyword stuffing"})
            total_score = cap

    total_score = max(0.0, min(100.0, round(total_score, 1)))

    strengths: list[str] = []
    weaknesses: list[str] = []
    for g in groups:
        if g["score"] >= 80:
            strengths.append(f"{g['label']}: {g['score']}/100 — {g['checks_passed']} checks passed")
        elif g["score"] < 55:
            failed = [c for c in g["checks"] if c["status"] == "failed"]
            hint = failed[0]["title"] if failed else g["label"]
            weaknesses.append(f"{g['label']}: {g['score']}/100 — cần cải thiện ({hint})")

    priority_fixes: list[dict[str, Any]] = []
    for g in sorted(groups, key=lambda x: x["score"]):
        for c in g["checks"]:
            if c["status"] == "failed":
                priority_fixes.append(
                    {
                        "group": g["id"],
                        "group_label": g["label"],
                        "check_id": c["id"],
                        "title": c["title"],
                        "problem": c["problem"],
                        "fix": c["fix"],
                        "priority": "high",
                    }
                )
            elif c["status"] == "warning" and len(priority_fixes) < 12:
                priority_fixes.append(
                    {
                        "group": g["id"],
                        "group_label": g["label"],
                        "check_id": c["id"],
                        "title": c["title"],
                        "problem": c["problem"],
                        "fix": c["fix"],
                        "priority": "medium",
                    }
                )
    priority_fixes = priority_fixes[:10]

    ai_suggestions: list[str] = []
    if pk:
        ai_suggestions.append(
            f"Tối ưu title/meta để chứa «{pk}» và khớp intent {serp_i}."
        )
    if thin:
        ai_suggestions.append(f"Mở rộng nội dung từ ~{wc} lên ít nhất 800–1200 từ cho query informational.")
    if not ld_blocks:
        ai_suggestions.append("Thêm JSON-LD Article hoặc WebPage + BreadcrumbList.")
    if imgs_no_alt > 0:
        ai_suggestions.append(f"Bổ sung alt cho {imgs_no_alt} ảnh — mô tả ngữ cảnh, không nhồi keyword.")
    if weaknesses:
        ai_suggestions.append(f"Ưu tiên nhóm yếu nhất: {weaknesses[0].split('—')[0].strip()}.")
    if not ai_suggestions:
        ai_suggestions.append("Duy trì chất lượng; theo dõi GSC và cập nhật nội dung định kỳ.")

    return {
        "total_score": total_score,
        "group_scores": group_scores,
        "groups": groups,
        "strengths": strengths[:8],
        "weaknesses": weaknesses[:8],
        "priority_fixes": priority_fixes,
        "ai_suggestions": ai_suggestions[:6],
        "penalties_applied": penalties_applied,
        "primary_keyword": pk or None,
        "secondary_keywords": sec,
        "page_type": ptype,
        "weights": GROUP_WEIGHTS,
        "group_labels": GROUP_LABELS,
    }
