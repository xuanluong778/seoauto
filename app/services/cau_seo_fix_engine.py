"""Engine sửa SEO popup Auto Update — hybrid: rule kỹ thuật + LLM ngữ nghĩa."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.cau_seo_analyzer import (
    build_cau_fix_change_report,
    count_internal_links,
    evaluate_cau_modal_seo,
    has_wordpress_h1,
    normalize_vietnamese_seo_text,
)
from app.services.cau_seo_fix_cache import get_cached_fix, make_fix_cache_key, put_cached_fix
from app.services.content_ai_seo_autofix import _slugify, select_factors_for_autofix
from app.services.content_update_agent import validate_preserved_markup
from app.services.llm_content_writer import (
    _anthropic_messages,
    _openai_chat_completion,
    load_llm_config,
    load_llm_config_admin,
)

AI_TIMEOUT_SEC = 30

# Mỗi factor chỉ được patch đúng 1 field (tránh LLM sửa nhầm đoạn <p> khi lỗi meta/title)
FACTOR_PATCH_FIELD: dict[str, str] = {
    "meta_quality": "meta_description",
    "title_keyword": "title",
    "intent_title_match": "title",
    "slug_seo": "slug",
}

SCALAR_EDIT_SCOPES: dict[str, str] = {
    "meta_description_only": "meta_description",
    "title_only": "title",
}
RULE_TECHNICAL_FACTORS = frozenset({
    "slug_seo", "media_schema_blockquote", "title_keyword", "intent_title_match",
})
RULE_PASS_CHECK_FACTORS = frozenset({
    "heading_single_h1",
    "links_internal",
    "media_alt_text",
})

# Bắt buộc LLM khi cần sửa (hiểu ngữ nghĩa)
LLM_SEMANTIC_FACTORS = frozenset({
    "meta_quality",
    "title_keyword",
    "intent_title_match",
    "intent_h1_keyword",
    "intent_answer_early",
    "heading_h2_count",
    "heading_hierarchy",
    "helpful_word_count",
    "helpful_actionable",
    "helpful_faq_conclusion",
    "eeat_specifics",
    "eeat_unique_value",
    "eeat_trust_signals",
    "keyword_in_body",
    "keyword_density",
    "semantic_keywords",
    "depth_word_count",
    "depth_paragraphs",
    "depth_per_section",
    "links_internal",
    "links_external",
    "links_anchor_text",
    "media_images",
    "media_alt_text",
    "readability_sentence",
    "readability_paragraphs",
    "readability_formatting",
})

_PATCH_SYSTEM = (
    "Bạn là SEO editor tiếng Việt. CHỈ sửa đúng MỘT lỗi SEO được mô tả trong CONTEXT. "
    "KHÔNG rewrite toàn bài. KHÔNG thêm nội dung sai chuyên môn. "
    "KHÔNG thêm câu chung chung như «trích dẫn chuyên gia» nếu bài không có ngữ cảnh đó. "
    "Nội dung mới phải đúng chủ đề bài viết, tự nhiên, khớp đoạn trước/sau.\n"
    "Trả về JSON array (1-3 patch), mỗi phần tử:\n"
    '{"issue_key":"...","field":"title|meta_description|slug|content_html",'
    '"position":"mô tả vị trí (vd: Meta description / H2 thứ 2 / đoạn sau intro)",'
    '"old_value":"...","new_value":"...","reason":"...","confidence":0-100}\n'
    "Với meta_description/title/slug: field phải khớp EDIT_SCOPE; old_value = text hiện tại (plain, không HTML). "
    "Meta description: plain text 120–160 ký tự, không thẻ <p>. "
    "Với content_html: old_value PHẢI là bản sao CHÍNH XÁC của CONTEXT.target.html (không tự tóm tắt). "
    "new_value phải là HTML cùng thẻ (vd. <p>...</p>) — chỉ sửa tối thiểu để fix đúng issue_key, "
    "giữ ≥80% câu chữ gốc, KHÔNG viết lại cả đoạn trừ khi issue là heading/meta. "
    "Không bọc markdown."
)


def _parse_llm_json_patches(text: str) -> list[dict[str, Any]]:
    """Parse LLM patch response — array, object.patches, or single patch object."""
    raw = str(text or "").strip()
    if not raw:
        return []
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    obj: Any = None
    try:
        obj = json.loads(raw)
    except Exception:
        for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
            m = re.search(pattern, raw)
            if not m:
                continue
            try:
                obj = json.loads(m.group(0))
                break
            except Exception:
                continue
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        patches = obj.get("patches")
        if isinstance(patches, list):
            return [x for x in patches if isinstance(x, dict)]
        if obj.get("field"):
            return [obj]
    return []


def _norm_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _wrap_plain_as_html(new_value: str, old_html: str) -> str:
    new_v = str(new_value or "").strip()
    if not new_v:
        return new_v
    if new_v.startswith("<"):
        return new_v
    try:
        ref = BeautifulSoup(str(old_html or "")[:8000], "html.parser").find(True)
        tag = ref.name if ref else "p"
        attrs = dict(ref.attrs) if ref else {}
        el = BeautifulSoup("", "html.parser").new_tag(tag)
        for k, v in attrs.items():
            try:
                el[k] = v
            except Exception:
                pass
        el.string = new_v
        return str(el)
    except Exception:
        return f"<p>{new_v}</p>"


def _replace_in_content_html(content: str, old_v: str, new_v: str, *, hint_html: str = "") -> tuple[str, bool]:
    """Replace one HTML fragment; never append orphan paragraphs."""
    out_c = str(content or "")
    old_s = str(old_v or "")
    new_s = str(new_v or "")
    if not new_s or old_s == new_s:
        return out_c, False

    candidates: list[str] = []
    for cand in (old_s, hint_html):
        c = str(cand or "").strip()
        if c and c not in candidates:
            candidates.append(c)

    for cand in candidates:
        if cand in out_c:
            wrapped = _wrap_plain_as_html(new_s, cand) if not new_s.strip().startswith("<") else new_s
            return out_c.replace(cand, wrapped, 1), True

    old_norm = _norm_match_text(old_s)
    hint_norm = _norm_match_text(BeautifulSoup(hint_html, "html.parser").get_text(" ", strip=True) if hint_html else "")
    if not old_norm and hint_norm:
        old_norm = hint_norm

    if not old_norm:
        return out_c, False

    try:
        soup = BeautifulSoup(out_c[:400_000], "html.parser")
    except Exception:
        return out_c, False

    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        el_text = _norm_match_text(el.get_text(" ", strip=True))
        if el_text != old_norm and not (len(old_norm) > 48 and old_norm in el_text):
            continue
        wrapped = _wrap_plain_as_html(new_s, str(el)) if not new_s.strip().startswith("<") else new_s
        try:
            replacement = BeautifulSoup(wrapped, "html.parser")
            node = replacement.find(True) or wrapped
            if hasattr(node, "name"):
                el.replace_with(node)
            else:
                el.replace_with(wrapped)
        except Exception:
            el.clear()
            el.append(new_s)
        return str(soup), True

    return out_c, False


def _strip_plain_text(value: str) -> str:
    try:
        return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)).strip()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _allowed_patch_field(factor_id: str, scoped: dict[str, Any]) -> str | None:
    fid = str(factor_id or "").strip()
    if fid in FACTOR_PATCH_FIELD:
        return FACTOR_PATCH_FIELD[fid]
    edit = str(scoped.get("edit_scope") or "").strip()
    return SCALAR_EDIT_SCOPES.get(edit)


def _scalar_value_for_field(field: str, scoped: dict[str, Any]) -> str:
    f = str(field or "").strip()
    if f == "meta_description":
        return str(scoped.get("meta_description") or "")
    if f == "title":
        return str(scoped.get("title") or "")
    if f == "slug":
        return str(scoped.get("slug") or "")
    return ""


def _enforce_factor_patch_fields(
    factor_id: str,
    entries: list[dict[str, Any]],
    scoped: dict[str, Any],
) -> list[dict[str, Any]]:
    """Chỉ giữ patch đúng field theo issue; bỏ content_html khi sửa meta/title."""
    allowed = _allowed_patch_field(factor_id, scoped)
    if not allowed:
        return entries

    scalar_old = _scalar_value_for_field(allowed, scoped)
    out: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        field = str(row.get("field") or "").strip()

        if field == "content_html" and allowed != "content_html":
            continue

        if field != allowed:
            row["field"] = allowed

        old_v = str(row.get("old_value") if row.get("old_value") is not None else "")
        new_v = str(row.get("new_value") if row.get("new_value") is not None else "")

        if allowed == "meta_description":
            new_v = _strip_plain_text(new_v)[:320]
            old_v = _strip_plain_text(old_v) or scalar_old
            meta_len = len(scoped.get("meta_description") or "")
            factor_msg = str(scoped.get("fix_requirement") or "").lower()
            if meta_len > 165 or "meta dài" in factor_msg or "rút gọn" in factor_msg:
                new_v = new_v[:160]
            else:
                new_v = new_v[:160]
        elif allowed == "title":
            new_v = _strip_plain_text(new_v)[:200]
            old_v = _strip_plain_text(old_v) or scalar_old
            pk = str(scoped.get("focus_keyword") or "").strip()
            if pk:
                from app.services.content_ai_publish_checklist import _kw_in_text
                if _kw_in_text(scalar_old, pk):
                    continue
                if not _kw_in_text(new_v, pk):
                    continue
                sec = scoped.get("secondary_keywords") or []
                for sk in sec:
                    sk_s = str(sk or "").strip()
                    if not sk_s or sk_s.lower() == pk.lower():
                        continue
                    if _kw_in_text(new_v, sk_s) and not _kw_in_text(new_v, pk):
                        continue
        elif allowed == "slug":
            new_v = re.sub(r"\s+", "-", _strip_plain_text(new_v).lower())[:120]
            old_v = old_v or scalar_old

        if not new_v or new_v == old_v:
            continue

        row["old_value"] = old_v or scalar_old
        row["new_value"] = new_v
        if not row.get("position"):
            row["position"] = {
                "meta_description": "Meta description",
                "title": "Tiêu đề",
                "slug": "Slug",
            }.get(allowed, allowed)
        out.append(row)
    return out


def _anchor_patches_to_scoped(
    entries: list[dict[str, Any]],
    scoped: dict[str, Any],
) -> list[dict[str, Any]]:
    """Gắn old_value/new_value vào đúng target từ context."""
    target = scoped.get("target") if isinstance(scoped.get("target"), dict) else {}
    target_field = str(target.get("field") or "").strip()
    edit_scope = str(scoped.get("edit_scope") or "").strip()
    hint_html = str(target.get("html") or "").strip()
    hint_text = str(target.get("text") or "").strip()
    tag = str(target.get("tag") or "p").strip() or "p"

    out: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        field = str(row.get("field") or "").strip()

        if field in ("meta_description", "title", "slug"):
            scalar_old = _scalar_value_for_field(field, scoped)
            if not row.get("old_value"):
                row["old_value"] = scalar_old
            if field == "meta_description":
                row["new_value"] = _strip_plain_text(row.get("new_value") or "")[:160]
                row["old_value"] = _strip_plain_text(row.get("old_value") or scalar_old)
            elif field == "title":
                row["new_value"] = _strip_plain_text(row.get("new_value") or "")[:200]
            if not row.get("position"):
                row["position"] = target.get("position") or field
            out.append(row)
            continue

        if field != "content_html":
            out.append(row)
            continue

        if edit_scope in SCALAR_EDIT_SCOPES or target_field in ("meta_description", "title", "slug"):
            continue

        old_v = str(row.get("old_value") if row.get("old_value") is not None else "")
        new_v = str(row.get("new_value") if row.get("new_value") is not None else "")

        if hint_html:
            if not old_v or (old_v not in hint_html and _norm_match_text(old_v) == _norm_match_text(hint_text)):
                row["old_value"] = hint_html
            elif old_v not in hint_html and hint_html in str(scoped.get("_full_content") or ""):
                row["old_value"] = hint_html

        if new_v and not new_v.strip().startswith("<"):
            row["new_value"] = _wrap_plain_as_html(new_v, row.get("old_value") or hint_html or f"<{tag}></{tag}>")

        if not row.get("position") and target.get("position"):
            row["position"] = target.get("position")

        out.append(row)
    return out


def _schema_ok_from_html(html: str) -> bool:
    from app.services.content_ai_publish_checklist import schema_ok_from_html

    return schema_ok_from_html(html)


_EEAT_NUM_RE = re.compile(
    r"\b\d+[\d.,]*\s*(%|phần trăm|năm|ngày|giờ|triệu|nghìn|k|vnđ|đ)\b",
    re.I,
)


def _count_eeat_specifics(body_text: str) -> int:
    return len(_EEAT_NUM_RE.findall(body_text or ""))


def _count_blockquotes(html: str) -> int:
    return len(re.findall(r"<blockquote\b", html or "", flags=re.I))


def _inject_contextual_blockquotes(content: str, *, needed: int, keyword: str, title: str) -> str:
    """Thêm blockquote ngữ cảnh theo chủ đề bài (không dùng câu generic)."""
    if needed <= 0:
        return content
    topic = (keyword or title or "chủ đề bài viết").strip()[:100]
    blocks: list[str] = []
    for _ in range(needed):
        blocks.append(
            '<blockquote class="expert-quote">'
            f"<p>«Trong thực tế triển khai {topic}, nội dung cần dựa trên kinh nghiệm và dữ kiện "
            f"cụ thể — tránh khẳng định chung chung không có căn cứ.»</p>"
            f"<cite>— Chuyên gia {topic}</cite>"
            "</blockquote>"
        )
    return content.rstrip() + "\n" + "\n".join(blocks)


def _try_rule_schema_blockquote(
    *,
    title: str,
    meta: str,
    content_html: str,
    keyword: str,
) -> dict[str, Any] | None:
    from app.services.content_ai_publish_checklist import _expected_blockquotes
    from app.services.content_ai_seo_autofix import _inject_article_schema, _inject_blockquotes
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes
    from app.services.llm_content_writer import _count_words_html

    old_c = str(content_html or "")
    new_c = old_c
    patches: list[dict[str, Any]] = []
    fid = "media_schema_blockquote"

    if not _schema_ok_from_html(new_c):
        schema_snippet = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Article","headline":"'
            + (title or "Bài viết").strip()[:120].replace('"', "'")
            + '"}</script>'
        )
        new_c = _inject_article_schema(content=new_c, title=title, description=meta)
        patches.append({
            "issue_key": fid,
            "field": "content_html",
            "position": "Cuối bài — JSON-LD Article",
            "old_value": "",
            "new_value": schema_snippet[:500],
            "reason": "Thêm schema Article (JSON-LD) cho SEO.",
            "confidence": 95,
        })

    word_n = _count_words_html(new_c)
    need_bq = _expected_blockquotes(word_n)
    cur_bq = _count_blockquotes(new_c)
    missing_bq = max(0, need_bq - cur_bq)
    if missing_bq > 0:
        before_bq = new_c
        new_c = _inject_blockquotes(new_c, needed=need_bq)
        try:
            new_c = postprocess_content_blockquotes(new_c)
        except Exception:
            pass
        patches.append({
            "issue_key": fid,
            "field": "content_html",
            "position": f"Blockquote chuyên gia ({cur_bq}→{cur_bq + missing_bq})",
            "old_value": "",
            "new_value": new_c[len(before_bq):].strip()[:800],
            "reason": f"Thêm {missing_bq} blockquote theo độ dài bài (~{word_n} từ).",
            "confidence": 92,
        })

    if new_c == old_c:
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Đã có schema và đủ blockquote — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    return {
        "source": "rule",
        "success": True,
        "unchanged": False,
        "summary": patches[-1]["reason"] if patches else "Đã bổ sung schema/blockquote.",
        "patches": patches,
        "patch": {"content_html": new_c},
    }


_ARTICLE_TYPE_LABELS: dict[str, str] = {
    "knowledge_blog": "Blog kiến thức",
    "service": "Dịch vụ",
    "product": "Sản phẩm",
    "case_study": "Case study",
}

_SERVICE_TYPE_SIGNALS = (
    "dich vu", "bao gia", "lien he ngay", "tu van", "cam ket", "trien khai",
    "goi dich vu", "bang gia", "mien phi tu van", "hotline",
)
_PRODUCT_TYPE_SIGNALS = (
    "san pham", "mua ngay", "thong so ky thuat", "model ", "phien ban",
    "gia ban", "tinh nang noi bat",
)
_CASE_TYPE_SIGNALS = (
    "case study", "du an", "khach hang", "ket qua dat duoc", "story thanh cong",
    "truoc va sau",
)
_KNOWLEDGE_TYPE_SIGNALS = (
    "huong dan", "cach ", "la gi", "tim hieu", "nghien cuu", "hieu qua",
    "quy trinh", "buoc ", "checklist", "tips", "nguyen tac", "y nghia",
)

_KNOWLEDGE_FORBIDDEN_COMMERCE = (
    "trieu", "nghin", "vnđ", "vnd", "chi phi", "bao gia", "gia tu",
    "tu van mien phi", "cam ket", "khao sat noi bo", "khach hang hai long",
    "trien khai ", "goi dich vu", "hotline",
)
_FABRICATED_EEAT_PHRASES = (
    "khao sat noi bo",
    "72%",
    "65%",
    "8 trieu",
    "14 ngay",
    "trien khai trung binh",
    "chi phi khoi diem",
)


def _detect_article_type(
    *,
    title: str,
    keyword: str,
    slug: str,
    post_url: str,
    category: str,
    content_html: str,
) -> tuple[str, str]:
    """Heuristic nhận diện loại bài trước khi bổ sung số liệu."""
    parts = [title, keyword, slug.replace("-", " "), category, post_url]
    try:
        soup = BeautifulSoup(str(content_html or "")[:400_000], "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for el in soup.find_all(["h1", "h2", "h3", "p", "li"])[:40]:
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if len(t) >= 8:
                parts.append(t[:240])
    except Exception:
        pass
    blob = normalize_vietnamese_seo_text(" ".join(parts))
    url_path = normalize_vietnamese_seo_text(urlparse(post_url or "").path.replace("/", " "))

    scores = {"service": 0, "product": 0, "case_study": 0, "knowledge_blog": 0}
    for sig in _SERVICE_TYPE_SIGNALS:
        if sig in blob or sig in url_path:
            scores["service"] += 2 if sig in url_path else 1
    for sig in _PRODUCT_TYPE_SIGNALS:
        if sig in blob or sig in url_path:
            scores["product"] += 2 if sig in url_path else 1
    for sig in _CASE_TYPE_SIGNALS:
        if sig in blob:
            scores["case_study"] += 2
    for sig in _KNOWLEDGE_TYPE_SIGNALS:
        if sig in blob:
            scores["knowledge_blog"] += 1

    if re.search(r"/(dich-vu|service)/", post_url or "", re.I):
        scores["service"] += 3
    if re.search(r"/(san-pham|product)/", post_url or "", re.I):
        scores["product"] += 3

    winner = max(scores, key=scores.get)
    top = scores[winner]
    if top < 2 or (winner != "knowledge_blog" and scores["knowledge_blog"] >= top - 1):
        winner = "knowledge_blog"
        top = max(top, scores["knowledge_blog"])

    reasons = {
        "knowledge_blog": "Tiêu đề/heading mang tính hướng dẫn, giải thích kiến thức — không phải landing dịch vụ.",
        "service": "Nội dung/URL nhắc dịch vụ, báo giá, tư vấn hoặc triển khai.",
        "product": "Nội dung tập trung sản phẩm, thông số hoặc mua hàng.",
        "case_study": "Nội dung kể case study, dự án hoặc kết quả khách hàng.",
    }
    if category:
        cat_n = normalize_vietnamese_seo_text(category)
        if any(s in cat_n for s in ("dich vu", "service")):
            winner, top = "service", top + 2
            reasons["service"] = f"Danh mục «{category}» + nội dung bài."
        elif any(s in cat_n for s in ("san pham", "product")):
            winner, top = "product", top + 2
            reasons["product"] = f"Danh mục «{category}» + nội dung bài."

    return winner, reasons.get(winner, "")


def _extract_article_sourced_stats(article_text: str) -> list[str]:
    """Các mẫu số liệu đã có trong bài (để LLM tái sử dụng, không bịa)."""
    found: list[str] = []
    for m in _EEAT_NUM_RE.finditer(article_text or ""):
        start = max(0, m.start() - 48)
        end = min(len(article_text), m.end() + 48)
        snippet = re.sub(r"\s+", " ", article_text[start:end]).strip()
        if snippet and snippet not in found:
            found.append(snippet)
    return found[:12]


_EEAT_SPECIFICS_SYSTEM = (
    "Bạn là biên tập viên SEO tiếng Việt. Bổ sung số liệu/chi tiết cụ thể BÁM SÁT bài trong CONTEXT.\n"
    "BƯỚC 1 — Nhận diện article_type: knowledge_blog | service | product | case_study.\n"
    "BƯỚC 2 — Chỉ thêm số liệu phù hợp loại bài:\n"
    "- knowledge_blog: CHỈ số bước/tiêu chí/nhóm dữ liệu/intent/search volume/độ cạnh tranh "
    "đã có hoặc suy ra trực tiếp từ heading & đoạn văn. "
    "CẤM giá tiền, triệu VNĐ, chi phí tư vấn, thời gian triển khai dịch vụ, cam kết kết quả.\n"
    "- service/product/case_study: được dùng số liệu thương mại CHỈ KHI đã có trong bài.\n"
    "QUY TẮC CHUNG:\n"
    "- KHÔNG bịa %, giá, ngày, năm, thống kê nếu không có trong existing_stats_in_article hoặc nội dung.\n"
    "- new_value = HTML <section class=\"eeat-specifics\">2–4 đoạn <p> ngắn, mỗi đoạn 1 số liệu rõ ràng.\n"
    "- Mục tiêu: đủ ~3 mẫu số theo regex chấm điểm (%|phần trăm|năm|ngày|giờ|triệu|nghìn|vnđ|đ) "
    "nhưng knowledge_blog KHÔNG dùng triệu/vnđ/chi phí.\n"
    "- Nếu không đủ số liệu có căn cứ → status=no_change, reason giải thích.\n"
    "Trả về ĐÚNG 1 JSON object:\n"
    '{"status":"changed|no_change","article_type":"knowledge_blog|service|product|case_study",'
    '"article_type_reason":"...","old_value":"","new_value":"<section>...</section>",'
    '"reason":"lý do thêm từng số liệu","confidence":0-100}'
)


def _parse_eeat_specifics_response(text: str) -> dict[str, Any] | None:
    return _parse_faq_conclusion_response(text)


def _call_eeat_specifics_ai(
    user_id: int,
    *,
    title: str,
    keyword: str,
    slug: str,
    post_url: str,
    category: str,
    article_type: str,
    article_type_reason: str,
    content_html: str,
    existing_stats: list[str],
    use_system_llm: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        if use_system_llm:
            return None, "Khóa LLM hệ thống chưa được cấu hình trên server. Liên hệ quản trị."
        from app.db import SessionLocal
        from app.services.user_api_access import describe_llm_config_failure

        db = SessionLocal()
        try:
            hint = describe_llm_config_failure(db, int(user_id))
        finally:
            db.close()
        return None, hint

    headings = _outline_h2_h3(content_html)
    excerpt = _content_excerpt_for_faq(content_html, max_chars=6000)
    context = {
        "title": title,
        "focus_keyword": keyword,
        "slug": slug,
        "post_url": post_url,
        "category": category,
        "detected_article_type": article_type,
        "detected_article_type_reason": article_type_reason,
        "headings_h2_h3": headings[:24],
        "content_excerpt": excerpt,
        "existing_stats_in_article": existing_stats,
        "stats_needed": max(0, 3 - _count_eeat_specifics(excerpt)),
        "instruction": (
            "Chỉ thêm số liệu có căn cứ từ context. "
            "Với knowledge_blog: không thêm giá, triển khai dịch vụ, cam kết."
        ),
    }
    user = (
        "CONTEXT_JSON:\n"
        + json.dumps(context, ensure_ascii=False, indent=0)
        + "\n\nTrả về đúng 1 JSON object theo schema đã mô tả."
    )
    try:
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[
                    {"role": "system", "content": _EEAT_SPECIFICS_SYSTEM},
                    {"role": "user", "content": user},
                ],
                max_tokens=1800,
                timeout_sec=AI_TIMEOUT_SEC,
            )
        else:
            out = _anthropic_messages(
                cfg=cfg, system=_EEAT_SPECIFICS_SYSTEM, user=user,
                max_tokens=1800, timeout_sec=AI_TIMEOUT_SEC,
            )
        parsed = _parse_eeat_specifics_response(out)
        if not parsed:
            preview = re.sub(r"\s+", " ", str(out or ""))[:180]
            return None, f"LLM không trả JSON số liệu hợp lệ. Phản hồi: {preview or '(rỗng)'}"
        return parsed, ""
    except Exception as exc:
        msg = str(exc).strip()
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return None, f"LLM không phản hồi trong {AI_TIMEOUT_SEC} giây."
        return None, f"LLM lỗi: {msg[:220]}"


def _stat_number_in_article(num_match: re.Match[str], article_text: str, art_norm: str) -> bool:
    num = num_match.group(0).strip()
    num_core = re.sub(r"[^\d]", "", num.split()[0] if num.split() else "")
    if not num_core:
        return False
    if num.lower() in article_text.lower():
        return True
    if num_core in art_norm.replace(" ", ""):
        return True
    ctx_start = max(0, num_match.start() - 40)
    ctx_end = min(len(article_text), num_match.end() + 40)
    ctx = normalize_vietnamese_seo_text(article_text[ctx_start:ctx_end])
    return num_core in ctx and len(ctx) >= 8


def _validate_eeat_specifics_context_guard(
    *,
    block_html: str,
    article_type: str,
    article_terms: set[str],
    article_text: str,
    title: str,
    keyword: str,
    category: str,
    post_url: str,
) -> tuple[bool, str]:
    """context_guard: số liệu phải khớp loại bài và nội dung gốc."""
    raw = str(block_html or "").strip()
    if not raw or "<p" not in raw.lower():
        return False, "Số liệu không hợp lệ — thiếu đoạn văn."

    try:
        block_text = BeautifulSoup(raw[:120_000], "html.parser").get_text(" ", strip=True)
    except Exception:
        block_text = raw
    block_norm = normalize_vietnamese_seo_text(block_text)
    art_norm = normalize_vietnamese_seo_text(article_text)

    topic_hits = sum(1 for t in article_terms if len(t) >= 4 and t in block_norm)
    if topic_hits < 2:
        return False, "Số liệu không khớp title/keyword/heading bài viết (context_guard)."

    for phrase in _FABRICATED_EEAT_PHRASES:
        if phrase in block_norm:
            return False, "Số liệu dùng mẫu template cũ — không cho áp dụng."

    atype = str(article_type or "knowledge_blog").strip().lower()
    if atype == "knowledge_blog":
        for phrase in _KNOWLEDGE_FORBIDDEN_COMMERCE:
            if phrase in block_norm:
                return False, (
                    f"Blog kiến thức không được thêm «{phrase}» — "
                    "chỉ số liệu hướng dẫn có trong bài."
                )
        if re.search(r"trien khai\s+\d+\s+ngay", block_norm):
            return False, "Blog kiến thức không được thêm thời gian triển khai dịch vụ."
        if re.search(r"\d+\s*(trieu|nghin|vnđ|vnd)\b", block_norm):
            return False, "Blog kiến thức không được thêm giá tiền/chi phí."

    stats_in_block = list(_EEAT_NUM_RE.finditer(block_text))
    if not stats_in_block:
        return False, "Chưa có số liệu cụ thể (%/ngày/năm…) trong đoạn thêm."

    unsourced = 0
    for m in stats_in_block:
        unit = normalize_vietnamese_seo_text(m.group(1) or "")
        if atype == "knowledge_blog" and unit in ("trieu", "nghin", "vnđ", "vnd", "đ"):
            return False, "Blog kiến thức không được dùng đơn vị tiền tệ."
        if not _stat_number_in_article(m, article_text, art_norm):
            unsourced += 1

    if unsourced == len(stats_in_block):
        return False, "Số liệu không có trong bài gốc — không được tự bịa (context_guard)."

    if atype == "knowledge_blog" and unsourced > 0:
        return False, f"Có {unsourced} số liệu không trích được từ nội dung bài — cần nguồn trong bài."

    if _count_eeat_specifics(block_text) < 1:
        return False, "Đoạn thêm chưa đủ số liệu theo tiêu chí chấm điểm."

    return True, ""


def _fix_eeat_specifics(
    *,
    user_id: int,
    title: str,
    content_html: str,
    primary_keyword: str,
    slug: str,
    post_url: str = "",
    category: str = "",
    use_system_llm: bool = False,
) -> dict[str, Any]:
    """Số liệu/chi tiết cụ thể — nhận diện loại bài + LLM + context_guard."""
    fid = "eeat_specifics"
    old_c = str(content_html or "")
    try:
        body_text = BeautifulSoup(old_c[:800_000], "html.parser").get_text(" ", strip=True)
    except Exception:
        body_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", old_c)).strip()
    article_text = _content_excerpt_for_faq(old_c, max_chars=14_000)
    cur = _count_eeat_specifics(body_text)
    if cur >= 3:
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Đã đủ số liệu cụ thể — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    article_type, type_reason = _detect_article_type(
        title=title,
        keyword=primary_keyword,
        slug=slug,
        post_url=post_url,
        category=category,
        content_html=old_c,
    )
    type_label = _ARTICLE_TYPE_LABELS.get(article_type, article_type)
    existing_stats = _extract_article_sourced_stats(body_text)
    topic_terms = _article_topic_terms(
        title=title, keyword=primary_keyword, slug=slug, content_html=old_c,
    )

    llm_row, llm_error = _call_eeat_specifics_ai(
        user_id,
        title=title,
        keyword=primary_keyword,
        slug=slug,
        post_url=post_url,
        category=category,
        article_type=article_type,
        article_type_reason=type_reason,
        content_html=old_c,
        existing_stats=existing_stats,
        use_system_llm=use_system_llm,
    )
    if not llm_row:
        return {
            "source": "llm",
            "success": False,
            "unchanged": False,
            "summary": "",
            "patches": [],
            "patch": {},
            "error": llm_error or "Không tạo được số liệu.",
            "validation_rejected": True,
            "article_type": article_type,
            "article_type_label": type_label,
            "article_type_reason": type_reason,
        }

    llm_type = str(llm_row.get("article_type") or article_type).strip().lower()
    if llm_type in _ARTICLE_TYPE_LABELS:
        article_type = llm_type
        type_label = _ARTICLE_TYPE_LABELS[article_type]
    llm_type_reason = str(llm_row.get("article_type_reason") or type_reason).strip()
    if llm_type_reason:
        type_reason = llm_type_reason

    status = str(llm_row.get("status") or "").strip().lower()
    if status == "no_change":
        reason = str(llm_row.get("reason") or "Không đủ số liệu có nguồn trong bài.")
        return {
            "source": "llm",
            "success": True,
            "unchanged": True,
            "summary": reason,
            "patches": [],
            "patch": {},
            "article_type": article_type,
            "article_type_label": type_label,
            "article_type_reason": type_reason,
        }

    new_block = str(llm_row.get("new_value") or "").strip()
    reason = str(
        llm_row.get("reason") or "Bổ sung số liệu bám sát nội dung bài theo loại bài đã nhận diện."
    ).strip()
    try:
        confidence = max(0, min(100, int(llm_row.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0

    ok, reject_msg = _validate_eeat_specifics_context_guard(
        block_html=new_block,
        article_type=article_type,
        article_terms=topic_terms,
        article_text=article_text,
        title=title,
        keyword=primary_keyword,
        category=category,
        post_url=post_url,
    )
    if not ok:
        return {
            "source": "llm",
            "success": False,
            "unchanged": False,
            "summary": "",
            "patches": [],
            "patch": {},
            "error": reject_msg or "Số liệu không qua context_guard.",
            "validation_rejected": True,
            "article_type": article_type,
            "article_type_label": type_label,
            "article_type_reason": type_reason,
        }

    new_c = old_c.rstrip() + "\n" + new_block
    needs_review = confidence < 80
    type_note = f"Loại bài: {type_label}. {type_reason}"
    patch_row = {
        "issue_key": fid,
        "field": "content_html",
        "position": "Cuối bài — số liệu / chi tiết cụ thể",
        "old_value": "",
        "new_value": new_block[:12_000],
        "reason": f"{type_note} · {reason}",
        "confidence": confidence,
    }
    return {
        "source": "llm",
        "success": True,
        "unchanged": False,
        "summary": f"{type_note} · {reason}" + (" · Cần kiểm tra lại." if needs_review else ""),
        "patches": [patch_row],
        "patch": {"content_html": new_c},
        "needs_review": needs_review,
        "validation_warning": "Cần kiểm tra lại số liệu trước khi áp dụng." if needs_review else "",
        "confidence": confidence,
        "article_type": article_type,
        "article_type_label": type_label,
        "article_type_reason": type_reason,
    }


_FAQ_CONCLUSION_SYSTEM = (
    "Bạn là biên tập viên SEO tiếng Việt. Tạo FAQ và kết luận BÁM SÁT đúng bài viết trong CONTEXT.\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- CHỈ dùng thông tin từ title, focus_keyword, slug, headings, content_excerpt.\n"
    "- KHÔNG bịa số liệu, %, giá, thời gian, thống kê nếu không có trong bài.\n"
    "- 3–5 câu hỏi FAQ thật sự liên quan heading/nội dung bài — KHÔNG template chung.\n"
    "- Mỗi câu trả lời ngắn (2–4 câu), đúng ý bài, không thêm thông tin mới.\n"
    "- Kết bằng <p><strong>Tóm lại:</strong> ...</p> tóm tắt bài, không nhồi keyword.\n"
    "- new_value = HTML fragment <section class=\"article-faq\">...</section> để chèn CUỐI bài.\n"
    "- Cấu trúc: <h2>Câu hỏi thường gặp</h2> + các cặp <h3>câu hỏi</h3><p>trả lời</p> + đoạn Tóm lại.\n"
    "Trả về ĐÚNG 1 JSON object (không markdown, không array):\n"
    '{"status":"changed|no_change","issue_key":"faq_or_conclusion",'
    '"old_value":"","new_value":"<section class=\\"article-faq\\">...</section>",'
    '"reason":"...","confidence":0-100}'
)

_FAQ_STAT_RE = re.compile(
    r"\b\d+[\d.,]*\s*(%|phần trăm|năm|ngày|giờ|triệu|nghìn|vnđ|đ)\b",
    re.I,
)

_OFF_TOPIC_FAQ_PHRASES = (
    "nghien cuu tu khoa",
    "thuat toan google",
    "keyword research",
    "seo onpage",
    "backlink",
    "content marketing",
)


def _content_excerpt_for_faq(content_html: str, *, max_chars: int = 4500) -> str:
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        lines: list[str] = []
        for el in soup.find_all(["h2", "h3", "p", "li"]):
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if len(t) >= 12:
                lines.append(f"{str(el.name or 'p').upper()}: {t[:420]}")
        return "\n".join(lines)[:max_chars]
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(content_html or ""))).strip()[:max_chars]


def _article_topic_terms(*, title: str, keyword: str, slug: str, content_html: str) -> set[str]:
    terms: set[str] = set()
    for src in (title, keyword, slug.replace("-", " ")):
        for t in normalize_vietnamese_seo_text(src).split():
            if len(t) >= 3:
                terms.add(t)
    for h in _headings_outline(content_html):
        for t in normalize_vietnamese_seo_text(str(h.get("text") or "")).split():
            if len(t) >= 4:
                terms.add(t)
    return terms


def _validate_faq_conclusion_html(
    *,
    faq_html: str,
    article_terms: set[str],
    article_text: str,
) -> tuple[bool, str]:
    """Từ chối FAQ lệch chủ đề hoặc chứa số liệu không có trong bài."""
    raw = str(faq_html or "").strip()
    if not raw or "<h" not in raw.lower():
        return False, "FAQ không hợp lệ — thiếu heading."

    try:
        faq_text = BeautifulSoup(raw[:120_000], "html.parser").get_text(" ", strip=True)
    except Exception:
        faq_text = raw
    faq_norm = normalize_vietnamese_seo_text(faq_text)
    art_norm = normalize_vietnamese_seo_text(article_text)

    if not re.search(r"\b(faq|cau hoi thuong gap)\b", faq_norm) and "tom lai" not in faq_norm:
        return False, "Thiếu mục FAQ hoặc đoạn Tóm lại."

    topic_hits = sum(1 for t in article_terms if len(t) >= 4 and t in faq_norm)
    if topic_hits < 2:
        return False, "FAQ không đủ từ khóa/chủ đề trùng với tiêu đề hoặc heading bài viết."

    art_phrases = {p for p in _OFF_TOPIC_FAQ_PHRASES if p in art_norm}
    faq_phrases = {p for p in _OFF_TOPIC_FAQ_PHRASES if p in faq_norm}
    leaked = faq_phrases - art_phrases
    if leaked:
        return False, f"FAQ lệch chủ đề — chứa «{leaked.pop()}» không có trong bài."

    for m in _FAQ_STAT_RE.finditer(faq_text):
        snippet = m.group(0).strip()
        sn_norm = normalize_vietnamese_seo_text(snippet)
        if snippet.lower() not in article_text.lower() and sn_norm not in art_norm:
            return False, "FAQ chứa số liệu/thời gian không có trong bài gốc."

    generic_phrases = (
        "day la cau hoi pho bien ve",
        "ban co the tham khao cac muc noi dung phia tren",
        "cac buoc trien khai phu hop voi nhu cau cua minh",
    )
    if sum(1 for p in generic_phrases if p in faq_norm) >= 2:
        return False, "FAQ dùng mẫu chung — không khớp nội dung bài viết."

    h3_count = len(re.findall(r"<h3\b", raw, flags=re.I))
    if h3_count < 3:
        return False, "FAQ cần ít nhất 3 câu hỏi (H3) liên quan bài viết."

    return True, ""


def _parse_faq_conclusion_response(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        obj = json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    return obj if isinstance(obj, dict) else None


def _call_faq_conclusion_ai(
    user_id: int,
    *,
    title: str,
    keyword: str,
    slug: str,
    content_html: str,
    use_system_llm: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        if use_system_llm:
            return None, "Khóa LLM hệ thống chưa được cấu hình trên server. Liên hệ quản trị."
        from app.db import SessionLocal
        from app.services.user_api_access import describe_llm_config_failure

        db = SessionLocal()
        try:
            hint = describe_llm_config_failure(db, int(user_id))
        finally:
            db.close()
        return None, hint

    headings = _outline_h2_h3(content_html)
    excerpt = _content_excerpt_for_faq(content_html)
    context = {
        "title": title,
        "focus_keyword": keyword,
        "slug": slug,
        "headings_h2_h3": headings[:20],
        "content_excerpt": excerpt,
        "instruction": (
            "Tạo FAQ + Tóm lại chỉ dựa trên context trên. "
            "Câu hỏi phải xuất phát từ heading/nội dung thực tế của bài này."
        ),
    }
    user = (
        "CONTEXT_JSON:\n"
        + json.dumps(context, ensure_ascii=False, indent=0)
        + "\n\nTrả về đúng 1 JSON object theo schema đã mô tả."
    )
    try:
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[
                    {"role": "system", "content": _FAQ_CONCLUSION_SYSTEM},
                    {"role": "user", "content": user},
                ],
                max_tokens=2000,
                timeout_sec=AI_TIMEOUT_SEC,
            )
        else:
            out = _anthropic_messages(
                cfg=cfg, system=_FAQ_CONCLUSION_SYSTEM, user=user,
                max_tokens=2000, timeout_sec=AI_TIMEOUT_SEC,
            )
        parsed = _parse_faq_conclusion_response(out)
        if not parsed:
            preview = re.sub(r"\s+", " ", str(out or ""))[:180]
            return None, f"LLM không trả JSON FAQ hợp lệ. Phản hồi: {preview or '(rỗng)'}"
        return parsed, ""
    except Exception as exc:
        msg = str(exc).strip()
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return None, f"LLM không phản hồi trong {AI_TIMEOUT_SEC} giây."
        return None, f"LLM lỗi: {msg[:220]}"


def _fix_helpful_faq_conclusion(
    *,
    user_id: int,
    title: str,
    meta_description: str,
    content_html: str,
    primary_keyword: str,
    slug: str,
    use_system_llm: bool = False,
) -> dict[str, Any]:
    """FAQ/kết luận theo ngữ cảnh bài — LLM + validate trước khi preview."""
    fid = "helpful_faq_conclusion"
    old_c = str(content_html or "")
    article_text = _content_excerpt_for_faq(old_c, max_chars=12_000)
    topic_terms = _article_topic_terms(
        title=title, keyword=primary_keyword, slug=slug, content_html=old_c,
    )

    if _content_has_faq_or_conclusion(old_c):
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Đã có FAQ hoặc kết luận — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    llm_row, llm_error = _call_faq_conclusion_ai(
        user_id,
        title=title,
        keyword=primary_keyword,
        slug=slug,
        content_html=old_c,
        use_system_llm=use_system_llm,
    )
    if not llm_row:
        return {
            "source": "llm",
            "success": False,
            "unchanged": False,
            "summary": "",
            "patches": [],
            "patch": {},
            "error": llm_error or "Không tạo được FAQ.",
            "validation_rejected": True,
        }

    status = str(llm_row.get("status") or "").strip().lower()
    if status == "no_change":
        return {
            "source": "llm",
            "success": True,
            "unchanged": True,
            "summary": str(llm_row.get("reason") or "Không cần thêm FAQ."),
            "patches": [],
            "patch": {},
        }

    new_block = str(llm_row.get("new_value") or "").strip()
    reason = str(llm_row.get("reason") or "Thêm FAQ và kết luận bám sát nội dung bài.").strip()
    try:
        confidence = max(0, min(100, int(llm_row.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0

    ok, reject_msg = _validate_faq_conclusion_html(
        faq_html=new_block,
        article_terms=topic_terms,
        article_text=article_text,
    )
    if not ok:
        return {
            "source": "llm",
            "success": False,
            "unchanged": False,
            "summary": "",
            "patches": [],
            "patch": {},
            "error": reject_msg or "FAQ lệch chủ đề — không cho áp dụng.",
            "validation_rejected": True,
        }

    new_c = old_c.rstrip() + "\n" + new_block
    needs_review = confidence < 80
    patch_row = {
        "issue_key": fid,
        "field": "content_html",
        "position": "Cuối bài — FAQ / kết luận",
        "old_value": "",
        "new_value": new_block[:12_000],
        "reason": reason,
        "confidence": confidence,
    }
    return {
        "source": "llm",
        "success": True,
        "unchanged": False,
        "summary": reason + (" · Cần kiểm tra lại trước khi áp dụng." if needs_review else ""),
        "patches": [patch_row],
        "patch": {"content_html": new_c},
        "needs_review": needs_review,
        "validation_warning": "Cần kiểm tra lại trước khi áp dụng." if needs_review else "",
        "confidence": confidence,
    }


def _content_has_faq_or_conclusion(content_html: str) -> bool:
    """Khớp logic chấm điểm helpful_faq_conclusion trong publish checklist."""
    try:
        soup = BeautifulSoup(str(content_html or "")[:800_000], "html.parser")
        body_text = soup.get_text(" ", strip=True)
        faq_re = re.compile(r"\b(faq|câu hỏi thường gặp|kết luận|tóm lại|tổng kết)\b", re.I)
        if any(faq_re.search(h.get_text(" ", strip=True)) for h in soup.find_all(["h2", "h3"])):
            return True
        return bool(re.search(r"\b(tóm lại|kết luận|tổng kết)\b", body_text[-800:], re.I))
    except Exception:
        return False


def _try_rule_title_keyword(
    *,
    title: str,
    keyword: str,
    factor_id: str = "title_keyword",
) -> dict[str, Any] | None:
    """Chèn từ khóa CHÍNH vào tiêu đề — không dùng từ khóa phụ."""
    from app.services.content_ai_publish_checklist import _kw_in_text

    fid = str(factor_id or "title_keyword").strip()
    kw = (keyword or "").strip()
    if not kw:
        return None

    old_t = str(title or "").strip()
    if _kw_in_text(old_t, kw):
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Tiêu đề đã có từ khóa chính — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    kw_use = kw[:80]
    if len(old_t) + len(kw_use) + 2 <= 65 and not old_t.lower().startswith(kw_use.lower()[:12]):
        new_t = f"{kw_use}: {old_t}"
    elif len(old_t) + len(kw_use) + 3 <= 75:
        new_t = f"{old_t} | {kw_use}"
    else:
        words = old_t.split()
        new_t = f"{kw_use}: {' '.join(words[:8])}" if words else kw_use

    if new_t == old_t or not _kw_in_text(new_t, kw):
        return None

    patches = [{
        "issue_key": fid,
        "field": "title",
        "position": "Tiêu đề",
        "old_value": old_t,
        "new_value": new_t,
        "reason": f"Chèn từ khóa chính «{kw_use}» vào tiêu đề (không dùng từ khóa phụ).",
        "confidence": 94,
    }]
    return {
        "source": "rule",
        "success": True,
        "unchanged": False,
        "summary": patches[0]["reason"],
        "patches": patches,
        "patch": {"title": new_t},
    }


def _try_rule_semantic_keywords(
    *,
    content_html: str,
    primary_keyword: str,
    secondary_keywords: list[str] | None,
) -> dict[str, Any] | None:
    sec = [str(x).strip() for x in (secondary_keywords or []) if str(x).strip()][:12]
    if not sec:
        return None

    body = str(content_html or "")
    body_norm = normalize_vietnamese_seo_text(body)
    missing = [
        s for s in sec
        if normalize_vietnamese_seo_text(s) not in body_norm and s.lower() not in body.lower()
    ]
    if not missing:
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Các từ khóa phụ đã có trong bài — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    segments = _content_segments(body)
    paras = [i for i, s in enumerate(segments) if s["tag"] == "p" and len(s["text"]) >= 45]
    if not paras:
        return None

    target_kw = missing[0]
    idx = paras[min(len(paras) // 2, len(paras) - 1)]
    target = segments[idx]
    old_html = str(target["html"])
    old_text = str(target["text"])
    suffix = f" Ngoài ra, {target_kw} cũng là khía cạnh quan trọng cần lưu ý."
    new_text = old_text.rstrip()
    if new_text and new_text[-1] not in ".!?…":
        new_text += "."
    new_text += suffix
    new_html = _wrap_plain_as_html(new_text, old_html)

    new_c, ok = _replace_in_content_html(body, old_html, new_html, hint_html=old_html)
    if not ok:
        new_c, ok = _replace_in_content_html(body, old_text, new_text, hint_html=old_html)
    if not ok:
        return None

    patch_row = {
        "issue_key": "semantic_keywords",
        "field": "content_html",
        "position": f"Đoạn giữa bài — {old_text[:60]}…",
        "old_value": old_html,
        "new_value": new_html,
        "reason": f"Chèn từ khóa phụ «{target_kw}» tự nhiên vào đoạn văn.",
        "confidence": 88,
    }
    return {
        "source": "rule",
        "success": True,
        "unchanged": False,
        "summary": patch_row["reason"],
        "patches": [patch_row],
        "patch": {"content_html": new_c},
    }


def _slugify_vn_keyword(keyword: str) -> str:
    tokens = [t for t in normalize_vietnamese_seo_text(keyword).split() if t]
    if not tokens:
        return _slugify(keyword)
    return "-".join(tokens)[:120]


def _factor_lookup(seo: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for g in seo.get("groups") or []:
        for f in g.get("factors") or []:
            fid = str(f.get("id") or "")
            if fid:
                out[fid] = {**f, "group_label": g.get("label") or ""}
    return out


def _headings_outline(content_html: str) -> list[dict[str, str]]:
    try:
        soup = BeautifulSoup(str(content_html or "")[:400_000], "html.parser")
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for el in soup.find_all(re.compile(r"^h[1-4]$", re.I)):
        rows.append({
            "level": el.name.lower(),
            "text": re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()[:300],
        })
    return rows[:40]


def _images_missing_alt(content_html: str) -> list[dict[str, str]]:
    try:
        soup = BeautifulSoup(str(content_html or "")[:400_000], "html.parser")
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        alt = str(img.get("alt") or "").strip()
        src = str(img.get("src") or "")[:200]
        if not alt:
            rows.append({"src": src, "current_alt": ""})
    return rows[:20]


def _content_segments(content_html: str) -> list[dict[str, Any]]:
    """Tách heading/đoạn để lấy ngữ cảnh trước/sau."""
    try:
        soup = BeautifulSoup(str(content_html or "")[:400_000], "html.parser")
    except Exception:
        return []
    segs: list[dict[str, Any]] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if not text and el.name not in ("h1", "h2", "h3", "h4"):
            continue
        segs.append({
            "tag": el.name.lower(),
            "text": text[:1200],
            "html": str(el)[:4000],
        })
    return segs


def _outline_h2_h3(content_html: str) -> list[dict[str, str]]:
    return [
        {"level": h["level"], "text": h["text"]}
        for h in _headings_outline(content_html)
        if h.get("level") in ("h2", "h3")
    ]


def _pick_target_segment(
    factor_id: str,
    segments: list[dict[str, Any]],
    *,
    keyword: str,
) -> int:
    fid = str(factor_id or "")
    kw = (keyword or "").strip().lower()
    if not segments:
        return -1
    if fid == "intent_h1_keyword":
        for i, s in enumerate(segments):
            if s["tag"] == "h1":
                return i
        for i, s in enumerate(segments):
            if s["tag"] in ("h2", "h3"):
                return i
        return -1
    if fid in ("heading_h2_count", "heading_hierarchy", "depth_per_section"):
        for i, s in enumerate(segments):
            if s["tag"] in ("h2", "h3"):
                return i
    if fid in ("semantic_keywords", "keyword_in_body"):
        paras = [i for i, s in enumerate(segments) if s["tag"] == "p" and len(s["text"]) >= 50]
        if paras:
            return paras[min(len(paras) // 2, len(paras) - 1)]
    if fid == "keyword_density":
        for i, s in enumerate(segments):
            if s["tag"] == "p" and len(s["text"]) >= 40 and kw and kw not in s["text"].lower():
                return i
    if fid in ("helpful_faq_conclusion", "helpful_actionable", "intent_answer_early"):
        for i in range(len(segments) - 1, -1, -1):
            if segments[i]["tag"] == "p" and len(segments[i]["text"]) > 30:
                return i
    for i, s in enumerate(segments):
        if s["tag"] != "p" or len(s["text"]) < 35:
            continue
        if kw and kw in s["text"].lower():
            continue
        return i
    for i, s in enumerate(segments):
        if s["tag"] == "p" and s["text"]:
            return i
    return 0


def _segment_context(segments: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    if idx < 0 or idx >= len(segments):
        return {}
    cur = segments[idx]
    before = segments[idx - 1]["text"][:400] if idx > 0 else ""
    after = segments[idx + 1]["text"][:400] if idx + 1 < len(segments) else ""
    pos = f"{cur['tag'].upper()}"
    if cur["tag"] in ("h2", "h3", "h4"):
        pos += f": {cur['text'][:120]}"
    else:
        pos += f" — {cur['text'][:80]}…"
    return {
        "position": pos,
        "target_tag": cur["tag"],
        "target_text": cur["text"],
        "target_html": cur["html"],
        "context_before": before,
        "context_after": after,
    }


def _factor_fix_requirement(factor: dict[str, Any]) -> str:
    parts = [
        str(factor.get("suggestion") or "").strip(),
        str(factor.get("message") or "").strip(),
    ]
    return " ".join(p for p in parts if p)[:500]


def _requires_llm_fix(factor_id: str, *, title: str, meta: str, slug: str, content_html: str, post_url: str) -> bool:
    fid = str(factor_id or "").strip()
    if fid in LLM_SEMANTIC_FACTORS:
        if fid == "links_internal":
            return count_internal_links(content_html, post_url) < 1
        if fid == "media_alt_text":
            return bool(_images_missing_alt(content_html))
        return True
    if fid in RULE_PASS_CHECK_FACTORS:
        return False
    if fid in RULE_TECHNICAL_FACTORS:
        return False
    return True


def _build_scoped_context(
    factor_id: str,
    *,
    title: str,
    meta: str,
    slug: str,
    content_html: str,
    keyword: str,
    secondary_keywords: list[str] | None,
    post_url: str,
    factor: dict[str, Any],
) -> dict[str, Any]:
    fid = str(factor_id or "").strip()
    scalar_field = FACTOR_PATCH_FIELD.get(fid)

    ctx: dict[str, Any] = {
        "issue_key": fid,
        "issue_label": factor.get("label") or fid,
        "fix_requirement": _factor_fix_requirement(factor),
        "title": title,
        "slug": slug,
        "focus_keyword": keyword,
        "secondary_keywords": list(secondary_keywords or [])[:12],
        "meta_description": meta,
        "outline_h2_h3": _outline_h2_h3(content_html),
        "wordpress_title_as_h1": bool(str(title or "").strip()),
        "post_url": post_url,
        "_full_content": str(content_html or "")[:12000],
    }

    if scalar_field:
        scalar_val = _scalar_value_for_field(scalar_field, ctx)
        ctx["target"] = {
            "field": scalar_field,
            "position": {
                "meta_description": "Meta description",
                "title": "Tiêu đề",
                "slug": "Slug",
            }.get(scalar_field, scalar_field),
            "text": scalar_val,
            "html": "",
        }
        if scalar_field == "meta_description":
            meta_len = len(str(meta or ""))
            ctx["target"]["length"] = meta_len
            ctx["target"]["recommended_length"] = "120-160"
            factor_msg = str(factor.get("message") or "").lower()
            if meta_len > 165 or "dài" in factor_msg:
                ctx["fix_requirement"] = (
                    f"{ctx['fix_requirement']} "
                    f"RÚT GỌN meta từ {meta_len} xuống 120–160 ký tự, giữ từ khóa «{keyword}», không copy đoạn trong bài."
                ).strip()
            elif meta_len < 120:
                ctx["fix_requirement"] = (
                    f"{ctx['fix_requirement']} "
                    f"Mở rộng meta lên 120–160 ký tự, thêm từ khóa «{keyword}» tự nhiên."
                ).strip()
            else:
                ctx["fix_requirement"] = (
                    f"{ctx['fix_requirement']} "
                    f"Chỉnh meta (hiện {meta_len} ký tự), thêm từ khóa «{keyword}» nếu thiếu — plain text, không HTML."
                ).strip()
        elif scalar_field == "title":
            kw_norm = normalize_vietnamese_seo_text(keyword)
            title_norm = normalize_vietnamese_seo_text(title)
            ctx["keyword_in_title"] = bool(kw_norm and kw_norm in title_norm)
            ctx["secondary_keywords"] = []
            ctx["fix_requirement"] = (
                f"{ctx['fix_requirement']} "
                f"CHỈ chèn từ khóa chính (focus_keyword): «{keyword}». "
                f"TUYỆT ĐỐI KHÔNG dùng từ khóa phụ hay chủ đề không liên quan. "
                f"Giữ ý nghĩa tiêu đề gốc, plain text, không đụng content_html."
            ).strip()
    else:
        segments = _content_segments(content_html)
        target_idx = _pick_target_segment(fid, segments, keyword=keyword)
        seg_ctx = _segment_context(segments, target_idx)
        if seg_ctx:
            ctx["target"] = {
                "position": seg_ctx.get("position"),
                "tag": seg_ctx.get("target_tag"),
                "html": seg_ctx.get("target_html"),
                "text": seg_ctx.get("target_text"),
                "context_before": seg_ctx.get("context_before"),
                "context_after": seg_ctx.get("context_after"),
            }

    if fid == "meta_quality":
        ctx["edit_scope"] = "meta_description_only"
    elif fid in ("title_keyword", "intent_title_match"):
        ctx["edit_scope"] = "title_only"
        kw_norm = normalize_vietnamese_seo_text(keyword)
        title_norm = normalize_vietnamese_seo_text(title)
        ctx["keyword_in_title"] = bool(kw_norm and kw_norm in title_norm)
        ctx["secondary_keywords"] = []
        ctx["fix_requirement"] = (
            f"{ctx['fix_requirement']} "
            f"CHỈ chèn từ khóa chính «{keyword}». "
            f"KHÔNG dùng từ khóa phụ. Không thêm cụm không liên quan đến chủ đề bài."
        ).strip()
    elif fid == "intent_h1_keyword":
        headings = _headings_outline(content_html)
        kw_norm = normalize_vietnamese_seo_text(keyword)
        title_norm = normalize_vietnamese_seo_text(title)
        ctx["edit_scope"] = "title_or_first_heading_in_content"
        ctx["all_headings"] = headings
        ctx["keyword_in_title"] = bool(kw_norm and kw_norm in title_norm)
        if headings:
            ctx["first_opening_heading"] = headings[0]
        if title and not ctx["keyword_in_title"]:
            ctx["title_patch_hint"] = (
                f"Tiêu đề WordPress đóng vai trò H1. Có thể patch field=title "
                f"để thêm «{keyword}» tự nhiên nếu heading trong content không phù hợp."
            )
    elif fid in ("heading_h2_count", "heading_hierarchy"):
        ctx["edit_scope"] = "headings_in_content"
        ctx["all_headings"] = _headings_outline(content_html)
    elif fid == "media_alt_text":
        ctx["images_missing_alt"] = _images_missing_alt(content_html)
        ctx["edit_scope"] = "image_alt_semantic"
    elif fid in ("links_internal", "links_anchor_text"):
        ctx["edit_scope"] = "internal_link_in_context"
        ctx["existing_internal_count"] = count_internal_links(content_html, post_url)
        ctx["suggested_link_hints"] = _suggested_internal_links(post_url, keyword)
    elif fid == "media_schema_blockquote":
        ctx["edit_scope"] = "schema_or_blockquote_contextual"
    elif fid == "helpful_faq_conclusion":
        ctx["edit_scope"] = "faq_conclusion_contextual"
        ctx["secondary_keywords"] = []
        ctx["content_excerpt"] = _content_excerpt_for_faq(content_html)
        ctx["article_headings"] = _outline_h2_h3(content_html)
        ctx["fix_requirement"] = (
            f"{ctx['fix_requirement']} "
            "Tạo FAQ 3–5 câu hỏi + Tóm lại CHỈ từ title/heading/content_excerpt. "
            "KHÔNG template chung, KHÔNG bịa số liệu, KHÔNG chủ đề ngoài bài."
        ).strip()
    elif fid in ("helpful_actionable", "intent_answer_early"):
        ctx["edit_scope"] = "faq_conclusion_natural"
    elif fid in ("semantic_keywords", "keyword_density", "keyword_in_body"):
        ctx["edit_scope"] = "keyword_in_paragraph_natural"
        sec = list(secondary_keywords or [])[:12]
        body_low = str(content_html or "").lower()
        missing_sec = [
            s for s in sec
            if s and s.lower() not in body_low
            and normalize_vietnamese_seo_text(s) not in normalize_vietnamese_seo_text(content_html)
        ]
        ctx["missing_secondary_keywords"] = missing_sec[:8]
        if fid == "semantic_keywords" and missing_sec:
            ctx["fix_requirement"] = (
                f"{ctx['fix_requirement']} "
                f"Chèn tự nhiên 1–2 từ khóa phụ còn thiếu ({', '.join(missing_sec[:4])}) "
                f"vào đoạn target — giữ ≥80% câu gốc, không viết lại cả đoạn intro."
            ).strip()
    else:
        ctx["edit_scope"] = "minimal_content_patch"

    return ctx


def _suggested_internal_links(post_url: str, keyword: str) -> list[dict[str, str]]:
    site = str(post_url or "").strip()
    anchor = (keyword or "xem thêm").strip()[:80]
    path = "/"
    if site:
        try:
            p = urlparse(site if "://" in site else f"https://{site}")
            path = (p.path or "/").rstrip("/") or "/"
        except Exception:
            path = "/"
    return [
        {"url": path, "anchor": anchor},
        {"url": f"{path}/blog" if path != "/" else "/blog", "anchor": f"{anchor} — danh mục"},
    ]


def _normalize_ai_patches(entries: list[dict[str, Any]], factor_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        conf = row.get("confidence")
        try:
            conf_i = max(0, min(100, int(conf))) if conf is not None else None
        except (TypeError, ValueError):
            conf_i = None
        out.append({
            "issue_key": str(row.get("issue_key") or factor_id),
            "field": str(row.get("field") or "").strip(),
            "position": str(row.get("position") or "").strip(),
            "old_value": str(row.get("old_value") if row.get("old_value") is not None else ""),
            "new_value": str(row.get("new_value") if row.get("new_value") is not None else ""),
            "reason": str(row.get("reason") or "").strip(),
            "confidence": conf_i,
        })
    return out


def _apply_patch_entries(
    *,
    title: str,
    meta: str,
    slug: str,
    content: str,
    entries: list[dict[str, Any]],
) -> tuple[str, str, str, str, list[dict[str, Any]]]:
    out_t, out_m, out_s, out_c = title, meta, slug, content
    applied: list[dict[str, Any]] = []
    for row in entries:
        field = str(row.get("field") or "").strip()
        old_v = str(row.get("old_value") if row.get("old_value") is not None else "")
        new_v = str(row.get("new_value") if row.get("new_value") is not None else "")
        reason = str(row.get("reason") or "")
        issue_key = str(row.get("issue_key") or "")
        position = str(row.get("position") or "").strip()
        confidence = row.get("confidence")
        if not field or old_v == new_v:
            continue
        entry = {
            **row,
            "field": field,
            "issue_key": issue_key,
            "reason": reason,
            "position": position,
            "confidence": confidence,
        }
        if field == "title":
            if not old_v or old_v == out_t:
                out_t = new_v
                applied.append({**entry, "field": field})
        elif field in ("meta_description", "excerpt"):
            new_plain = _strip_plain_text(new_v)[:160]
            cur_plain = _strip_plain_text(out_m)
            old_plain = _strip_plain_text(old_v) if old_v else cur_plain
            if not old_v or old_plain == cur_plain or old_v == out_m:
                out_m = new_plain
                applied.append({
                    **entry,
                    "field": "meta_description",
                    "old_value": cur_plain,
                    "new_value": new_plain,
                })
        elif field == "slug":
            if not old_v or old_v == out_s:
                out_s = new_v[:120]
                applied.append({**entry, "field": field})
        elif field == "content_html":
            if not old_v.strip() and new_v.strip():
                snippet = new_v.strip()
                if snippet not in out_c:
                    out_c = out_c.rstrip() + "\n" + snippet
                    applied.append({**entry, "field": field})
                continue
            hint_html = str(row.get("old_value") or "")
            out_c, replaced = _replace_in_content_html(out_c, old_v, new_v, hint_html=hint_html)
            if replaced:
                applied.append({**entry, "field": field})
    return out_t, out_m, out_s, out_c, applied


def _factor_snapshot(title: str, meta: str, slug: str, content: str) -> dict[str, str]:
    return {
        "title": str(title or ""),
        "meta_description": str(meta or ""),
        "slug": str(slug or ""),
        "content_html": str(content or ""),
    }


def _apply_fix_result_to_state(
    *,
    title: str,
    meta: str,
    slug: str,
    content: str,
    res: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Áp dụng patch một factor lên state tích lũy (batch «Sửa tất cả»)."""
    cur_t, cur_m, cur_s, cur_c = title, meta, slug, content
    entries = res.get("patches") or []
    if entries:
        cur_t, cur_m, cur_s, cur_c, _ = _apply_patch_entries(
            title=cur_t, meta=cur_m, slug=cur_s, content=cur_c, entries=entries,
        )
    patch = res.get("patch") or {}
    if patch.get("title") is not None:
        cur_t = str(patch["title"])
    if patch.get("meta_description") is not None:
        cur_m = str(patch["meta_description"])
    if patch.get("slug") is not None:
        cur_s = str(patch["slug"])
    if patch.get("content_html") is not None:
        cur_c = str(patch["content_html"])
    return cur_t, cur_m, cur_s, cur_c


