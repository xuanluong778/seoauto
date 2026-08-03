from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values

_BLOCKED_URL_RE = re.compile(
    r"(favicon|sprite|logo|icon|emoji|avatar|profile|banner-ad|/ads/|"
    r"pixel|tracking|spacer|1x1|button\.|badge|wallpaper|meme|"
    r"giphy\.com|tenor\.com|pinterest\.[a-z]+/pin|"
    r"alamy\.com|shutterstock|gettyimages|istockphoto|"
    r"twimg\.com/profile|facebook\.com/photo\.php)",
    re.I,
)
_STOPWORDS = frozenset(
    "và của cho với trong là có được không các một bạn chúng tôi "
    "the this that from with your our for are was will".split()
)


@lru_cache(maxsize=1)
def _env_local() -> dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "env.local"
    if not p.is_file():
        return {}
    return {str(k): str(v or "") for k, v in (dotenv_values(p) or {}).items() if k}


def _getenv(name: str) -> str:
    return str((os.getenv(name) or _env_local().get(name) or "")).strip()


def keyword_tokens(text: str, *, min_len: int = 3) -> list[str]:
    raw = re.sub(r"[^\w\s\u00c0-\u1ef9-]", " ", str(text or "").lower())
    out: list[str] = []
    seen: set[str] = set()
    for w in raw.split():
        if len(w) < min_len or w in _STOPWORDS:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def is_blocked_image_url(url: str) -> bool:
    u = str(url or "").strip().lower()
    if not u.startswith("http"):
        return True
    if _BLOCKED_URL_RE.search(u):
        return True
    if re.search(r"\.(svg|gif)(\?|$)", u) and "gif" in u:
        if "thumbnail" not in u and "photo" not in u:
            return True
    return False


_GENERIC_BRAND_NOISE_RE = re.compile(
    r"(google\s*pay|g\s*pay|google\s*logo|googlegemini|wooden.{0,24}google|"
    r"google\s*search\s*(homepage|page)|alphabet\s*inc|play\s*store)",
    re.I,
)
_IRRELEVANT_NOISE_RE = re.compile(
    r"(lượng\s*tử|quantum|google\s*pay|wooden.{0,20}google|gemini\s*logo|"
    r"homepage|play\s*store|celebrity|meme)",
    re.I,
)


def _keyword_semantic_not_brand(keyword: str) -> bool:
    kw = str(keyword or "").lower()
    hints = (
        "thuật toán", "algorithm", "seo", "tối ưu", "ranking", "hướng dẫn",
        "là gì", "cách ", "chiến lược", "minh họa", "sơ đồ", "diagram",
    )
    return any(h in kw for h in hints)


def is_generic_brand_noise_image(item: dict[str, Any], keyword: str) -> bool:
    """Ảnh logo/homepage thương hiệu không phù hợp khi chủ đề là khái niệm SEO."""
    if not _keyword_semantic_not_brand(keyword):
        return False
    blob = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("link") or ""),
            str(item.get("context") or ""),
        ]
    ).lower()
    if _GENERIC_BRAND_NOISE_RE.search(blob):
        return True
    kw_tokens = keyword_tokens(keyword, min_len=4)
    non_brand = [t for t in kw_tokens if t not in ("google", "gmail", "youtube")]
    if non_brand and "google" in blob:
        return not any(t in blob for t in non_brand[:4])
    return False


def score_image_relevance(item: dict[str, Any], terms: list[str]) -> float:
    blob = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("link") or ""),
            str(item.get("alt") or ""),
            str(item.get("context") or ""),
        ]
    ).lower()
    if is_blocked_image_url(str(item.get("link") or "")):
        return -100.0

    all_tokens: list[str] = []
    for term in terms:
        all_tokens.extend(keyword_tokens(term, min_len=4))

    if not all_tokens:
        return 0.0

    score = 0.0
    matched = 0
    for tok in all_tokens:
        if tok in blob:
            matched += 1
            score += 8.0 if len(tok) >= 6 else 5.0

    ratio = matched / max(len(all_tokens), 1)
    score += ratio * 20.0

    # Phải khớp ít nhất 1 token quan trọng (>=4 ký tự)
    important = [t for t in all_tokens if len(t) >= 4]
    if important and not any(t in blob for t in important):
        score *= 0.25

    primary = str(terms[0] or "").strip() if terms else ""
    if _keyword_semantic_not_brand(primary) and _GENERIC_BRAND_NOISE_RE.search(blob):
        score -= 55.0
    if _keyword_semantic_not_brand(primary) and _IRRELEVANT_NOISE_RE.search(blob):
        score -= 40.0

    kw_tokens = keyword_tokens(primary, min_len=4)
    non_brand = [t for t in kw_tokens if t not in ("google", "gmail", "youtube")]
    if non_brand and "google" in blob.lower():
        if not any(t in blob for t in non_brand[:4]):
            score -= 35.0

    kw_low = primary.lower()
    concept_boosts: tuple[str, ...] = ()
    if "thuật toán" in kw_low:
        concept_boosts = ("algorithm", "ranking", "diagram", "flowchart", "infographic", "analytics", "search engine")
    elif "seo" in kw_low or "tối ưu" in kw_low:
        concept_boosts = ("seo", "optimization", "ranking", "analytics", "dashboard", "marketing", "search engine")
    hits = sum(1 for term in concept_boosts if term in blob)
    if hits:
        score += hits * 10.0

    return score


