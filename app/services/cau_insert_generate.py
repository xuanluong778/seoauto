"""CAU «Thêm nội dung» — per-type suggestions and preview generation.

Auto Update modal only. Never writes into the article: the caller inserts the
returned preview HTML client-side at the «+» position. Manual builds are free;
credit is charged by the router only after a successful LLM result.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any
from urllib.parse import urlparse


INSERT_TYPES = frozenset({
    "heading", "paragraph", "cta", "faq", "list", "table", "internal_link", "image",
})

# Estimated credits when AI (LLM) generates the block. Manual/template = 0.
INSERT_CREDIT_EST: dict[str, int] = {
    "heading": 5,          # + content scales with word count (see estimate_insert_credit)
    "paragraph": 4,
    "cta": 3,
    "faq": 6,
    "list": 3,
    "table": 4,
    "internal_link": 2,
    "image": 2,
    "suggest": 2,
}

PARAGRAPH_PURPOSES = {
    "intro": "Mở đoạn/giới thiệu",
    "explain": "Giải thích chi tiết",
    "example": "Ví dụ thực tế",
    "compare": "So sánh/đối chiếu",
    "summary": "Tóm tắt/kết luận",
}
PARAGRAPH_LENGTHS = {"short": 40, "medium": 90, "long": 160}
PARAGRAPH_TONES = {
    "neutral": "trung lập",
    "professional": "chuyên nghiệp",
    "friendly": "thân thiện",
    "persuasive": "thuyết phục",
}
CTA_CHANNELS = {
    "call": {"label": "Gọi điện", "button": "Gọi ngay", "href": "tel:"},
    "zalo": {"label": "Zalo", "button": "Chat Zalo", "href": "https://zalo.me/"},
    "booking": {"label": "Đặt lịch", "button": "Đặt lịch ngay", "href": "#dat-lich"},
    "buy": {"label": "Mua hàng", "button": "Mua ngay", "href": "#mua-hang"},
}
LIST_KINDS = {"steps": "Các bước thực hiện", "benefits": "Lợi ích", "checklist": "Checklist"}
TABLE_KINDS = {
    "pricing": "Bảng giá",
    "comparison": "So sánh",
    "process": "Quy trình",
    "specs": "Thông số",
}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def _word_count(html: str) -> int:
    t = _plain(html)
    return len(t.split()) if t else 0


def _body_word_count(html: str) -> int:
    """Số từ phần nội dung (không tính chữ trong heading)."""
    body = re.sub(r"<h[1-6][^>]*>[\s\S]*?</h[1-6]>", " ", str(html or ""), flags=re.I)
    return _word_count(body)


def _strip_code_fence(raw: str) -> str:
    html = str(raw or "").strip()
    if html.startswith("```"):
        html = re.sub(r"^```(?:html)?\s*", "", html)
        html = re.sub(r"\s*```$", "", html)
    return html.strip()


def insert_word_target(insert_type: str, options: dict[str, Any]) -> int | None:
    """Số từ mục tiêu người dùng yêu cầu (None nếu loại này không có mục tiêu)."""
    if insert_type == "heading" and options.get("with_content"):
        return max(50, min(2000, int(options.get("word_count") or 200)))
    if insert_type == "paragraph":
        return PARAGRAPH_LENGTHS.get(str(options.get("length") or "medium"), 90)
    return None


def _trim_html_to_words(html: str, max_words: int) -> str:
    """Rút gọn HTML về tối đa max_words từ (không tính heading), cắt theo câu."""
    parts = [p for p in re.split(
        r"(?<=</p>)|(?<=</ul>)|(?<=</ol>)|(?<=</h1>)|(?<=</h2>)|(?<=</h3>)|(?<=</h4>)|(?<=</table>)|(?<=</figure>)|(?<=</div>)",
        str(html or ""),
    ) if p.strip()]
    out: list[str] = []
    used = 0
    for part in parts:
        is_heading = bool(re.match(r"\s*<h[1-6]", part, flags=re.I))
        w = 0 if is_heading else _word_count(part)
        if not is_heading and used + w > max_words:
            remain = max_words - used
            if remain >= 12 and re.match(r"\s*<p", part, flags=re.I):
                sents = re.split(r"(?<=[.!?…])\s+", _plain(part))
                acc: list[str] = []
                c = 0
                for s in sents:
                    n = len(s.split())
                    if c + n > remain:
                        break
                    acc.append(s)
                    c += n
                if acc:
                    out.append("<p>" + _esc(" ".join(acc)) + "</p>")
            break
        out.append(part)
        used += w
    return "".join(out) if out else str(html or "")


def fit_word_count(
    html: str,
    target: int,
    *,
    chat: Any = None,
    keyword: str = "",
    max_rounds: int = 3,
) -> str:
    """Ép nội dung về khoảng ±10% số từ yêu cầu: thiếu thì nhờ AI viết tiếp và
    ghép vào, thừa thì rút gọn theo câu. ``chat(system, user, word_target)`` trả
    về chuỗi HTML bổ sung hoặc None khi lỗi."""
    t = max(1, int(target or 0))
    lo = max(1, round(t * 0.9))
    hi = max(lo + 1, round(t * 1.1))
    cur = str(html or "")
    for _ in range(max(1, int(max_rounds))):
        wc = _body_word_count(cur)
        if wc > hi:
            cur = _trim_html_to_words(cur, hi)
            continue
        if wc >= lo:
            break
        need = t - wc
        if chat is None:
            break
        more = chat(
            (
                "Bạn là biên tập viên SEO tiếng Việt. Chỉ trả về HTML các đoạn bổ sung "
                "(<p>, <ul><li>…), KHÔNG thêm heading mới, không markdown, không lời dẫn."
            ),
            (
                f"Nội dung hiện tại ({wc} từ):\n{cur[:6000]}\n\n"
                f"Viết TIẾP khoảng {need} từ nữa, không lặp lại ý đã viết"
                + (f", bám sát keyword «{keyword}» và đúng địa phương trong keyword" if keyword else "")
                + ". Chia thành nhiều <p> ngắn (2–4 câu/đoạn). Không bịa số liệu. Chỉ trả về phần HTML bổ sung."
            ),
            need,
        )
        more = _strip_code_fence(more or "")
        if not more or "<" not in more:
            break
        cur = cur.rstrip() + more
    # vòng cuối: nếu vẫn thừa thì cắt về trần cho chắc
    if _body_word_count(cur) > hi:
        cur = _trim_html_to_words(cur, hi)
    return cur


def _esc(text: str) -> str:
    return escape(str(text or ""), quote=True)


# ---- Ngữ cảnh keyword: tách «dịch vụ» + «địa phương», casing thương hiệu ----

_STOPWORDS_VI = frozenset("và của cho với tại ở các có là một những khi để từ trên dưới".split())

_BRAND_CASE = {
    "macbook": "MacBook", "iphone": "iPhone", "ipad": "iPad", "imac": "iMac",
    "airpods": "AirPods", "ios": "iOS", "android": "Android", "wordpress": "WordPress",
    "seo": "SEO", "cpu": "CPU", "vga": "VGA", "ssd": "SSD", "led": "LED", "tv": "TV",
}

_LOC_MARKERS = ("quận", "huyện", "phường", "thị xã", "thị trấn", "thành phố", "tp.", "q.")
_CITY_NAMES = (
    "hà nội", "hồ chí minh", "tphcm", "hcm", "sài gòn", "đà nẵng", "cần thơ",
    "hải phòng", "biên hòa", "thủ đức", "bình dương", "đồng nai", "nha trang",
    "vũng tàu", "huế", "đà lạt", "buôn ma thuột", "quy nhơn", "thanh hóa", "vinh",
)

_SERVICE_VERBS = (
    "sửa", "thay", "lắp", "vệ sinh", "bảo dưỡng", "bảo trì", "thiết kế", "thi công",
    "cho thuê", "thuê", "mua", "bán", "chuyển", "diệt", "in", "giặt", "nâng cấp",
    "cài", "phục hồi", "độ", "dịch vụ", "khám", "chữa", "trị", "đào tạo", "spa",
)


def _smart_case(text: str) -> str:
    """Viết hoa chữ đầu + đúng casing thương hiệu (macbook → MacBook)."""
    words = str(text or "").split()
    out: list[str] = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in _BRAND_CASE:
            out.append(_BRAND_CASE[lw])
        elif i == 0:
            out.append(w[:1].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def _mid_case(text: str) -> str:
    """Casing dùng giữa câu: giữ thương hiệu, chữ đầu thường (sửa MacBook)."""
    s = _smart_case(text)
    if not s:
        return s
    first = s.split()[0].lower()
    if first in _BRAND_CASE:
        return s
    return s[:1].lower() + s[1:]


def _loc_title(loc: str) -> str:
    return " ".join(w if w.isdigit() else (w[:1].upper() + w[1:]) for w in str(loc or "").split())


def split_service_location(keyword: str) -> tuple[str, str]:
    """Tách «dịch vụ» và «địa phương» — vd. «sửa macbook quận 10» → («sửa macbook», «quận 10»)."""
    k = " ".join(str(keyword or "").split())
    low = k.lower()
    pos = -1
    for m in _LOC_MARKERS:
        i = low.find(" " + m)
        if i > 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        for c in _CITY_NAMES:
            i = low.find(" " + c)
            if i > 0:
                pos = i
                break
    if pos < 0:
        return k, ""
    service = re.sub(r"\s+(tại|ở|khu vực)$", "", k[:pos].strip(" -–,"), flags=re.I)
    location = re.sub(r"^(tại|ở|khu vực)\s+", "", k[pos:].strip(" -–,"), flags=re.I)
    return (service or k), location


_GENERIC_HEADING_RE = re.compile(
    r"là gì|khái niệm|trong thực tế|tổng quan|chủ đề", re.I
)


def _filter_headings(titles: list[str], *, keyword: str, existing: list[str]) -> list[str]:
    """Loại heading chung chung, sai chủ đề hoặc thiếu địa phương của keyword."""
    kw_tokens = {
        t for t in re.findall(r"\w+", str(keyword or "").lower())
        if len(t) >= 2 and t not in _STOPWORDS_VI
    }
    _, location = split_service_location(keyword)
    loc_low = location.lower()
    out: list[str] = []
    for t in _dedupe_titles(titles, existing):
        low = t.lower()
        if _GENERIC_HEADING_RE.search(low):
            continue
        if kw_tokens and not any(tok in low for tok in kw_tokens):
            continue
        if loc_low and loc_low not in low:
            continue
        out.append(t)
    return out


def build_insert_context(
    *,
    blocks: list[Any],
    insert_index: int,
    title: str = "",
    keyword: str = "",
    url: str = "",
) -> dict[str, Any]:
    """Context around the «+» position: prev/next heading, existing headings,
    nearby text and existing link URLs — so AI avoids duplication."""
    from app.services.cau_block_model import heading_level

    idx = max(0, min(int(insert_index or 0), len(blocks)))
    prev_heading = ""
    next_heading = ""
    for b in reversed(blocks[:idx]):
        if heading_level(b) is not None:
            prev_heading = _plain(b.current_content)
            break
    for b in blocks[idx:]:
        if heading_level(b) is not None:
            next_heading = _plain(b.current_content)
            break
    existing_headings = [
        _plain(b.current_content)
        for b in blocks
        if heading_level(b) is not None and _plain(b.current_content)
    ]
    near_parts: list[str] = []
    for b in blocks[max(0, idx - 2): idx + 2]:
        t = _plain(b.current_content)
        if t:
            near_parts.append(t)
    all_html = "".join(getattr(b, "current_content", "") or "" for b in blocks)
    existing_links = sorted(set(
        re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', all_html, flags=re.I)
    ))[:50]
    existing_questions = [
        _plain(m)
        for m in re.findall(r"<(?:h3|h4)\b[^>]*>([\s\S]*?)</(?:h3|h4)>", all_html, flags=re.I)
        if "?" in _plain(m)
    ]
    return {
        "title": str(title or "").strip(),
        "keyword": str(keyword or "").strip(),
        "url": str(url or "").strip(),
        "insert_index": idx,
        "prev_heading": prev_heading,
        "next_heading": next_heading,
        "existing_headings": existing_headings[:40],
        "nearby_text": " ".join(near_parts)[:600],
        "existing_links": existing_links,
        "existing_questions": existing_questions[:20],
    }


def _dedupe_titles(candidates: list[str], existing: list[str]) -> list[str]:
    seen = {e.strip().lower() for e in existing if e}
    out: list[str] = []
    for c in candidates:
        key = c.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(c.strip())
    return out


def _heading_candidates(keyword: str) -> list[str]:
    """Heading bám sát keyword: đúng dịch vụ + đúng địa phương, không chung chung."""
    kw = " ".join(str(keyword or "").split())
    service, location = split_service_location(kw)
    svc_mid = _mid_case(service)          # «sửa MacBook»
    loc = _loc_title(location)            # «Quận 10»

    # Tách «đối tượng» khỏi động từ dịch vụ: «sửa macbook» → «MacBook»
    obj = service
    low = service.lower()
    for v in sorted(_SERVICE_VERBS, key=len, reverse=True):
        if low.startswith(v + " "):
            obj = service[len(v):].strip()
            break
    obj_mid = _mid_case(obj)
    is_service = bool(low) and (
        low.startswith("dịch vụ") or any(low.startswith(v + " ") for v in _SERVICE_VERBS)
    )

    if loc:
        base = [
            f"Dịch vụ {svc_mid} tại {loc}",
            f"Các lỗi {obj_mid} thường gặp tại {loc}" if is_service and obj != service else f"Lưu ý khi chọn {svc_mid} tại {loc}",
            f"Quy trình {svc_mid} {loc}",
            f"Bảng giá {svc_mid} tại {loc}",
            f"Địa chỉ {svc_mid} uy tín ở {loc}",
            f"Cam kết bảo hành khi {svc_mid} tại {loc}",
            f"Vì sao nên chọn {svc_mid} tại {loc}?",
        ]
    elif is_service:
        base = [
            f"Dịch vụ {svc_mid} chuyên nghiệp",
            f"Quy trình {svc_mid} chuẩn",
            f"Bảng giá {svc_mid} mới nhất",
            f"Địa chỉ {svc_mid} uy tín",
            f"Cam kết bảo hành khi {svc_mid}",
            f"Các lỗi {obj_mid} thường gặp" if obj != service else f"Lưu ý khi {svc_mid}",
        ]
    else:
        base = [
            f"Hướng dẫn {svc_mid} chi tiết",
            f"Kinh nghiệm {svc_mid} thực tế",
            f"Chi phí {svc_mid} mới nhất",
            f"Những sai lầm cần tránh khi {svc_mid}",
            f"Câu hỏi thường gặp về {svc_mid}",
            f"Checklist trước khi {svc_mid}",
        ]
    return base


def suggest_insert(*, kind: str, context: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
    """Template suggestions (free). LLM refinement is layered on by the router."""
    kw = str(context.get("keyword") or "").strip() or "chủ đề"
    title = str(context.get("title") or "").strip()
    existing = list(context.get("existing_headings") or [])
    n = max(3, min(int(count or 5), 5))

    if kind == "heading":
        seed = kw if kw != "chủ đề" else (title or kw)
        titles = _filter_headings(_heading_candidates(seed), keyword=seed, existing=existing)
        if len(titles) < 3:
            # fallback: giữ đủ 3-5 gợi ý, vẫn dedupe với heading đã có
            titles = _dedupe_titles(_heading_candidates(seed), existing)
        return [{"title": t} for t in titles[:n]]

    if kind == "cta":
        items = []
        for ch, cfg in CTA_CHANNELS.items():
            items.append({
                "channel": ch,
                "title": f"{cfg['label']}: tư vấn {kw} miễn phí",
                "body": f"Đội ngũ sẵn sàng hỗ trợ về {kw}" + (f" cho «{title}»" if title else "") + ".",
                "button": cfg["button"],
            })
        return items[:max(3, n)]

    if kind == "faq":
        existing_q = {q.strip().lower() for q in (context.get("existing_questions") or [])}
        base_q = [
            f"{kw.capitalize()} phù hợp với ai?",
            f"Chi phí {kw} khoảng bao nhiêu?",
            f"Cần lưu ý gì khi bắt đầu với {kw}?",
            f"{kw.capitalize()} có nhược điểm nào không?",
            f"Mất bao lâu để thấy kết quả với {kw}?",
        ]
        out = [q for q in base_q if q.strip().lower() not in existing_q][:n]
        return [{"question": q} for q in out]

    raise ValueError(f"Loại gợi ý không hỗ trợ: {kind}")


def validate_internal_url(url: str, site_base: str) -> bool:
    """Internal links must be real URLs of the connected website."""
    u = str(url or "").strip()
    if not u:
        return False
    if u.startswith("/") and not u.startswith("//"):
        return True
    try:
        pu = urlparse(u)
        pb = urlparse(str(site_base or ""))
    except ValueError:
        return False
    if pu.scheme not in {"http", "https"} or not pu.netloc:
        return False
    if not pb.netloc:
        return False
    return pu.netloc.lower().lstrip("www.") == pb.netloc.lower().lstrip("www.")


def _gen_heading(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    level = max(2, min(4, int(options.get("level") or 2)))
    title = str(options.get("title") or "").strip() or "Heading mới"
    with_content = bool(options.get("with_content"))
    html = f"<h{level}>{_esc(title)}</h{level}>"
    warnings: list[str] = []
    lowered = title.strip().lower()
    if lowered in {h.strip().lower() for h in context.get("existing_headings") or []}:
        warnings.append("Heading trùng với heading đã có trong bài.")
    if with_content:
        kw = str(options.get("keyword") or context.get("keyword") or "").strip()
        words = max(50, min(2000, int(options.get("word_count") or 200)))
        brief = str(options.get("brief") or "").strip()
        sents = [
            f"{title} là phần quan trọng" + (f" khi tìm hiểu {kw}" if kw else "") + ".",
            "Nội dung dưới đây tóm tắt các ý chính, điều kiện áp dụng và lưu ý thực tế.",
        ]
        if brief:
            sents.append(f"Trọng tâm: {brief}.")
        sents.append(f"Độ dài mục tiêu khoảng {words} từ; hãy chỉnh sửa lại theo thực tế của bạn.")
        html += "".join(f"<p>{_esc(s)}</p>" for s in sents)
    return html, warnings


def _gen_paragraph(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    purpose = str(options.get("purpose") or "explain")
    length = str(options.get("length") or "medium")
    tone = str(options.get("tone") or "neutral")
    kw = str(options.get("keyword") or context.get("keyword") or "").strip() or "chủ đề"
    purpose_label = PARAGRAPH_PURPOSES.get(purpose, PARAGRAPH_PURPOSES["explain"])
    tone_label = PARAGRAPH_TONES.get(tone, "trung lập")
    target = PARAGRAPH_LENGTHS.get(length, 90)
    prev_h = str(context.get("prev_heading") or "").strip()
    sents = [
        (f"Trong phần «{prev_h}», " if prev_h else "") + f"{purpose_label.lower()} về {kw} giúp người đọc nắm ý nhanh.",
        f"Đoạn văn viết theo giọng {tone_label}, độ dài khoảng {target} từ.",
        "Bạn có thể chỉnh sửa trực tiếp trong preview trước khi áp dụng.",
    ]
    return "<p>" + " ".join(_esc(s) for s in sents) + "</p>", []


def _gen_cta(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    channel = str(options.get("channel") or "call")
    cfg = CTA_CHANNELS.get(channel) or CTA_CHANNELS["call"]
    kw = str(options.get("keyword") or context.get("keyword") or "").strip() or "dịch vụ"
    title = str(options.get("title") or "").strip() or f"Tư vấn {kw} miễn phí"
    body = str(options.get("body") or "").strip() or f"Liên hệ ngay để được hỗ trợ nhanh về {kw}."
    button = str(options.get("button") or "").strip() or cfg["button"]
    target = str(options.get("target") or "").strip()
    href = target or cfg["href"]
    html = (
        '<div class="wp-block-group cau-cta">'
        f"<h3>{_esc(title)}</h3>"
        f"<p>{_esc(body)}</p>"
        f'<p class="cta"><a class="wp-block-button__link" href="{_esc(href)}">{_esc(button)}</a></p>'
        "</div>"
    )
    warnings: list[str] = []
    if channel in {"call", "zalo"} and not target:
        warnings.append("Chưa có số điện thoại/Zalo — nhớ điền link đích trước khi cập nhật WP.")
    return html, warnings


def _gen_faq(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    kw = str(options.get("keyword") or context.get("keyword") or "").strip() or "chủ đề"
    items = options.get("items") or []
    if not items:
        items = [{"question": s["question"], "answer": ""} for s in suggest_insert(kind="faq", context=context, count=3)]
    parts = [f"<h3>Câu hỏi thường gặp về {_esc(kw)}</h3>"]
    for it in items[:8]:
        q = str((it or {}).get("question") or "").strip()
        if not q:
            continue
        a = str((it or {}).get("answer") or "").strip() or (
            f"Câu trả lời ngắn gọn, đúng trọng tâm cho «{q}» — hãy bổ sung số liệu thực tế của bạn."
        )
        parts.append(f"<p><strong>Hỏi:</strong> {_esc(q)}</p><p><strong>Đáp:</strong> {_esc(a)}</p>")
    return "".join(parts), []


def _gen_list(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    kind = str(options.get("list_kind") or "steps")
    kw = str(options.get("keyword") or context.get("keyword") or "").strip() or "chủ đề"
    raw_items = [str(x).strip() for x in (options.get("items") or []) if str(x).strip()]
    if not raw_items:
        if kind == "benefits":
            raw_items = [f"Tiết kiệm thời gian khi áp dụng {kw}", "Giảm sai sót vận hành", "Dễ đo lường kết quả"]
        elif kind == "checklist":
            raw_items = ["Xác định mục tiêu", f"Chuẩn bị điều kiện cho {kw}", "Kiểm tra kết quả và tinh chỉnh"]
        else:
            raw_items = ["Xác định nhu cầu", "Thu thập thông tin", "Triển khai và đo kết quả"]
    tag = "ol" if kind == "steps" else "ul"
    lis = "".join(f"<li>{_esc(x)}</li>" for x in raw_items[:12])
    return f"<{tag}>{lis}</{tag}>", []


def _gen_table(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    kind = str(options.get("table_kind") or "comparison")
    kw = str(options.get("keyword") or context.get("keyword") or "").strip() or "chủ đề"
    if kind == "pricing":
        head = ["Gói", "Giá", "Ghi chú"]
        rows = [["Cơ bản", "Liên hệ", f"Phù hợp bắt đầu với {kw}"], ["Nâng cao", "Liên hệ", "Đầy đủ tính năng"]]
    elif kind == "process":
        head = ["Bước", "Nội dung", "Kết quả"]
        rows = [["1", "Khảo sát nhu cầu", "Xác định phạm vi"], ["2", "Triển khai", "Bàn giao và đo lường"]]
    elif kind == "specs":
        head = ["Thông số", "Giá trị"]
        rows = [[f"{kw}", "—"], ["Bảo hành", "—"]]
    else:
        head = ["Tiêu chí", "Phương án 1", "Phương án 2"]
        rows = [["Chi phí", "—", "—"], ["Hiệu quả", "—", "—"]]
    thead = "".join(f"<th>{_esc(h)}</th>" for h in head)
    tbody = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>", []


def _gen_internal_link(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    url = str(options.get("url") or "").strip()
    site_base = str(options.get("site_base") or "").strip()
    if not url:
        raise ValueError("Cần chọn URL nội bộ của website.")
    if site_base and not validate_internal_url(url, site_base):
        raise ValueError("URL không thuộc website đã kết nối — chỉ dùng URL thật của site.")
    kw = str(options.get("keyword") or context.get("keyword") or "").strip()
    anchor = str(options.get("anchor") or "").strip() or (kw or _plain(url)[:60] or "bài viết liên quan")
    sentence = str(options.get("sentence") or "").strip()
    warnings: list[str] = []
    if url in (context.get("existing_links") or []):
        warnings.append("URL này đã có trong bài — cân nhắc tránh trùng lặp internal link.")
    esc_url = _esc(url)
    if sentence and "{link}" in sentence:
        before, _, after = sentence.partition("{link}")
        html = f"<p>{_esc(before)}<a href=\"{esc_url}\">{_esc(anchor)}</a>{_esc(after)}</p>"
    elif sentence:
        html = f"<p>{_esc(sentence)} <a href=\"{esc_url}\">{_esc(anchor)}</a>.</p>"
    else:
        html = f"<p>Xem thêm: <a href=\"{esc_url}\">{_esc(anchor)}</a>.</p>"
    return html, warnings


def _gen_image(options: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str]]:
    url = str(options.get("url") or "").strip()
    if not re.match(r"^https?://", url, flags=re.I):
        raise ValueError("URL ảnh không hợp lệ (cần http/https).")
    kw = str(options.get("keyword") or context.get("keyword") or "").strip()
    alt = str(options.get("alt") or "").strip() or (f"Hình minh họa {kw}" if kw else "Hình minh họa")
    caption = str(options.get("caption") or "").strip()
    cap_html = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
    html = (
        '<figure class="wp-block-image">'
        f'<img src="{_esc(url)}" alt="{_esc(alt)}" loading="lazy" />'
        f"{cap_html}</figure>"
    )
    return html, []


_GENERATORS = {
    "heading": _gen_heading,
    "paragraph": _gen_paragraph,
    "cta": _gen_cta,
    "faq": _gen_faq,
    "list": _gen_list,
    "table": _gen_table,
    "internal_link": _gen_internal_link,
    "image": _gen_image,
}


def estimate_insert_credit(insert_type: str, options: dict[str, Any]) -> int:
    base = int(INSERT_CREDIT_EST.get(insert_type, 4))
    if insert_type == "heading" and options.get("with_content"):
        words = max(50, min(2000, int(options.get("word_count") or 200)))
        return max(5, min(25, round(words / 40)))
    if insert_type == "faq":
        n = len(options.get("items") or []) or 3
        return max(3, min(20, 2 * n))
    return base


def generate_insert_preview(
    *,
    insert_type: str,
    options: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Template preview (free). Router may refine with LLM and charge on success."""
    t = str(insert_type or "").strip()
    gen = _GENERATORS.get(t)
    if gen is None:
        raise ValueError(f"Loại nội dung không hỗ trợ: {insert_type}")
    html, warnings = gen(dict(options or {}), dict(context or {}))
    return {
        "insert_type": t,
        "html": html,
        "word_count": _word_count(html),
        "credit_estimate": estimate_insert_credit(t, dict(options or {})),
        "warnings": warnings,
        "insert_index": int(context.get("insert_index") or 0),
        "source": "template",
    }


