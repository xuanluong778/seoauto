"""
Chấm điểm bài đích & gợi ý anchor — theo quy trình internal link chuẩn SEO (Content AI).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.content_draft_builder import detect_search_intent

# Anchor chung chung — không dùng (mục 3.2 sơ đồ tri thức)
_BAD_ANCHOR_PATTERNS = (
    re.compile(r"^xem\s*thêm\.?$", re.I),
    re.compile(r"^tại\s*đây\.?$", re.I),
    re.compile(r"^click\s*(vào\s*)?đây\.?$", re.I),
    re.compile(r"^bài\s*viết\s*này\.?$", re.I),
    re.compile(r"^đọc\s*tiếp\.?$", re.I),
    re.compile(r"^link\s*này\.?$", re.I),
    re.compile(r"^nguồn\s*này\.?$", re.I),
    re.compile(r"^here$", re.I),
    re.compile(r"^click\s*here\.?$", re.I),
    re.compile(r"^read\s*more\.?$", re.I),
)

_MONEY_PATH = re.compile(
    r"/(dich-vu|dịch-vụ|service|services|bao-gia|báo-giá|pricing|mua-|san-pham|sản-phẩm|"
    r"product|shop|khoa-hoc|khóa-học|course|dang-ky|đăng-ký|tu-van|tư-vấn|lien-he|liên-hệ)/",
    re.I,
)
_SERVICE_PATH = re.compile(
    r"/(dich-vu|dịch-vụ|service|services|giai-phap|giải-pháp|thue-|thuê-|lam-|làm-)/",
    re.I,
)
_PILLAR_HINT = re.compile(
    r"\b(pillar|trụ cột|tổng hợp|toàn diện|hướng dẫn đầy đủ|complete guide|"
    r"ultimate guide|a-z|từ a đến z)\b",
    re.I,
)

_WEAK_TITLE_WORDS = {
    "nhung", "những", "cach", "cách", "hướng", "dẫn", "guide", "top", "các", "một", "cho",
    "và", "của", "theo", "khi", "này", "đó", "seo", "là", "gì",
}


def _fold_vi(s: str) -> str:
    t = unicodedata.normalize("NFD", str(s or ""))
    folded = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded).casefold().strip()


def _topic_tokens(seed: str) -> set[str]:
    stop = {
        "và", "của", "cho", "với", "là", "có", "được", "trong", "này", "đó", "các", "một",
        "the", "for", "with", "from", "that", "this", "your", "you", "are", "was", "will",
    }
    return {
        w
        for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", str(seed or "").lower())
        if w not in stop
    }


def is_bad_anchor(text: str) -> bool:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if len(t) < 2:
        return True
    for pat in _BAD_ANCHOR_PATTERNS:
        if pat.match(t):
            return True
    low = t.casefold()
    if low in {"xem thêm", "tại đây", "click vào đây", "bài viết này", "đọc tiếp", "link này"}:
        return True
    return False


def classify_target_page_type(*, url: str, title: str = "", categories: list[str] | None = None) -> str:
    """money_page | service | pillar | course | blog | category | other"""
    try:
        path = (urlparse(str(url or "").strip()).path or "/").lower()
    except Exception:
        path = "/"
    blob = f"{path} {title} {' '.join(categories or [])}".lower()
    if _MONEY_PATH.search(path) or any(
        x in blob for x in ("báo giá", "bao gia", "đặt mua", "mua ngay", "pricing")
    ):
        return "money_page"
    if re.search(r"/(khoa-hoc|khóa-học|course|hoc-|học-)/", path, re.I) or "khóa học" in blob:
        return "course"
    if _SERVICE_PATH.search(path) or "dịch vụ" in blob or "dich vu" in blob:
        return "service"
    if _PILLAR_HINT.search(title) or any(
        x in blob for x in ("pillar", "trụ cột", "tổng hợp", "toàn diện")
    ):
        return "pillar"
    if any(x in path for x in ("/category/", "/chuyen-muc/", "/tag/", "/tu-khoa/")):
        return "category"
    return "blog"


def _intent_norm(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if "commercial" in s:
        return "commercial"
    if "transaction" in s:
        return "transactional"
    if "navigat" in s:
        return "navigational"
    return "informational"


def _intent_match_score(article_intent: str, target_intent: str, target_page_type: str) -> float:
    ai = _intent_norm(article_intent)
    ti = _intent_norm(target_intent)
    if ai == ti:
        return 1.0
    pairs = {
        ("transactional", "commercial"),
        ("commercial", "transactional"),
        ("informational", "commercial"),
    }
    if (ai, ti) in pairs:
        return 0.65
    if ai == "transactional" and target_page_type in {"money_page", "service", "course"}:
        return 0.85
    if ai == "informational" and target_page_type in {"blog", "pillar"}:
        return 0.75
    return 0.35


def find_anchor_phrase_in_content(content_html: str, post: dict) -> str:
    """Cụm trong HTML khớp title/tag/category/slug — casing gốc."""
    raw_html = str(content_html or "").strip()
    if not raw_html or not isinstance(post, dict):
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    body_text_raw = soup.get_text(" ", strip=True)
    body_lower = body_text_raw.lower()
    if not body_lower.strip():
        return ""

    title = BeautifulSoup(str(post.get("title") or ""), "html.parser").get_text(" ", strip=True)
    title_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", title)

    for n in (6, 5, 4, 3, 2):
        for i in range(0, max(0, len(title_words) - n + 1)):
            cand = " ".join(title_words[i : i + n]).strip()
            if len(cand) < 6:
                continue
            if all(w.lower() in _WEAK_TITLE_WORDS for w in cand.split()):
                continue
            idx = body_lower.find(cand.lower())
            if idx >= 0:
                return body_text_raw[idx : idx + len(cand)]

    for label in list(post.get("category_names") or []) + list(post.get("tag_names") or []):
        phrase = BeautifulSoup(str(label or ""), "html.parser").get_text(" ", strip=True).strip()
        if len(phrase) < 4:
            continue
        idx = body_lower.find(phrase.lower())
        if idx >= 0:
            return body_text_raw[idx : idx + len(phrase)]

    slug_raw = str(post.get("slug") or "").strip().strip("/")
    for slug_try in (slug_raw.replace("-", " "), slug_raw):
        if len(slug_try) < 6:
            continue
        idx = body_lower.find(slug_try.lower())
        if idx >= 0:
            return body_text_raw[idx : idx + len(slug_try)]
    return ""


def _shorten_anchor_from_title(title: str, *, max_words: int = 8) -> str:
    words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", str(title or ""))
    kept: list[str] = []
    for w in words:
        if w.lower() in _WEAK_TITLE_WORDS and len(kept) >= 2:
            continue
        kept.append(w)
        if len(kept) >= max_words:
            break
    out = " ".join(kept).strip()
    return out[:80] if out else ""


def suggest_natural_anchor(
    *,
    post: dict,
    content_html: str = "",
    focus_keyword: str = "",
) -> str:
    """
    Ưu tiên cụm đã có trong bài → focus keyword bài đích → rút gọn tiêu đề (2–8 từ).
    """
    in_body = find_anchor_phrase_in_content(content_html, post)
    if in_body and not is_bad_anchor(in_body) and 2 <= len(in_body.split()) <= 10:
        return in_body.strip()[:80]

    fk = str(focus_keyword or post.get("focus_keyword") or "").strip()
    if fk and not is_bad_anchor(fk):
        return fk[:80]

    title = str(post.get("title") or "").strip()
    if "|" in title:
        title = title.split("|")[0].strip()
    short = _shorten_anchor_from_title(title)
    if short and not is_bad_anchor(short):
        return short

    slug_phrase = str(post.get("slug") or "").replace("-", " ").strip()
    if slug_phrase and not is_bad_anchor(slug_phrase):
        return slug_phrase[:80]
    return short or title[:80]


def sanitize_anchor(anchor: str, *, post: dict | None = None, content_html: str = "") -> str:
    """Loại anchor xấu; thay bằng suggested nếu cần."""
    raw = str(anchor or "").strip()
    if raw and not is_bad_anchor(raw):
        return raw[:80]
    return suggest_natural_anchor(post=post or {}, content_html=content_html)


def compute_relevance_score(
    *,
    post: dict,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    article_search_intent: str = "",
    content_plain: str = "",
    topic_tokens: set[str] | None = None,
) -> dict[str, Any]:
    """
    Điểm 0–100 theo sơ đồ: chủ đề, keyword/entity, category/tag, intent, giá trị trang, ngữ cảnh.
    """
    if not isinstance(post, dict):
        return {"relevance_score": 0, "priority": "low", "page_type": "other", "anchor_in_body": False}

    title = str(post.get("title") or "").lower()
    cats = " ".join(str(c) for c in (post.get("category_names") or [])).lower()
    tags = " ".join(str(t) for t in (post.get("tag_names") or [])).lower()
    slug = str(post.get("slug") or "").replace("-", " ").lower()
    url = str(post.get("link") or post.get("target_url") or "")
    page_type = classify_target_page_type(
        url=url,
        title=str(post.get("title") or ""),
        categories=list(post.get("category_names") or []),
    )

    seed = f"{article_primary_keyword} {article_secondary_keywords} {content_plain[:2000]}"
    topic = topic_tokens if topic_tokens is not None else _topic_tokens(seed)
    target_intent = detect_search_intent(
        str(post.get("focus_keyword") or article_primary_keyword or title[:80])
    )
    art_intent = article_search_intent or detect_search_intent(article_primary_keyword)

    # 30% chủ đề (overlap title + slug)
    topic_hits = sum(1 for t in topic if t in title or t in slug)
    topic_ratio = min(1.0, topic_hits / max(3, len(topic) * 0.35)) if topic else 0.0
    topic_pts = 30.0 * topic_ratio

    # 20% keyword / entity
    fk = str(post.get("focus_keyword") or "").strip().lower()
    kw_blob = f"{title} {cats} {tags} {fk}"
    kw_hits = sum(1 for t in topic if t in kw_blob)
    if article_primary_keyword and _fold_vi(article_primary_keyword) in _fold_vi(kw_blob):
        kw_hits += 2
    kw_ratio = min(1.0, kw_hits / max(2, len(topic) * 0.4)) if topic else 0.2
    kw_pts = 20.0 * kw_ratio

    # 15% category / tag
    cat_pts = 0.0
    plain_fold = _fold_vi(content_plain)
    for c in post.get("category_names") or []:
        if len(str(c)) >= 3 and _fold_vi(str(c)) in plain_fold:
            cat_pts = 15.0
            break
    if cat_pts < 15.0:
        for tg in post.get("tag_names") or []:
            if len(str(tg)) >= 4 and _fold_vi(str(tg)) in plain_fold:
                cat_pts = 12.0
                break
        if cat_pts == 0.0 and topic:
            if any(t in cats or t in tags for t in topic):
                cat_pts = 8.0

    # 15% search intent
    intent_pts = 15.0 * _intent_match_score(art_intent, target_intent, page_type)

    # 10% giá trị SEO / chuyển đổi (money, service, pillar)
    value_map = {
        "money_page": 10.0,
        "service": 9.0,
        "course": 8.5,
        "pillar": 8.0,
        "blog": 5.0,
        "category": 4.0,
        "other": 3.0,
    }
    value_pts = value_map.get(page_type, 3.0)
    if _intent_norm(art_intent) == "transactional" and page_type in {"money_page", "service", "course"}:
        value_pts = min(10.0, value_pts + 1.5)

    # 10% ngữ cảnh (cụm bài đích xuất hiện trong content)
    ctx_pts = 0.0
    anchor_in_body = False
    if content_plain:
        for ph in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{4,}", title):
            if _fold_vi(ph) in plain_fold:
                ctx_pts += 2.5
        if _fold_vi(title[:60]) in plain_fold:
            ctx_pts += 4.0
        anchor_in_body = bool(find_anchor_phrase_in_content(
            f"<p>{content_plain}</p>" if "<" not in content_plain[:20] else content_plain,
            post,
        ))
        if anchor_in_body:
            ctx_pts = 10.0
    ctx_pts = min(10.0, ctx_pts)

    total = int(round(min(100.0, topic_pts + kw_pts + cat_pts + intent_pts + value_pts + ctx_pts)))
    if total >= 80:
        priority = "high"
    elif total >= 60:
        priority = "medium"
    else:
        priority = "low"

    return {
        "relevance_score": total,
        "priority": priority,
        "page_type": page_type,
        "target_search_intent": _intent_norm(target_intent),
        "article_search_intent": _intent_norm(art_intent),
        "anchor_in_body": anchor_in_body,
        "score_breakdown": {
            "topic": round(topic_pts, 1),
            "keyword": round(kw_pts, 1),
            "category_tag": round(cat_pts, 1),
            "intent": round(intent_pts, 1),
            "page_value": round(value_pts, 1),
            "context": round(ctx_pts, 1),
        },
    }