_OFF_TOPIC_IMAGE_RE = re.compile(
    r"(formula\s*[_\s-]?1|\bf1\b|grand\s+prix|nascar|motorsport|"
    r"race\s*car|racing\s+track|motorsport|football\s+stadium|"
    r"wedding\s+ceremony|beach\s+vacation|night\s+skyline|fireworks)",
    re.I,
)

MIN_RELEVANCE_SCORE = 14.0
WEB_IMAGE_MIN_SCORE = MIN_RELEVANCE_SCORE * 0.55


def _expand_relevance_terms(terms: list[str]) -> list[str]:
    blob = " ".join(terms).lower()
    extra: list[str] = []
    if re.search(r"sửa|repair|máy tính|may tinh|laptop|computer|pc", blob):
        extra.extend(["repair", "computer", "laptop", "technician", "workshop", "it"])
    if re.search(r"seo|content|blog", blob):
        extra.extend(["seo", "content", "marketing", "blog", "writing"])
    out = list(terms)
    out.extend(extra)
    return out


def filter_and_rank_web_images(
    items: list[dict[str, Any]],
    *,
    primary_keyword: str = "",
    title: str = "",
    h2_heading: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Lọc ảnh lệch chủ đề (đua xe, wedding…) và xếp theo điểm liên quan."""
    terms = [
        re.sub(r"\s+", " ", str(t or "").strip())
        for t in (
            primary_keyword,
            str(title or "").split("|", 1)[0].strip() if title else "",
            h2_heading,
        )
        if str(t or "").strip()
    ]
    terms = _expand_relevance_terms(terms)
    n = max(1, min(int(limit or 12), 20))
    pool: list[dict[str, Any]] = []
    for it in items:
        link = str(it.get("link") or "").strip()
        if not link or is_blocked_image_url(link):
            continue
        blob = " ".join(
            [
                str(it.get("title") or ""),
                str(it.get("link") or ""),
                str(it.get("context") or ""),
            ]
        )
        sc = score_image_relevance(it, terms)
        if _OFF_TOPIC_IMAGE_RE.search(blob) and sc < MIN_RELEVANCE_SCORE:
            continue
        if sc < WEB_IMAGE_MIN_SCORE:
            continue
        it2 = dict(it)
        it2["_relevance_score"] = sc
        pool.append(it2)

    if not pool:
        for it in items:
            link = str(it.get("link") or "").strip()
            if not link or is_blocked_image_url(link):
                continue
            blob = " ".join(
                [
                    str(it.get("title") or ""),
                    str(it.get("link") or ""),
                    str(it.get("context") or ""),
                ]
            )
            if _OFF_TOPIC_IMAGE_RE.search(blob):
                continue
            sc = score_image_relevance(it, terms)
            it2 = dict(it)
            it2["_relevance_score"] = sc
            pool.append(it2)

    pool.sort(key=lambda x: -float(x.get("_relevance_score") or 0))
    out: list[dict[str, Any]] = []
    for it in pool[:n]:
        clean = {k: v for k, v in it.items() if not str(k).startswith("_")}
        out.append(clean)
    return out


def build_stock_photo_english_query(
    *,
    primary_keyword: str = "",
    title: str = "",
    section_heading: str = "",
) -> str:
    """Câu truy vấn tiếng Anh cho Pexels/SerpAPI khi từ khóa VI khó khớp."""
    blob = " ".join(
        [
            str(primary_keyword or ""),
            str(title or "").split("|", 1)[0],
            str(section_heading or ""),
        ]
    ).lower()
    rules: list[tuple[str, str]] = [
        (r"sửa.*(máy tính|may tinh|pc|computer|laptop)", "computer repair technician workshop"),
        (r"(máy tính|may tinh|laptop|pc).*(sửa|repair)", "laptop repair service technician"),
        (r"sửa.*(điện thoại|dien thoai|iphone|smartphone)", "smartphone repair technician"),
        (r"(seo|content marketing|blog)", "SEO content marketing workspace"),
        (r"(kỹ thuật|ky thuat|it support)", "IT support technician office"),
    ]
    for pat, eng in rules:
        if re.search(pat, blob, re.I):
            return eng
    tokens = keyword_tokens(primary_keyword or title, min_len=4)
    if tokens:
        return " ".join(tokens[:6]) + " professional photo"
    return ""


def _openai_chat(*, system: str, user: str, max_tokens: int = 200) -> str:
    key = _getenv("OPENAI_API_KEY")
    if not key:
        return ""
    model = _getenv("OPENAI_MODEL") or "gpt-4o-mini"
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=35,
        )
    except Exception:
        return ""
    if r.status_code >= 400:
        return ""
    try:
        data = r.json()
        msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        return str(msg.get("content") or "").strip()
    except Exception:
        return ""


def build_llm_image_search_query(
    *,
    primary_keyword: str,
    title: str = "",
    section_heading: str = "",
    section_content: str = "",
) -> str:
    """Tạo câu truy vấn ảnh ngắn, sát chủ đề (ưu tiên tiếng Việt)."""
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    h2 = re.sub(r"\s+", " ", str(section_heading or "").strip())
    t = re.sub(r"\s+", " ", str(title or "").split("|", 1)[0].strip())
    section = re.sub(r"\s+", " ", str(section_content or "").strip())[:280]

    if h2 and section:
        base = f"{pk} {h2} {section[:80]}".strip()
    elif h2 and pk:
        base = f"{pk} {h2}"
    elif pk:
        base = pk
    elif h2:
        base = h2
    else:
        base = t or "dịch vụ"

    system = (
        "Bạn tạo 1 câu tìm kiếm ảnh minh họa cho bài blog SEO tiếng Việt. "
        "Chỉ trả về đúng 1 câu 4-12 từ, không dấu ngoặc, không giải thích. "
        "Ảnh phải là photo/diagram thật liên quan chủ đề bài viết. "
        "KHÔNG tìm logo Google, Google Pay, homepage Google, ảnh gỗ chữ GOOGLE, văn phòng generic. "
        "Ưu tiên: sơ đồ, infographic, minh họa khái niệm, dashboard SEO phù hợp từ khóa."
    )
    user = (
        f"Từ khóa chính: {pk}\nTiêu đề bài: {t}\n"
        f"Mục trong bài: {h2 or '(ảnh đại diện)'}\n"
        f"Nội dung đoạn: {section or '(chưa có)'}"
    )
    llm_q = _openai_chat(system=system, user=user, max_tokens=60)
    llm_q = re.sub(r"^[\"'“”]+|[\"'“”]+$", "", llm_q).strip()
    if 4 <= len(llm_q) <= 120:
        return llm_q[:120]
    return base[:120]


def pick_best_image_candidate(
    candidates: list[dict[str, Any]],
    *,
    primary_keyword: str,
    title: str = "",
    section_heading: str = "",
    section_content: str = "",
) -> dict[str, Any] | None:
    terms = [
        primary_keyword,
        title.split("|", 1)[0].strip() if title else "",
        section_heading,
        section_content[:200] if section_content else "",
    ]
    terms = [re.sub(r"\s+", " ", t).strip() for t in terms if t]

    pool: list[dict[str, Any]] = []
    for it in candidates:
        link = str(it.get("link") or "").strip()
        if not link or is_blocked_image_url(link):
            continue
        sc = score_image_relevance(it, terms)
        it2 = dict(it)
        it2["_relevance_score"] = sc
        if sc >= MIN_RELEVANCE_SCORE * 0.5:
            pool.append(it2)

    if not pool:
        return None

    pool.sort(key=lambda x: -float(x.get("_relevance_score") or 0))
    top = pool[:10]

    if float(top[0].get("_relevance_score") or 0) >= MIN_RELEVANCE_SCORE * 1.8:
        return top[0]

    if not _getenv("OPENAI_API_KEY"):
        return top[0] if float(top[0].get("_relevance_score") or 0) >= MIN_RELEVANCE_SCORE else None

    lines = []
    for i, it in enumerate(top):
        lines.append(
            f"{i}. title={str(it.get('title') or '')[:100]} | url={str(it.get('link') or '')[:80]}"
        )
    ctx = (
        f"Từ khóa: {primary_keyword}\nTiêu đề: {title}\nMục: {section_heading or 'ảnh đại diện'}\n"
        f"Đoạn văn: {(section_content or '')[:300]}\n"
        f"Chọn 1 ảnh PHÙ HỢP NHẤT (photo minh họa đúng chủ đề). Trả JSON: {{\"index\": 0}}\n"
        f"Nếu không có ảnh phù hợp: {{\"index\": -1}}\n\n"
        + "\n".join(lines)
    )
    raw = _openai_chat(
        system="Chỉ trả JSON hợp lệ, không markdown.",
        user=ctx,
        max_tokens=40,
    )
    idx = -1
    try:
        m = re.search(r"\{[^{}]*\}", raw)
        if m:
            idx = int(json.loads(m.group(0)).get("index", -1))
    except Exception:
        pass
    if 0 <= idx < len(top):
        chosen = top[idx]
        if float(chosen.get("_relevance_score") or 0) >= MIN_RELEVANCE_SCORE * 0.6:
            return chosen
    best = top[0]
    return best if float(best.get("_relevance_score") or 0) >= MIN_RELEVANCE_SCORE else None