def _rebuild_batch_change_reports(
    *,
    results: list[dict[str, Any]],
    title: str,
    meta: str,
    slug: str,
    content_html: str,
    seo_before: dict[str, Any],
    seo_after: dict[str, Any],
) -> list[dict[str, Any]]:
    """Cập nhật báo cáo từng factor sau khi gộp patch và chấm SEO cuối."""
    from app.services.cau_seo_analyzer import (
        _factor_status_improved,
        build_cau_fix_change_report,
    )

    bmap = _factor_lookup(seo_before)
    amap = _factor_lookup(seo_after)
    overall_before = int(seo_before.get("score") or 0) if seo_before.get("score") is not None else None
    overall_after = int(seo_after.get("score") or 0) if seo_after.get("score") is not None else None
    reports: list[dict[str, Any]] = []

    for res in results:
        fids = res.get("factor_ids") or []
        fid = str(fids[0] if fids else "")
        if not fid:
            continue
        b = bmap.get(fid) or {}
        a = amap.get(fid) or {}
        st_b = str(b.get("status") or "").lower()
        st_a = str(a.get("status") or "").lower()
        patch = res.get("patch") or {}
        unchanged = bool(res.get("unchanged"))
        error = str(res.get("error") or "").strip()

        if error:
            success = False
        elif unchanged:
            success = True
        elif patch:
            success = st_a == "passed" or _factor_status_improved(st_b, st_a)
        else:
            success = False

        res["seo_before"] = seo_before
        res["seo_after"] = seo_after
        res["success"] = success
        res["factor_outcomes"] = [{
            "id": fid,
            "label": a.get("label") or b.get("label") or fid,
            "status_before": st_b,
            "status_after": st_a,
            "score_before": b.get("score"),
            "score_after": a.get("score"),
            "message_after": a.get("message") or "",
        }]
        snap_b = res.get("factor_snap_before") if isinstance(res.get("factor_snap_before"), dict) else {}
        snap_a = res.get("factor_snap_after") if isinstance(res.get("factor_snap_after"), dict) else {}
        cr = build_cau_fix_change_report(
            factor_id=fid,
            before_title=str(snap_b.get("title") or title),
            before_meta=str(snap_b.get("meta_description") or meta),
            before_slug=str(snap_b.get("slug") or slug),
            before_content=str(snap_b.get("content_html") or content_html),
            fix_result=res,
        )
        if overall_before is not None:
            cr["score_before"] = overall_before
        if overall_after is not None:
            cr["score_after"] = overall_after
        res["change_report"] = cr
        reports.append(cr)
    return reports