def build_insert_llm_prompt(
    *,
    insert_type: str,
    options: dict[str, Any],
    context: dict[str, Any],
    draft_html: str,
) -> tuple[str, str]:
    """(system, user) prompt — includes title/keyword and prev/next section to avoid repetition."""
    system = (
        "Bạn là biên tập viên SEO tiếng Việt. Chỉ trả về HTML của khối cần chèn "
        "(không trả cả bài, không markdown fence, không lời dẫn). Giữ HTML hợp lệ, "
        "không bịa link/ảnh mới ngoài dữ liệu được cung cấp. Viết nội dung thật, "
        "hữu ích — không viết placeholder, không nhồi nhét keyword."
    )
    kw = str(context.get("keyword") or "").strip()
    _service, _location = split_service_location(kw)
    target = insert_word_target(str(insert_type or ""), dict(options or {}))
    ctx_lines = [
        f"Loại khối: {insert_type}",
        f"Tiêu đề bài: {context.get('title') or '—'}",
        f"Keyword chính: {kw or '—'}",
        f"URL bài viết: {context.get('url') or '—'}",
        f"Heading phía trước vị trí chèn: {context.get('prev_heading') or '—'}",
        f"Heading phía sau vị trí chèn: {context.get('next_heading') or '—'}",
        f"Các heading đã có (tránh trùng lặp): {'; '.join(context.get('existing_headings') or [])[:800] or '—'}",
        f"Nội dung lân cận: {context.get('nearby_text') or '—'}",
        f"Tùy chọn người dùng: {options}",
    ]
    if _location:
        ctx_lines.append(
            f"Địa phương trong keyword: «{_location}» — nội dung phải nói đúng địa phương này, không nói nơi khác."
        )
    if target:
        ctx_lines.append(
            f"SỐ TỪ BẮT BUỘC: khoảng {target} từ (chấp nhận {round(target * 0.9)}–{round(target * 1.1)} từ, "
            "không tính chữ trong heading). Viết đủ độ dài, chia nhiều đoạn <p> ngắn "
            "(ưu tiên 2–4 câu mỗi đoạn, không gom thành đoạn quá dài)."
        )
    user = (
        "\n".join(ctx_lines)
        + "\n\nDRAFT HTML (cải thiện, không đổi loại khối, không lặp lại ý đã có trong bài):\n"
        + str(draft_html or "")[:4000]
    )
    return system, user


