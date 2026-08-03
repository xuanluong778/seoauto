from __future__ import annotations

import hashlib
import html
import random
import re
import unicodedata
from collections import Counter
from typing import Any
from urllib.parse import urlparse
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup, Tag

from app.services.serp_fetcher import fetch_serp_for_keyword


_ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "a",
    "img",
    "figure",
    "figcaption",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "code",
    "pre",
    "hr",
    "br",
    "div",
    "span",
    "script",
}

_DROP_TAGS = {"style", "iframe", "object", "embed", "noscript"}
_SAFE_ATTRS = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "div": {"class"},
    "span": {"class"},
    "p": {"class"},
    "h1": {"class"},
    "h2": {"class"},
    "h3": {"class"},
    "script": {"type"},
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "la",
    "cua",
    "cho",
    "va",
    "tu",
    "tai",
    "tren",
    "duoc",
    "mot",
    "nhung",
    "cac",
    "the",
}


def _normalize_domain(host: str) -> str:
    h = (host or "").strip().lower()
    return h[4:] if h.startswith("www.") else h


def _guess_title_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        segs = (p.path or "").strip("/").split("/")
        seg = segs[-1] if segs else ""
        seg = seg or (p.hostname or "")
        seg = seg.replace("-", " ").replace("_", " ")
        seg = re.sub(r"\s+", " ", seg).strip()
        return seg[:80] if seg else url
    except Exception:
        return url


def _tokenize_for_match(s: str) -> list[str]:
    toks = re.findall(r"[a-zA-Z0-9À-ỹ]{3,}", (s or "").lower())
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        t2 = t.strip()
        if not t2 or t2 in _STOPWORDS:
            continue
        if t2 in seen:
            continue
        seen.add(t2)
        out.append(t2)
    return out[:10]


