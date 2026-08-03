"""
Checklist chấm điểm SEO 1 URL — 15 nhóm (0–100), trọng số, pass/warning/fail,
hard gate Search Intent (cap tổng điểm), bảng + insight hành động.
Dựa trên dữ liệu thực từ crawl + SERP (khi có keyword).
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

# Trọng số (tổng = 1.0). Search Intent hard gate — trọng số cao + cap khi fail.
FIFTEEN_WEIGHTS: dict[str, float] = {
    "search_intent": 0.16,
    "eeat": 0.08,
    "helpful_content": 0.08,
    "content_depth_serp": 0.10,
    "keyword_semantic": 0.09,
    "structure": 0.08,
    "featured_snippet": 0.05,
    "ux_readability": 0.07,
    "speed_mobile_cwv": 0.09,
    "internal_link": 0.05,
    "external_link": 0.04,
    "schema_markup": 0.05,
    "freshness": 0.03,
    "ctr_optimization": 0.04,
    "serp_benchmark": 0.07,
}

FIFTEEN_LABELS: list[tuple[str, str]] = [
    ("search_intent", "1. Search Intent (hard gate)"),
    ("eeat", "2. E-E-A-T"),
    ("helpful_content", "3. Helpful Content"),
    ("content_depth_serp", "4. Content Depth & Coverage (so với top 10 SERP)"),
    ("keyword_semantic", "5. Keyword & Semantic SEO"),
    ("structure", "6. Structure (title, meta, H1–H3)"),
    ("featured_snippet", "7. Featured Snippet"),
    ("ux_readability", "8. UX / Readability"),
    ("speed_mobile_cwv", "9. Speed & Mobile (Core Web Vitals proxy)"),
    ("internal_link", "10. Internal Link"),
    ("external_link", "11. External Link"),
    ("schema_markup", "12. Schema Markup"),
    ("freshness", "13. Freshness"),
    ("ctr_optimization", "14. CTR Optimization"),
    ("serp_benchmark", "15. SERP Benchmark (so sánh đối thủ)"),
]

_INTENT_FAIL = 46.0
_INTENT_WARN = 62.0


def _status(score: float, *, fail_at: float = _INTENT_FAIL, warn_at: float = _INTENT_WARN) -> str:
    if score < fail_at:
        return "fail"
    if score < warn_at:
        return "warning"
    return "pass"


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup((html or "")[:600_000], "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")


def _title_quality_proxy(title: str, keyword: str) -> float:
    t = (title or "").strip().lower()
    if not t:
        return 0.15
    score = 0.35
    if 25 <= len(t) <= 72:
        score += 0.25
    elif len(t) > 72:
        score += 0.1
    kws = [w for w in re.findall(r"[a-zà-ỹ0-9]{3,}", (keyword or "").lower()) if len(w) > 2][:4]
    for w in kws:
        if w in t:
            score += 0.12
    return max(0.0, min(1.0, round(score, 3)))


def _featured_snippet_score(html: str) -> tuple[float, str]:
    sp = _soup(html)
    for tag in sp(["script", "style"]):
        tag.decompose()
    paras = sp.find_all("p")
    short_blocks = 0
    for p in paras[:15]:
        wc = len(p.get_text(" ", strip=True).split())
        if 38 <= wc <= 68:
            short_blocks += 1
    lists_n = len(sp.find_all(["ul", "ol"]))
    tables_n = len(sp.find_all("table"))
    sc = 32.0 + min(40.0, short_blocks * 12.0) + (18.0 if lists_n or tables_n else 0.0)
    sc = min(100.0, sc)
    ev = f"Đoạn ~40–70 từ (ước): {short_blocks} khối; list/table: {lists_n}/{tables_n}."
    return round(sc, 1), ev


def _serp_depth_proxy(
    serp_rows: list[dict[str, Any]],
    our_wc: int,
    serp_top10_crawl: dict[str, Any] | None = None,
) -> tuple[float, str]:
    crawl = serp_top10_crawl or {}
    st = crawl.get("stats") or {}
    ok_n = int(st.get("successful") or 0)
    if ok_n >= 3 and int(st.get("median_word_count") or 0) > 0:
        bench_wc = max(400, int(st.get("median_word_count") or 0))
        p75 = int(st.get("p75_word_count") or bench_wc)
        ratio = our_wc / max(1, bench_wc)
        if ratio >= 1.05:
            sc = 94.0
        elif ratio >= 0.82:
            sc = 80.0
        elif ratio >= 0.6:
            sc = 62.0
        else:
            sc = max(22.0, 35.0 + ratio * 42.0)
        ev = (
            f"Crawl HTML top SERP: {ok_n}/{st.get('attempted', ok_n)} URL OK; median ~{bench_wc} từ, p75 ~{p75}. "
            f"Bạn ~{our_wc} từ → tỷ lệ ~{round(ratio, 2)}."
        )
        return round(min(100.0, sc), 1), ev

    if not serp_rows:
        return 52.0, "Không có SERP — không so được độ sâu với top 10; dùng mục tiêu nội bộ ≥1000 từ."
    snips = [len(str(r.get("snippet") or r.get("description") or "")) for r in serp_rows[:10]]
    avg_snip = sum(snips) / max(1, len(snips))
    bench_wc = max(900, min(2400, int(avg_snip * 12)))
    ratio = our_wc / max(1, bench_wc)
    if ratio >= 1.05:
        sc = 94.0
    elif ratio >= 0.75:
        sc = 78.0
    elif ratio >= 0.5:
        sc = 58.0
    else:
        sc = 38.0 + ratio * 25.0
    tail = ""
    if ok_n > 0:
        tail = f" (Crawl chỉ {ok_n}/10 thành công — fallback snippet.)"
    ev = f"Word count trang ~{our_wc}; benchmark ước từ SERP ~{bench_wc} từ (proxy snippet×12). Tỷ lệ ~{round(ratio, 2)}.{tail}"
    return round(min(100.0, sc), 1), ev


def _serp_benchmark_score(
    serp_rows: list[dict[str, Any]],
    *,
    keyword: str,
    our_title: str,
    serp_analysis: dict[str, Any] | None,
    serp_top10_crawl: dict[str, Any] | None = None,
) -> tuple[float, str]:
    crawl = serp_top10_crawl or {}
    st = crawl.get("stats") or {}
    ok_pages = [p for p in (crawl.get("pages") or []) if p.get("ok")]
    our_tq = _title_quality_proxy(our_title, keyword)

    if len(ok_pages) >= 3:
        crawled_tq = [_title_quality_proxy(str(p.get("title") or ""), keyword) for p in ok_pages]
        avg_tq = sum(crawled_tq) / len(crawled_tq)
        gap = our_tq - avg_tq
        sc = 52.0 + min(48.0, max(-40.0, gap * 95.0))
        kh = int(st.get("keyword_in_title_hits") or 0)
        ev = (
            f"Crawl HTML {len(ok_pages)} đối thủ: title-quality TB ~{avg_tq:.2f}, bạn ~{our_tq:.2f}. "
            f"Keyword trong title (HTML crawl): {kh}/{len(ok_pages)}."
        )
        return round(max(0.0, min(100.0, sc)), 1), ev

    if not serp_rows:
        return 48.0, "Không có top 10 — benchmark chỉ dựa trên title bạn."
    comps = list((serp_analysis or {}).get("competitors") or [])
    tqs = [float(r.get("title_quality_score") or 0) for r in comps[:10] if r.get("title_quality_score") is not None]
    if tqs:
        avg_tq = sum(tqs) / len(tqs)
        gap = our_tq - avg_tq
        sc = 55.0 + min(45.0, max(-35.0, gap * 90.0))
        ev = f"Title quality proxy bạn {our_tq:.2f} vs trung bình top {len(tqs)} ~{avg_tq:.2f}."
    else:
        titles = [str(r.get("title") or "") for r in serp_rows[:10]]
        kw_l = (keyword or "").lower()
        hit = sum(1 for t in titles if kw_l and kw_l in t.lower())
        our_hit = 1 if kw_l and kw_l in our_title.lower() else 0
        sc = 50.0 + (15 if our_hit else 0) + min(35.0, hit * 3.5)
        ev = f"Keyword trong title SERP: {hit}/10; trang bạn: {'có' if our_hit else 'chưa'}."
    return round(max(0.0, min(100.0, sc)), 1), ev


def _fix_playbook(fid: str, ctx: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """giai_phap, before, after, outline (optional)"""
    kw = str(ctx.get("keyword") or "[keyword]")
    title = str(ctx.get("title") or "[title]")
    meta = str(ctx.get("meta") or "[meta]")
    books: dict[str, tuple[str, str, str, str | None]] = {
        "search_intent": (
            "Mở top 3 SERP, ghi format (blog/PLP/tool); viết intro + H1 khớp intent dominant.",
            f"BEFORE: «{title[:55]}» (góc không khớp SERP).",
            f"AFTER: «{kw.title()}: [promise đúng intent SERP] (2026)» + intro trả lời đúng câu hỏi người tìm.",
            "H1: … | H2: Tiêu chí chọn | H2: So sánh | H2: FAQ | H2: Kết luận + CTA",
        ),
        "eeat": (
            "Byline + schema Person/Organization + link About; trích nguồn cho claim nhạy cảm.",
            "BEFORE: Không tên tác giả, không nguồn.",
            "AFTER: «Biên tập: … — cập nhật …» + 1–2 external uy tín.",
            None,
        ),
        "helpful_content": (
            "Thêm checklist, ví dụ số liệu, FAQ 3–5 câu; trả lời trực tiếp ngay đầu mục.",
            "BEFORE: Mô tả chung, không ví dụ.",
            "AFTER: Mỗi H2 có 1 ví dụ + bullet tiêu chí.",
            "H2: Trả lời nhanh | H2: Bước thực hiện | H2: Lỗi thường gặp",
        ),
        "content_depth_serp": (
            "So word count với benchmark SERP (proxy); thêm H2 phụ, case study, bảng.",
            "BEFORE: ~400 từ cho chủ đề cạnh tranh.",
            "AFTER: ≥1200–1800 từ có mục lục logic + FAQ.",
            None,
        ),
        "keyword_semantic": (
            "Bổ sung token phụ trong H2/H3; dùng PAA/related searches làm outline phụ.",
            "BEFORE: Lặp keyword chính.",
            "AFTER: Cụm đồng nghĩa + long-tail tự nhiên.",
            None,
        ),
        "structure": (
            "Title ≤60 ký tự; meta 140–160 + CTA; 1 H1; H2/H3 phân cấp.",
            f"BEFORE: meta «{meta[:60]}…»",
            "AFTER: Title + meta đủ độ dài, keyword đầu title.",
            None,
        ),
        "featured_snippet": (
            "Sau H2 quan trọng: đoạn 40–60 từ định nghĩa/trả lời + ol/table nếu list.",
            "BEFORE: Chỉ đoạn dài không có khối trả lời ngắn.",
            "AFTER: 1 đoạn 45–55 từ + 3 bullet bước.",
            None,
        ),
        "ux_readability": (
            "Đoạn 40–90 từ; alt ảnh; viewport; câu ngắn trên mobile.",
            "BEFORE: Wall of text.",
            "AFTER: Chia đoạn + bullet sau mỗi luận điểm.",
            None,
        ),
        "speed_mobile_cwv": (
            "HTTPS, giảm script blocking; đo PSI/Lab CWV thật — hiện chỉ proxy HTML.",
            "BEFORE: Nhiều script / thiếu viewport.",
            "AFTER: Lazyload, tối ưu font, giảm third-party.",
            None,
        ),
        "internal_link": (
            "3–8 internal contextual; ghi trong brief: [internal link: anchor → URL].",
            "BEFORE: Ít link nội bộ trong body.",
            "AFTER: Link pillar + 2 bài hỗ trợ từ đoạn liên quan.",
            None,
        ),
        "external_link": (
            "1–3 nguồn uy tín (gov/edu/tài liệu gốc): [external link: mô tả → URL].",
            "BEFORE: Không trích dẫn ngoài.",
            "AFTER: Mỗi claim nhạy cảm có footnote nguồn.",
            None,
        ),
        "schema_markup": (
            "JSON-LD Article/Product/FAQPage phù hợp; validate Rich Results.",
            "BEFORE: Thiếu hoặc lỗi schema.",
            "AFTER: Article + author + datePublished hợp lệ.",
            None,
        ),
        "freshness": (
            "Hiển thị ngày cập nhật + dateModified schema trung thực.",
            "BEFORE: Không ngày.",
            "AFTER: «Cập nhật: …» + JSON-LD dateModified.",
            None,
        ),
        "ctr_optimization": (
            "Title có số/năm/modifier; meta khác title; theo dõi GSC CTR theo query.",
            f"BEFORE: «{title[:50]}»",
            "AFTER: Title cụ thể + lợi ích đo được + brand.",
            None,
        ),
        "serp_benchmark": (
            "So title/H1 với top 10; bắt chước format thắng (không copy) + vượt depth.",
            "BEFORE: Lệch format SERP.",
            "AFTER: Cùng thể loại (listicle/bảng/tool) + USP riêng.",
            None,
        ),
    }
    return books.get(fid, ("Rà soát theo dẫn chứng heuristic.", "—", "—", None))


def build_fifteen_pillar_assessment(
    *,
    components: dict[str, float],
    breakdown: dict[str, Any],
    all_issues: list[dict[str, Any]],
    serp_rows: list[dict[str, Any]],
    serp_analysis: dict[str, Any] | None,
    keyword: str | None,
    html: str,
    page_data: dict[str, Any],
    normalized_url: str,
    our_word_count: int,
    serp_top10_crawl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kw = (keyword or "").strip()
    title = str(page_data.get("title") or "")
    meta = str(page_data.get("meta_description") or "")
    ld = breakdown.get("schema") or {}
    links_meta = breakdown.get("links") or {}
    internal_n = int(links_meta.get("internal") or 0)
    ext_hosts = int(links_meta.get("external_hosts") or 0)

    intent_mismatch = any(
        str(it.get("type")) == "intent_mismatch_serp" for it in (all_issues or []) if str(it.get("pillar")) == "intent"
    )
    raw_intent = float(components.get("intent") or 0.0)
    if intent_mismatch and raw_intent > 58.0:
        raw_intent = min(raw_intent, 58.0)

    depth_serp_sc, depth_ev = _serp_depth_proxy(serp_rows, our_word_count, serp_top10_crawl=serp_top10_crawl)
    depth_blended = round(0.55 * float(components.get("content_depth") or 0) + 0.45 * depth_serp_sc, 1)

    feat_sc, feat_ev = _featured_snippet_score(html)

    bench_sc, bench_ev = _serp_benchmark_score(
        serp_rows,
        keyword=kw,
        our_title=title,
        serp_analysis=serp_analysis,
        serp_top10_crawl=serp_top10_crawl,
    )

    internal_sc = min(100.0, 28.0 + internal_n * 5.5)
    external_sc = min(100.0, 32.0 + ext_hosts * 10.0)

    speed_note = (
        "Proxy: HTTPS/HTTP/viewport/số script — không thay LCP/INP lab. "
        "Hành động: chạy PageSpeed Insights + Search Console Core Web Vitals."
    )

    items: list[dict[str, Any]] = []
    for fid, label in FIFTEEN_LABELS:
        w = FIFTEEN_WEIGHTS[fid]
        if fid == "search_intent":
            sc = raw_intent
            ev_parts = [
                f"Heuristic intent trang vs keyword«{kw or '—'}»: điểm intent pillar {sc}.",
            ]
            if serp_rows and breakdown.get("intent"):
                pi = (breakdown["intent"].get("page_intent") or {}).get("intent")
                si = breakdown["intent"].get("serp_intent")
                ev_parts.append(f"Intent trang ~{pi}; dominant SERP ~{si}.")
            if intent_mismatch:
                ev_parts.append("Phát hiện lệch intent vs SERP (issue intent_mismatch_serp).")
            reason = " ".join(ev_parts)
        elif fid == "eeat":
            sc = float(components.get("eeat") or 0.0)
            sig = breakdown.get("eeat", {}).get("signals") or []
            reason = f"Điểm EEAT pillar {sc}. " + (" | ".join(str(s) for s in sig[:4]) if sig else "Ít tín hiệu schema/byline.")
        elif fid == "helpful_content":
            sc = float(components.get("helpful_content") or 0.0)
            h = breakdown.get("helpful_content", {})
            reason = f"Điểm helpful {sc}. FAQ headings: {h.get('faq_headings', 0)}; list/table: {h.get('lists', 0)}/{h.get('tables', 0)}."
        elif fid == "content_depth_serp":
            sc = depth_blended
            reason = depth_ev + f" Điểm depth pillar gốc: {components.get('content_depth', 0)}."
        elif fid == "keyword_semantic":
            sc = float(components.get("keyword_semantic") or 0.0)
            ks = breakdown.get("keyword_semantic", {}).get("signals") or []
            reason = " ".join(str(s) for s in ks[:3]) or f"Token/keyword trong title-body (pillar {sc})."
        elif fid == "structure":
            sc = float(components.get("structure") or 0.0)
            reason = f"H2 ~{breakdown.get('structure', {}).get('h2_count', '—')}; title/meta/H1 theo pillar structure."
        elif fid == "featured_snippet":
            sc = feat_sc
            reason = feat_ev
        elif fid == "ux_readability":
            sc = float(components.get("ux_readability") or 0.0)
            u = breakdown.get("ux_readability", {})
            reason = f"ASL ~{u.get('avg_sentence_length_words', '—')} từ/câu; pillar {sc}."
        elif fid == "speed_mobile_cwv":
            sc = float(components.get("speed_mobile") or 0.0)
            reason = speed_note + f" Điểm proxy pillar: {sc}."
        elif fid == "internal_link":
            sc = internal_sc
            reason = f"Internal links (body ước lượng): ~{internal_n}."
        elif fid == "external_link":
            sc = external_sc
            reason = f"Host external khác nhau: ~{ext_hosts}."
        elif fid == "schema_markup":
            sc = float(components.get("schema") or 0.0)
            reason = f"JSON-LD blocks: {ld.get('blocks', '—')}; valid: {ld.get('valid', '—')}."
        elif fid == "freshness":
            sc = float(components.get("freshness") or 0.0)
            reason = "Header/meta/LD date hints từ pillar freshness."
        elif fid == "ctr_optimization":
            sc = float(components.get("ctr") or 0.0)
            c = breakdown.get("ctr", {})
            reason = f"Title len {c.get('title_len', '—')}; meta len {c.get('meta_len', '—')}; vị trí dùng: {c.get('position_used', '—')}."
        elif fid == "serp_benchmark":
            sc = bench_sc
            reason = bench_ev
        else:
            sc = 50.0
            reason = "—"

        st = _status(sc) if fid != "search_intent" else _status(sc, fail_at=44.0, warn_at=60.0)
        if fid == "search_intent" and intent_mismatch:
            st = "fail" if sc < 70 else "warning"

        w_score = round(sc * w, 3)
        fix, before, after, outline = _fix_playbook(fid, {"keyword": kw, "title": title, "meta": meta})

        items.append(
            {
                "id": fid,
                "name": label,
                "status": st,
                "score": round(sc, 1),
                "weight": w,
                "weight_percent": round(w * 100, 1),
                "weighted_score": w_score,
                "reason": reason[:900],
                "fix_actions": fix,
                "before_example": before,
                "after_example": after,
                "outline_suggestion": outline,
            }
        )

    weighted_sum = round(sum(x["weighted_score"] for x in items), 2)
    intent_item = next((x for x in items if x["id"] == "search_intent"), None)
    intent_fail = intent_item and intent_item["status"] == "fail"
    intent_warn = intent_item and intent_item["status"] == "warning"

    cap_applied: float | None = None
    total_capped = weighted_sum
    if intent_fail:
        cap_applied = min(52.0, weighted_sum * 0.68)
        total_capped = round(cap_applied, 1)
    elif intent_warn:
        total_capped = round(min(weighted_sum, weighted_sum * 0.88 + 2.0), 1)

    total_capped = max(0.0, min(100.0, total_capped))

    # Impact: thấp điểm × trọng số
    low = sorted(items, key=lambda x: (100.0 - float(x["score"])) * float(x["weight"]), reverse=True)

    ref = "https://developers.google.com/search/docs/fundamentals/creating-helpful-content"
    deploy = normalized_url or "—"

    table_rows: list[dict[str, str]] = []
    for it in items:
        dg = f"{it['status'].upper()} | {it['score']}/100 | TS {it['weight_percent']}% | ĐQ {it['weighted_score']}"
        note = it.get("after_example") or ""
        if it.get("outline_suggestion"):
            note = (note + " | Outline: " + str(it["outline_suggestion"]))[:480]
        table_rows.append(
            {
                "checklist": it["name"],
                "danh_gia": dg,
                "dan_chung_chi_tiet": it["reason"],
                "giai_phap": it["fix_actions"],
                "link_tham_khao": ref if it["id"] == "search_intent" else "https://developers.google.com/search/docs",
                "hien_trang": (it.get("before_example") or "—")[:400],
                "link_trien_khai": deploy,
                "note": note[:450],
            }
        )

    top_fixes = []
    for it in low[:6]:
        top_fixes.append(
            {
                "id": it["id"],
                "priority": "P0" if it["status"] == "fail" else ("P1" if it["status"] == "warning" else "P2"),
                "missing": it["reason"][:240],
                "fix": it["fix_actions"],
                "before_example": it.get("before_example"),
                "after_example": it.get("after_example"),
                "outline_suggestion": it.get("outline_suggestion"),
            }
        )

    return {
        "items": items,
        "weights": FIFTEEN_WEIGHTS,
        "weighted_raw": weighted_sum,
        "total_capped": total_capped,
        "serp_top10_crawl_summary": (serp_top10_crawl or {}).get("stats"),
        "intent_hard_gate": {
            "intent_status": intent_item["status"] if intent_item else "unknown",
            "intent_score": intent_item["score"] if intent_item else None,
            "intent_mismatch_issue": intent_mismatch,
            "cap_applied_value": cap_applied,
            "note": "Sai Search Intent → cap tổng điểm (fail) hoặc giảm nhẹ (warning).",
        },
        "checklist_table_rows": table_rows,
        "top_priority_by_impact": [{"id": x["id"], "name": x["name"], "impact_gap": round((100 - x["score"]) * x["weight"], 3)} for x in low[:8]],
        "top_fixes": top_fixes,
    }