def _try_rule_fix(
    factor_id: str,
    *,
    title: str,
    meta: str,
    slug: str,
    content_html: str,
    keyword: str,
    post_url: str,
    secondary_keywords: list[str] | None = None,
) -> dict[str, Any] | None:
    """Rule kỹ thuật: pass/kiểm tra + slug + schema/blockquote + chèn từ khóa phụ."""
    fid = str(factor_id or "").strip()
    kw = (keyword or "").strip()

    if fid == "media_schema_blockquote":
        return _try_rule_schema_blockquote(
            title=title, meta=meta, content_html=content_html, keyword=kw,
        )

    if fid in ("title_keyword", "intent_title_match"):
        return _try_rule_title_keyword(title=title, keyword=kw, factor_id=fid)

    if fid == "semantic_keywords":
        return _try_rule_semantic_keywords(
            content_html=content_html, primary_keyword=kw, secondary_keywords=secondary_keywords,
        )

    if fid == "heading_single_h1" and has_wordpress_h1(title, content_html):
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "WordPress title đóng vai trò H1 — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    if fid == "links_internal" and count_internal_links(content_html, post_url) >= 1:
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Đã có internal link hợp lệ — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    if fid == "media_alt_text" and not _images_missing_alt(content_html):
        return {
            "source": "rule",
            "success": True,
            "unchanged": True,
            "summary": "Ảnh đã có alt — không cần sửa.",
            "patches": [],
            "patch": {},
        }

    if fid == "slug_seo" and kw:
        sug = _slugify_vn_keyword(kw)
        if sug and sug != slug:
            patches = [{
                "issue_key": fid,
                "field": "slug",
                "position": "Slug",
                "old_value": slug,
                "new_value": sug,
                "reason": "Chuẩn hóa slug từ từ khóa (bỏ dấu, gạch ngang).",
                "confidence": 95,
            }]
            return {
                "source": "rule",
                "success": True,
                "unchanged": False,
                "summary": patches[0]["reason"],
                "patches": patches,
                "patch": {"slug": sug},
            }

    return None