def _fetch_related_internal_posts_for_injection(
    *,
    target_website: str,
    topic: str,
    max_posts: int = 5,
) -> list[dict[str, str]]:
    """
    Fetch bài viết liên quan nội bộ để chèn internal links.
    Ưu tiên SERP (site:domain + topic), fallback sitemap.xml.
    """
    tw = (target_website or "").strip()
    if tw and not tw.lower().startswith(("http://", "https://")):
        tw = "https://" + tw
    if not tw or not topic:
        return []
    parsed = urlparse(tw)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or ""
    domain = _normalize_domain(host)
    if not domain:
        return []
    base = f"{scheme}://{host}".rstrip("/")

    related: list[dict[str, str]] = []

    # 1) SERP-based
    try:
        q = f"site:{domain} {topic}"
        snap = fetch_serp_for_keyword(q, top_n=10, use_cache=True)
        urls = list(snap.get("serp_urls") or [])
        titles = list(snap.get("titles") or [])
        for i, u in enumerate(urls):
            if len(related) >= max_posts:
                break
            if not u:
                continue
            try:
                h2 = urlparse(u).hostname or ""
                if _normalize_domain(h2) != domain:
                    continue
            except Exception:
                continue
            t_title = titles[i] if i < len(titles) else ""
            t_title = str(t_title or "").strip() or _guess_title_from_url(u)
            if any(x.get("url") == u for x in related):
                continue
            related.append({"url": u, "title": t_title})
    except Exception:
        pass

    # 2) sitemap.xml fallback
    if len(related) < 3:
        try:
            sm_url = base + "/sitemap.xml"
            r = requests.get(sm_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and r.text:
                root = ET.fromstring(r.text)
                locs: list[str] = []
                for el in root.iter():
                    if str(el.tag or "").endswith("loc") and el.text:
                        locs.append(el.text.strip())
                tokens = _tokenize_for_match(topic)
                scored: list[tuple[int, str]] = []
                for u in locs:
                    try:
                        h2 = urlparse(u).hostname or ""
                        if _normalize_domain(h2) != domain:
                            continue
                    except Exception:
                        continue
                    pth = (urlparse(u).path or "").lower()
                    score = 0
                    for tok in tokens:
                        if tok and tok in pth:
                            score += 1
                    if score > 0:
                        scored.append((score, u))
                scored.sort(key=lambda x: x[0], reverse=True)
                for _score, u in scored[:20]:
                    if len(related) >= max_posts:
                        break
                    if any(x.get("url") == u for x in related):
                        continue
                    related.append({"url": u, "title": _guess_title_from_url(u)})
        except Exception:
            pass

    # Final dedupe
    out: list[dict[str, str]] = []
    seen_url: set[str] = set()
    for it in related:
        u = str(it.get("url") or "").strip()
        if not u or u in seen_url:
            continue
        seen_url.add(u)
        out.append({"url": u, "title": str(it.get("title") or "").strip() or _guess_title_from_url(u)})
        if len(out) >= max_posts:
            break
    return out


def _inject_related_internal_links(
    html_content: str,
    *,
    title: str,
    primary_keyword: str,
    target_website: str,
) -> str:
    """
    Post-process nội dung draft:
    - Nếu có <a href="#"> ... (bài liên quan) => thay bằng link thật.
    - Chỉ chèn tối đa 2–3 link inline trong bài (mặc định 3).
    - Anchor text lấy theo ngữ cảnh gần nhất (H2/H3 chứa placeholder).
    - Tránh để còn link `href="#"` bị gãy: phần placeholder dư sẽ chuyển thành text (span).
    - Nếu không có placeholder => chèn blockquote “Bài liên quan” (top 3) trước FAQ.
    """
    if not html_content or not target_website:
        return html_content
    topic = (primary_keyword or "").strip() or (title or "").strip()
    if not topic:
        return html_content

    related = _fetch_related_internal_posts_for_injection(
        target_website=target_website,
        topic=topic,
        max_posts=6,
    )
    if not related:
        return html_content

    soup = BeautifulSoup(html_content, "html.parser")

    max_inline_links_total = 3

    def _clean_anchor_text(txt: str) -> str:
        raw = str(txt or "").strip()
        # Remove common placeholder suffix.
        raw = re.sub(r"\s*\(?\s*bài\s*liên\s*quan\s*\)?\.?$", "", raw, flags=re.I).strip()
        raw = raw.strip()
        return raw[:160] if raw else raw

    def _score_related_for_context(ctx_text: str, rp: dict[str, str]) -> int:
        ctx_toks = _tokenize_for_match(ctx_text)
        rt = str(rp.get("title") or "").lower()
        ru = str(rp.get("url") or "").lower()
        score = 0
        for tok in ctx_toks:
            if tok and (tok in rt or tok in ru):
                score += 1
        return score

    placeholders = soup.find_all("a", href="#")
    if placeholders:
        used_urls: set[str] = set()
        injected = 0

        # Replace placeholder links section-by-section based on the nearest heading.
        for heading in soup.find_all(["h2", "h3"]):
            if injected >= max_inline_links_total:
                break
            ctx = str(heading.get_text(" ", strip=True) or "")
            if not ctx:
                continue

            # Collect placeholder anchors within this heading's section until next h2/h3.
            sec_placeholders: list[Tag] = []
            for sib in heading.next_siblings:
                if isinstance(sib, Tag) and sib.name in ("h2", "h3"):
                    break
                if not isinstance(sib, Tag):
                    continue
                found = sib.find_all("a", href="#")
                if found:
                    sec_placeholders.extend(found)
                    if len(sec_placeholders) >= 2:
                        break

            if not sec_placeholders:
                continue

            # Pick best matching related post not used yet.
            best_rp: dict[str, str] | None = None
            best_score = -1
            for rp in related:
                url = str(rp.get("url") or "").strip()
                if not url or url in used_urls:
                    continue
                sc = _score_related_for_context(ctx, rp)
                if sc > best_score:
                    best_score = sc
                    best_rp = rp

            if not best_rp or not best_rp.get("url"):
                continue

            # Inject only one inline link for this section.
            a0 = sec_placeholders[0]
            a0["href"] = best_rp["url"]
            # Anchor text: prefer context heading text, cleaned from placeholder suffix.
            a0_text = a0.get_text(" ", strip=True)
            cleaned = _clean_anchor_text(a0_text) or ctx
            if cleaned and cleaned.lower() == "bài liên quan":
                cleaned = ctx
            if cleaned:
                a0.string = cleaned
            used_urls.add(str(best_rp["url"]).strip())
            injected += 1

            # Remove remaining placeholders to avoid broken links.
            for extra_a in sec_placeholders[1:]:
                if injected >= max_inline_links_total:
                    txt = _clean_anchor_text(extra_a.get_text(" ", strip=True))
                    span = soup.new_tag("span")
                    span.string = txt or ctx
                    extra_a.replace_with(span)

        # After injecting, remove any leftover href="#" placeholders.
        for a in soup.find_all("a", href="#"):
            txt = _clean_anchor_text(a.get_text(" ", strip=True))
            span = soup.new_tag("span")
            span.string = txt or topic
            a.replace_with(span)

        return str(soup)

    # Insert a new blockquote before FAQ if possible
    anchor = None
    for h2 in soup.find_all(["h2", "h3"]):
        txt = str(h2.get_text(" ", strip=True) or "").lower()
        if "câu hỏi thường gặp" in txt or "faq" in txt:
            anchor = h2
            break

    links_html = " · ".join(
        f'<a href="{html.escape(rp["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(rp["title"])}</a>'
        for rp in related[:3]
        if rp.get("url")
    )
    blockquote_html = (
        '<blockquote style="margin:12px 0; padding:10px 12px; border-left:3px solid rgba(69,211,255,0.9); '
        'background: rgba(2,6,23,0.14); border-radius: 10px;">'
        f"<strong>Bài liên quan:</strong> {links_html}. "
        "Bạn có thể mở các bài này để hiểu sâu hơn rồi quay lại bài chính."
        "</blockquote>"
    )
    node = BeautifulSoup(blockquote_html, "html.parser")
    first = node.contents[0] if node.contents else None
    if anchor and anchor.parent:
        anchor.insert_before(first)
    else:
        # fallback: append near end
        if soup.body:
            soup.body.append(first)
        else:
            soup.append(first)
    return str(soup)

_TITLE_PATTERNS_TRAINING = (
    "{kw} uy tín | Lên top ngay khi học",
    "{kw} chuyên sâu: Lộ trình thực chiến từ A-Z",
    "{kw} bài bản cho người mới | Học nhanh, làm được ngay",
    "{kw} hiệu quả: Bí quyết tối ưu để website tăng trưởng bền vững",
    "{kw} chuyên nghiệp | Checklist đầy đủ để bứt phá thứ hạng",
)

_TITLE_PATTERNS_SERVICE = (
    # Kept for backward compat (onsite services). Use _service_mode() to pick right tuple.
    "{kw} nhanh chóng | Hỗ trợ tận nơi, giá rõ ràng",
    "{kw} uy tín | Có mặt nhanh, xử lý gọn",
    "{kw} tại nhà | Kỹ thuật viên đến tận nơi",
)

_TITLE_PATTERNS_SERVICE_ONLINE = (
    "{kw} uy tín | Tư vấn online, triển khai nhanh",
    "{kw} chuyên nghiệp | Quy trình rõ ràng, báo giá minh bạch",
    "{kw} trọn gói | Chuẩn SEO, giao diện đẹp, tối ưu chuyển đổi",
)

_TITLE_PATTERNS_SERVICE_ONSITE = (
    "{kw} nhanh chóng | Hỗ trợ tận nơi, giá rõ ràng",
    "{kw} uy tín | Có mặt nhanh, xử lý gọn",
    "{kw} tại nhà | Kỹ thuật viên đến tận nơi",
)

_TITLE_PATTERNS_HOWTO = (
    "6 cách {kw} nhanh chóng | Đơn giản nhất",
    "7 cách {kw} tại nhà | Làm theo là được",
    "{kw}: Nguyên nhân & cách khắc phục nhanh (cập nhật mới)",
)


def _is_training_keyword(pk: str) -> bool:
    s = (pk or "").lower()
    signals = (
        "dao tao",
        "đào tạo",
        "khoa hoc",
        "khóa học",
        "hoc ",
        "học ",
        "lop ",
        "lớp ",
    )
    return any(x in s for x in signals)


def _is_service_keyword(pk: str) -> bool:
    s = (pk or "").lower()
    signals = (
        "cai ",
        "cài ",
        "cai dat",
        "cài đặt",
        "cai win",
        "cài win",
        "cai windows",
        "cài windows",
        "ghost win",
        "cai lai win",
        "cài lại win",
        "tan noi",
        "tận nơi",
        "tai nha",
        "tại nhà",
        "sua",
        "sửa",
        "dich vu",
        "dịch vụ",
        "bao gia",
        "báo giá",
        "gia re",
        "giá rẻ",
    )
    return any(x in s for x in signals)


def _article_variant_index(topic: str, title: str) -> int:
    key = re.sub(r"\s+", " ", f"{topic}|{title}".strip()).lower()
    return int(hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:8], 16) % 4


