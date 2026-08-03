"""
Checklist biên tập SEO (on-page + intent + UX) — mỗi tiêu chí 0–100 + dòng bảng checklist_table.
Heuristic từ HTML đã fetch; an toàn khi thiếu keyword/HTML.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from app.services.search_intent import classify_search_intent

_CTA_RE = re.compile(
    r"\b(mua|xem|tải|đăng|liên hệ|khám phá|bắt đầu|thử|mua ngay|đặt|nhận|get|buy|shop|try|contact|learn more)\b",
    re.I,
)
_EXAMPLE_RE = re.compile(r"\b(ví dụ|case study|thực tế|ví dụ:|for example|e\.g\.)\b", re.I)
_CONCLUSION_RE = re.compile(
    r"\b(kết luận|tóm lại|tổng kết|cuối cùng|hãy|cta|đăng ký|liên hệ ngay|in summary)\b",
    re.I,
)
_FAQ_HEADING = re.compile(r"faq|câu hỏi|hỏi đáp|frequently asked", re.I)


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup((html or "")[:800_000], "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-zà-ỹ0-9]+", (s or "").lower()) if len(t) > 2][:12]


def _first_n_words(text: str, n: int) -> str:
    words = re.findall(r"[\wà-ỹ]+", text or "", re.I)
    return " ".join(words[:n])


def _row(
    checklist: str,
    danh_gia: str,
    dan_chung: str,
    giai_phap: str,
    link_ref: str,
    hien_trang: str,
    deploy_url: str,
    note: str,
) -> dict[str, str]:
    return {
        "checklist": checklist,
        "danh_gia": danh_gia,
        "dan_chung_chi_tiet": dan_chung,
        "giai_phap": giai_phap,
        "link_tham_khao": link_ref,
        "hien_trang": hien_trang[:500] if hien_trang else "—",
        "link_trien_khai": deploy_url or "—",
        "note": note[:500] if note else "—",
    }


def _same_site(href: str, base_netloc: str) -> bool:
    try:
        p = urlparse(href)
        if p.scheme in ("mailto", "tel", "javascript", "data", ""):
            return False
        if not p.netloc:
            return True
        h = (p.netloc or "").lower().removeprefix("www.")
        b = base_netloc.lower().removeprefix("www.")
        return h == b or h.endswith("." + b)
    except Exception:
        return False


def build_editorial_checklist_table(
    *,
    normalized_url: str,
    final_url: str,
    html: str,
    page_data: dict[str, Any],
    keyword: str | None,
    serp_intent_pkg: dict[str, Any] | None,
    ld_blocks: list[dict[str, Any]],
    body_word_count: int,
) -> dict[str, Any]:
    # Parse riêng để tránh mutate soup dùng cho pillar khác.
    sp = _soup(html)
    for tag in sp(["script", "style", "noscript"]):
        tag.decompose()
    title = str(page_data.get("title") or "").strip()
    meta = str(page_data.get("meta_description") or "").strip()
    h1_list = sp.find_all("h1")
    h1_text = " ".join(h.get_text(" ", strip=True) for h in h1_list[:2])[:200]
    h2n = len(sp.find_all("h2"))
    h3n = len(sp.find_all("h3"))
    full_text = sp.get_text(" ", strip=True)
    first100 = _first_n_words(full_text, 100)
    kw = (keyword or "").strip()
    kw_low = kw.lower()
    kw_tokens = _tokens(kw) if kw else []

    base_netloc = urlparse(final_url or normalized_url).netloc or urlparse(normalized_url).netloc
    deploy = (final_url or normalized_url or "").strip() or "—"

    path = urlparse(final_url or normalized_url).path or ""
    path_slug = path.strip("/").split("/")[-1] if path else ""
    path_len_score = 100.0 if len(path) <= 45 else max(0.0, 100.0 - (len(path) - 45) * 1.5)
    slug_kw = any(t in path_slug.lower() for t in kw_tokens[:4]) if kw_tokens else False

    internal_samples: list[str] = []
    external_samples: list[str] = []
    internal_n = 0
    ext_hosts: set[str] = set()
    base_u = final_url or normalized_url
    for a in sp.find_all("a", href=True, limit=200):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        abs_u = urljoin(base_u, href)
        label = (a.get_text(" ", strip=True) or "")[:40]
        if _same_site(abs_u, base_netloc):
            internal_n += 1
            if len(internal_samples) < 4:
                internal_samples.append(f"{label} → {abs_u[:80]}")
        else:
            try:
                h = (urlparse(abs_u).hostname or "").lower()
                if h:
                    ext_hosts.add(h)
                    if len(external_samples) < 4:
                        external_samples.append(f"{label} → {h}")
            except Exception:
                pass

    imgs = sp.find_all("img")
    img_n = len(imgs)
    miss_alt = sum(1 for im in imgs if not str(im.get("alt") or "").strip())

    lists_n = len(sp.find_all(["ul", "ol"]))
    tables_n = len(sp.find_all("table"))
    paras = sp.find_all("p")
    p_lens = [len(p.get_text(" ", strip=True).split()) for p in paras[:40] if p.get_text(strip=True)]
    avg_p = sum(p_lens) / len(p_lens) if p_lens else 0

    blob = f"{title} {meta}".strip()
    page_intent = classify_search_intent(blob or "content")
    page_i = str(page_intent.get("intent") or "informational")
    serp_i = str((serp_intent_pkg or {}).get("serp_intent") or "") if serp_intent_pkg else ""
    intent_align = 72.0
    if kw:
        if serp_i and page_i == serp_i:
            intent_align = 92.0
        elif serp_i:
            intent_align = 55.0
        else:
            intent_align = 68.0
    else:
        intent_align = 58.0 + min(30.0, float(page_intent.get("confidence") or 0.5) * 30)

    # Title
    tl = len(title)
    title_score = 0.0
    if not title:
        title_score = 5.0
    else:
        title_score = 55.0
        if tl <= 60:
            title_score += 25.0
        else:
            title_score += max(0.0, 25.0 - (tl - 60) * 1.2)
        if kw_low and kw_low in title.lower():
            title_score += 20.0
        elif kw_tokens and any(t in title.lower() for t in kw_tokens[:3]):
            title_score += 14.0
    title_score = min(100.0, title_score)

    # Meta
    ml = len(meta)
    meta_score = 0.0
    if 140 <= ml <= 160:
        meta_score += 42.0
    elif 120 <= ml <= 175:
        meta_score += 32.0
    elif meta:
        meta_score += 18.0
    if kw_low and kw_low in meta.lower():
        meta_score += 28.0
    elif kw_tokens and any(t in meta.lower() for t in kw_tokens[:3]):
        meta_score += 18.0
    if meta and _CTA_RE.search(meta):
        meta_score += 30.0
    else:
        meta_score += 8.0
    meta_score = min(100.0, meta_score)

    # URL
    url_score = (path_len_score * 0.55) + (35.0 if slug_kw else 10.0)
    url_score = min(100.0, url_score)

    # Headings
    h1c = len(h1_list)
    head_score = 40.0
    if h1c == 1:
        head_score += 35.0
    elif h1c == 0:
        head_score += 5.0
    else:
        head_score += 18.0
    head_score += min(25.0, h2n * 3.5)
    head_score += min(10.0, h3n * 1.2)
    head_score = min(100.0, head_score)

    # Keyword placement
    place_score = 35.0
    if kw_low:
        if kw_low in title.lower():
            place_score += 22.0
        if kw_low in h1_text.lower():
            place_score += 22.0
        if kw_low in first100.lower() or (kw_tokens and sum(1 for t in kw_tokens[:4] if t in first100.lower()) >= 2):
            place_score += 21.0
    else:
        place_score = 50.0
    place_score = min(100.0, place_score)

    # Semantic: token coverage in body (proxy)
    body_low = full_text.lower()[:25_000]
    sem_score = 45.0
    if kw_tokens:
        hits = sum(1 for t in kw_tokens if t in body_low)
        sem_score += min(35.0, hits * 8.0)
        # đa dạng heading chứa token
        hx_text = " ".join(x.get_text(" ", strip=True).lower() for x in sp.find_all(["h2", "h3"])[:20])
        sem_score += min(20.0, sum(3 for t in kw_tokens if t in hx_text))
    sem_score = min(100.0, sem_score)

    # Helpful + examples
    help_score = 40.0 + min(35.0, body_word_count / 40.0)
    if _EXAMPLE_RE.search(full_text):
        help_score += 18.0
    if lists_n >= 2 or tables_n >= 1:
        help_score += 12.0
    help_score = min(100.0, help_score)

    # Readability bullets
    read_score = 50.0
    if avg_p and avg_p <= 95:
        read_score += 22.0
    if lists_n >= 1:
        read_score += 18.0
    if avg_p and avg_p > 120:
        read_score -= 20.0
    read_score = max(0.0, min(100.0, read_score))

    # FAQ
    faq_h = sum(1 for hx in sp.find_all(["h2", "h3"]) if _FAQ_HEADING.search(hx.get_text(" ", strip=True)))
    faq_schema = any("faqpage" in json.dumps(b).lower() for b in (ld_blocks or [])[:12])
    faq_score = 35.0 + (25.0 if faq_h else 0.0) + (40.0 if faq_schema else 0.0)
    if faq_h and faq_schema:
        faq_score = min(100.0, faq_score + 10.0)
    faq_score = min(100.0, faq_score)

    # Featured snippet proxy: đoạn ngắn + list/table
    fs_score = 35.0
    short_blocks = 0
    for p in paras[:12]:
        wc = len(p.get_text(" ", strip=True).split())
        if 35 <= wc <= 70:
            short_blocks += 1
    if short_blocks:
        fs_score += min(35.0, short_blocks * 12.0)
    if lists_n or tables_n:
        fs_score += 22.0
    fs_score = min(100.0, fs_score)

    # Internal / external links
    int_score = min(100.0, 30.0 + internal_n * 4.5 + min(25.0, len(ext_hosts) * 5.0))
    ext_score = min(100.0, 35.0 + len(ext_hosts) * 8.0)

    # Images ALT
    img_score = 70.0 if not img_n else max(0.0, 100.0 - (miss_alt / max(1, img_n)) * 85.0)

    # EEAT proxy (light)
    html_head = (html or "")[:120_000]
    eeat_score = 45.0
    if re.search(r"\b(by|author|đăng bởi|biên tập|reviewed\s+by)\b", html_head, re.I):
        eeat_score += 25.0
    if re.search(r"\b(nghiên cứu|theo\s+\w+|nguồn:|source:)\b", html_head, re.I):
        eeat_score += 18.0
    if any("person" in str(b.get("@type", "")).lower() or "organization" in str(b.get("@type", "")).lower() for b in (ld_blocks or [])[:8]):
        eeat_score += 22.0
    eeat_score = min(100.0, eeat_score)

    # Mobile UX
    vp = bool(html and re.search(r'name=["\']viewport["\']', html, re.I))
    ux_score = 52.0 + (22.0 if vp else 0.0)
    sents = max(1, len(re.split(r"[.!?]+", full_text[:15_000])))
    asl = len(re.findall(r"[\wà-ỹ]+", full_text[:15_000], re.I)) / sents if sents else 0
    if 12 <= asl <= 26:
        ux_score += 18.0
    elif asl > 32:
        ux_score -= 12.0
    ux_score = max(0.0, min(100.0, ux_score))

    # Depth 1000–2000+
    depth_score = 25.0
    if body_word_count >= 2000:
        depth_score = 95.0
    elif body_word_count >= 1500:
        depth_score = 85.0
    elif body_word_count >= 1000:
        depth_score = 72.0
    elif body_word_count >= 600:
        depth_score = 52.0
    elif body_word_count >= 400:
        depth_score = 38.0
    else:
        depth_score = max(15.0, body_word_count / 25.0)

    # Conclusion + CTA in closing portion
    tail = full_text[max(0, len(full_text) // 4 * 3) :]
    conc_score = 40.0
    if _CONCLUSION_RE.search(tail):
        conc_score += 35.0
    if _CTA_RE.search(tail):
        conc_score += 25.0
    conc_score = min(100.0, conc_score)

    def pct(x: float) -> str:
        return f"{round(max(0.0, min(100.0, x)), 0):.0f}/100"

    def grade(x: float) -> str:
        if x >= 78:
            return "Đạt tốt"
        if x >= 55:
            return "Đạt một phần"
        return "Cần cải thiện"

    ref_intent = "https://developers.google.com/search/docs/fundamentals/creating-helpful-content"
    ref_title = "https://developers.google.com/search/docs/appearance/title-link"
    ref_meta = "https://developers.google.com/search/docs/appearance/snippet"
    ref_url = "https://developers.google.com/search/docs/crawling-indexing/url-structure"
    ref_head = "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/Heading_Elements"
    ref_sem = "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"
    ref_snip = "https://developers.google.com/search/docs/appearance/featured-snippets"
    ref_eeat = ref_intent
    ref_mob = "https://web.dev/learn/design/responsive-images/"

    rows: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []

    def add(
        cid: str,
        label: str,
        score: float,
        evidence: str,
        fix: str,
        ref: str,
        current: str,
        note: str,
    ) -> None:
        sc = round(max(0.0, min(100.0, score)), 1)
        items.append({"id": cid, "label": label, "score": sc})
        rows.append(
            _row(
                f"[Biên tập] {label}",
                f"{grade(score)} · {pct(score)}",
                evidence,
                fix,
                ref,
                current[:420],
                deploy,
                note[:420],
            )
        )

    add(
        "intent_reader",
        "Search intent + đúng nhu cầu người đọc",
        intent_align,
        f"Intent trang (title/meta): {page_i}. SERP dominant: {serp_i or '—'}. Keyword: «{kw or '—'}».",
        "Khớp format top 3 SERP; viết intro trả lời đúng kỳ vọng (mua vs học); chỉnh title/H1 theo intent.",
        ref_intent,
        f"Title: «{title[:80]}»" if title else "Thiếu title.",
        "Rewrite intro 2–3 câu promise đo lường được.",
    )
    add(
        "title_ctr",
        "Tiêu đề ≤60 ký tự, keyword, hấp dẫn CTR",
        title_score,
        f"Độ dài title: {tl} ký tự. Keyword trong title: {'có' if kw_low and kw_low in title.lower() else 'không / một phần'}.",
        "≤60 ký tự; keyword đầu hoặc gần đầu; thêm số/năm/modifier (so sánh, hướng dẫn) tăng CTR.",
        ref_title,
        title or "—",
        f"Ví dụ: «{(kw.title() if kw else 'Chủ đề')}: bảng tiêu chí + checklist (2026)»",
    )
    add(
        "meta_cta",
        "Meta description 140–160 ký tự, keyword + CTA",
        meta_score,
        f"Meta {ml} ký tự. CTA: {'có' if meta and _CTA_RE.search(meta) else 'chưa rõ'}.",
        "140–160 ký tự; 1 câu lợi ích + keyword tự nhiên + CTA (xem, tải, so sánh…).",
        ref_meta,
        meta or "—",
        "Tránh trùng hệt title; thêm proof (số, năm).",
    )
    add(
        "url_keyword",
        "URL ngắn gọn, chứa từ khóa",
        url_score,
        f"Path ~{len(path)} ký tự. Slug cuối: «{path_slug[:60]}». Token keyword trong slug: {'có' if slug_kw else 'không'}.",
        "Rút path; slug Latinh-VN không dấu; giữ 1–3 cấp khi có thể.",
        ref_url,
        path or "—",
        "Ví dụ: /blog/hosting-wordpress-thay-vì /p?id=12&x=…",
    )
    add(
        "headings",
        "Cấu trúc: 1 H1, nhiều H2, H3 hợp lý",
        head_score,
        f"H1: {h1c}. H2: {h2n}. H3: {h3n}.",
        "Một H1 = chủ đề; H2 chia phần lớn; H3 chi tiết — không nhảy cấp tùy tiện.",
        ref_head,
        (h1_text[:120] or "—"),
        "Gộp nhiều H1 nếu có; thêm H2 cho mỗi mục lớn.",
    )
    add(
        "keyword_placement",
        "Keyword chính: title, H1, 100 từ đầu; phân bổ tự nhiên",
        place_score,
        f"100 từ đầu (rút gọn): «{_first_n_words(first100, 22)}…»",
        "Mở bài với câu chứa keyword/cụm đồng nghĩa; tránh nhồi; dùng biến thể ở H2.",
        ref_sem,
        first100[:200] + "…" if len(first100) > 200 else first100,
        "Kiểm mật độ ~1–2% tổng bài cho cụm chính (heuristic).",
    )
    add(
        "semantic",
        "Từ khóa phụ + đồng nghĩa (semantic SEO)",
        sem_score,
        f"Token keyword trong body (ước lượng): {sum(1 for t in kw_tokens if t in body_low)}/{max(1, len(kw_tokens))} token.",
        "Thêm H2 cho subtopic; bộ từ liên quan (giá, cấu hình, lỗi, so sánh…) xuất hiện tự nhiên.",
        ref_sem,
        "—",
        "Dùng PAA / related searches để lấy cụm phụ.",
    )
    add(
        "helpful_examples",
        "Nội dung hữu ích, chi tiết, ví dụ thực tế",
        help_score,
        f"~{body_word_count} từ. Dấu hiệu ví dụ/case: {'có' if _EXAMPLE_RE.search(full_text) else 'chưa thấy'}.",
        "Mỗi H2 ≥ 1 ví dụ cụ thể (số, tên tool, bước); checklist nếu procedural.",
        ref_intent,
        f"Độ dài body ~{body_word_count} từ.",
        "Bổ sung case «trước/sau» hoặc bảng so sánh.",
    )
    add(
        "readability_bullets",
        "Đoạn ngắn + bullet khi cần",
        read_score,
        f"Đoạn p (mẫu đầu): trung bình ~{avg_p:.0f} từ/đoạn. Danh sách ul/ol: {lists_n}.",
        "Mục tiêu ~40–90 từ/đoạn web; dùng bullet sau luận điểm phức tạp.",
        "https://www.w3.org/WAI/WCAG21/Understanding/readable.html",
        f"{len(paras)} thẻ <p>.",
        "Chia đoạn dài; thêm tiểu mục bullet.",
    )
    add(
        "faq_block",
        "FAQ (nếu phù hợp)",
        faq_score,
        f"Heading FAQ-style: {faq_h}. Schema FAQPage: {'có' if faq_schema else 'không'}.",
        "3–6 câu hỏi khớp PAA; FAQPage JSON-LD nếu đúng format Q/A.",
        ref_snip,
        "—",
        "Thêm H2 «Câu hỏi thường gặp» + câu trả lời ngắn.",
    )
    add(
        "featured_snippet",
        "Featured snippet (40–60 từ + list/bảng)",
        fs_score,
        f"Đoạn ~35–70 từ (mẫu): {short_blocks}. Bảng/list: {tables_n} bảng, {lists_n} list.",
        "Ngay sau H1/H2 quan trọng: đoạn 40–60 từ trả lời trực tiếp; kèm ol/table nếu list.",
        ref_snip,
        "—",
        "Định nghĩa ngắn + bước đánh số để tăng cơ hội snippet.",
    )
    add(
        "internal_links",
        "Internal link hợp lý (ghi [internal link: …])",
        int_score,
        f"Số link nội bộ (ước lượng): {internal_n}.",
        "3–8 link contextual; trong bài ghi chú: [internal link: anchor → URL đầy đủ].",
        "https://developers.google.com/search/docs/crawling-indexing/links-crawlable",
        " | ".join(internal_samples) if internal_samples else "—",
        "Ví dụ: [internal link: Hướng dẫn SSL → https://domain.com/huong-dan-ssl]",
    )
    add(
        "external_links",
        "External link uy tín ([external link: …])",
        ext_score,
        f"Số host ngoài khác nhau: {len(ext_hosts)}.",
        "Trích dẫn nguồn gov/edu/tổ chức hoặc tài liệu gốc: [external link: mô tả → URL].",
        ref_intent,
        " | ".join(external_samples) if external_samples else "—",
        "Mỗi claim nhạy cảm nên có 1 nguồn ngoài.",
    )
    add(
        "images_alt",
        "Hình minh họa + ALT chuẩn SEO",
        img_score,
        f"Ảnh: {img_n}, thiếu alt: {miss_alt}.",
        "Mỗi ảnh thông tin: ALT mô tả ngắn; decorative: alt=\"\". Gợi ý ảnh: screenshot bảng, infographic quy trình.",
        "https://developers.google.com/search/docs/appearance/google-images",
        f"{img_n} ảnh, ALT đủ: {img_n - miss_alt}.",
        f"ALT mẫu: «Biểu đồ so sánh {kw or 'chủ đề'} theo tháng»",
    )
    add(
        "eeat",
        "E-E-A-T (chuyên môn, dẫn chứng, đáng tin)",
        eeat_score,
        "Heuristic: byline/reviewed, nguồn trích dẫn, Person/Organization schema.",
        "Tên tác giả + kinh nghiệm; trích nguồn; trang About/Contact; schema thật.",
        ref_eeat,
        "—",
        "Thêm khối «Kiểm chứng» với link ngoài uy tín.",
    )
    add(
        "ux_mobile",
        "UX: dễ đọc, thân thiện mobile",
        ux_score,
        f"Viewport: {'có' if vp else 'thiếu'}. Độ dài câu TB ~{asl:.1f} từ/câu (mẫu).",
        "Viewport meta; font-size/chữ nền đủ tương phản; câu ngắn trên mobile.",
        ref_mob,
        "—",
        "Thêm skip-to-content nếu layout phức tạp.",
    )
    add(
        "content_depth",
        "1000–2000+ từ, sâu hơn top 10 (mục tiêu)",
        depth_score,
        f"Word count body ~{body_word_count} (parser). So top 10: cần SERP API + crawl đối thủ để so chính xác.",
        "Nếu <1000: mở rộng H2 phụ; case study; FAQ; bảng so sánh. Mục tiêu ≥1500 cho pillar.",
        ref_intent,
        f"{body_word_count} từ.",
        "Lấy trung bình độ dài top 10 từ tool SERP rồi +20% từ cho depth.",
    )
    add(
        "conclusion_cta",
        "Kết luận + CTA rõ",
        conc_score,
        f"1/4 cuối bài có tín hiệu kết/CTA: kết luận={bool(_CONCLUSION_RE.search(tail))}, CTA={bool(_CTA_RE.search(tail))}.",
        "H2 «Kết luận» + 2–4 câu tóm + 1 CTA đo được (đăng ký, xem bảng giá, tải checklist).",
        ref_meta,
        tail[-220:] if tail else "—",
        "CTA ví dụ: «Tải checklist PDF» / «Xem gói phù hợp».",
    )

    avg = round(sum(x["score"] for x in items) / max(1, len(items)), 1)
    return {
        "rows": rows,
        "items": items,
        "average_score": avg,
        "checklist_version": "editorial_v1",
    }