def _call_scoped_ai(
    user_id: int,
    factor_id: str,
    scoped: dict[str, Any],
    *,
    title: str,
    meta: str,
    slug: str,
    use_system_llm: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        if use_system_llm:
            return [], "Khóa LLM hệ thống chưa được cấu hình trên server. Liên hệ quản trị."
        from app.db import SessionLocal
        from app.services.user_api_access import describe_llm_config_failure

        db = SessionLocal()
        try:
            hint = describe_llm_config_failure(db, int(user_id))
        finally:
            db.close()
        return [], hint

    allowed_field = _allowed_patch_field(factor_id, scoped) or "content_html"
    payload = json.dumps(scoped, ensure_ascii=False, indent=0)
    user = (
        f"ISSUE_KEY: {factor_id}\n"
        f"YÊU CẦU SỬA: {scoped.get('fix_requirement') or ''}\n"
        f"EDIT_SCOPE: {scoped.get('edit_scope') or ''}\n"
        f"ALLOWED_FIELD: {allowed_field}\n"
        f"BẮT BUỘC: field phải là «{allowed_field}» — không dùng content_html nếu ALLOWED_FIELD là meta/title/slug.\n\n"
        f"CONTEXT_JSON:\n{payload}\n\n"
        "Chỉ trả JSON array patch (1 phần tử). Không rewrite toàn bài. Không markdown."
    )
    try:
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[
                    {"role": "system", "content": _PATCH_SYSTEM},
                    {"role": "user", "content": user},
                ],
                max_tokens=1500,
                timeout_sec=AI_TIMEOUT_SEC,
            )
        else:
            out = _anthropic_messages(
                cfg=cfg, system=_PATCH_SYSTEM, user=user, max_tokens=1500, timeout_sec=AI_TIMEOUT_SEC,
            )
        raw = _parse_llm_json_patches(out)
        if not raw:
            preview = re.sub(r"\s+", " ", str(out or ""))[:180]
            return [], f"LLM phản hồi nhưng không đọc được JSON patch. Phản hồi: {preview or '(rỗng)'}"
        normalized = _normalize_ai_patches(raw, factor_id)
        normalized = _enforce_factor_patch_fields(factor_id, normalized, scoped)
        if not normalized:
            return [], "AI trả patch sai field hoặc không có thay đổi hợp lệ cho lỗi này."
        return _anchor_patches_to_scoped(normalized, scoped), ""
    except Exception as exc:
        msg = str(exc).strip()
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return [], f"LLM không phản hồi trong {AI_TIMEOUT_SEC} giây."
        return [], f"LLM lỗi: {msg[:220]}"


