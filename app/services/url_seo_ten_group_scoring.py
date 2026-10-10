"""
Chấm điểm SEO 1 URL theo 10 nhóm (tổng 100 điểm) — SSOT main score.
Legacy 12 trụ / 15 checklist không ảnh hưởng total_score ở đây.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.seo_score_intent import analyze_search_intent
from app.services.seo_score_link_analyzer import analyze_page_links
from app.services.seo_score_schema_checks import evaluate_schema_for_page
from app.services.seo_score_ssot import (
    GROUP_LABELS,
    GROUP_WEIGHTS,
    SCORING_VERSION,
    compute_ssot_total,
    count_checks_by_status,
    group_score_from_checks,
    make_check,
)

_LINK_PARTIAL_WARNING = "Chưa đủ dữ liệu để đánh giá link"

PENALTY_CAPS: dict[str, float] = {
    "http_404_500": 40.0,
    "noindex": 50.0,
    "robots_blocked": 50.0,
    "canonical_wrong": 70.0,
    "thin_content": 75.0,
    "spam": 30.0,
}


def _check(**kwargs: Any) -> dict[str, Any]:
    """Backward-compatible alias — maps legacy passed/warning/failed to SSOT statuses."""
    st = str(kwargs.pop("status", "warning"))
    legacy_map = {"passed": "PASS", "warning": "WARNING", "failed": "FAIL"}
    if st in legacy_map:
        st = legacy_map[st]
    fix = kwargs.pop("fix", "")
    return make_check(status=st, fix=fix, recommendation=fix, **kwargs)


def _slug_from_url(url: str) -> str:
    try:
        path = urlparse(url).path.strip("/")
        return path.split("/")[-1] if path else ""
    except Exception:
        return ""


def _page_host_key(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _rel_tokens(rel_val: Any) -> set[str]:
    if rel_val is None:
        return set()
    if isinstance(rel_val, list):
        raw = " ".join(str(x) for x in rel_val)
    else:
        raw = str(rel_val)
    return {t.strip().lower() for t in raw.split() if t.strip()}


def _empty_link_profile(*, partial: bool = True, warning: str | None = _LINK_PARTIAL_WARNING) -> dict[str, Any]:
    return {
        "internal_links_count": 0,
        "external_links_count": 0,
        "total_links_count": 0,
        "broken_links": [],
        "anchor_texts": [],
        "nofollow_count": 0,
        "dofollow_count": 0,
        "links": [],
        "link_opportunities": [],
        "partial_data": partial,
        "warning": warning if partial else None,
    }


def analyze_page_links(
    html: str,
    base_url: str,
    *,
    soup: BeautifulSoup | None = None,
    parsed_links: list[dict[str, Any]] | None = None,
    verify_http: bool = True,
) -> dict[str, Any]:
    from app.services.seo_score_link_analyzer import analyze_page_links as _impl

    return _impl(
        html,
        base_url,
        soup=soup,
        parsed_links=parsed_links,
        verify_http=verify_http,
    )


def _anchor_diversity_score(rows: list[dict[str, Any]]) -> tuple[str, float, float, str]:
    """Return status, score, max_score, problem."""
    if not rows:
        return "warning", 5.0, 25.0, "Không có anchor text để đánh giá."
    texts = [str(r.get("anchor") or "").strip().lower() for r in rows if str(r.get("anchor") or "").strip()]
    if not texts:
        return "warning", 8.0, 25.0, "Link thiếu anchor text mô tả."
    unique = len(set(texts))
    ratio = unique / max(1, len(texts))
    if ratio >= 0.65 and len(texts) >= 3:
        return "passed", 25.0, 25.0, ""
    if ratio >= 0.4:
        return "warning", 15.0, 25.0, "Anchor text hơi lặp — nên đa dạng hơn."
    return "warning", 8.0, 25.0, "Anchor text trùng lặp nhiều — dễ over-optimize."


def ensure_ten_groups_complete(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Đảm bảo đủ 10 nhóm (kể cả links) cho UI/API."""
    by_id = {str(g.get("id") or ""): g for g in groups if g.get("id")}
    complete: list[dict[str, Any]] = []
    for gid in GROUP_WEIGHTS:
        if gid in by_id:
            complete.append(by_id[gid])
            continue
        w = GROUP_WEIGHTS[gid]
        placeholder_checks = [
            _check(
                check_id=f"{gid}_partial",
                title=GROUP_LABELS.get(gid, gid),
                status="warning",
                score=0,
                max_score=100,
                problem=_LINK_PARTIAL_WARNING if gid == "links" else "Chưa có dữ liệu nhóm.",
                impact="Không tính điểm giả cho nhóm này.",
                fix="Thử chấm điểm lại hoặc kiểm tra URL có phản hồi HTML.",
            )
        ]
        gscore = 0.0
        complete.append(
            {
                "id": gid,
                "label": GROUP_LABELS.get(gid, gid),
                "weight": w,
                "weight_percent": round(w / sum(GROUP_WEIGHTS.values()) * 100, 1),
                "score": gscore,
                "weighted_points": 0.0,
                "checks": placeholder_checks,
                "checks_passed": 0,
                "checks_warning": 1,
                "checks_failed": 0,
                "partial_data": True,
                "warning": _LINK_PARTIAL_WARNING if gid == "links" else "Chưa đủ dữ liệu nhóm.",
            }
        )
    return complete


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
    link_profile: dict[str, Any] | None = None,
    serp_rows: list[dict[str, Any]] | None = None,
    schema_validation: dict[str, Any] | None = None,
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

    if link_profile is None:
        link_profile = analyze_page_links(html, normalized_url or url, soup=soup, verify_http=True)
    internal_links = int(link_profile.get("internal_links_count") or 0)
    external_links = int(link_profile.get("external_links_count") or 0)
    links_partial = bool(link_profile.get("partial_data"))
    links_warning = str(link_profile.get("warning") or "")
    link_rows = list(link_profile.get("links") or [])

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

    # --- Search Intent (SERP Top 10 evidence) ---
    si_checks: list[dict[str, Any]] = []
    intent_pkg = analyze_search_intent(
        keyword=pk or None,
        page_type=ptype,
        title=title,
        body_text=body_text,
        serp_rows=serp_rows,
        page_intent_breakdown=(breakdown.get("intent") or {}).get("page_intent"),
    )
    ist = str(intent_pkg.get("status") or "UNKNOWN")
    ic_conf = float(intent_pkg.get("confidence") or 0.0)
    ic_score = 50 if ist == "PASS" else (30 if ist == "WARNING" else 15)
    si_checks.append(
        make_check(
            check_id="intent_match",
            title="Khớp intent SERP Top 10",
            status=ist if pk else "UNKNOWN",
            score=ic_score if pk else 10,
            max_score=50,
            confidence=ic_conf if pk else 0.2,
            evidence=intent_pkg.get("evidence") or {},
            problem=str(intent_pkg.get("mismatch_reason") or ""),
            impact="Intent lệch SERP → khó top 10." if intent_pkg.get("mismatch") else "Intent phù hợp SERP.",
            recommendation="Điều chỉnh format nội dung theo SERP winners." if intent_pkg.get("mismatch") else "—",
        )
    )
    if ptype != "unknown":
        si_checks.append(
            make_check(
                check_id="page_type",
                title=f"Page type: {ptype}",
                status="PASS",
                score=25,
                max_score=25,
                confidence=0.7,
                evidence={"page_type": ptype},
                problem="",
                impact="Đối chiếu checklist theo loại trang.",
                recommendation="—",
            )
        )
    else:
        si_checks.append(
            make_check(
                check_id="page_type",
                title="Page type",
                status="UNKNOWN",
                score=10,
                max_score=25,
                confidence=0.35,
                evidence={},
                problem="Chưa chọn loại trang.",
                impact="—",
                recommendation="Chọn page type để so khớp SERP chính xác hơn.",
            )
        )
    has_cta = bool(re.search(r"(mua|đăng ký|liên hệ|contact|buy|order)", body_text, re.I))
    si_checks.append(
        make_check(
            check_id="cta_intent",
            title="CTA / conversion signals",
            status="PASS" if has_cta else "WARNING",
            score=25 if has_cta else 12,
            max_score=25,
            confidence=0.55 if has_cta else 0.4,
            evidence={"cta_detected": has_cta},
            problem="" if has_cta else "Chưa thấy CTA rõ.",
            impact="Commercial/transactional intent.",
            recommendation="Thêm CTA rõ nếu landing/commercial.",
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
        make_check(
            check_id="uniqueness",
            title="Nội dung độc đáo",
            status="UNKNOWN",
            score=0,
            max_score=30,
            confidence=0.0,
            evidence={"method": "heuristic_unavailable"},
            problem="Chưa có crawl đối thủ / fingerprint để xác minh uniqueness.",
            impact="—",
            recommendation="Tránh copy; bổ sung insight riêng (không khẳng định duplicate).",
        )
    )

    # --- Links ---
    lk_checks: list[dict[str, Any]] = []
    if links_partial:
        lk_checks.append(
            _check(
                check_id="links_data",
                title="Dữ liệu link",
                status="warning",
                score=0,
                max_score=100,
                problem=links_warning or _LINK_PARTIAL_WARNING,
                impact="Không thể chấm điểm link chính xác.",
                fix="Kiểm tra URL trả HTML; thử lại sau khi trang tải đủ nội dung.",
            )
        )
    else:
        if internal_links >= 5:
            lk_checks.append(
                _check(
                    check_id="internal_links",
                    title="Internal links",
                    status="passed",
                    score=50,
                    max_score=50,
                    problem="",
                    impact=f"{internal_links} internal link.",
                    fix="—",
                )
            )
        elif internal_links >= 1:
            lk_checks.append(
                _check(
                    check_id="internal_links",
                    title="Internal links",
                    status="warning",
                    score=20 + min(15, internal_links * 3),
                    max_score=50,
                    problem=f"Chỉ có {internal_links} internal link.",
                    impact="PageRank nội bộ còn yếu.",
                    fix="Link tới pillar/cluster liên quan.",
                )
            )
        else:
            lk_checks.append(
                _check(
                    check_id="internal_links",
                    title="Internal links",
                    status="warning",
                    score=5,
                    max_score=50,
                    problem="Không có internal link crawl được.",
                    impact="PageRank nội bộ yếu.",
                    fix="Thêm liên kết nội bộ contextual.",
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
                    impact=f"{external_links} external link.",
                    fix="—",
                )
            )
        else:
            lk_checks.append(
                _check(
                    check_id="external_links",
                    title="External links",
                    status="warning",
                    score=8,
                    max_score=25,
                    problem="Không có external link.",
                    impact="Thiếu tín hiệu E-E-A-T.",
                    fix="Link nguồn tham khảo chất lượng.",
                )
            )

        ad_status, ad_score, ad_max, ad_problem = _anchor_diversity_score(link_rows)
        lk_checks.append(
            _check(
                check_id="anchor_diversity",
                title="Anchor text đa dạng",
                status=ad_status,
                score=ad_score,
                max_score=ad_max,
                problem=ad_problem,
                impact="Tránh over-optimize anchor.",
                fix="Dùng anchor mô tả, không lặp keyword quá mức.",
            )
        )

        broken = list(link_profile.get("broken_links") or [])
        if broken:
            lk_checks.append(
                make_check(
                    check_id="broken_links",
                    title="Broken links (HTTP evidence)",
                    status="FAIL" if len(broken) >= 2 else "WARNING",
                    score=5 if broken else 20,
                    max_score=20,
                    confidence=0.85,
                    evidence={"broken": broken[:5], "http_verified": link_profile.get("http_verified")},
                    problem=f"{len(broken)} URL trả HTTP lỗi/không truy cập.",
                    impact="Bot và người dùng gặp dead-end.",
                    recommendation="Sửa hoặc gỡ link trỏ tới URL lỗi.",
                )
            )
        else:
            lk_checks.append(
                make_check(
                    check_id="broken_links",
                    title="Broken links (HTTP evidence)",
                    status="PASS" if link_profile.get("http_verified") else "UNKNOWN",
                    score=20 if link_profile.get("http_verified") else 12,
                    max_score=20,
                    confidence=0.8 if link_profile.get("http_verified") else 0.4,
                    evidence={"http_verified": link_profile.get("http_verified")},
                    problem="" if link_profile.get("http_verified") else "Chưa kiểm tra HTTP (hoặc không có URL tuyệt đối).",
                    impact="Không phát hiện broken link có bằng chứng HTTP.",
                    recommendation="—",
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

    # --- Schema (syntax + page-type fit) ---
    sch_checks: list[dict[str, Any]] = []
    schema_eval = evaluate_schema_for_page(ld_blocks, page_type=ptype, validation=schema_validation)
    sch_pct = float(schema_eval.get("score_percent") or 0)
    sch_st = str(schema_eval.get("status") or "UNKNOWN")
    sch_checks.append(
        make_check(
            check_id="structured_data",
            title="Structured data (JSON-LD)",
            status=sch_st if ld_blocks else "FAIL",
            score=round(sch_pct * 0.5, 1),
            max_score=50,
            confidence=float(schema_eval.get("confidence") or 0.5),
            evidence=schema_eval.get("evidence") or {},
            problem=str(schema_eval.get("problem") or ""),
            impact="Rich results eligibility.",
            recommendation="Thêm/sửa JSON-LD đúng page type." if not schema_eval.get("type_match") else "—",
        )
    )
    sch_checks.append(
        make_check(
            check_id="schema_valid",
            title="Schema validation",
            status="PASS" if schema_eval.get("valid") else ("FAIL" if ld_blocks else "FAIL"),
            score=round(min(30.0, sch_pct * 0.3), 1),
            max_score=30,
            confidence=float(schema_eval.get("confidence") or 0.5),
            evidence={"errors": (schema_eval.get("errors") or [])[:5], "types": schema_eval.get("types")},
            problem="; ".join((schema_eval.get("errors") or [])[:3]) or "—",
            impact="Invalid schema không giúp rich results.",
            recommendation="Sửa lỗi JSON-LD và required fields.",
        )
    )
    needs_local = ptype in ("landing", "homepage") or "local" in str(intent_pkg.get("dominant_intent") or "")
    sch_checks.append(
        make_check(
            check_id="local_business",
            title="Local Business (nếu cần)",
            status="UNKNOWN" if not needs_local else ("PASS" if "LocalBusiness" in (schema_eval.get("types") or []) else "WARNING"),
            score=20 if "LocalBusiness" in (schema_eval.get("types") or []) else (8 if needs_local else 12),
            max_score=20,
            confidence=0.45,
            evidence={"needs_local": needs_local, "types": schema_eval.get("types")},
            problem="" if "LocalBusiness" in (schema_eval.get("types") or []) else "Chưa xác minh LocalBusiness.",
            impact="Local pack.",
            recommendation="Thêm LocalBusiness nếu có địa chỉ.",
        )
    )

    # --- UX / Mobile / Speed (no fake CWV PASS) ---
    ux_checks: list[dict[str, Any]] = []
    viewport = bool(soup.find("meta", attrs={"name": "viewport"})) if soup else False
    ux_checks.append(
        make_check(
            check_id="mobile_viewport",
            title="Mobile compatibility (viewport)",
            status="PASS" if viewport else "FAIL",
            score=15 if viewport else 0,
            max_score=15,
            confidence=0.9 if viewport else 0.85,
            evidence={"viewport_present": viewport},
            problem="" if viewport else "Thiếu meta viewport.",
            impact="Mobile-friendly baseline.",
            recommendation='Thêm <meta name="viewport" content="width=device-width, initial-scale=1">.' if not viewport else "—",
        )
    )

    speed_proxy = float((breakdown.get("speed_mobile") or {}).get("score") or 0)
    has_perf_signal = speed_proxy > 0 and ok
    ux_checks.append(
        make_check(
            check_id="performance_proxy",
            title="Performance signals (HTML proxy)",
            status="WARNING" if has_perf_signal else "UNKNOWN",
            score=min(20.0, speed_proxy * 0.2) if has_perf_signal else 0,
            max_score=20,
            confidence=0.45 if has_perf_signal else 0.0,
            evidence={"proxy_score": speed_proxy, "method": "html_weight_heuristic"},
            problem="" if has_perf_signal else "Chưa có PSI/CrUX — chỉ ước tính thô.",
            impact="Không thay thế lab/field CWV.",
            recommendation="Chạy PageSpeed Insights để đo LCP/INP/CLS thật.",
        )
    )

    ux_checks.append(
        make_check(
            check_id="readability",
            title="Readability (heuristic)",
            status="UNKNOWN",
            score=8,
            max_score=15,
            confidence=0.35,
            evidence={"method": "sentence_length_proxy"},
            problem="Heuristic — chưa có readability lab.",
            impact="UX engagement.",
            recommendation="Rút gọn câu dài, thêm subheading.",
        )
    )

    ux_checks.append(
        make_check(
            check_id="cwv_lab",
            title="Core Web Vitals (field/lab)",
            status="UNKNOWN",
            score=0,
            max_score=15,
            confidence=0.0,
            evidence={"psi_available": False, "crux_available": False},
            problem="Không có dữ liệu PSI/CrUX trong SEO Score.",
            impact="—",
            recommendation="Chạy PSI/Lighthouse; không suy diễn PASS từ viewport.",
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
        gscore = group_score_from_checks(checks)
        w = GROUP_WEIGHTS.get(gid, 0.0)
        wp = round(gscore * w / 100.0, 2)
        weighted_total += wp
        group_scores[gid] = gscore
        counts = count_checks_by_status(checks)
        groups.append(
            {
                "id": gid,
                "label": GROUP_LABELS.get(gid, gid),
                "weight": w,
                "weight_percent": round(w / weight_sum * 100, 1),
                "score": gscore,
                "weighted_points": wp,
                "contribution": wp,
                "checks": checks,
                "checks_passed": counts["pass"],
                "checks_warning": counts["warning"],
                "checks_failed": counts["fail"],
                "checks_unknown": counts["unknown"],
                **(
                    {
                        "link_data": link_profile,
                        "partial_data": bool(link_profile.get("partial_data")),
                        "warning": link_profile.get("warning"),
                    }
                    if gid == "links"
                    else {}
                ),
            }
        )

    groups = ensure_ten_groups_complete(groups)
    group_scores = {str(g["id"]): float(g["score"]) for g in groups}
    penalties_applied: list[dict[str, Any]] = []

    ssot = compute_ssot_total(groups)
    total_score = float(ssot["total_score"])
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
    ssot["total_score"] = total_score

    strengths: list[str] = []
    weaknesses: list[str] = []
    for g in groups:
        if g["score"] >= 80:
            strengths.append(f"{g['label']}: {g['score']}/100 — {g['checks_passed']} checks passed")
        elif g["score"] < 55:
            failed = [c for c in g["checks"] if c.get("status") in ("FAIL", "failed")]
            hint = failed[0]["title"] if failed else g["label"]
            weaknesses.append(f"{g['label']}: {g['score']}/100 — cần cải thiện ({hint})")

    priority_fixes: list[dict[str, Any]] = []
    for g in sorted(groups, key=lambda x: x["score"]):
        for c in g["checks"]:
            st = c.get("status")
            if st in ("FAIL", "failed"):
                priority_fixes.append(
                    {
                        "group": g["id"],
                        "group_label": g["label"],
                        "check_id": c["id"],
                        "title": c["title"],
                        "problem": c["problem"],
                        "fix": c.get("recommendation") or c.get("fix"),
                        "priority": "high",
                    }
                )
            elif st in ("WARNING", "warning", "UNKNOWN") and len(priority_fixes) < 12:
                priority_fixes.append(
                    {
                        "group": g["id"],
                        "group_label": g["label"],
                        "check_id": c["id"],
                        "title": c["title"],
                        "problem": c["problem"],
                        "fix": c.get("recommendation") or c.get("fix"),
                        "priority": "medium",
                    }
                )
    priority_fixes = priority_fixes[:10]

    ai_suggestions: list[str] = []
    if pk:
        ai_suggestions.append(
            f"Tối ưu title/meta để chứa «{pk}» và khớp intent {intent_pkg.get('serp_intent') or 'SERP'}."
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
        "scoring_version": SCORING_VERSION,
        "intent_analysis": intent_pkg,
        "ssot": ssot,
    }
