"""
Báo cáo tối ưu SEO từ kết quả scoreboard: ưu tiên theo impact, nguyên nhân gắn signal,
BEFORE/AFTER mẫu, outline gợi ý, checklist hành động.
"""

from __future__ import annotations

from typing import Any

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Tài liệu tham khảo theo loại issue (mỗi dòng = 1 URL khi hiển thị)
REF_LINKS_BY_TYPE: dict[str, str] = {
    "intent_mismatch_serp": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "missing_org_person_schema": "https://schema.org/Organization\nhttps://schema.org/Person",
    "thin_trust_nav": "https://developers.google.com/search/docs/appearance/google-business-profile",
    "missing_byline": "https://developers.google.com/search/docs/appearance/structured-data/article",
    "thin_helpful": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "title_length": "https://developers.google.com/search/docs/appearance/title-link",
    "missing_title": "https://developers.google.com/search/docs/appearance/title-link",
    "missing_meta": "https://developers.google.com/search/docs/appearance/snippet",
    "missing_h1": "https://developers.google.com/search/docs/appearance/structured-data/article",
    "multiple_h1": "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/Heading_Elements",
    "keyword_not_in_title": "https://developers.google.com/search/docs/appearance/title-link",
    "images_missing_alt": "https://developer.mozilla.org/en-US/docs/Web/API/HTMLImageElement/alt",
    "long_sentences": "https://www.w3.org/WAI/WCAG21/Understanding/readable.html",
    "https": "https://developers.google.com/search/docs/crawling-indexing/https",
    "noindex": "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag",
    "viewport": "https://developer.mozilla.org/en-US/docs/Web/HTML/Viewport_meta_tag",
    "low_internal": "https://developers.google.com/search/docs/crawling-indexing/links-crawlable",
    "no_ld_json": "https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data",
    "schema_errors": "https://validator.schema.org/",
    "thin": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "no_visible_date": "https://developers.google.com/search/docs/appearance/structured-data/article",
    "low_position": "https://developers.google.com/search/blog/2024/03/generative-ai-search",
}

REF_LINKS_BY_PILLAR: dict[str, str] = {
    "intent": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "eeat": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "helpful_content": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "structure": "https://developers.google.com/search/docs/appearance/snippet",
    "keyword_semantic": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
    "ux_readability": "https://web.dev/learn/accessibility/",
    "speed_mobile": "https://web.dev/learn/performance/",
    "links": "https://developers.google.com/search/docs/crawling-indexing/links-crawlable",
    "schema": "https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data",
    "content_depth": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
    "freshness": "https://developers.google.com/search/docs/appearance/google-dates",
    "ctr": "https://developers.google.com/search/docs/appearance/snippet",
}


def _signals_for_pillar(breakdown: dict[str, Any], pillar: str) -> str:
    meta = breakdown.get(pillar) or {}
    sigs = meta.get("signals")
    if isinstance(sigs, list) and sigs:
        return " | ".join(str(s) for s in sigs[:6])
    return ""


def _ref_links(issue_type: str, pillar: str) -> str:
    t = REF_LINKS_BY_TYPE.get(issue_type) or ""
    p = REF_LINKS_BY_PILLAR.get(pillar) or ""
    parts = [x for x in (t, p) if x]
    if not parts:
        return "https://developers.google.com/search/docs"
    # gộp, trùng URL thì bỏ
    seen: set[str] = set()
    out: list[str] = []
    for block in parts:
        for line in block.split("\n"):
            u = line.strip()
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return "\n".join(out)