def _extract_district_label(pk: str) -> str:
    s = (pk or "").strip()
    m = re.search(r"(quận|quan|q\.?)\s*(\d{1,2})\b", s, flags=re.I)
    if m:
        return f"Quận {int(m.group(2))}"
    m2 = re.search(r"(huyện|huyen)\s+([^\s,|]+)", s, flags=re.I)
    if m2:
        return f"Huyện {m2.group(2).strip()}"
    return ""


def _is_pc_repair_topic(pk: str) -> bool:
    s = (pk or "").lower()
    return any(x in s for x in ("máy tính", "may tinh", "laptop", "pc ", " pc", "macbook"))


def _strip_markdown_code_fence(s: str) -> str:
    t = str(s or "").strip()
    if not t.startswith("```"):
        return t
    t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t).strip()
    t = re.sub(r"\s*```\s*$", "", t).strip()
    return t


def extract_clean_html_fragment(raw: str) -> str:
    """
    Keep only the HTML fragment: drop preamble/postamble prose outside tags.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"<\s*(?:h1|h2|h3|article|section|main|div|html|body|p|ul|ol|table)\b", s, flags=re.I)
    if m:
        s = s[m.start() :].lstrip()
    else:
        m2 = re.search(r"<\s*[a-z]", s, flags=re.I)
        if m2:
            s = s[m2.start() :].lstrip()
    last_gt = s.rfind(">")
    if last_gt >= 0:
        tail = s[last_gt + 1 :].strip()
        if tail and "<" not in tail:
            s = s[: last_gt + 1]
    return s.strip()


def _finalize_content_html(s: str) -> str:
    out = extract_clean_html_fragment(_strip_markdown_code_fence(s))
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes
    from app.services.content_ai_publish_checklist import strip_publish_checklist_from_html
    from app.services.content_table_format import enhance_tables_in_html

    out = postprocess_content_blockquotes(out)
    out = strip_publish_checklist_from_html(out)
    return enhance_tables_in_html(out)


def _service_mode(pk: str) -> str:
    """
    Service mode classifier.
    Returns: "online" | "onsite" | "generic"
    """
    raw = re.sub(r"\s+", " ", (pk or "").strip())
    # Ignore tagline after "|" for semantic classification.
    core = re.split(r"\s*[|]\s*", raw, maxsplit=1)[0].strip()
    s = core.lower()
    if not s:
        return "generic"
    onsite_signals = (
        "tan noi",
        "tận nơi",
        "tai nha",
        "tại nhà",
        "co mat",
        "có mặt",
        "den tan noi",
        "đến tận nơi",
        "kỹ thuật viên",
        "ky thuat vien",
    )
    if any(x in s for x in onsite_signals):
        return "onsite"
    online_signals = (
        "thiet ke website",
        "thiết kế website",
        "thiet ke web",
        "thiết kế web",
        "lam website",
        "làm website",
        "lam web",
        "làm web",
        "web design",
        "website design",
        "seo",
        "marketing",
        "quang cao",
        "quảng cáo",
        "google ads",
        "facebook ads",
        "hosting",
        "domain",
        "ten mien",
        "tên miền",
        "lap trinh",
        "lập trình",
        "ui ux",
        "ui/ux",
        "wordpress",
        "shopify",
    )
    if any(x in s for x in online_signals):
        return "online"
    # If keyword contains "dịch vụ" but not onsite, default to online-ish (safer wording)
    if "dich vu" in s or "dịch vụ" in s:
        return "online"
    return "generic"


def _is_howto_keyword(pk: str) -> bool:
    s = (pk or "").lower()
    signals = (
        "sửa lỗi",
        "không ",
        "bi loi",
        "bị lỗi",
        "khac phuc",
        "khắc phục",
        "cach ",
        "cách ",
        "nguyen nhan",
        "nguyên nhân",
    )
    return any(x in s for x in signals)


def _has_local_service_signal(pk: str) -> bool:
    s = (pk or "").lower()
    signals = (
        "quận",
        "quan ",
        "q.",
        " q",
        "near me",
        "tại nhà",
        "tai nha",
        "tận nơi",
        "tan noi",
        "gần đây",
        "gan day",
    )
    return any(x in s for x in signals)


def _detect_search_intent(pk: str) -> str:
    """
    Canonical intent classes used by Content AI.
    Returns: transactional | commercial investigation | informational | navigational
    """
    raw = re.sub(r"\s+", " ", (pk or "").strip())
    kw = re.split(r"\s*[|]\s*", raw, maxsplit=1)[0].strip()
    if not kw:
        return "informational"
    if _has_local_service_signal(kw):
        return "transactional"
    s = kw.lower()
    nav_signals = ("facebook", "youtube", "wikipedia", "official", "chính hãng", "trang chủ", ".com")
    if any(x in s for x in nav_signals):
        return "navigational"
    compare_signals = (
        "so sánh",
        "so sanh",
        "review",
        "đánh giá",
        "danh sách",
        "top ",
        "tốt nhất",
        "bao nhiêu",
        "giá ",
        "gia ",
    )
    if any(x in s for x in compare_signals):
        return "commercial investigation"
    if _is_service_keyword(kw):
        return "transactional"
    return "informational"


def detect_search_intent(pk: str) -> str:
    return _detect_search_intent(pk)


def content_ai_has_local_service_signal(keyword: str) -> bool:
    """
    Public: từ khóa có tín hiệu dịch vụ tại chỗ / địa phương.
    Dùng chung cho lớp điều khiển (UI, outline) và lớp LLM (prompt) — một nguồn với _detect_search_intent.
    """
    return _has_local_service_signal(keyword)


def content_ai_normalize_pasted_body(
    *,
    primary_keyword: str,
    title: str,
    content: str,
) -> str:
    """
    Lớp nội dung HTML body (KHÔNG sinh article bằng rule).

    Chỉ trả về HTML khi người dùng đã dán sẵn và qua kiểm tra intent/template.
    Trả về chuỗi rỗng nếu không có bản dán hợp lệ — sinh body chỉ qua LLM (`generate_content_ai_suggestion`).
    Tách biệt khỏi lớp điều khiển rule trong `suggest_content_ai_field` (title/meta/outline/...).
    """
    pk = re.sub(r"\s+", " ", (primary_keyword or "").strip())
    t = re.sub(r"\s+", " ", (title or "").strip())
    if not pk:
        return ""
    detected_intent = _detect_search_intent(pk or t or "")
    provided_content = (content or "").strip()
    if not provided_content:
        return ""
    keep_existing = True
    if detected_intent == "transactional":
        lowered = provided_content.lower()
        if _looks_like_generic_template(provided_content):
            keep_existing = False
        if "landing page" not in lowered and "dịch vụ" not in lowered:
            keep_existing = False
    elif detected_intent == "informational":
        if _looks_like_transactional_copy(provided_content):
            keep_existing = False
    elif _looks_like_generic_template(provided_content):
        keep_existing = False
    if keep_existing:
        return _finalize_content_html(provided_content)
    return ""


def _looks_like_generic_template(text: str) -> bool:
    s = (text or "").lower()
    markers = (
        "nguồn tham khảo: google helpful content",
        "e-e-a-t",
        "link ngoài gợi ý",
        "bài này viết để",
        "câu hỏi thường gặp",
        "checklist hành động",
        "định nghĩa nhanh",
    )
    hit = sum(1 for m in markers if m in s)
    return hit >= 2


def _looks_like_transactional_copy(text: str) -> bool:
    s = (text or "").lower()
    markers = (
        "đặt lịch",
        "lien he",
        "liên hệ",
        "báo giá",
        "bao gia",
        "dịch vụ",
        "cam kết",
        "cta",
        "khuyến mãi",
    )
    return sum(1 for m in markers if m in s) >= 2


def _sanitize_mixed_style_phrases(text: str) -> str:
    out = str(text or "")
    substitutions = [
        (r"(?i)\bin this article we will\b", "Thông tin dưới đây tập trung trực tiếp vào nhu cầu của khách"),
        (r"(?i)\btrong bài viết này\b", "Khi bạn đọc tiếp"),
        (r"(?i)\btrong trải nghiệm của mình\b", "Theo dữ liệu vận hành thực tế"),
        (r"(?i)\bcác bước làm\b", "quy trình xử lý"),
        (r"(?i)\[CẦN XÁC NHẬN\]", ""),
        (r"(?i)\blocal service page\b", ""),
        (r"(?i)\blà trang dịch vụ địa phương\b", "phục vụ khách tại khu vực này"),
        (r"(?i)\bchuẩn local service page\b", "theo quy trình rõ ràng"),
    ]
    for pattern, repl in substitutions:
        out = re.sub(pattern, repl, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return out.strip()


def _transactional_ready(html_text: str) -> bool:
    s = str(html_text or "").lower()
    checks = [
        any(x in s for x in ("dịch vụ", "dich vu", "hỗ trợ", "ho tro")),
        any(x in s for x in ("kinh nghiệm", "kinh nghiem", "khách hàng", "khach hang", "bảo hành", "bao hanh")),
        any(x in s for x in ("bao gồm", "bao gom", "hạng mục", "hang muc")),
        any(x in s for x in ("chi phí", "chi phi", "bảng giá", "bang gia", "giá", "gia")),
        any(x in s for x in ("liên hệ", "lien he", "hotline", "zalo", "đặt lịch", "dat lich", "booking")),
    ]
    return all(checks)


def _classify_intent(pk: str) -> str:
    """
    Rough intent classifier from primary keyword.
    Returns: "howto" | "service" | "training" | "info"
    """
    raw = re.sub(r"\s+", " ", (pk or "").strip())
    # Ignore tagline after "|" for intent classification.
    kw = re.split(r"\s*[|]\s*", raw, maxsplit=1)[0].strip()
    if not kw:
        return "info"
    if _is_training_keyword(kw):
        return "training"
    canonical = _detect_search_intent(kw)
    if canonical == "transactional":
        return "service"
    if canonical in {"commercial investigation", "navigational", "informational"}:
        return "info"
    # How-to should win when explicitly about lỗi/khắc phục
    if _is_howto_keyword(kw):
        return "howto"
    if _is_service_keyword(kw):
        return "service"
    return "info"


def _ensure_contains_keyword(text: str, pk: str) -> str:
    out = re.sub(r"\s+", " ", str(text or "").strip())
    kw = re.sub(r"\s+", " ", str(pk or "").strip())
    if not out or not kw:
        return out
    if kw.lower() in out.lower():
        return out
    return f"{kw} - {out}".strip()


def _suggest_title_from_keyword(pk: str) -> str:
    raw = re.sub(r"\s+", " ", (pk or "").strip())
    # Titles should follow the semantic core, not the marketing tagline.
    kw = re.split(r"\s*[|]\s*", raw, maxsplit=1)[0].strip()
    if not kw:
        return ""
    kw_len = len(kw)
    intent = _classify_intent(kw)
    if intent == "howto":
        patterns = _TITLE_PATTERNS_HOWTO
    elif intent == "service":
        mode = _service_mode(kw)
        if mode == "onsite":
            patterns = _TITLE_PATTERNS_SERVICE_ONSITE
        elif mode == "online":
            patterns = _TITLE_PATTERNS_SERVICE_ONLINE
        else:
            # Long local keywords leave little room after " | " — use shorter taglines.
            if kw_len > 26:
                patterns = (
                    "{kw} uy tín | Có mặt nhanh, báo giá rõ",
                    "{kw} chuyên nghiệp | Tận nơi, bảo hành minh bạch",
                )
            else:
                patterns = (
                    "{kw} uy tín | Báo giá rõ ràng, quy trình minh bạch",
                    "{kw} chuyên nghiệp | Tư vấn nhanh, triển khai chuẩn",
                )
    elif intent == "training":
        patterns = _TITLE_PATTERNS_TRAINING
    else:
        patterns = (
            "{kw}: Hướng dẫn & checklist thực hành (mới nhất)",
            "{kw}: Kinh nghiệm thực tế, tránh sai lầm phổ biến",
            "{kw}: Tổng hợp cách làm đúng, tiết kiệm thời gian",
        )
    title = random.choice(patterns).format(kw=kw)
    return _ensure_contains_keyword(title, kw)


_TITLE_SHORT_SUFFIXES = (
    "Có mặt nhanh",
    "Báo giá rõ ràng",
    "Tư vấn miễn phí",
    "Hỗ trợ tận nơi",
    "Xử lý gọn, chuẩn",
    "Đặt lịch nhanh",
)


def _fit_title_segment(segment: str, room: int) -> str:
    """Trim `segment` to at most `room` chars without dangling a cut mid-clause when possible."""
    seg = re.sub(r"\s+", " ", str(segment or "").strip())
    if not seg or room <= 0:
        return ""
    if len(seg) <= room:
        return seg
    # Prefer first comma-separated clause if it fits (avoids "… triển" without "khai chuẩn").
    if "," in seg:
        first = seg.split(",", 1)[0].strip()
        if first and len(first) <= room:
            return first
    cut = seg[:room].rstrip()
    # Drop trailing fragment if cut landed inside a word (alnum continues in seg[room]).
    if room < len(seg) and cut and cut[-1].isalnum() and seg[room : room + 1].isalnum():
        sp = max(cut.rfind(" "), cut.rfind(","), cut.rfind(";"))
        if sp >= max(6, room // 4):
            cut = cut[:sp].rstrip(" ,;")
    elif " " in cut:
        cut = cut.rsplit(" ", 1)[0].strip()
    return cut


def _pick_right_title_for_room(right: str, room: int) -> str:
    """Choose a complete right-hand title after ` | ` that fits `room` characters."""
    r = re.sub(r"\s+", " ", str(right or "").strip())
    if not r:
        return ""
    if len(r) <= room:
        return r
    if "," in r:
        first = r.split(",", 1)[0].strip()
        if first and len(first) <= room:
            return first
    for s in _TITLE_SHORT_SUFFIXES:
        if len(s) <= room:
            return s
    return _fit_title_segment(r, room)


def _extend_pipe_title_for_min_len(t: str, *, min_len: int, hard_max: int) -> str:
    """
    Nếu tiêu đề dạng «kw | tagline» hơi ngắn: bổ sung ý lợi ích sau tagline (không dùng (mới)/năm giả).
    """
    t = re.sub(r"\s+", " ", str(t or "").strip())
    if not t or "|" not in t or len(t) >= min_len:
        return t
    left, _, right = t.partition("|")
    left, right = left.strip(), right.strip()
    if not left or not right:
        return t
    sep = " | "
    tails = [
        " – có mặt nhanh",
        " – báo giá rõ",
        " – tận nơi",
        " – đặt lịch nhanh",
    ]
    for tail in tails:
        cand = f"{left}{sep}{right}{tail}".strip()
        cand = re.sub(r"\s+", " ", cand)
        if len(cand) <= hard_max and len(cand) >= min_len:
            return cand
    return t


def _balance_pipe_title(t: str, limit: int) -> str:
    """Keep `left | right` under `limit` by shortening the right side first, then the left."""
    t = re.sub(r"\s+", " ", str(t or "").strip())
    if "|" not in t:
        return _fit_title_segment(t, limit)
    left, _, right = t.partition("|")
    left, right = left.strip(), right.strip()
    if not left:
        return _fit_title_segment(t.replace("|", " ").strip(), limit)
    sep = " | "
    room = limit - len(left) - len(sep)
    if room < 8:
        left = _fit_title_segment(left, max(limit - len(sep) - 10, 28))
        room = limit - len(left) - len(sep)
    right2 = _pick_right_title_for_room(right, max(room, 8)) if room >= 8 else ""
    out = f"{left}{sep}{right2}".strip() if right2 else left
    return re.sub(r"\s+", " ", out).strip()


def _trim_title_len(title: str, *, min_len: int = 48, max_len: int = 60, hard_min: int = 38, hard_max: int = 68) -> str:
    """
    Chuẩn hoá độ dài tiêu đề (SERP ~50–60 ký tự là gợi ý, không nhồi (mới)/năm giả).

    - Ưu tiên giữ dạng «từ khóa | lợi ích», cắt bớt phần sau pipe nếu quá dài.
    - Nếu hơi ngắn: chỉ bổ sung cụm lợi ích có nghĩa (qua _extend_pipe_title_for_min_len), không dùng placeholder kiểu (mới).
    """
    t = re.sub(r"\s+", " ", str(title or "").strip())
    if not t:
        return ""
    # First pass: respect pipe so the marketing tail is not chopped mid-phrase.
    if "|" in t:
        if len(t) > max_len:
            t = _balance_pipe_title(t, max_len)
        if len(t) > hard_max:
            t = _balance_pipe_title(t, hard_max)
    elif len(t) > hard_max:
        words = t.split(" ")
        out = ""
        for w in words:
            cand = (out + " " + w).strip()
            if len(cand) > hard_max:
                break
            out = cand
        t = out or _fit_title_segment(t, hard_max)
    # Land near max_len without breaking `keyword | tagline`
    if len(t) > max_len:
        if "|" in t:
            t = _balance_pipe_title(t, max_len)
        else:
            t = _fit_title_segment(t, max_len)
    # Chỉ kéo dài có ý nghĩa khi thiếu chút độ dài — không đệm (mới)/2026 máy móc
    if "|" in t and len(t) < min_len:
        t = _extend_pipe_title_for_min_len(t, min_len=min_len, hard_max=hard_max)
        if len(t) > max_len and "|" in t:
            t = _balance_pipe_title(t, max_len)
    # Dưới hard_min: chấp nhận (tiêu đề ngắn vẫn hợp lệ), không gắn từ rác
    if len(t) < hard_min and "|" in t:
        t = _extend_pipe_title_for_min_len(t, min_len=hard_min, hard_max=hard_max)
    return re.sub(r"\s+", " ", t).strip()


def _ensure_keyword_once_at_start(title: str, kw: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "").strip())
    k = re.sub(r"\s+", " ", str(kw or "").strip())
    if not t or not k:
        return t
    # remove duplicate keyword occurrences (case-insensitive)
    pattern = re.compile(re.escape(k), flags=re.I)
    matches = list(pattern.finditer(t))
    if len(matches) > 1:
        # keep first, remove others
        first_end = matches[0].end()
        prefix = t[:first_end]
        rest = t[first_end:]
        rest = pattern.sub("", rest)
        t = re.sub(r"\s+", " ", (prefix + rest)).strip(" -|")
        t = re.sub(r"\s+", " ", t).strip()
    # ensure keyword at start
    if not t.lower().startswith(k.lower()):
        # remove leading keyword elsewhere to avoid duplicate
        t2 = pattern.sub("", t, count=1).strip(" -|")
        t = f"{k} – {t2}".strip()
    return re.sub(r"\s+", " ", t).strip()


def _build_secondary_keyword_suggestions(pk: str, sec_top: list[str]) -> list[str]:
    base = re.sub(r"\s+", " ", (pk or "").strip())
    if not base:
        return sec_top[:5]
    if _is_training_keyword(base):
        defaults = [
            f"{base} cho người mới",
            f"chi phí {base}",
            f"lộ trình {base}",
            f"kinh nghiệm {base}",
            f"{base} uy tín",
            f"nội dung {base} thực hành",
        ]
    elif _is_service_keyword(base):
        defaults = [
            f"{base} giá rẻ",
            f"{base} uy tín",
            f"{base} gần đây",
            f"{base} nhanh",
            f"{base} bao nhiêu tiền",
            f"đánh giá {base}",
        ]
    else:
        defaults = [
            f"{base} là gì",
            f"hướng dẫn {base}",
            f"kinh nghiệm {base}",
            f"checklist {base}",
            f"{base} hiệu quả",
            f"tối ưu {base}",
        ]

    merged: list[str] = []
    seen: set[str] = set()
    for k in sec_top + defaults:
        c = re.sub(r"\s+", " ", str(k or "").strip())
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
        if len(merged) >= 6:
            break
    return merged


def _slugify(text: str) -> str:
    t = (text or "").replace("Đ", "D").replace("đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return re.sub(r"-{2,}", "-", t)


def _normalize_slug(slug: str, fallback_title: str) -> str:
    base = _slugify(slug or "")
    if not base:
        base = _slugify(fallback_title or "")
    return base or "draft-post"


def _normalize_target_base_url(target_website: str) -> str:
    raw = (target_website or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    netloc = (parsed.netloc or "").strip().lower()
    if not netloc:
        return ""
    return f"{parsed.scheme or 'https'}://{netloc}"


def _build_slug_url(slug: str, fallback_title: str, target_website: str, primary_keyword: str) -> str:
    _ = _normalize_target_base_url(target_website)
    keyword = _slugify(primary_keyword or "") or _slugify(slug or "") or _slugify(fallback_title or "")
    return keyword or "draft-post"


def _random_seo_title(primary_keyword: str) -> str:
    return _suggest_title_from_keyword(primary_keyword)


def _is_probably_markdown(content: str) -> bool:
    if not content:
        return False
    if "<" in content and ">" in content:
        return False
    return bool(re.search(r"(^|\n)\s{0,3}(#|[-*]\s+|\d+\.\s+)", content))


def _markdown_to_html(md: str) -> str:
    lines = (md or "").splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            continue
        m_head = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if m_head:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            lvl = len(m_head.group(1))
            txt = html.escape(m_head.group(2).strip())
            out.append(f"<h{lvl}>{txt}</h{lvl}>")
            continue
        m_ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m_ul:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(m_ul.group(1).strip())}</li>")
            continue
        m_ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m_ol:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{html.escape(m_ol.group(1).strip())}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        out.append(f"<p>{html.escape(line.strip())}</p>")
    if in_ul:
        out.append("</ul>")
    if in_ol:
        out.append("</ol>")
    return "\n".join(out)


def _sanitize_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all("script"):
        t = str(tag.get("type") or "").strip().lower()
        if t != "application/ld+json":
            tag.decompose()
    for tag in soup.find_all(True):
        name = str(tag.name or "").lower()
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        allowed = _SAFE_ATTRS.get(name, set())
        attrs = dict(tag.attrs or {})
        for key in list(attrs.keys()):
            k = str(key).lower()
            if k.startswith("on"):
                del tag.attrs[key]
                continue
            if allowed and k not in allowed:
                del tag.attrs[key]
                continue
            val = attrs.get(key)
            if isinstance(val, list):
                val = " ".join(str(x) for x in val)
            v = str(val or "").strip()
            if k in {"href", "src"} and re.match(r"^\s*(javascript:|data:text/html)", v, flags=re.I):
                del tag.attrs[key]
    body = soup.body
    if body:
        cleaned = "".join(str(x) for x in body.contents).strip()
    else:
        cleaned = str(soup).strip()
    return cleaned


def _optimize_headings(content_html: str, title: str) -> str:
    soup = BeautifulSoup(content_html or "", "html.parser")
    h1s = soup.find_all("h1")
    if not h1s:
        new_h1 = soup.new_tag("h1")
        new_h1.string = title or "Untitled"
        if soup.contents:
            soup.insert(0, new_h1)
        else:
            soup.append(new_h1)
    else:
        for extra in h1s[1:]:
            extra.name = "h2"

    if soup.find("h3") and not soup.find("h2"):
        first_h3 = soup.find("h3")
        if first_h3:
            first_h3.name = "h2"
    return str(soup)


def _extract_text(content_html: str) -> str:
    soup = BeautifulSoup(content_html or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _fit_meta_len(src: str, *, min_len: int = 140, max_len: int = 160) -> str:
    """Trim or lightly extend meta to SERP-friendly 140–160 characters."""
    src = re.sub(r"\s+", " ", (src or "").strip())
    if not src:
        return ""
    if len(src) > max_len:
        cut = src[:max_len]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        src = cut.strip()
    if len(src) >= min_len:
        return src
    return src


def _make_meta_description(meta_description: str | None, content_html: str, title: str) -> str:
    src = (meta_description or "").strip()
    if not src:
        text = _extract_text(content_html)
        src = text or title
    src = re.sub(r"\s+", " ", src).strip()
    src = _fit_meta_len(src)
    if len(src) >= 140:
        return src
    extra = _extract_text(content_html)
    if extra and extra.lower() != src.lower():
        combined = re.sub(r"\s+", " ", f"{src} {extra}".strip())
        fitted = _fit_meta_len(combined)
        if len(fitted) >= 140:
            return fitted
    return src


def _clean_tags(tags: list[str] | None, title: str, content_html: str) -> list[str]:
    if tags:
        out: list[str] = []
        seen: set[str] = set()
        for t in tags:
            c = re.sub(r"\s+", " ", str(t or "").strip())
            if not c:
                continue
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out[:10]

    text = f"{title} {_extract_text(content_html)}".lower()
    words = re.findall(r"[a-z0-9]{3,}", _slugify(text).replace("-", " "))
    freq = Counter(w for w in words if w not in _STOPWORDS)
    candidates = [w for w, _ in freq.most_common(6)]
    return candidates or ["seo-content"]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        token = re.sub(r"\s+", " ", part.strip())
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def build_draft_payload(
    *,
    title: str,
    content: str,
    slug: str | None = None,
    tags: list[str] | None = None,
    meta_description: str | None = None,
    target_website: str | None = None,
    primary_keyword: str | None = None,
    secondary_keywords: list[str] | None = None,
    outline_content: str | None = None,
    featured_image: str | None = None,
    gallery_images: list[str] | None = None,
    scheduled_at: str | None = None,
    categories: list[int] | None = None,
) -> dict[str, Any]:
    t = _trim_title_len((title or "").strip()) or "Untitled Draft"
    raw = content or ""
    primary_kw = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    if not raw.strip() and outline_content:
        raw = outline_content
    html_content = _markdown_to_html(raw) if _is_probably_markdown(raw) else raw
    safe_html = _sanitize_html(html_content)
    optimized_html = _optimize_headings(safe_html, t)
    # Auto internal-link injection (uses SERP + sitemap heuristic; no DB required).
    # Keep it best-effort: if network fails or site has no sitemap, we just keep content as-is.
    try:
        optimized_html = _inject_related_internal_links(
            optimized_html,
            title=t,
            primary_keyword=primary_kw,
            target_website=target_website or "",
        )
    except Exception:
        pass
    out_slug = _build_slug_url(slug or "", t, target_website or "", primary_kw)
    meta_seed = meta_description
    if not meta_seed and primary_kw:
        meta_seed = f"{t} - Tu khoa chinh: {primary_kw}"
    out_meta = _make_meta_description(meta_seed, optimized_html, t)
    out_tags = _clean_tags(tags, t, optimized_html)
    for kw in secondary_keywords or []:
        kw_clean = re.sub(r"\s+", " ", str(kw or "").strip())
        if kw_clean and kw_clean.lower() not in {x.lower() for x in out_tags}:
            out_tags.append(kw_clean)
        if len(out_tags) >= 10:
            break
    if primary_kw and primary_kw.lower() not in {x.lower() for x in out_tags}:
        out_tags.insert(0, primary_kw)
    out_tags = out_tags[:10]
    cat_ids: list[int] = []
    for x in categories or []:
        try:
            cid = int(x)
        except (TypeError, ValueError):
            continue
        if cid > 0 and cid not in cat_ids:
            cat_ids.append(cid)
        if len(cat_ids) >= 20:
            break
    out: dict[str, Any] = {
        "title": t,
        "slug": out_slug,
        "content": optimized_html,
        "meta_description": out_meta,
        "tags": out_tags,
        "featured_image": (featured_image or "").strip(),
        "gallery_images": [str(x).strip() for x in (gallery_images or []) if str(x).strip()],
        "scheduled_at": (scheduled_at or "").strip(),
    }
    if cat_ids:
        out["categories"] = cat_ids
    return out


def suggest_content_ai_field(
    *,
    field: str,
    title: str = "",
    content: str = "",
    target_website: str = "",
    slug: str = "",
    tags: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
) -> str:
    """
    Lớp điều khiển (rule-based): gợi ý title, meta, outline, slug, tags, keyword…

    Không sinh HTML body article tại đây. Nội dung body: LLM (`generate_content_ai_suggestion`)
    hoặc `content_ai_normalize_pasted_body` khi field == \"content\".
    """
    f = (field or "").strip().lower()
    t = re.sub(r"\s+", " ", title.strip())
    pk = re.sub(r"\s+", " ", primary_keyword.strip())
    sec = _split_csv(secondary_keywords)
    sec_top = sec[:4]

    if f == "title":
        if not pk:
            return ""
        kw = re.split(r"\s*[|]\s*", re.sub(r"\s+", " ", pk.strip()), maxsplit=1)[0].strip()
        base = _random_seo_title(kw)
        base = _ensure_keyword_once_at_start(base, kw)
        return _trim_title_len(base)

    if f == "target_website":
        if target_website.strip():
            return target_website.strip()
        return "https://example.com"

    if f == "primary_keyword":
        if pk:
            return pk
        source = t or _extract_text(content)[:80]
        words = re.findall(r"[a-z0-9]{3,}", _slugify(source).replace("-", " "))
        guess = " ".join(words[:3]).strip()
        return guess or "seo onpage"

    if f == "secondary_keywords":
        if not pk:
            return ""
        variants = _build_secondary_keyword_suggestions(pk, sec_top)
        return ", ".join(variants[:5])

    if f == "outline_content":
        if not pk:
            return ""
        try:
            from app.services.content_ai_knowledge_context import (
                build_outline_from_knowledge_rule,
                get_relevant_knowledge_for_keyword,
            )

            kb = get_relevant_knowledge_for_keyword(pk, target_website=target_website or "")
            if kb.get("found"):
                kb_outline = build_outline_from_knowledge_rule(kb, title=t or pk)
                if kb_outline.strip():
                    return kb_outline
        except Exception:
            pass
        topic = pk
        sec_keywords = sec_top or [f"{topic} là gì", f"cách triển khai {topic}"]
        dl = _extract_district_label(topic)
        detected_intent = _detect_search_intent(topic)
        if detected_intent == "transactional":
            area = dl or "khu vực bạn cần hỗ trợ"
            return "\n".join(
                [
                    f"<h1>{t or topic}</h1>",
                    f"<h2>Dịch vụ {topic} phù hợp khi nào?</h2>",
                    "<h3>Triệu chứng/tình huống nên gọi ngay</h3>",
                    "<h3>Những gì khách cần chuẩn bị trước khi đặt lịch</h3>",
                    f"<h2>Quy trình tiếp nhận và xử lý tại {area}</h2>",
                    "<h3>Tiếp nhận thông tin và xác nhận lịch</h3>",
                    "<h3>Kiểm tra tại chỗ và đề xuất phương án</h3>",
                    "<h2>Bảng giá tham khảo, bảo hành và cam kết</h2>",
                    "<h2>Câu hỏi thường gặp + kêu gọi đặt lịch</h2>",
                ]
            )
        if _is_service_keyword(topic) and _is_pc_repair_topic(topic):
            dl2 = dl or "khu vực"
            return "\n".join(
                [
                    f"<h1>{t or topic}</h1>",
                    f"<h2>Triệu chứng thường gặp khi bạn cần {topic}</h2>",
                    "<h3>Máy chậm, treo, không lên nguồn</h3>",
                    "<h3>Dữ liệu &amp; sao lưu trước khi gọi thợ</h3>",
                    f"<h2>Lịch hẹn &amp; quy trình làm việc tại {dl2}</h2>",
                    f"<h3>Chuẩn bị tại nhà ({dl2})</h3>",
                    "<h3>Kiểm tra ban đầu &amp; báo hướng xử lý</h3>",
                    "<h2>Chi phí, bảo hành và điều nên hỏi trước</h2>",
                    "<h2>Câu hỏi thường gặp</h2>",
                ]
            )
        # Return HTML heading tags (user-friendly for copy/paste into editors)
        return "\n".join(
            [
                f"<h1>{t or topic}</h1>",
                f"<h2>{topic} là gì?</h2>",
                "<h3>Định nghĩa nhanh</h3>",
                "<h3>Khi nào nên áp dụng</h3>",
                "<h2>Quy trình triển khai</h2>",
                f"<h3>Bước 1: Nghiên cứu {sec_keywords[0]}</h3>",
                f"<h3>Bước 2: Tối ưu nội dung theo {sec_keywords[-1]}</h3>",
                "<h2>Lỗi thường gặp và cách khắc phục</h2>",
                "<h2>Checklist hành động</h2>",
            ]
        )

    if f == "slug":
        return _build_slug_url(
            slug=slug or "",
            fallback_title=t or pk or "draft-post",
            target_website=target_website or "",
            primary_keyword=pk or "",
        )

    if f == "meta_description":
        if not pk:
            return ""
        kw = pk
        intent = _classify_intent(kw)
        if intent == "howto":
            base = (
                f"Hướng dẫn {kw}: nguyên nhân thường gặp, cách kiểm tra và các bước khắc phục nhanh tại nhà. "
                f"Mẹo đơn giản, dễ làm, tiết kiệm thời gian."
            )
        elif intent == "service":
            mode = _service_mode(kw)
            if mode == "onsite":
                base = (
                    f"{kw} nhanh chóng: kỹ thuật viên hỗ trợ tận nơi, thao tác an toàn và gọn. "
                    f"Báo giá rõ ràng trước khi làm, có hướng dẫn sử dụng sau khi hoàn tất."
                )
            else:
                # online / generic service: avoid "tận nơi", focus on remote workflow & deliverables
                base = (
                    f"{kw}: tư vấn online, triển khai theo quy trình rõ ràng (brief → thiết kế → bàn giao). "
                    f"Báo giá minh bạch, tối ưu SEO/cấu trúc, hỗ trợ chỉnh sửa sau bàn giao."
                )
        elif intent == "training":
            base = (
                f"Khóa học {kw} uy tín, chuyên nghiệp. "
                f"Giúp bạn nắm vững quy trình, thực hành bài bản và áp dụng hiệu quả."
            )
        else:
            base = f"{kw}: tổng hợp kiến thức cốt lõi, hướng dẫn thực hành và checklist để áp dụng nhanh, tránh sai lầm thường gặp."
        base = _ensure_contains_keyword(base, kw)
        # keep keyword once (roughly)
        base = re.sub(r"\s+", " ", base).strip()
        # 150–160 chars target (approx)
        return _make_meta_description(base, "", kw)

    if f == "tags":
        if not pk:
            return ""
        if tags.strip():
            return ", ".join(_split_csv(tags)[:8])
        candidate = []
        candidate.append(pk)
        candidate.extend(sec_top)
        return ", ".join(candidate[:8])

    if f == "content":
        return content_ai_normalize_pasted_body(primary_keyword=pk, title=t, content=content)
    return ""

