"""
Content Score 0–100 cho Content AI — rule-based, read-only (không sửa HTML).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.content_draft_builder import detect_search_intent

_KW_TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.I)
_FAQ_HEADING_RE = re.compile(
    r"faq|câu\s*hỏi|hỏi\s*đáp|questions?\s*and\s*answers|thường\s*gặp",
    re.I,
)
_CTA_RE = re.compile(
    r"liên hệ|đặt lịch|gọi ngay|đăng ký|đặt mua|báo giá|tư vấn|hotline|zalo|"
    r"nhận tư vấn|đặt hàng|mua ngay|đăng ký ngay|contact us",
    re.I,
)
_GENERIC_ALT_RE = re.compile(r"^(image|img|ảnh|photo|hình|picture|pic)$", re.I)
_INTERNAL_HINT_RE = re.compile(r"<!--\s*internal\s*:", re.I)

_CATEGORY_WEIGHTS: dict[str, float] = {
    "search_intent": 8.0,
    "title_meta_slug": 12.0,
    "heading_structure": 12.0,
    "keyword_semantic": 12.0,
    "content_depth": 15.0,
    "eeat_helpful": 10.0,
    "internal_link": 10.0,
    "image_alt": 8.0,
    "readability": 8.0,
    "cta": 5.0,
}


def _tokens(s: str) -> list[str]:
    return [t for t in _KW_TOKEN_RE.findall((s or "").lower()) if len(t) > 2]


def _kw_in_text(text: str, kw: str) -> bool:
    k = (kw or "").strip().lower()
    if not k:
        return True
    t = (text or "").lower()
    if k in t:
        return True
    parts = _tokens(kw)
    if len(parts) >= 2:
        return all(p in t for p in parts[: min(4, len(parts))])
    return any(p in t for p in parts[:3]) if parts else False


def _grade_from_score(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _parse_html_safe(html: str) -> BeautifulSoup:
    raw = str(html or "").strip()
    if not raw:
        return BeautifulSoup("", "html.parser")
    try:
        return BeautifulSoup(raw[:800_000], "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")


def _word_count(soup: BeautifulSoup) -> int:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    words = re.findall(r"[\wà-ỹ]+", soup.get_text(" ", strip=True), re.I)
    return len(words)


def _avg_sentence_words(text: str) -> float:
    parts = re.split(r"[.!?…]+", text)
    lens = [len(re.findall(r"[\wà-ỹ]+", p, re.I)) for p in parts if p.strip()]
    if not lens:
        return 0.0
    return sum(lens) / len(lens)


def _category_result(
    *,
    score: int,
    passed: list[str],
    warnings: list[str],
    missing: list[str],
    suggestions: list[str],
) -> dict[str, Any]:
    score = max(0, min(100, int(score)))
    if score >= 75:
        status = "ok"
    elif score >= 50:
        status = "warn"
    else:
        status = "fail"
    return {
        "score": score,
        "status": status,
        "passed": passed,
        "warnings": warnings,
        "missing": missing,
        "suggestions": suggestions,
    }


def _score_search_intent(*, primary_keyword: str, title: str, meta: str) -> dict[str, Any]:
    pk = (primary_keyword or "").strip()
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    if not pk:
        return _category_result(
            score=25,
            passed=passed,
            warnings=warnings,
            missing=["Chưa có từ khóa chính để xác định search intent."],
            suggestions=["Nhập từ khóa chính phản ánh đúng ý người tìm kiếm."],
        )
    intent = detect_search_intent(pk)
    passed.append(f"Search intent ước lượng: {intent}.")
    score = 70
    blob = f"{title} {meta} {pk}".lower()
    if intent == "transactional" and any(x in blob for x in ("dịch vụ", "báo giá", "mua", "đặt", "giá")):
        score += 20
        passed.append("Tiêu đề/meta phù hợp intent giao dịch.")
    elif intent == "informational" and any(x in blob for x in ("là gì", "cách", "hướng dẫn", "guide", "mẹo")):
        score += 20
        passed.append("Tiêu đề/meta phù hợp intent tìm hiểu.")
    elif intent == "commercial investigation":
        score += 15
        passed.append("Intent thương mại — nên có so sánh/lợi ích rõ.")
    else:
        warnings.append("Intent và góc tiêu đề/meta có thể chưa khớp hoàn toàn.")
        suggestions.append(f"Căn title/meta theo intent «{intent}».")
        score += 5
    return _category_result(score=score, passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_title_meta_slug(
    *,
    primary_keyword: str,
    title: str,
    meta: str,
    slug: str,
) -> dict[str, Any]:
    pk = (primary_keyword or "").strip()
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    score = 0
    t = (title or "").strip()
    m = (meta or "").strip()
    s = (slug or "").strip().strip("/")

    if t:
        score += 25
        passed.append("Có tiêu đề bài viết.")
        if 30 <= len(t) <= 60:
            score += 15
            passed.append("Độ dài title trong khoảng SEO (~30–60 ký tự).")
        elif len(t) < 20:
            warnings.append("Title hơi ngắn.")
            suggestions.append("Mở rộng title đến ~48–58 ký tự, có lợi ích rõ.")
        elif len(t) > 65:
            warnings.append("Title có thể bị cắt trên SERP.")
            suggestions.append("Rút title xuống dưới ~60 ký tự.")
        else:
            score += 8
    else:
        missing.append("Thiếu tiêu đề (title).")

    if m:
        score += 20
        passed.append("Có meta description.")
        if 120 <= len(m) <= 165:
            score += 15
            passed.append("Meta description ~140–160 ký tự.")
        elif len(m) < 100:
            warnings.append("Meta description ngắn.")
            suggestions.append("Viết meta 140–160 ký tự, có CTA nhẹ.")
        elif len(m) > 170:
            warnings.append("Meta description dài — có thể bị cắt.")
        else:
            score += 8
    else:
        missing.append("Thiếu meta description.")

    if s:
        score += 15
        passed.append("Có slug URL.")
        if pk and _tokens(pk)[0][:12] in s.replace("-", " "):
            score += 10
            passed.append("Slug gợi ý liên quan từ khóa.")
    else:
        warnings.append("Chưa có slug — nên tạo slug ngắn, có từ khóa.")

    if pk:
        if t and _kw_in_text(t, pk):
            score += 10
            passed.append("Từ khóa chính có trong title.")
        else:
            missing.append("Từ khóa chính chưa có trong title.")
            suggestions.append("Đưa từ khóa chính lên đầu title.")
        if m and _kw_in_text(m, pk):
            score += 5
            passed.append("Từ khóa chính có trong meta.")
        else:
            warnings.append("Meta chưa chứa từ khóa chính.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_heading_structure(soup: BeautifulSoup) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")
    score = 0
    if len(h1s) == 1:
        score += 35
        passed.append("Đúng một thẻ H1.")
    elif not h1s:
        missing.append("Thiếu H1 duy nhất.")
        suggestions.append("Thêm một H1 chứa từ khóa chính.")
    else:
        warnings.append(f"Có {len(h1s)} thẻ H1 — nên chỉ giữ một.")
        score += 15
    n_h2 = len(h2s)
    if n_h2 >= 4:
        score += 35
        passed.append(f"Có {n_h2} mục H2 — cấu trúc rõ.")
    elif n_h2 >= 2:
        score += 22
        warnings.append(f"Chỉ có {n_h2} H2 — nên thêm mục nội dung.")
        suggestions.append("Bổ sung thêm 2–4 H2 theo dàn ý.")
    else:
        missing.append("Thiếu H2 (cần ≥2).")
        suggestions.append("Chia bài thành các mục H2 logic.")
    if h3s:
        score += 15
        passed.append(f"Có {len(h3s)} H3 hỗ trợ phân cấp.")
    else:
        warnings.append("Chưa có H3 — nên thêm chi tiết dưới H2.")
        score += 5
    if h2s and any(_FAQ_HEADING_RE.search(h.get_text(" ", strip=True)) for h in h2s):
        score += 10
        passed.append("Có section FAQ (H2).")
    else:
        warnings.append("Chưa thấy mục FAQ.")
        suggestions.append("Thêm H2 «Câu hỏi thường gặp» với 3–5 câu hỏi.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_keyword_semantic(
    *,
    soup: BeautifulSoup,
    primary_keyword: str,
    secondary_keywords: str,
    body_text: str,
) -> dict[str, Any]:
    pk = (primary_keyword or "").strip()
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    score = 0
    if not pk:
        return _category_result(
            score=20,
            passed=passed,
            warnings=warnings,
            missing=["Thiếu từ khóa chính."],
            suggestions=["Nhập từ khóa chính trước khi chấm điểm."],
        )
    low = body_text.lower()
    if _kw_in_text(body_text, pk):
        score += 35
        passed.append("Từ khóa chính xuất hiện trong nội dung.")
        idx = low.find(pk.lower().split()[0] if pk else "")
        first_120 = " ".join(re.findall(r"[\wà-ỹ]+", body_text[:800], re.I)[:120])
        if _kw_in_text(first_120, pk):
            score += 15
            passed.append("Từ khóa có trong ~100 từ đầu.")
        else:
            warnings.append("Từ khóa chưa nằm sớm trong bài.")
            suggestions.append("Đưa từ khóa chính vào đoạn mở bài.")
    else:
        missing.append("Từ khóa chính không thấy trong thân bài.")
    sec_hits = 0
    for part in re.split(r"[,;|\n]+", secondary_keywords or ""):
        ph = part.strip()
        if len(ph) < 3:
            continue
        if _kw_in_text(body_text, ph):
            sec_hits += 1
    if sec_hits >= 2:
        score += 25
        passed.append(f"Có {sec_hits} từ khóa phụ/semantic trong bài.")
    elif sec_hits == 1:
        score += 12
        warnings.append("Mới có 1 từ khóa phụ — nên rải thêm LSI.")
    else:
        warnings.append("Từ khóa phụ chưa xuất hiện trong bài.")
        suggestions.append("Rải 3–5 cụm từ khóa phụ tự nhiên.")
    exact = len(re.findall(re.escape(pk.lower()), low)) if pk else 0
    wc = max(_word_count(soup), 1)
    density = (exact / wc) * 100
    if exact == 0:
        pass
    elif density > 4.0 or exact > max(12, wc // 70):
        warnings.append(f"Có thể nhồi từ khóa ({exact} lần, ~{density:.1f}%).")
        suggestions.append("Giảm lặp từ khóa chính, dùng biến thể.")
        score = max(0, score - 15)
    elif density <= 2.5:
        score += 15
        passed.append("Mật độ từ khóa ổn.")
    else:
        score += 8
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_content_depth(
    *,
    soup: BeautifulSoup,
    word_n: int,
    target_word_count: int | None,
) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    target = 1000
    if target_word_count is not None:
        try:
            target = max(200, min(int(target_word_count), 20000))
        except (TypeError, ValueError):
            target = 1000
    score = 0
    if word_n < 150:
        missing.append(f"Nội dung quá ngắn (~{word_n} từ).")
        suggestions.append(f"Mở rộng bài đến ~{target} từ.")
        return _category_result(score=15, passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)
    ratio = word_n / target if target else 1
    if ratio >= 0.85:
        score += 45
        passed.append(f"Độ dài ~{word_n} từ (mục tiêu ~{target}).")
    elif ratio >= 0.55:
        score += 28
        warnings.append(f"~{word_n} từ — thấp hơn mục tiêu ~{target}.")
        suggestions.append(f"Thêm 2–3 section để đạt ~{target} từ.")
    else:
        score += 12
        missing.append(f"Thiếu độ sâu nội dung so với mục tiêu ({word_n}/{target} từ).")
    if soup.find_all(["ul", "ol"]):
        score += 15
        passed.append("Có danh sách (ul/ol).")
    else:
        warnings.append("Chưa có bullet/list.")
        suggestions.append("Thêm checklist hoặc danh sách bước.")
    if soup.find("table"):
        score += 15
        passed.append("Có bảng (table).")
    else:
        warnings.append("Chưa có bảng so sánh/tóm tắt.")
        suggestions.append("Thêm bảng khi phù hợp chủ đề.")
    paras = [p for p in soup.find_all("p") if len(p.get_text(" ", strip=True)) > 40]
    if len(paras) >= 6:
        score += 15
        passed.append(f"Có {len(paras)} đoạn văn đủ dài.")
    elif len(paras) >= 3:
        score += 8
    else:
        warnings.append("Ít đoạn văn — bài có thể thiếu chi tiết.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_eeat_helpful(body_text: str, soup: BeautifulSoup) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    low = body_text.lower()
    score = 40
    signals = [
        ("ví dụ", "Có ví dụ minh họa."),
        ("kinh nghiệm", "Có góc kinh nghiệm thực tế."),
        ("theo", "Có tham chiếu/nguồn."),
        ("bước", "Có hướng dẫn từng bước."),
        ("lưu ý", "Có lưu ý quan trọng."),
    ]
    hit = 0
    for kw, msg in signals:
        if kw in low:
            hit += 1
            passed.append(msg)
    score += min(35, hit * 8)
    if re.search(r"\d+%|\d+\s*(năm|tháng|ngày|giờ|triệu|nghìn)", low):
        score += 10
        passed.append("Có số liệu cụ thể (cần kiểm tra độ chính xác).")
    else:
        warnings.append("Ít số liệu/case cụ thể.")
    if soup.find_all("blockquote"):
        score += 10
        passed.append("Có trích dẫn/blockquote.")
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        raw = script.string or script.get_text() or ""
        if raw.strip():
            try:
                data = json.loads(raw)
                types: set[str] = set()
                if isinstance(data, dict):
                    types.add(str(data.get("@type", "")).lower())
                    for g in data.get("@graph") or []:
                        if isinstance(g, dict):
                            types.add(str(g.get("@type", "")).lower())
                if types & {"article", "blogposting", "faqpage"}:
                    score += 15
                    passed.append("Có schema JSON-LD (Article/FAQ).")
                    break
            except Exception:
                pass
    else:
        warnings.append("Chưa có JSON-LD Article/FAQ.")
        suggestions.append("Thêm schema Article + FAQPage cuối bài.")
    if hit < 2:
        suggestions.append("Bổ sung ví dụ thực tế, quy trình, hoặc số liệu có nguồn.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _count_internal_external(soup: BeautifulSoup, target_website: str) -> tuple[int, int, int]:
    internal = 0
    external = 0
    base_host = ""
    if target_website:
        try:
            p = urlparse(
                target_website if "://" in target_website else f"https://{target_website.lstrip('/')}"
            )
            base_host = (p.netloc or "").lower().replace("www.", "")
        except Exception:
            base_host = ""
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("/"):
            internal += 1
            continue
        try:
            pu = urlparse(href if "://" in href else f"https://{href}")
            if pu.scheme not in {"http", "https"}:
                continue
            host = (pu.netloc or "").lower().replace("www.", "")
            if base_host and host == base_host:
                internal += 1
            elif host:
                external += 1
        except Exception:
            continue
    if _INTERNAL_HINT_RE.search(str(soup)):
        internal = max(internal, 1)
    return internal, external, len(soup.find_all("a", href=True))


def _score_internal_link(
    *,
    soup: BeautifulSoup,
    target_website: str,
    internal_links: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    internal, external, total_a = _count_internal_external(soup, target_website)
    planned = len(internal_links or [])
    score = 0
    if internal >= 2:
        score += 50
        passed.append(f"Có {internal} internal link trong HTML.")
    elif internal == 1:
        score += 32
        warnings.append("Chỉ có 1 internal link — nên thêm 1–2 link ngữ cảnh.")
        suggestions.append("Dùng «Tìm bài liên quan» và chèn thêm link.")
    elif planned >= 1:
        score += 25
        warnings.append(f"Đã chọn {planned} link kế hoạch nhưng chưa thấy trong HTML.")
        suggestions.append("Bấm «Đi link» để chèn anchor vào bài.")
    else:
        missing.append("Chưa có internal link trong bài.")
        suggestions.append("Thêm 2–4 internal link tới bài/dịch vụ liên quan.")
    if external >= 1:
        score += 25
        passed.append(f"Có {external} external link.")
    else:
        warnings.append("Chưa có external link uy tín.")
        suggestions.append("Thêm 1 link Wikipedia/Google doc khi phù hợp.")
    if total_a > 0:
        bad_anchors = 0
        for a in soup.find_all("a", href=True):
            txt = a.get_text(" ", strip=True).lower()
            if txt in {"xem thêm", "tại đây", "click vào đây", "đọc tiếp", "link này"}:
                bad_anchors += 1
        if bad_anchors:
            warnings.append(f"Có {bad_anchors} anchor chung chung (xem thêm/tại đây).")
            score = max(0, score - 10)
        else:
            score += 15
            passed.append("Anchor text không dùng cụm chung chung.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_image_alt(soup: BeautifulSoup) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    imgs = soup.find_all("img")
    if not imgs:
        return _category_result(
            score=35,
            passed=passed,
            warnings=["Chưa có ảnh minh họa."],
            missing=[],
            suggestions=["Thêm figure/ảnh dưới mỗi H2 với alt mô tả."],
        )
    good = 0
    bad = 0
    for img in imgs:
        alt = str(img.get("alt") or "").strip()
        if len(alt) >= 8 and not _GENERIC_ALT_RE.match(alt):
            good += 1
        else:
            bad += 1
    score = int((good / max(len(imgs), 1)) * 100)
    passed.append(f"{good}/{len(imgs)} ảnh có alt mô tả tốt.")
    if bad:
        warnings.append(f"{bad} ảnh thiếu alt hoặc alt chung chung.")
        suggestions.append("Viết alt 8–12 từ, có từ khóa/biến thể tự nhiên.")
    h2_n = len(soup.find_all("h2"))
    if h2_n and good < h2_n:
        warnings.append("Số ảnh ít hơn số mục H2.")
        suggestions.append("Mỗi H2 nên có ít nhất một ảnh minh họa.")
    return _category_result(score=score, passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_readability(body_text: str, word_n: int) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    if word_n < 50:
        return _category_result(
            score=20,
            passed=passed,
            warnings=warnings,
            missing=["Không đủ văn bản để đánh giá readability."],
            suggestions=["Viết thêm nội dung trước khi chấm."],
        )
    avg = _avg_sentence_words(body_text)
    score = 55
    if 12 <= avg <= 28:
        score += 30
        passed.append(f"Độ dài câu trung bình ~{avg:.0f} từ — dễ đọc.")
    elif avg > 35:
        warnings.append(f"Câu dài trung bình ~{avg:.0f} từ — nên chia nhỏ.")
        suggestions.append("Tách câu dài thành 2–3 câu ngắn.")
        score += 10
    elif avg < 8:
        warnings.append("Câu quá ngắn, có thể rời rạc.")
        score += 15
    long_paras = len(re.findall(r"\n\n+", body_text))  # rough
    if word_n > 400:
        score += 15
        passed.append("Bài đủ dài để đánh giá nhịp đọc.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def _score_cta(body_text: str, soup: BeautifulSoup) -> dict[str, Any]:
    passed: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    suggestions: list[str] = []
    low = body_text.lower()
    tail = low[-1200:] if len(low) > 1200 else low
    score = 30
    if _CTA_RE.search(tail):
        score += 45
        passed.append("Có lời kêu gọi hành động (CTA) gần cuối bài.")
    elif _CTA_RE.search(low):
        score += 30
        warnings.append("Có CTA nhưng chưa rõ ở đoạn kết.")
        suggestions.append("Thêm CTA rõ ở cuối bài (liên hệ/đăng ký/báo giá).")
    else:
        missing.append("Chưa thấy CTA (liên hệ, đăng ký, báo giá…).")
        suggestions.append("Kết bài bằng 1 đoạn CTA phù hợp search intent.")
    if soup.find_all("a", href=True):
        score += 15
        passed.append("Có link hỗ trợ chuyển đổi.")
    return _category_result(score=min(100, score), passed=passed, warnings=warnings, missing=missing, suggestions=suggestions)


def evaluate_content_score(
    *,
    title: str = "",
    slug: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    html_content: str = "",
    target_word_count: int | None = None,
    target_website: str = "",
    internal_links: list[dict[str, Any]] | None = None,
    use_llm_enhancement: bool = False,
) -> dict[str, Any]:
    """
    Chấm điểm SEO read-only. ``use_llm_enhancement`` reserved — hiện chỉ rule-based.
    """
    _ = use_llm_enhancement
    raw_html = str(html_content or "").strip()
    if not raw_html:
        missing = [
            "Chưa có nội dung HTML — không thể chấm điểm đầy đủ.",
            "Thêm nội dung hoặc bấm «Tạo content» trước.",
        ]
        empty_details = {
            k: {"score": 0, "status": "fail", "notes": "Thiếu HTML"}
            for k in _CATEGORY_WEIGHTS
        }
        return {
            "total_score": 8,
            "grade": "F",
            "passed_items": [],
            "warning_items": [],
            "missing_items": missing,
            "suggestions": [
                "Viết hoặc dán nội dung vào editor.",
                "Nhập từ khóa chính, title và meta.",
            ],
            "detail_scores": empty_details,
            "word_count": 0,
            "scoring_mode": "rule_based",
        }

    soup = _parse_html_safe(raw_html)
    body_text = soup.get_text(" ", strip=True)
    word_n = _word_count(BeautifulSoup(str(soup), "html.parser"))

    calculators = {
        "search_intent": lambda: _score_search_intent(
            primary_keyword=primary_keyword, title=title, meta=meta_description
        ),
        "title_meta_slug": lambda: _score_title_meta_slug(
            primary_keyword=primary_keyword,
            title=title,
            meta=meta_description,
            slug=slug,
        ),
        "heading_structure": lambda: _score_heading_structure(soup),
        "keyword_semantic": lambda: _score_keyword_semantic(
            soup=soup,
            primary_keyword=primary_keyword,
            secondary_keywords=secondary_keywords,
            body_text=body_text,
        ),
        "content_depth": lambda: _score_content_depth(
            soup=soup, word_n=word_n, target_word_count=target_word_count
        ),
        "eeat_helpful": lambda: _score_eeat_helpful(body_text, soup),
        "internal_link": lambda: _score_internal_link(
            soup=soup,
            target_website=target_website,
            internal_links=internal_links,
        ),
        "image_alt": lambda: _score_image_alt(soup),
        "readability": lambda: _score_readability(body_text, word_n),
        "cta": lambda: _score_cta(body_text, soup),
    }

    detail_scores: dict[str, Any] = {}
    passed_items: list[str] = []
    warning_items: list[str] = []
    missing_items: list[str] = []
    suggestions: list[str] = []
    weighted = 0.0

    for key, weight in _CATEGORY_WEIGHTS.items():
        cat = calculators[key]()
        detail_scores[key] = {
            "score": cat["score"],
            "status": cat["status"],
            "weight": weight,
            "passed": cat["passed"],
            "warnings": cat["warnings"],
            "missing": cat["missing"],
            "suggestions": cat["suggestions"],
        }
        weighted += cat["score"] * (weight / 100.0)
        for p in cat["passed"]:
            passed_items.append(f"[{key}] {p}")
        for w in cat["warnings"]:
            warning_items.append(f"[{key}] {w}")
        for m in cat["missing"]:
            missing_items.append(f"[{key}] {m}")
        for s in cat["suggestions"]:
            if s not in suggestions:
                suggestions.append(s)

    total_score = int(round(weighted))
    total_score = max(0, min(100, total_score))

    return {
        "total_score": total_score,
        "grade": _grade_from_score(total_score),
        "passed_items": passed_items[:40],
        "warning_items": warning_items[:30],
        "missing_items": missing_items[:25],
        "suggestions": suggestions[:20],
        "detail_scores": detail_scores,
        "word_count": word_n,
        "scoring_mode": "rule_based",
    }