def _truncate(s: str, max_len: int = 420) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def build_checklist_table_rows(
    enriched_issues: list[dict[str, Any]],
    *,
    breakdown: dict[str, Any],
    page_url: str,
) -> list[dict[str, str]]:
    """
    Mỗi dòng: CHECKLIST → NOTE (key khớp thứ tự cột UI).
    """
    rows: list[dict[str, str]] = []
    bd = breakdown or {}
    for it in enriched_issues:
        pillar = str(it.get("pillar") or "")
        typ = str(it.get("type") or "")
        actions = it.get("actions") or []
        act0 = str(actions[0]) if actions else str(it.get("fix") or "")
        checklist_cell = _truncate(f"[Kỹ thuật · {it.get('priority') or '?'}] {it.get('missing') or typ}", 220)
        score_meta = bd.get(pillar) or {}
        sub = score_meta.get("score")
        danh_gia = f"{it.get('priority') or '—'} · {it.get('severity') or '—'} · {pillar}"
        if sub is not None:
            danh_gia += f" · điểm trụ ~{sub}"

        sig = _signals_for_pillar(bd, pillar)
        dc_parts = [str(it.get("message") or ""), str(it.get("root_cause") or "")]
        if sig:
            dc_parts.append(f"Tín hiệu breakdown: {sig}")
        dan_chung = _truncate(". ".join(p for p in dc_parts if p), 600)

        fixes = [str(it.get("fix") or "")]
        fixes.extend(str(a) for a in actions if a)
        giai_phap = _truncate(" → ".join(f for f in fixes if f), 500)

        links_ref = _ref_links(typ, pillar)
        hien = _truncate(str(it.get("before_example") or "—"), 400)
        note = _truncate(str(it.get("after_example") or ""), 400)
        if it.get("outline_suggestion"):
            ol = it["outline_suggestion"]
            if isinstance(ol, list) and ol:
                note = _truncate(note + " | Outline: " + " / ".join(str(x) for x in ol[:4]), 500)

        rows.append(
            {
                "checklist": checklist_cell,
                "danh_gia": danh_gia,
                "dan_chung_chi_tiet": dan_chung,
                "giai_phap": giai_phap,
                "link_tham_khao": links_ref,
                "hien_trang": hien,
                "link_trien_khai": page_url or "—",
                "note": note or "—",
            }
        )
    return rows


def _kw(ctx: dict[str, Any]) -> str:
    return str(ctx.get("keyword") or "").strip() or "[từ khóa mục tiêu]"


def _title(ctx: dict[str, Any]) -> str:
    t = str(ctx.get("title") or "").strip()
    return t if t else "[chưa có title — cần thêm <title>]"


def _meta(ctx: dict[str, Any]) -> str:
    m = str(ctx.get("meta_description") or "").strip()
    return m if m else "[chưa có meta description]"