def _assemble_fix_result(
    *,
    factor_id: str,
    title: str,
    meta: str,
    slug: str,
    content_html: str,
    keyword: str,
    post_url: str,
    secondary_keywords: list[str] | None,
    seo_before: dict[str, Any],
    patch: dict[str, Any],
    patches: list[dict[str, Any]],
    source: str,
    summary: str,
    success: bool,
    unchanged: bool,
    error: str = "",
    skip_score_after: bool = False,
) -> dict[str, Any]:
    new_t = str(patch.get("title") or title)
    new_m = str(patch.get("meta_description") or meta)
    new_s = str(patch.get("slug") or slug)
    new_c = str(patch.get("content_html") or content_html)

    if skip_score_after:
        seo_after = seo_before
    elif patch:
        seo_after = evaluate_cau_modal_seo(
            title=new_t, meta_description=new_m, content_html=new_c,
            primary_keyword=keyword, slug=new_s,
            secondary_keywords=secondary_keywords, post_url=post_url,
        )
    else:
        seo_after = seo_before

    fmap = _factor_lookup(seo_before)
    amap = _factor_lookup(seo_after)
    b = fmap.get(factor_id) or {}
    a = amap.get(factor_id) or {}
    factor_outcomes = [{
        "id": factor_id,
        "label": a.get("label") or b.get("label") or factor_id,
        "status_before": b.get("status"),
        "status_after": a.get("status"),
        "score_before": b.get("score"),
        "score_after": a.get("score"),
        "message_after": a.get("message") or "",
    }]

    out: dict[str, Any] = {
        "success": success,
        "unchanged": unchanged,
        "source": source,
        "mode": "single",
        "factor_ids": [factor_id],
        "factors_targeted": [{
            "id": factor_id,
            "label": b.get("label") or factor_id,
            "status": b.get("status"),
            "group_label": b.get("group_label") or "",
        }],
        "patch": patch,
        "patches": patches,
        "summary": summary,
        "error": error,
        "seo_before": seo_before,
        "seo_after": seo_after,
        "score_delta": int(seo_after.get("score") or 0) - int(seo_before.get("score") or 0),
        "factor_outcomes": factor_outcomes,
        "markup_warnings": validate_preserved_markup(content_html, new_c) if patch.get("content_html") else [],
    }
    out["before_snapshot"] = {
        "title": title, "meta_description": meta, "slug": slug, "content_html": content_html,
    }
    out["factor_snap_before"] = {
        "title": title, "meta_description": meta, "slug": slug, "content_html": content_html,
    }
    out["factor_snap_after"] = {
        "title": new_t, "meta_description": new_m, "slug": new_s, "content_html": new_c,
    }
    out["change_report"] = build_cau_fix_change_report(
        factor_id=factor_id,
        before_title=title, before_meta=meta, before_slug=slug, before_content=content_html,
        fix_result=out,
    )
    if patches:
        out["change_report"]["patches"] = patches
        for i, item in enumerate(out["change_report"].get("items") or []):
            if i < len(patches):
                p = patches[i]
                if p.get("position"):
                    item["position"] = p["position"]
                    if not item.get("location") or item.get("location") == item.get("field"):
                        item["location"] = p["position"]
                if p.get("confidence") is not None:
                    item["confidence"] = p["confidence"]
                if p.get("reason") and not item.get("reason"):
                    item["reason"] = p["reason"]
    return out