def try_llm_suggest(
    *,
    kind: str,
    context: dict[str, Any],
    count: int,
    user_id: int | None,
    use_system_llm: bool,
) -> list[dict[str, Any]] | None:
    """LLM suggestions (headings/CTA/FAQ). Returns None on any failure."""
    try:
        from app.services.llm_content_writer import _cau_modal_llm_chat
    except Exception:
        return None
    n = max(3, min(int(count or 5), 5))
    what = {
        "heading": f"{n} tiêu đề heading (mỗi dòng 1 tiêu đề, không đánh số)",
        "cta": f"{n} CTA theo định dạng mỗi dòng: tiêu đề | nội dung 1 câu | chữ nút",
        "faq": f"{n} câu hỏi thường gặp (mỗi dòng 1 câu hỏi)",
    }.get(kind)
    if not what:
        return None
    kw = str(context.get("keyword") or "").strip()
    _service, _location = split_service_location(kw)
    system = (
        "Bạn là biên tập viên SEO tiếng Việt. Chỉ trả về danh sách thuần văn bản, "
        "mỗi dòng một mục, không markdown, không lời dẫn."
    )
    heading_rules = ""
    if kind == "heading":
        heading_rules = (
            "\nQUY TẮC HEADING (bắt buộc):\n"
            "- Heading phải bám sát keyword và chủ đề bài, phục vụ đúng ý định tìm kiếm.\n"
            + (f"- Keyword có yếu tố địa phương «{_location}» — MỌI heading phải nhắc đúng địa phương này.\n" if _location else "")
            + "- CẤM heading chung chung kiểu «… là gì?», «Lợi ích … trong thực tế», «Tổng quan về …».\n"
            "- Ưu tiên dạng: Dịch vụ …, Quy trình …, Bảng giá …, Địa chỉ … uy tín, Các lỗi … thường gặp.\n"
            "- Không trùng hoặc gần trùng heading đã có trong bài.\n"
        )
    user = (
        f"Tiêu đề bài: {context.get('title') or '—'}\n"
        f"Keyword: {kw or '—'}\n"
        f"URL bài viết: {context.get('url') or '—'}\n"
        f"Heading trước vị trí chèn: {context.get('prev_heading') or '—'}\n"
        f"Heading sau vị trí chèn: {context.get('next_heading') or '—'}\n"
        f"Nội dung lân cận vị trí chèn: {str(context.get('nearby_text') or '—')[:400]}\n"
        f"Các heading đã có (KHÔNG lặp lại): {'; '.join(context.get('existing_headings') or [])[:800] or '—'}\n"
        f"{heading_rules}\n"
        f"Hãy gợi ý {what}."
    )
    try:
        raw = _cau_modal_llm_chat(
            system=system, user=user, user_id=user_id,
            use_system_llm=use_system_llm, timeout_sec=45, word_target=120,
        )
    except Exception:
        return None
    lines = [
        re.sub(r"^[\d\-\*\.\)\s]+", "", ln).strip()
        for ln in str(raw or "").splitlines()
    ]
    lines = [ln for ln in lines if len(ln) >= 4][:n]
    if not lines:
        return None
    if kind == "cta":
        out = []
        for ln in lines:
            parts = [p.strip() for p in ln.split("|")]
            out.append({
                "channel": "",
                "title": parts[0] if parts else ln,
                "body": parts[1] if len(parts) > 1 else "",
                "button": parts[2] if len(parts) > 2 else "",
            })
        return out
    if kind == "faq":
        return [{"question": ln} for ln in lines]
    existing = list(context.get("existing_headings") or [])
    kw_seed = kw or str(context.get("title") or "")
    titles = _filter_headings(lines, keyword=kw_seed, existing=existing)
    if len(titles) < 3:
        titles = _dedupe_titles(lines, existing)
    if not titles:
        return None
    return [{"title": t} for t in titles]


