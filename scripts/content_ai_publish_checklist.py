"""
Checklist / SEO Score 100 điểm — 30 yếu tố trong 10 nhóm.
Chạy heuristic trên server; không nhúng vào HTML bài.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

_CHECKLIST_SECTION_RE = re.compile(
    r"checklist\s*seo|checklist\s*trước\s*khi\s*publish|kiểm\s*tra\s*trước\s*khi\s*publish",
    re.I,
)
_KW_TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.I)
_INTERNAL_HINT_RE = re.compile(r"<!--\s*internal\s*:", re.I)
_GENERIC_ALT_RE = re.compile(r"^(image|img|ảnh|photo|hình|picture|pic)$", re.I)
_EEAT_RE = re.compile(
    r"\b(kinh nghiệm|thực tế|chuyên gia|uy tín|cam kết|bảo hành|chứng nhận|"
    r"đã kiểm tra|case study|thực tế|đội ngũ|năm kinh nghiệm)\b",
    re.I,
)


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


def strip_publish_checklist_from_html(html: str) -> str:
    """Gỡ section Checklist SEO khỏi body bài (LLM đôi khi vẫn sinh ra)."""
    raw = str(html or "").strip()
    if not raw:
        return raw
    try:
        soup = BeautifulSoup(raw[:800_000], "html.parser")
    except Exception:
        return raw
    removed = False
    for h2 in list(soup.find_all("h2")):
        label = h2.get_text(" ", strip=True)
        if not _CHECKLIST_SECTION_RE.search(label):
            continue
        node = h2
        while node is not None:
            nxt = node.next_sibling
            try:
                node.decompose()
                removed = True
            except Exception:
                pass
            if nxt is None:
                break
            if getattr(nxt, "name", None) in ("h1", "h2"):
                break
            node = nxt
    if not removed:
        return raw
    out = str(soup).strip()
    return out or raw


def _factor_score(status: str, max_score: int) -> float:
    if status == "passed":
        return float(max_score)
    if status == "warning":
        return round(max_score * 0.5, 1)
    return 0.0


def _make_factor(
    factor_id: str,
    label: str,
    max_score: int,
    status: str,
    message: str,
    suggestion: str,
) -> dict[str, Any]:
    labels = {
        "passed": "Đạt",
        "warning": "Cần tối ưu",
        "failed": "Không đạt",
    }
    legacy = {"passed": "ok", "warning": "warn", "failed": "fail"}
    st = status if status in labels else "warning"
    return {
        "id": factor_id,
        "label": label,
        "score": _factor_score(st, max_score),
        "max_score": max_score,
        "status": st,
        "status_label": labels[st],
        "message": message[:400],
        "suggestion": suggestion[:400],
        "_legacy_status": legacy[st],
    }


def _make_group(group_id: str, label: str, factors: list[dict[str, Any]]) -> dict[str, Any]:
    max_score = sum(int(f.get("max_score") or 0) for f in factors)
    score = round(sum(float(f.get("score") or 0) for f in factors), 1)
    return {
        "id": group_id,
        "label": label,
        "max_score": max_score,
        "score": score,
        "factors": factors,
    }


def _grade_from_score(score: float) -> tuple[str, str]:
    if score >= 90:
        return "excellent", "Xuất sắc"
    if score >= 75:
        return "good", "Tốt"
    if score >= 60:
        return "needs_work", "Cần tối ưu"
    return "not_ready", "Không nên publish"


def _expected_blockquotes(word_n: int) -> int:
    if word_n < 800:
        return 0
    if word_n < 1200:
        return 1
    if word_n <= 2000:
        return 2
    return 3


def _legacy_item(factor: dict[str, Any]) -> dict[str, str]:
    detail = factor.get("message") or ""
    sug = factor.get("suggestion") or ""
    if sug and sug not in detail:
        detail = f"{detail} {sug}".strip()
    return {
        "id": str(factor.get("id") or ""),
        "label": str(factor.get("label") or ""),
        "status": str(factor.get("_legacy_status") or "warn"),
        "detail": detail[:400],
    }


def evaluate_publish_checklist(
    *,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """30 yếu tố / 10 nhóm — tổng 100 điểm."""
    pk = (primary_keyword or "").strip()
    title_s = (title or "").strip()
    meta_s = (meta_description or "").strip()
    slug_s = (slug or "").strip().lower()
    sec_kws = [str(x).strip() for x in (secondary_keywords or []) if str(x).strip()]

    from app.services.content_table_format import enhance_tables_in_html

    html = enhance_tables_in_html(strip_publish_checklist_from_html(content_html or ""))

    try:
        soup = BeautifulSoup(html[:800_000], "html.parser")
    except Exception:
        soup = BeautifulSoup("", "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body_text = soup.get_text(" ", strip=True)
    words = re.findall(r"[\wà-ỹ]+", body_text, re.I)
    word_n = len(words)
    intro_text = body_text[:600]

    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")
    imgs = soup.find_all("img")
    blockquotes = soup.find_all("blockquote")
    bq_n = len(blockquotes)
    lists = soup.find_all(["ul", "ol"])
    paras = soup.find_all("p")

    internal_n = 0
    external_n = 0
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("/") or "internal" in href.lower():
            internal_n += 1
            continue
        try:
            p = urlparse(href)
            if p.scheme in ("http", "https"):
                external_n += 1
        except Exception:
            pass
    if _INTERNAL_HINT_RE.search(html):
        internal_n = max(internal_n, 1)

    # --- 1. Search Intent (10) ---
    if not pk:
        f_intent_title = _make_factor(
            "intent_title_match", "Tiêu đề phản ánh intent", 3, "warning",
            "Chưa có từ khóa chính để đối chiếu intent.", "Nhập từ khóa chính ở bước Brief.",
        )
    elif _kw_in_text(title_s, pk):
        f_intent_title = _make_factor(
            "intent_title_match", "Tiêu đề phản ánh intent", 3, "passed",
            "Tiêu đề chứa từ khóa / cụm tương đương.", "Giữ tiêu đề tự nhiên, không nhồi từ khóa.",
        )
    else:
        f_intent_title = _make_factor(
            "intent_title_match", "Tiêu đề phản ánh intent", 3, "failed",
            "Tiêu đề chưa thể hiện rõ intent từ khóa.", f"Thêm «{pk}» hoặc biến thể vào tiêu đề.",
        )

    h1_text = h1s[0].get_text(" ", strip=True) if h1s else (h2s[0].get_text(" ", strip=True) if h2s else title_s)
    if not pk:
        f_intent_h1 = _make_factor("intent_h1_keyword", "H1/H2 mở bài có từ khóa", 3, "warning", "Chưa có từ khóa.", "Nhập từ khóa chính.")
    elif _kw_in_text(h1_text, pk):
        f_intent_h1 = _make_factor("intent_h1_keyword", "H1/H2 mở bài có từ khóa", 3, "passed", "Heading đầu bài có từ khóa.", "Duy trì cấu trúc heading rõ ràng.")
    else:
        f_intent_h1 = _make_factor("intent_h1_keyword", "H1/H2 mở bài có từ khóa", 3, "warning", "Heading đầu chưa có từ khóa.", f"Thêm từ khóa vào H1 hoặc H2 đầu tiên.")

    if word_n < 80:
        f_intent_early = _make_factor("intent_answer_early", "Trả lời sớm trong mở bài", 4, "failed", "Bài quá ngắn — chưa trả lời intent.", "Viết ít nhất 2–3 đoạn mở bài trả lời câu hỏi người đọc.")
    elif _kw_in_text(intro_text, pk) or len(intro_text) > 200:
        f_intent_early = _make_factor("intent_answer_early", "Trả lời sớm trong mở bài", 4, "passed", "Mở bài có nội dung trả lời / ngữ cảnh rõ.", "Giữ đoạn mở bài trực diện, trả lời intent trong 150 từ đầu.")
    else:
        f_intent_early = _make_factor("intent_answer_early", "Trả lời sớm trong mở bài", 4, "warning", "Mở bài chưa nêu rõ câu trả lời.", "Thêm 1–2 câu tóm tắt giá trị bài ngay sau heading đầu.")

    g1 = _make_group("search_intent", "Search Intent", [f_intent_title, f_intent_h1, f_intent_early])

    # --- 2. Helpful Content (12) ---
    if word_n >= 800:
        f_helpful_len = _make_factor("helpful_word_count", "Độ dài đủ cung cấp giá trị", 4, "passed", f"~{word_n} từ — đủ chiều sâu.", "Duy trì nội dung hữu ích, tránh lan man.")
    elif word_n >= 500:
        f_helpful_len = _make_factor("helpful_word_count", "Độ dài đủ cung cấp giá trị", 4, "warning", f"~{word_n} từ — hơi ngắn.", "Mở rộng thêm ví dụ, bước thực hiện hoặc FAQ.")
    else:
        f_helpful_len = _make_factor("helpful_word_count", "Độ dài đủ cung cấp giá trị", 4, "failed", f"Chỉ ~{word_n} từ.", "Bổ sung nội dung thực chất — mục tiêu 800+ từ cho bài SEO.")

    if len(lists) >= 1 or re.search(r"\b(bước|step|cách|quy trình)\b", body_text, re.I):
        f_helpful_steps = _make_factor("helpful_actionable", "Có bước / list hành động", 4, "passed", "Có danh sách hoặc hướng dẫn từng bước.", "Giữ format dễ quét (bullet, numbered list).")
    elif word_n > 400:
        f_helpful_steps = _make_factor("helpful_actionable", "Có bước / list hành động", 4, "warning", "Chưa thấy list hoặc quy trình rõ.", "Thêm bullet/numbered list cho các bước thực hiện.")
    else:
        f_helpful_steps = _make_factor("helpful_actionable", "Có bước / list hành động", 4, "failed", "Thiếu nội dung hành động.", "Thêm checklist hoặc quy trình cụ thể.")

    faq_re = re.compile(r"\b(faq|câu hỏi thường gặp|kết luận|tóm lại|tổng kết)\b", re.I)
    has_faq = any(faq_re.search(h.get_text(" ", strip=True)) for h in soup.find_all(["h2", "h3"]))
    if has_faq or re.search(r"\b(tóm lại|kết luận|tổng kết)\b", body_text[-800:], re.I):
        f_helpful_faq = _make_factor("helpful_faq_conclusion", "FAQ hoặc kết luận", 4, "passed", "Có FAQ hoặc đoạn kết luận.", "Giữ phần kết giúp người đọc ra quyết định.")
    elif word_n > 600:
        f_helpful_faq = _make_factor("helpful_faq_conclusion", "FAQ hoặc kết luận", 4, "warning", "Chưa có FAQ / kết luận rõ.", "Thêm mục FAQ hoặc đoạn tóm tắt cuối bài.")
    else:
        f_helpful_faq = _make_factor("helpful_faq_conclusion", "FAQ hoặc kết luận", 4, "failed", "Thiếu phần kết / FAQ.", "Thêm H2 FAQ hoặc kết luận cuối bài.")

    g2 = _make_group("helpful_content", "Helpful Content", [f_helpful_len, f_helpful_steps, f_helpful_faq])

    # --- 3. E-E-A-T (12) ---
    nums = len(re.findall(r"\b\d+[\d.,]*\s*(%|phần trăm|năm|ngày|giờ|triệu|nghìn|k|vnđ|đ)\b", body_text, re.I))
    if nums >= 3:
        f_eeat_depth = _make_factor("eeat_specifics", "Số liệu / chi tiết cụ thể", 4, "passed", f"Có ~{nums} số liệu/chi tiết cụ thể.", "Tiếp tục dùng số liệu thật, có nguồn khi cần.")
    elif nums >= 1:
        f_eeat_depth = _make_factor("eeat_specifics", "Số liệu / chi tiết cụ thể", 4, "warning", "Ít số liệu cụ thể.", "Thêm giá, thời gian, % hoặc con số minh họa.")
    else:
        f_eeat_depth = _make_factor("eeat_specifics", "Số liệu / chi tiết cụ thể", 4, "failed", "Thiếu chi tiết cụ thể.", "Bổ sung số liệu, ví dụ thực tế tăng độ tin.")

    generic_hits = len(re.findall(r"\b(trong bài viết này|như chúng ta đã biết|vô cùng quan trọng|hãy cùng tìm hiểu)\b", body_text, re.I))
    if generic_hits == 0 and word_n > 400:
        f_eeat_unique = _make_factor("eeat_unique_value", "Giá trị riêng, ít mẫu chung", 4, "passed", "Ít cụm mẫu AI / generic.", "Giữ giọng văn tự nhiên, tránh lặp mẫu.")
    elif generic_hits <= 2:
        f_eeat_unique = _make_factor("eeat_unique_value", "Giá trị riêng, ít mẫu chung", 4, "warning", f"Có {generic_hits} cụm mẫu chung.", "Viết lại câu mở / chuyển ý tự nhiên hơn.")
    else:
        f_eeat_unique = _make_factor("eeat_unique_value", "Giá trị riêng, ít mẫu chung", 4, "failed", "Nhiều câu mẫu chung.", "Thay câu sáo rỗng bằng insight cụ thể.")

    if _EEAT_RE.search(body_text):
        f_eeat_trust = _make_factor("eeat_trust_signals", "Tín hiệu E-E-A-T / uy tín", 4, "passed", "Có tín hiệu kinh nghiệm / uy tín.", "Duy trì cam kết, bảo hành hoặc bằng chứng thực tế.")
    elif word_n > 500:
        f_eeat_trust = _make_factor("eeat_trust_signals", "Tín hiệu E-E-A-T / uy tín", 4, "warning", "Chưa thấy tín hiệu uy tín rõ.", "Thêm cam kết, kinh nghiệm thực tế hoặc quy trình minh bạch.")
    else:
        f_eeat_trust = _make_factor("eeat_trust_signals", "Tín hiệu E-E-A-T / uy tín", 4, "failed", "Thiếu tín hiệu trust.", "Bổ sung bảo hành, quy trình, case thực tế.")

    g3 = _make_group("eeat", "Unique Value & E-E-A-T", [f_eeat_depth, f_eeat_unique, f_eeat_trust])

    # --- 4. Title / Meta / Slug (10) ---
    if not pk:
        f_title_kw = _make_factor("title_keyword", "Tiêu đề có từ khóa", 3, "warning", "Chưa có từ khóa.", "Nhập từ khóa chính.")
    elif _kw_in_text(title_s, pk):
        f_title_kw = _make_factor("title_keyword", "Tiêu đề có từ khóa", 3, "passed", "Tiêu đề có từ khóa chính.", "Giữ tiêu đề 50–60 ký tự khi có thể.")
    else:
        f_title_kw = _make_factor("title_keyword", "Tiêu đề có từ khóa", 3, "failed", "Tiêu đề thiếu từ khóa.", f"Chèn «{pk}» vào tiêu đề.")

    meta_len = len(meta_s)
    if not meta_s:
        f_meta = _make_factor("meta_quality", "Meta description", 4, "failed", "Chưa có meta description.", "Viết meta 120–160 ký tự, có từ khóa và CTA.")
    elif pk and not _kw_in_text(meta_s, pk):
        f_meta = _make_factor("meta_quality", "Meta description", 4, "warning", "Meta chưa có từ khóa chính.", f"Thêm từ khóa «{pk}» vào meta.")
    elif meta_len < 70:
        f_meta = _make_factor("meta_quality", "Meta description", 4, "warning", f"Meta quá ngắn ({meta_len} ký tự).", "Mở rộng meta 120–160 ký tự.")
    elif meta_len > 170:
        f_meta = _make_factor("meta_quality", "Meta description", 4, "warning", f"Meta dài ({meta_len} ký tự).", "Rút gọn meta còn ~150 ký tự.")
    else:
        f_meta = _make_factor("meta_quality", "Meta description", 4, "passed", f"Meta {meta_len} ký tự, có từ khóa.", "Giữ meta hấp dẫn trên SERP.")

    if not slug_s:
        f_slug = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "warning", "Chưa có slug.", "Tạo slug ngắn, có từ khóa, không dấu.")
    elif pk and _kw_in_text(slug_s.replace("-", " "), pk):
        f_slug = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "passed", "Slug chứa từ khóa.", "Giữ slug ngắn gọn, dùng dấu gạch ngang.")
    elif re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", slug_s):
        f_slug = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "warning", "Slug OK nhưng chưa khớp từ khóa.", "Thêm token từ khóa vào slug.")
    else:
        f_slug = _make_factor("slug_seo", "Slug thân thiện SEO", 3, "failed", "Slug chưa chuẩn SEO.", "Dùng chữ thường, gạch ngang, không dấu.")

    g4 = _make_group("title_meta_slug", "Title / Meta / Slug", [f_title_kw, f_meta, f_slug])

    # --- 5. Heading Structure (8) ---
    if len(h1s) == 1:
        f_h1_single = _make_factor("heading_single_h1", "Một H1 duy nhất", 2, "passed", "Có đúng 1 thẻ H1.", "Không thêm H1 phụ.")
    elif len(h1s) == 0:
        f_h1_single = _make_factor("heading_single_h1", "Một H1 duy nhất", 2, "warning", "Không có H1 — dùng title hoặc thêm H1.", "Thêm một H1 chính cho bài.")
    else:
        f_h1_single = _make_factor("heading_single_h1", "Một H1 duy nhất", 2, "failed", f"Có {len(h1s)} H1.", "Chỉ giữ một H1, chuyển heading phụ sang H2.")

    if len(h2s) >= 3:
        f_h2_count = _make_factor("heading_h2_count", "Cấu trúc H2 đủ mục", 3, "passed", f"Có {len(h2s)} mục H2.", "Giữ outline rõ ràng theo H2.")
    elif len(h2s) >= 1:
        f_h2_count = _make_factor("heading_h2_count", "Cấu trúc H2 đủ mục", 3, "warning", f"Chỉ {len(h2s)} H2.", "Thêm H2 cho các phần nội dung chính.")
    else:
        f_h2_count = _make_factor("heading_h2_count", "Cấu trúc H2 đủ mục", 3, "failed", "Chưa có H2.", "Chia bài thành các mục H2.")

    if h1s and h2s and not h3s:
        f_hier = _make_factor("heading_hierarchy", "Thứ bậc heading", 3, "passed", "H1 → H2 hợp lý.", "Có thể thêm H3 cho mục con nếu cần.")
    elif not h1s and h2s:
        f_hier = _make_factor("heading_hierarchy", "Thứ bậc heading", 3, "warning", "Thiếu H1, chỉ có H2.", "Thêm H1 hoặc đảm bảo title = H1.")
    elif h3s and not h2s:
        f_hier = _make_factor("heading_hierarchy", "Thứ bậc heading", 3, "failed", "Có H3 nhưng thiếu H2.", "Sửa thứ bậc: H2 trước H3.")
    else:
        f_hier = _make_factor("heading_hierarchy", "Thứ bậc heading", 3, "passed", "Thứ bậc heading ổn.", "Tránh nhảy cấp heading.")

    g5 = _make_group("heading_structure", "Heading Structure", [f_h1_single, f_h2_count, f_hier])

    # --- 6. Keyword & Semantic SEO (10) ---
    if not pk:
        f_kw_body = _make_factor("keyword_in_body", "Từ khóa trong thân bài", 4, "warning", "Chưa có từ khóa.", "Nhập từ khóa chính.")
    elif _kw_in_text(body_text, pk):
        f_kw_body = _make_factor("keyword_in_body", "Từ khóa trong thân bài", 4, "passed", "Từ khóa xuất hiện trong nội dung.", "Rải tự nhiên ở mở bài, H2 và kết luận.")
    else:
        f_kw_body = _make_factor("keyword_in_body", "Từ khóa trong thân bài", 4, "failed", "Thân bài chưa có từ khóa.", f"Chèn «{pk}» vào ít nhất 1 đoạn và 1 H2.")

    if not pk:
        f_density = _make_factor("keyword_density", "Mật độ từ khóa", 3, "warning", "Chưa có từ khóa.", "—")
    else:
        pk_low = pk.lower()
        exact = len(re.findall(re.escape(pk_low), body_text.lower()))
        density = (exact / max(word_n, 1)) * 100.0
        if exact == 0:
            f_density = _make_factor("keyword_density", "Mật độ từ khóa", 3, "failed", "Từ khóa chưa xuất hiện.", "Thêm từ khóa tự nhiên vào bài.")
        elif density > 4.5 or exact > max(12, word_n // 80):
            f_density = _make_factor("keyword_density", "Mật độ từ khóa", 3, "failed", f"Nhồi từ khóa (~{exact} lần).", "Giảm lặp, dùng từ đồng nghĩa.")
        elif density > 2.8:
            f_density = _make_factor("keyword_density", "Mật độ từ khóa", 3, "warning", f"Mật độ hơi cao ({exact} lần).", "Kiểm tra câu chữ tự nhiên.")
        else:
            f_density = _make_factor("keyword_density", "Mật độ từ khóa", 3, "passed", f"Mật độ ổn ({exact} lần / ~{word_n} từ).", "Duy trì mật độ hiện tại.")

    sec_hit = sum(1 for sk in sec_kws[:5] if _kw_in_text(body_text, sk))
    if not sec_kws:
        f_semantic = _make_factor("semantic_keywords", "Từ khóa phụ / ngữ nghĩa", 3, "warning", "Chưa có từ khóa phụ.", "Thêm secondary keywords ở Brief.")
    elif sec_hit >= max(1, len(sec_kws[:5]) // 2):
        f_semantic = _make_factor("semantic_keywords", "Từ khóa phụ / ngữ nghĩa", 3, "passed", f"Có {sec_hit} từ khóa phụ trong bài.", "Tiếp tục rải semantic tự nhiên.")
    else:
        f_semantic = _make_factor("semantic_keywords", "Từ khóa phụ / ngữ nghĩa", 3, "warning", "Ít từ khóa phụ trong bài.", "Chèn thêm biến thể / từ khóa liên quan.")

    g6 = _make_group("keyword_semantic", "Keyword & Semantic SEO", [f_kw_body, f_density, f_semantic])

    # --- 7. Content Depth (12) ---
    if word_n >= 1200:
        f_depth_words = _make_factor("depth_word_count", "Độ sâu theo số từ", 4, "passed", f"~{word_n} từ — chiều sâu tốt.", "—")
    elif word_n >= 800:
        f_depth_words = _make_factor("depth_word_count", "Độ sâu theo số từ", 4, "warning", f"~{word_n} từ — đạt tối thiểu.", "Mở rộng thêm 200–400 từ nếu cạnh tranh cao.")
    else:
        f_depth_words = _make_factor("depth_word_count", "Độ sâu theo số từ", 4, "failed", f"Chỉ ~{word_n} từ.", "Mục tiêu 800+ từ cho bài pillar.")

    avg_para = word_n / max(len(paras), 1)
    if 40 <= avg_para <= 120:
        f_para = _make_factor("depth_paragraphs", "Cân bằng đoạn văn", 4, "passed", f"~{int(avg_para)} từ/đoạn.", "Giữ đoạn 2–4 câu dễ đọc.")
    elif avg_para > 150:
        f_para = _make_factor("depth_paragraphs", "Cân bằng đoạn văn", 4, "warning", "Đoạn văn dài.", "Chia nhỏ paragraph dài.")
    else:
        f_para = _make_factor("depth_paragraphs", "Cân bằng đoạn văn", 4, "warning", "Đoạn quá ngắn hoặc thiếu <p>.", "Gom ý thành đoạn 2–4 câu.")

    if len(h2s) >= 2 and word_n / max(len(h2s), 1) >= 120:
        f_section = _make_factor("depth_per_section", "Chiều sâu từng mục H2", 4, "passed", "Mỗi H2 có nội dung đủ dài.", "Duy trì 150+ từ / mục H2.")
    elif len(h2s) >= 1:
        f_section = _make_factor("depth_per_section", "Chiều sâu từng mục H2", 4, "warning", "Một số mục H2 còn mỏng.", "Mở rộng nội dung dưới từng H2.")
    else:
        f_section = _make_factor("depth_per_section", "Chiều sâu từng mục H2", 4, "failed", "Chưa có cấu trúc mục.", "Thêm H2 và nội dung chi tiết.")

    g7 = _make_group("content_depth", "Content Depth", [f_depth_words, f_para, f_section])

    # --- 8. Link SEO (8) ---
    if internal_n >= 2:
        f_int = _make_factor("links_internal", "Internal link", 3, "passed", f"Có {internal_n} liên kết nội bộ.", "Giữ 2–5 internal link phù hợp.")
    elif internal_n >= 1:
        f_int = _make_factor("links_internal", "Internal link", 3, "warning", "Chỉ 1 internal link.", "Thêm 1–2 internal link liên quan.")
    else:
        f_int = _make_factor("links_internal", "Internal link", 3, "failed", "Chưa có internal link.", "Dùng tab Internal Link hoặc chèn <a href> thủ công.")

    if external_n >= 1:
        f_ext = _make_factor("links_external", "External link uy tín", 3, "passed", f"Có {external_n} liên kết ngoài.", "Link nguồn uy tín khi trích dẫn.")
    else:
        f_ext = _make_factor("links_external", "External link uy tín", 3, "warning", "Chưa có external link.", "Thêm 1 link nguồn / tham khảo nếu phù hợp.")

    anchors_ok = 0
    anchors_bad = 0
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if len(txt) >= 3 and txt.lower() not in ("click here", "tại đây", "xem thêm", "here"):
            anchors_ok += 1
        else:
            anchors_bad += 1
    if anchors_ok >= 2 and anchors_bad == 0:
        f_anchor = _make_factor("links_anchor_text", "Anchor text mô tả", 2, "passed", "Anchor text mô tả rõ.", "Tránh «tại đây», «click here».")
    elif anchors_ok >= 1:
        f_anchor = _make_factor("links_anchor_text", "Anchor text mô tả", 2, "warning", "Một số anchor chưa mô tả.", "Đổi anchor thành cụm từ khóa / mô tả.")
    else:
        f_anchor = _make_factor("links_anchor_text", "Anchor text mô tả", 2, "failed" if (internal_n + external_n) > 0 else "warning", "Anchor text yếu hoặc chưa có link.", "Dùng anchor mô tả nội dung đích.")

    g8 = _make_group("link_seo", "Link SEO", [f_int, f_ext, f_anchor])

    # --- 9. Media / Schema / Blockquote (10) ---
    if imgs:
        f_img_pres = _make_factor("media_images", "Ảnh minh họa", 3, "passed", f"Có {len(imgs)} ảnh.", "Thêm ảnh sau các H2 chính nếu thiếu.")
    elif len(h2s) >= 2:
        f_img_pres = _make_factor("media_images", "Ảnh minh họa", 3, "warning", "Chưa có ảnh.", "Dùng tab Ảnh để chèn minh họa.")
    else:
        f_img_pres = _make_factor("media_images", "Ảnh minh họa", 3, "failed", "Thiếu ảnh minh họa.", "Thêm ít nhất 1 ảnh relevant.")

    if not imgs:
        f_alt = _make_factor("media_alt_text", "Alt text ảnh", 3, "warning", "Chưa có ảnh để kiểm alt.", "Thêm ảnh kèm alt mô tả.")
    else:
        bad = [str(img.get("alt") or "").strip() for img in imgs if len(str(img.get("alt") or "").strip()) < 4 or _GENERIC_ALT_RE.match(str(img.get("alt") or ""))]
        if not bad:
            f_alt = _make_factor("media_alt_text", "Alt text ảnh", 3, "passed", f"Tất cả {len(imgs)} ảnh có alt.", "Alt mô tả ngữ cảnh H2 / từ khóa.")
        elif len(bad) < len(imgs):
            f_alt = _make_factor("media_alt_text", "Alt text ảnh", 3, "warning", f"{len(imgs)-len(bad)}/{len(imgs)} alt tốt.", "Sửa alt ảnh còn generic hoặc trống.")
        else:
            f_alt = _make_factor("media_alt_text", "Alt text ảnh", 3, "failed", "Ảnh thiếu alt mô tả.", "Viết alt 8–12 từ mô tả ảnh.")

    schema_ok = False
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        raw_js = script.string or script.get_text() or ""
        if not raw_js.strip():
            continue
        try:
            data = json.loads(raw_js)
            types: set[str] = set()
            if isinstance(data, list):
                types = {str(x.get("@type", "")).lower() for x in data if isinstance(x, dict)}
            elif isinstance(data, dict):
                types = {str(data.get("@type", "")).lower()}
                graph = data.get("@graph")
                if isinstance(graph, list):
                    types |= {str(x.get("@type", "")).lower() for x in graph if isinstance(x, dict)}
            if types & {"article", "blogposting", "newsarticle", "faqpage", "question"}:
                schema_ok = True
                break
        except Exception:
            continue
    exp_bq = _expected_blockquotes(word_n)
    if schema_ok and (exp_bq == 0 or bq_n >= exp_bq):
        f_schema_bq = _make_factor(
            "media_schema_blockquote", "Schema & blockquote", 4, "passed",
            f"Schema OK; blockquote {bq_n}/{exp_bq or '—'} (~{word_n} từ).", "—",
        )
    elif not schema_ok and exp_bq > 0 and bq_n < exp_bq:
        f_schema_bq = _make_factor(
            "media_schema_blockquote", "Schema & blockquote", 4, "failed",
            f"Thiếu schema và blockquote ({bq_n}/{exp_bq}).",
            "Thêm JSON-LD + blockquote chuyên gia hoặc dùng «Sửa bằng AI».",
        )
    elif exp_bq > 0 and bq_n < exp_bq:
        f_schema_bq = _make_factor(
            "media_schema_blockquote", "Schema & blockquote", 4, "warning",
            f"Blockquote {bq_n}/{exp_bq} (~{word_n} từ)." + ("" if schema_ok else " Thiếu schema."),
            f"Thêm {exp_bq - bq_n} blockquote" + ("" if schema_ok else " và schema Article/FAQ") + ".",
        )
    elif not schema_ok:
        f_schema_bq = _make_factor(
            "media_schema_blockquote", "Schema & blockquote", 4, "warning",
            "Chưa có JSON-LD trong bài.",
            "Thêm FAQ/Article schema khi publish.",
        )
    else:
        f_schema_bq = _make_factor(
            "media_schema_blockquote", "Schema & blockquote", 4, "passed",
            f"Blockquote {bq_n} — không bắt buộc dưới 800 từ.", "—",
        )

    g9 = _make_group("media_schema_blockquote", "Media / Schema / Blockquote", [f_img_pres, f_alt, f_schema_bq])

    # --- 10. Readability / UX (8) ---
    sentences = re.split(r"[.!?…]+", body_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    avg_sent = sum(len(re.findall(r"[\wà-ỹ]+", s, re.I)) for s in sentences) / max(len(sentences), 1)
    if avg_sent <= 28:
        f_read_sent = _make_factor("readability_sentence", "Độ dài câu", 3, "passed", f"~{int(avg_sent)} từ/câu.", "Giữ câu ngắn, dễ đọc trên mobile.")
    elif avg_sent <= 38:
        f_read_sent = _make_factor("readability_sentence", "Độ dài câu", 3, "warning", "Một số câu dài.", "Chia câu dài thành 2 câu ngắn.")
    else:
        f_read_sent = _make_factor("readability_sentence", "Độ dài câu", 3, "failed", "Câu quá dài.", "Rút gọn câu, tránh câu phức nhiều mệnh đề.")

    long_paras = sum(1 for p in paras if len(re.findall(r"[\wà-ỹ]+", p.get_text(" ", strip=True), re.I)) > 180)
    if long_paras == 0:
        f_read_wall = _make_factor("readability_paragraphs", "Không wall-of-text", 3, "passed", "Không có đoạn quá dài.", "—")
    elif long_paras <= 2:
        f_read_wall = _make_factor("readability_paragraphs", "Không wall-of-text", 3, "warning", f"{long_paras} đoạn quá dài.", "Chia paragraph >180 từ.")
    else:
        f_read_wall = _make_factor("readability_paragraphs", "Không wall-of-text", 3, "failed", "Nhiều đoạn wall-of-text.", "Chia nhỏ paragraph, thêm list.")

    fmt_score = 0
    if len(lists) >= 1:
        fmt_score += 1
    if len(h2s) >= 2:
        fmt_score += 1
    if imgs:
        fmt_score += 1
    if fmt_score >= 2:
        f_read_fmt = _make_factor("readability_formatting", "Định dạng dễ quét", 2, "passed", "Có list / heading / media.", "Giữ layout scannable.")
    elif fmt_score == 1:
        f_read_fmt = _make_factor("readability_formatting", "Định dạng dễ quét", 2, "warning", "Format còn đơn điệu.", "Thêm list, ảnh hoặc thêm H2.")
    else:
        f_read_fmt = _make_factor("readability_formatting", "Định dạng dễ quét", 2, "failed", "Thiếu yếu tố format.", "Thêm bullet, ảnh, heading.")

    g10 = _make_group("readability_ux", "Readability / UX đọc", [f_read_sent, f_read_wall, f_read_fmt])

    groups = [g1, g2, g3, g4, g5, g6, g7, g8, g9, g10]
    total_score = round(sum(g["score"] for g in groups), 1)
    grade_tier, grade_label = _grade_from_score(total_score)

    all_factors: list[dict[str, Any]] = []
    for g in groups:
        for f in g["factors"]:
            clean = {k: v for k, v in f.items() if not k.startswith("_")}
            all_factors.append(clean)

    items = [_legacy_item(f) for g in groups for f in g["factors"]]
    counts = {"ok": 0, "warn": 0, "fail": 0, "manual": 0}
    for it in items:
        st = it.get("status") or "warn"
        if st in counts:
            counts[st] += 1

    clean_groups = []
    for g in groups:
        clean_groups.append({
            "id": g["id"],
            "label": g["label"],
            "max_score": g["max_score"],
            "score": g["score"],
            "factors": [{k: v for k, v in f.items() if not k.startswith("_")} for f in g["factors"]],
        })

    return {
        "score": int(round(total_score)),
        "score_raw": total_score,
        "grade_tier": grade_tier,
        "grade_label": grade_label,
        "groups": clean_groups,
        "factors": all_factors,
        "items": items,
        "summary": counts,
        "content_html_stripped": html,
        "word_count": word_n,
    }