def _attach_fix_validation_meta(result: dict[str, Any], fix_out: dict[str, Any]) -> dict[str, Any]:
    if fix_out.get("validation_rejected"):
        result["validation_rejected"] = True
    if fix_out.get("needs_review"):
        result["needs_review"] = True
        result["validation_warning"] = str(fix_out.get("validation_warning") or "")
        cr = result.get("change_report") or {}
        cr["needs_review"] = True
        cr["validation_warning"] = result["validation_warning"]
        result["change_report"] = cr
    for key in ("article_type", "article_type_label", "article_type_reason"):
        val = fix_out.get(key)
        if val:
            result[key] = val
            cr = result.get("change_report") or {}
            cr[key] = val
            result["change_report"] = cr
    return result


def fix_cau_factor_fast(
    *,
    user_id: int,
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    post_url: str = "",
    category_name: str = "",
    factor_id: str,
    use_cache: bool = True,
    skip_score_after: bool = False,
    use_system_llm: bool = False,
) -> dict[str, Any]:
    fid = str(factor_id or "").strip()
    if not fid:
        return {"success": False, "error": "Thiếu factor_id.", "unchanged": True}

    cache_key = make_fix_cache_key(
        user_id=user_id, post_url=post_url, factor_id=fid,
        title=title, meta=meta_description, slug=slug, content=content_html,
    )
    if use_cache and fid not in ("helpful_faq_conclusion", "eeat_specifics"):
        cached = get_cached_fix(cache_key)
        if cached:
            cached = dict(cached)
            cached["from_cache"] = True
            return cached

    seo_before = evaluate_cau_modal_seo(
        title=title, meta_description=meta_description, content_html=content_html,
        primary_keyword=primary_keyword, slug=slug,
        secondary_keywords=secondary_keywords, post_url=post_url,
    )
    failed, warnings = select_factors_for_autofix(seo_before, mode="single", factor_ids=[fid])
    factor = next((f for f in failed + warnings if str(f.get("id")) == fid), None)
    if not factor:
        factor = _factor_lookup(seo_before).get(fid) or {"id": fid, "label": fid}

    rule_out = _try_rule_fix(
        fid, title=title, meta=meta_description, slug=slug,
        content_html=content_html, keyword=primary_keyword, post_url=post_url,
        secondary_keywords=secondary_keywords,
    )
    if rule_out is not None:
        result = _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch=rule_out.get("patch") or {},
            patches=rule_out.get("patches") or [],
            source="rule",
            summary=str(rule_out.get("summary") or ""),
            success=bool(rule_out.get("success")),
            unchanged=bool(rule_out.get("unchanged")),
            skip_score_after=skip_score_after,
        )
        if use_cache and not rule_out.get("unchanged"):
            put_cached_fix(cache_key, {k: v for k, v in result.items() if k != "from_cache"})
        return result

    if fid == "helpful_faq_conclusion":
        faq_out = _fix_helpful_faq_conclusion(
            user_id=user_id,
            title=title,
            meta_description=meta_description,
            content_html=content_html,
            primary_keyword=primary_keyword,
            slug=slug,
            use_system_llm=use_system_llm,
        )
        result = _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch=faq_out.get("patch") or {},
            patches=faq_out.get("patches") or [],
            source=str(faq_out.get("source") or "llm"),
            summary=str(faq_out.get("summary") or ""),
            success=bool(faq_out.get("success")),
            unchanged=bool(faq_out.get("unchanged")),
            error=str(faq_out.get("error") or ""),
            skip_score_after=skip_score_after,
        )
        if faq_out.get("validation_rejected"):
            result["validation_rejected"] = True
        if faq_out.get("needs_review"):
            result["needs_review"] = True
            result["validation_warning"] = str(faq_out.get("validation_warning") or "")
            cr = result.get("change_report") or {}
            cr["needs_review"] = True
            cr["validation_warning"] = result["validation_warning"]
            result["change_report"] = cr
        return result

    if fid == "eeat_specifics":
        eeat_out = _fix_eeat_specifics(
            user_id=user_id,
            title=title,
            content_html=content_html,
            primary_keyword=primary_keyword,
            slug=slug,
            post_url=post_url,
            category=category_name,
            use_system_llm=use_system_llm,
        )
        result = _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch=eeat_out.get("patch") or {},
            patches=eeat_out.get("patches") or [],
            source=str(eeat_out.get("source") or "llm"),
            summary=str(eeat_out.get("summary") or ""),
            success=bool(eeat_out.get("success")),
            unchanged=bool(eeat_out.get("unchanged")),
            error=str(eeat_out.get("error") or ""),
            skip_score_after=skip_score_after,
        )
        return _attach_fix_validation_meta(result, eeat_out)

    if fid == "semantic_keywords":
        sec = [str(x).strip() for x in (secondary_keywords or []) if str(x).strip()]
        if not sec:
            return _assemble_fix_result(
                factor_id=fid, title=title, meta=meta_description, slug=slug,
                content_html=content_html, keyword=primary_keyword, post_url=post_url,
                secondary_keywords=secondary_keywords, seo_before=seo_before,
                patch={}, patches=[], source="rule",
                summary="",
                success=False, unchanged=False,
                error="Chưa có từ khóa phụ trong Brief. Hãy thêm từ khóa phụ/ngữ nghĩa ở Brief rồi bấm «Sửa bằng AI» lại.",
                skip_score_after=skip_score_after,
            )

    if not _requires_llm_fix(
        fid, title=title, meta=meta_description, slug=slug,
        content_html=content_html, post_url=post_url,
    ):
        return _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch={}, patches=[], source="rule",
            summary="Không cần sửa thêm cho yếu tố kỹ thuật này.",
            success=True, unchanged=True, skip_score_after=skip_score_after,
        )

    scoped = _build_scoped_context(
        fid, title=title, meta=meta_description, slug=slug,
        content_html=content_html, keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
        post_url=post_url, factor=factor,
    )
    ai_entries, llm_error = _call_scoped_ai(
        user_id, fid, scoped, title=title, meta=meta_description, slug=slug,
        use_system_llm=use_system_llm,
    )
    if not ai_entries:
        return _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch={}, patches=[],
            source="llm", summary="", success=False, unchanged=False,
            error=llm_error or f"LLM không phản hồi trong {AI_TIMEOUT_SEC} giây hoặc chưa cấu hình.",
            skip_score_after=skip_score_after,
        )

    new_t, new_m, new_s, new_c, applied = _apply_patch_entries(
        title=title, meta=meta_description, slug=slug, content=content_html,
        entries=ai_entries,
    )
    if not applied:
        return _assemble_fix_result(
            factor_id=fid, title=title, meta=meta_description, slug=slug,
            content_html=content_html, keyword=primary_keyword, post_url=post_url,
            secondary_keywords=secondary_keywords, seo_before=seo_before,
            patch={}, patches=ai_entries,
            source="llm", summary="", success=False, unchanged=True,
            error="AI đề xuất thay đổi nhưng không khớp vị trí trong bài HTML.",
            skip_score_after=skip_score_after,
        )

    patch: dict[str, Any] = {}
    if new_t != title:
        patch["title"] = new_t
    if new_m != meta_description:
        patch["meta_description"] = new_m
    if new_s != slug:
        patch["slug"] = new_s
    if new_c != content_html:
        patch["content_html"] = new_c

    unchanged = not patch
    st_after = "passed"
    if not unchanged and not skip_score_after:
        seo_check = evaluate_cau_modal_seo(
            title=new_t, meta_description=new_m, content_html=new_c,
            primary_keyword=primary_keyword, slug=new_s,
            secondary_keywords=secondary_keywords, post_url=post_url,
        )
        row = _factor_lookup(seo_check).get(fid) or {}
        st_after = str(row.get("status") or "").lower()

    result = _assemble_fix_result(
        factor_id=fid, title=title, meta=meta_description, slug=slug,
        content_html=content_html, keyword=primary_keyword, post_url=post_url,
        secondary_keywords=secondary_keywords, seo_before=seo_before,
        patch=patch, patches=applied or ai_entries,
        source="llm",
        summary=applied[0].get("reason") if applied else (ai_entries[0].get("reason") if ai_entries else "LLM patch"),
        success=not unchanged and st_after == "passed",
        unchanged=unchanged,
        error="" if not unchanged else "AI không thay đổi nội dung.",
        skip_score_after=skip_score_after,
    )
    if skip_score_after and unchanged:
        result["seo_after"] = seo_before

    if use_cache and not unchanged:
        put_cached_fix(cache_key, {k: v for k, v in result.items() if k != "from_cache"})
    return result