def try_llm_insert_html(
    *,
    insert_type: str,
    options: dict[str, Any],
    context: dict[str, Any],
    draft_html: str,
    user_id: int | None,
    use_system_llm: bool,
) -> str | None:
    """Return refined HTML on success, None on any failure (caller keeps template)."""
    try:
        from app.services.llm_content_writer import _cau_modal_llm_chat
    except Exception:
        return None
    system, user = build_insert_llm_prompt(
        insert_type=insert_type, options=options, context=context, draft_html=draft_html,
    )
    word_target = insert_word_target(insert_type, dict(options or {})) or 200
    try:
        raw = _cau_modal_llm_chat(
            system=system,
            user=user,
            user_id=user_id,
            use_system_llm=use_system_llm,
            timeout_sec=60,
            word_target=word_target,
        )
    except Exception:
        return None
    html = _strip_code_fence(raw)
    if not html or len(html) < 8 or "<" not in html:
        return None

    # Ép đúng số từ yêu cầu (±10%): thiếu thì nhờ AI viết tiếp, thừa thì rút gọn.
    strict_target = insert_word_target(insert_type, dict(options or {}))
    if strict_target:
        def _chat(sys_msg: str, user_msg: str, wt: int) -> str | None:
            try:
                return _cau_modal_llm_chat(
                    system=sys_msg,
                    user=user_msg,
                    user_id=user_id,
                    use_system_llm=use_system_llm,
                    timeout_sec=60,
                    word_target=max(50, int(wt or 50)),
                )
            except Exception:
                return None

        html = fit_word_count(
            html,
            strict_target,
            chat=_chat,
            keyword=str(context.get("keyword") or ""),
        )
    return html