def _playbook(issue_type: str, pillar: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Trả về missing, root_cause, actions, before/after, outline (tuỳ loại)."""
    kw = _kw(ctx)
    title = _title(ctx)
    meta = _meta(ctx)
    page_i = str((ctx.get("page_intent") or {}).get("intent") or "informational")
    serp_i = ctx.get("serp_intent")
    serp_s = str(serp_i) if serp_i else "informational"
    wc = int(ctx.get("word_count") or 0)

    generic = {
        "missing": "Tín hiệu on-page/SERP chưa đủ mạnh cho trụ này.",
        "root_cause": str(ctx.get("issue_message") or "Theo heuristic trong scoreboard."),
        "actions": [
            "Đọc kỹ `fix` của issue trong scoreboard và áp dụng trực tiếp lên HTML/CMS.",
            "Đo lại sau khi publish (GSC: impression/CTR/query).",
        ],
        "before_example": title[:120] if title.startswith("[") else f"Title hiện tại: «{title[:70]}…»" if len(title) > 70 else f"Title hiện tại: «{title}»",
        "after_example": f"Title gợi ý: «{kw.title()} — [lợi ích cụ thể trong 1 cụm] | [thương hiệu]» (30–55 ký tự).",
        "outline_suggestion": None,
    }

    pb: dict[str, dict[str, Any]] = {
        "intent_mismatch_serp": {
            "missing": f"Angle nội dung chưa khớp intent SERP (trang ~{page_i}, SERP ~{serp_s}).",
            "root_cause": f"Title/meta/H1 đang hướng {page_i} trong khi top SERP cho «{kw}» thiên {serp_s} — người dùng kỳ vọng khác (mua/so sánh vs học hỏi).",
            "actions": [
                f"Mở 5 kết quả top cho «{kw}»; ghi lại format (listicle, tool, pricing, blog).",
                "Viết lại intro 2–3 câu trả lời đúng kỳ vọng đó (commercial → USP/giá/bảo hành; informational → định nghĩa + bước).",
                "Sửa title/H1 để chứa promise khớp intent SERP, không chỉ nhồi keyword.",
            ],
            "before_example": f"Intro: «Chúng tôi cung cấp nhiều dịch vụ chất lượng…» + Title: «{title[:65]}»",
            "after_example": f"Intro (commercial): «So sánh 3 gói {kw} (giá, dung lượng, hỗ trợ) — chọn trong 5 phút.» + Title: «{kw.title()}: Bảng giá & gói phù hợp WordPress 2026»",
            "outline_suggestion": [
                f"H1: {kw.title()} — [đúng intent SERP: mua / so sánh / hướng dẫn]",
                "H2: Ai nên dùng / khi nào không nên",
                "H2: Tiêu chí chọn (checklist 5–7 ý)",
                "H2: So sánh nhanh (bảng)",
                "H2: Câu hỏi thường gặp (3–5 câu)",
                "H2: Kết luận + CTA rõ",
            ],
        },
        "missing_org_person_schema": {
            "missing": "Trust layer: không có Organization/Person trong JSON-LD.",
            "root_cause": "Google khó liên kết thực thể pháp lý/tác giả với domain — EEAT yếu dù nội dung tốt.",
            "actions": [
                "Thêm Organization (logo, url, sameAs mạng xã hội) + Person cho author thật.",
                "Article: author → Person, publisher → Organization.",
                "Kiểm tra Rich Results / Schema validator.",
            ],
            "before_example": "<script type=\"application/ld+json\">{ \"@context\": \"…\", \"@type\": \"WebPage\" }</script>  <!-- chỉ WebPage -->",
            "after_example": '{"@type":"Organization","name":"…","url":"…","logo":"…"} + {"@type":"Article","author":{"@type":"Person","name":"Nguyễn A"},"datePublished":"…"}',
            "outline_suggestion": None,
        },
        "thin_trust_nav": {
            "missing": "Liên kết minh bạch (About/Contact/Team) không lộ trong anchor đầu trang.",
            "root_cause": "Heuristic: không thấy anchor/href kiểu /about, /contact — người và bot khó xác minh chủ thể.",
            "actions": [
                "Thêm footer/header: Giới thiệu, Liên hệ, Chính sách (nếu có thương mại).",
                "Trang About: địa chỉ, mã số, ảnh team hoặc quy trình biên tập.",
            ],
            "before_example": "Footer chỉ có © 2026 — không link About/Contact.",
            "after_example": "Footer: Về chúng tôi | Liên hệ | Điều khoản | MST: … | Hotline …",
            "outline_suggestion": None,
        },
        "missing_byline": {
            "missing": "Byline tác giả / biên tập (Experience) không rõ trong HTML.",
            "root_cause": "Không có pattern byline/reviewed by — heuristic coi là thiếu trách nhiệm nội dung.",
            "actions": [
                "Đầu hoặc cuối bài: Tên + chức danh + 1 dòng kinh nghiệm liên quan chủ đề.",
                "Nếu YMYL: thêm reviewed by + credential ngắn.",
            ],
            "before_example": "<p>Nội dung bài viết bắt đầu ngay…</p>",
            "after_example": "<p><strong>Biên tập:</strong> Minh An — 6 năm vận hành WordPress cho SMB. <em>Cập nhật:</em> 04/2026.</p>",
            "outline_suggestion": None,
        },
        "thin_helpful": {
            "missing": "Độ đầy đủ helpful (ví dụ, checklist, FAQ) chưa đủ so kỳ vọng.",
            "root_cause": f"Word count ~{wc} + ít định dạng scannable — người dùng phải đoán, không được trả lời trực tiếp.",
            "actions": [
                "Thêm khối «Trả lời nhanh» 40–80 từ ngay sau intro.",
                "3 ví dụ cụ thể (số, tên tool, case) + 1 checklist.",
                "FAQ 3 câu khớp People Also Ask (nếu có dữ liệu).",
            ],
            "before_example": "«{kw} là một khái niệm quan trọng. Bài viết sau đây trình bày chi tiết…» (không giải quyết vấn đề cụ thể).",
            "after_example": f"«Muốn chọn {kw} đúng: (1) ngân sách, (2) quy mô traffic, (3) hỗ trợ. Dưới đây là checklist 7 ý + ví dụ cấu hình cho shop 500 đơn/ngày.»",
            "outline_suggestion": [
                f"H1: {kw.title()} — [kết quả cụ thể reader nhận được]",
                "H2: Trả lời nhanh (40–80 từ)",
                "H2: Tiêu chí chọn (bullet)",
                "H2: Các bước triển khai (numbered)",
                "H2: Lỗi thường gặp + cách xử",
                "H2: FAQ",
            ],
        },
        "title_length": {
            "missing": "Title chưa trong vùng tối ưu độ dài (heuristic ~30–55 ký tự).",
            "root_cause": "Title quá dài cắt snippet / quá ngắn thiếu promise — CTR và khớp SERP kém.",
            "actions": [
                "Đặt keyword chính trong 40 ký tự đầu.",
                "Thêm modifier phù intent: năm, so sánh, hướng dẫn, giá.",
            ],
            "before_example": title,
            "after_example": f"«{kw.title()} — Hướng dẫn + bảng so sánh (2026)»",
            "outline_suggestion": None,
        },
        "missing_title": {
            "missing": "Thẻ <title>.",
            "root_cause": "Không có title — snippet và ranking signal on-page mất trọng tâm.",
            "actions": ["Thêm <title> duy nhất trong <head>.", "Trùng chủ đề với H1 chính."],
            "before_example": "<title></title> hoặc không có.",
            "after_example": f"<title>{kw.title()} | [lợi ích 1 cụm] — [Brand]</title>",
            "outline_suggestion": None,
        },
        "missing_meta": {
            "missing": "Meta description đủ dài (~140–160 ký tự) + CTA.",
            "root_cause": "Snippet tự động kém kiểm soát — CTR thấp dù rank được.",
            "actions": [
                "1 câu promise + 1 câu proof (số, năm) + CTA nhẹ.",
                "Tránh trùng hệt title; bổ sung góc khác.",
            ],
            "before_example": meta if len(meta) > 5 else "[trống hoặc < 80 ký tự]",
            "after_example": f"«Chọn {kw} đúng nhu cầu: so sánh tiêu chí, ví dụ cấu hình, checklist. Cập nhật 2026 — [CTA: Xem bảng]»",
            "outline_suggestion": None,
        },
        "missing_h1": {
            "missing": "Một H1 rõ ràng.",
            "root_cause": "Cấu trúc heading lỏng — chủ đề chính không machine/human obvious.",
            "actions": ["Một H1 duy nhất = chủ đề chính.", "H2 chia phần; không nhảy cấp H3 ngay sau body."],
            "before_example": "<h2>Bắt đầu luôn bằng H2</h2> (không có H1)",
            "after_example": f"<h1>{kw.title()} — [góc bài]</h1>",
            "outline_suggestion": [
                f"H1: {kw.title()} — …",
                "H2: Tổng quan",
                "H2: Chi tiết / hướng dẫn",
                "H2: Tóm tắt",
            ],
        },
        "multiple_h1": {
            "missing": "Một H1 duy nhất.",
            "root_cause": "Nhiều H1 làm loãng chủ đề chính.",
            "actions": ["Giữ 1 H1; đổi các H1 còn lại thành H2/H3.", "Đồng bộ với title."],
            "before_example": "<h1>Giới thiệu</h1> … <h1>Dịch vụ</h1>",
            "after_example": f"<h1>{kw.title()} — …</h1> … <h2>Giới thiệu</h2> … <h2>Dịch vụ</h2>",
            "outline_suggestion": None,
        },
        "keyword_not_in_title": {
            "missing": "Cụm/từ chính của keyword trong title.",
            "root_cause": "Title không chứa token keyword — liên quan chủ đề kém trong snippet.",
            "actions": [
                "Đưa cụm chính vào đầu hoặc giữa title tự nhiên.",
                "Giữ biến thể từ vựng trong H2 (semantic).",
            ],
            "before_example": f"Title: «{title[:75]}» (không chứa «{kw}»)",
            "after_example": f"Title: «{kw.title()} — [benefit ngắn] | Brand»",
            "outline_suggestion": None,
        },
        "images_missing_alt": {
            "missing": "Alt mô tả có ý nghĩa cho ảnh thông tin.",
            "root_cause": "Ảnh mang thông tin nhưng không có text thay thế — accessibility + image SEO.",
            "actions": ["Alt 1 cụm: chủ thể + ngữ cảnh.", "Ảnh trang trí: alt=\"\"."],
            "before_example": '<img src="/chart.png">',
            "after_example": '<img src="/chart.png" alt="Biểu đồ so sánh chi phí hosting theo tháng 2026">',
            "outline_suggestion": None,
        },
        "long_sentences": {
            "missing": "Nhịp câu ngắn, dễ quét.",
            "root_cause": "ASL (từ/câu) cao — paragraph khó đọc trên mobile.",
            "actions": ["Chia câu > 30 từ.", "Dùng bullet sau mỗi luận điểm."],
            "before_example": "Một đoạn 4–5 câu dài liên tục không xuống dòng.",
            "after_example": "Luận điểm 1 (12–18 từ). Luận điểm 2. • Bullet hỗ trợ.",
            "outline_suggestion": None,
        },
        "https": {
            "missing": "HTTPS end-to-end.",
            "root_cause": "HTTP hoặc mixed — trust + ranking baseline kém.",
            "actions": ["Cài chứng chỉ, redirect 301 HTTP→HTTPS.", "Sửa internal link cứng sang https."],
            "before_example": "http://domain.com/page",
            "after_example": "https://domain.com/page (301 từ mọi HTTP).",
            "outline_suggestion": None,
        },
        "noindex": {
            "missing": "Cho phép index (nếu đây là landing SEO).",
            "root_cause": "meta robots hoặc X-Robots-Tag chứa noindex.",
            "actions": ["Gỡ noindex trên URL công khai.", "Giữ noindex cho staging/thank-you."],
            "before_example": '<meta name="robots" content="noindex,nofollow">',
            "after_example": '<meta name="robots" content="index,follow"> hoặc bỏ hẳn meta robots nếu mặc định index.',
            "outline_suggestion": None,
        },
        "viewport": {
            "missing": "Thẻ viewport.",
            "root_cause": "Mobile usability kém — Core / UX ảnh hưởng gián tiếp.",
            "actions": ['Thêm <meta name="viewport" content="width=device-width, initial-scale=1">.'],
            "before_example": "<head>… không có viewport …</head>",
            "after_example": '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "outline_suggestion": None,
        },
        "low_internal": {
            "missing": "Liên kết nội bộ tới pillar/cluster liên quan.",
            "root_cause": "Ít internal link — PageRank phân phối và chủ đề liên kết yếu.",
            "actions": [
                "3–8 link contextual tới bài pillar + bài con.",
                "Anchor mô tả, không chỉ «click here».",
            ],
            "before_example": "Bài đứng một mình, chỉ menu + 1 link «Trang chủ».",
            "after_example": f"Trong đoạn về {kw}: link tới «/hub/{kw.replace(' ', '-')}/» và 2 bài hỗ trợ.",
            "outline_suggestion": None,
        },
        "no_ld_json": {
            "missing": "JSON-LD phù hợp loại trang.",
            "root_cause": "Không có structured data — rich result & clarity thấp.",
            "actions": ["Article / Product / FAQPage / HowTo tùy format.", "Validate schema.org."],
            "before_example": "Không có <script type=\"application/ld+json\">",
            "after_example": '{"@context":"https://schema.org","@type":"Article",...}',
            "outline_suggestion": None,
        },
        "schema_errors": {
            "missing": "JSON-LD hợp lệ theo schema.org.",
            "root_cause": "Lỗi parse/field bắt buộc — rich result có thể bị bỏ qua.",
            "actions": ["Sửa theo thông báo validator.", "Đảm bảo @context, @type, url/name."],
            "before_example": "JSON-LD thiếu trường bắt buộc hoặc sai kiểu.",
            "after_example": "Bản sửa đã validate (Rich Results Test).",
            "outline_suggestion": None,
        },
        "thin": {
            "missing": "Độ sâu nội dung (từ + heading) cho intent.",
            "root_cause": f"~{wc} từ — khó cover subtopic và semantic variants.",
            "actions": [
                "Thêm 2–3 H2 mới: edge case, so sánh, triển khai.",
                "Mỗi H2 ≥ 120–180 từ có ví dụ/số.",
            ],
            "before_example": "300 từ mô tả chung, không có case.",
            "after_example": f"800–1500 từ: định nghĩa + tiêu chí + bước + lỗi thường gặp + FAQ cho «{kw}».",
            "outline_suggestion": [
                f"H1: {kw.title()}",
                "H2: Khái niệm & phạm vi",
                "H2: Cách làm (từng bước)",
                "H2: Ví dụ / case",
                "H2: So sánh phương án",
                "H2: FAQ",
            ],
        },
        "no_visible_date": {
            "missing": "Ngày published/updated hiển thị + schema date.",
            "root_cause": "Freshness signal yếu cho chủ đề biến động.",
            "actions": [
                "Hiển thị «Cập nhật: dd/mm/yyyy» trung thực khi sửa nội dung.",
                "Article dateModified trong JSON-LD.",
            ],
            "before_example": "Không có ngày trên bài.",
            "after_example": "<time datetime=\"2026-04-19\">Cập nhật 19/04/2026</time> + dateModified trong LD+JSON.",
            "outline_suggestion": None,
        },
        "low_position": {
            "missing": "Độ liên quan + snippet hấp dẫn để leo rank.",
            "root_cause": "Vị trí SERP thấp — CTR và traffic thấp; thường do intent/content/title yếu hơn đối thủ.",
            "actions": [
                "So khớp intent với top 3 (format + depth).",
                "Viết lại title/meta theo angle mới + FAQ schema nếu phù hợp.",
            ],
            "before_example": f"Title generic: «{title[:60]}»",
            "after_example": f"Title cụ thể + số + năm: «{kw.title()}: 7 tiêu chí + checklist (2026)»",
            "outline_suggestion": None,
        },
    }

    spec = pb.get(issue_type, {})
    if not spec:
        g = dict(generic)
        g["root_cause"] = f"Issue `{issue_type}` trên trụ `{pillar}` — {g['root_cause']}"
        return g

    out = {**spec}
    out.setdefault("actions", generic["actions"])
    return out


def _build_context(scoreboard: dict[str, Any]) -> dict[str, Any]:
    snap = dict(scoreboard.get("page_snapshot") or {})
    bd = dict(scoreboard.get("breakdown") or {})
    intent_b = bd.get("intent") or {}
    serp = scoreboard.get("serp") or {}
    depth_b = bd.get("content_depth") or {}
    ctx: dict[str, Any] = {
        "keyword": serp.get("keyword") or intent_b.get("keyword") or "",
        "title": snap.get("title", ""),
        "meta_description": snap.get("meta_description", ""),
        "page_intent": intent_b.get("page_intent") or {},
        "serp_intent": intent_b.get("serp_intent") or serp.get("serp_intent"),
        "word_count": int(depth_b.get("word_count") or 0),
    }
    return ctx


def build_url_seo_optimization_report(scoreboard: dict[str, Any]) -> dict[str, Any]:
    from app.services.url_seo_scoreboard import PILLAR_WEIGHTS

    scores = dict((scoreboard.get("scores") or {}).get("components") or {})
    weights = dict(scoreboard.get("weights") or {})
    if not weights:
        s = sum(PILLAR_WEIGHTS.values())
        weights = {k: round(v / s, 4) for k, v in PILLAR_WEIGHTS.items()}

    pillar_gaps: list[dict[str, Any]] = []
    for pillar, sc in scores.items():
        w = float(weights.get(pillar, 0.0))
        gap = max(0.0, 100.0 - float(sc))
        pillar_gaps.append(
            {
                "pillar": pillar,
                "score": float(sc),
                "weight": w,
                "weighted_gap": round(gap * w, 3),
                "impact_note": "Càng cao càng nên ưu tiên (điểm thấp × trọng số).",
            }
        )
    pillar_gaps.sort(key=lambda x: -x["weighted_gap"])

    ctx = _build_context(scoreboard)
    issues_raw = list(scoreboard.get("issues") or [])
    wmap = {p["pillar"]: p["weighted_gap"] for p in pillar_gaps}

    enriched: list[dict[str, Any]] = []
    for it in issues_raw:
        p = str(it.get("pillar") or "")
        typ = str(it.get("type") or "")
        c = {**ctx, "issue_message": it.get("message")}
        pb = _playbook(typ, p, c)
        enriched.append(
            {
                **it,
                "missing": pb.get("missing"),
                "root_cause": pb.get("root_cause"),
                "actions": pb.get("actions"),
                "before_example": pb.get("before_example"),
                "after_example": pb.get("after_example"),
                "outline_suggestion": pb.get("outline_suggestion"),
                "pillar_weighted_gap": wmap.get(p, 0.0),
            }
        )

    enriched.sort(
        key=lambda x: (
            PRIORITY_ORDER.get(str(x.get("priority")), 9),
            -float(x.get("pillar_weighted_gap") or 0),
        )
    )

    outlines = [x for x in enriched if x.get("outline_suggestion")]
    checklist: list[str] = []
    for x in enriched[:18]:
        for a in x.get("actions") or []:
            if a and a not in checklist:
                checklist.append(str(a))
    for extra in pillar_gaps[:4]:
        pill = extra["pillar"]
        if extra["score"] < 62:
            checklist.append(f"[Trụ {pill} điểm {extra['score']}] Mở breakdown `{pill}` và xử theo signals + issues liên quan.")

    rewrite_block = []
    for pg in pillar_gaps[:3]:
        pill = pg["pillar"]
        if pill in ("intent", "helpful_content", "content_depth", "keyword_semantic", "structure", "ctr") and pg["score"] < 68:
            rewrite_block.append(
                {
                    "pillar": pill,
                    "score": pg["score"],
                    "prompt": f"Tăng điểm {pill}: áp dụng BEFORE/AFTER trong issue cùng trụ; ưu tiên title/intro nếu là intent/keyword.",
                }
            )

    page_url = str(scoreboard.get("normalized_url") or scoreboard.get("url") or "").strip()
    bd = scoreboard.get("breakdown") or {}
    table_src = enriched[:28]
    fifteen = scoreboard.get("fifteen_pillar_assessment") or {}
    f15_rows = list(fifteen.get("checklist_table_rows") or [])
    issue_rows = build_checklist_table_rows(table_src, breakdown=bd, page_url=page_url)
    checklist_table = f15_rows + issue_rows
    ec = scoreboard.get("editorial_checklist") or {}
    editorial_summary = {
        "average_score": ec.get("average_score"),
        "items": ec.get("items") or [],
        "version": ec.get("checklist_version"),
    }
    if not checklist_table:
        for pg in pillar_gaps[:10]:
            if float(pg.get("score") or 100) >= 72:
                continue
            pill = str(pg.get("pillar") or "")
            sig = _signals_for_pillar(bd, pill)
            checklist_table.append(
                {
                    "checklist": f"(Theo trụ) Rà soát & tăng chất lượng: {pill}",
                    "danh_gia": f"Điểm ~{pg['score']} · gap trọng số {pg['weighted_gap']} · không có issue heuristic riêng",
                    "dan_chung_chi_tiet": _truncate(sig or f"Trụ {pill} điểm thấp hơn mục tiêu; xem raw breakdown.", 500),
                    "giai_phap": "Đối chiếu top SERP (nếu có keyword), bổ sung nội dung/signal phù hợp trụ điểm.",
                    "link_tham_khao": REF_LINKS_BY_PILLAR.get(pill, "https://developers.google.com/search/docs"),
                    "hien_trang": "—",
                    "link_trien_khai": page_url or "—",
                    "note": "Chạy lại chấm điểm sau khi chỉnh sửa URL.",
                }
            )
        if not checklist_table:
            checklist_table.append(
                {
                    "checklist": "Không có issue heuristic / trụ điểm thấp rõ — duy trì & đo GSC.",
                    "danh_gia": "Ổn định",
                    "dan_chung_chi_tiet": "Heuristic không báo lỗi nặng.",
                    "giai_phap": "Theo dõi query, CTR, và cập nhật định kỳ.",
                    "link_tham_khao": "https://search.google.com/search-console",
                    "hien_trang": "—",
                    "link_trien_khai": page_url or "—",
                    "note": "—",
                }
            )

    return {
        "keyword_used": (ctx.get("keyword") or None) or None,
        "pillar_impact_rank": pillar_gaps,
        "top_problems": enriched[:12],
        "issue_playbooks": enriched,
        "outline_suggestions": [o["outline_suggestion"] for o in outlines[:3] if o.get("outline_suggestion")],
        "content_rewrite_focus": rewrite_block,
        "checklist": checklist[:22],
        "checklist_table": checklist_table,
        "editorial_summary": editorial_summary,
        "fifteen_pillar_summary": {
            "total_capped": fifteen.get("total_capped"),
            "weighted_raw": fifteen.get("weighted_raw"),
            "intent_hard_gate": fifteen.get("intent_hard_gate"),
            "top_priority_by_impact": fifteen.get("top_priority_by_impact") or [],
        },
        "fifteen_top_fixes": list(fifteen.get("top_fixes") or []),
    }