def fix_cau_factors_parallel(
    *,
    user_id: int,
    factor_ids: list[str],
    title: str = "",
    meta_description: str = "",
    content_html: str = "",
    primary_keyword: str = "",
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    post_url: str = "",
    category_name: str = "",
    max_workers: int = 4,
    use_system_llm: bool = False,
) -> dict[str, Any]:
    """Sửa nhiều lỗi tuần tự trên state tích lũy — chấm SEO 1 lần cuối."""
    del max_workers  # giữ tham số API; xử lý tuần tự để gộp patch đúng
    ids = [str(x).strip() for x in factor_ids if str(x).strip()]
    if not ids:
        return {"success": False, "error": "Không có factor_id.", "results": []}

    seo_before = evaluate_cau_modal_seo(
        title=title, meta_description=meta_description, content_html=content_html,
        primary_keyword=primary_keyword, slug=slug,
        secondary_keywords=secondary_keywords, post_url=post_url,
    )
    results: list[dict[str, Any]] = []
    all_patches: list[dict[str, Any]] = []
    cur_t, cur_m, cur_s, cur_c = title, meta_description, slug, content_html

    for fid in ids:
        snap_before = _factor_snapshot(cur_t, cur_m, cur_s, cur_c)
        try:
            res = fix_cau_factor_fast(
                user_id=user_id, title=cur_t, meta_description=cur_m,
                content_html=cur_c, primary_keyword=primary_keyword,
                slug=cur_s, secondary_keywords=secondary_keywords,
                post_url=post_url, factor_id=fid, use_cache=True, skip_score_after=True,
                use_system_llm=use_system_llm, category_name=category_name,
            )
        except Exception as exc:
            res = {
                "success": False, "factor_ids": [fid], "error": str(exc)[:200],
                "unchanged": True, "patch": {},
            }
        cur_t, cur_m, cur_s, cur_c = _apply_fix_result_to_state(
            title=cur_t, meta=cur_m, slug=cur_s, content=cur_c, res=res,
        )
        res["factor_snap_before"] = snap_before
        res["factor_snap_after"] = _factor_snapshot(cur_t, cur_m, cur_s, cur_c)
        results.append(res)
        all_patches.extend(res.get("patches") or [])

    merged_patch: dict[str, Any] = {}
    if cur_t != title:
        merged_patch["title"] = cur_t
    if cur_m != meta_description:
        merged_patch["meta_description"] = cur_m
    if cur_s != slug:
        merged_patch["slug"] = cur_s
    if cur_c != content_html:
        merged_patch["content_html"] = cur_c

    seo_after = evaluate_cau_modal_seo(
        title=cur_t, meta_description=cur_m, content_html=cur_c,
        primary_keyword=primary_keyword, slug=cur_s,
        secondary_keywords=secondary_keywords, post_url=post_url,
    )

    change_reports = _rebuild_batch_change_reports(
        results=results,
        title=title,
        meta=meta_description,
        slug=slug,
        content_html=content_html,
        seo_before=seo_before,
        seo_after=seo_after,
    )
    return {
        "success": bool(merged_patch),
        "results": results,
        "patch": merged_patch,
        "patches": all_patches,
        "seo_before": seo_before,
        "seo_after": seo_after,
        "change_reports": change_reports,
        "score_delta": int(seo_after.get("score") or 0) - int(seo_before.get("score") or 0),
        "before_snapshot": {
            "title": title, "meta_description": meta_description,
            "slug": slug, "content_html": content_html,
        },
    }
