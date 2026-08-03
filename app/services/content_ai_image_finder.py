"""Tìm ảnh minh họa từ nguồn API hợp lệ (không scrape Google Images / Bing)."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import dotenv_values
from sqlalchemy.orm import Session

from app.models.user import User

from app.services.content_image_context import (
    build_image_search_query_for_section,
    detect_article_topic,
    extract_image_contexts_from_article,
)
from app.services.google_cse_images import google_cse_image_search
from app.services.image_relevance import (
    MIN_RELEVANCE_SCORE,
    is_blocked_image_url,
    is_generic_brand_noise_image,
    pick_best_image_candidate,
    score_image_relevance,
)

Orientation = Literal["landscape", "portrait", "any"]


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "env.local"
    if not p.is_file():
        return {}
    return {str(k): str(v or "") for k, v in (dotenv_values(p) or {}).items() if k}


def _getenv(name: str) -> str:
    return str((os.getenv(name) or _env_map().get(name) or "")).strip()


def _normalize_query(q: str) -> str:
    qq = re.sub(r"\s+", " ", (q or "").strip())
    if len(qq) > 200:
        qq = qq[:200].rsplit(" ", 1)[0] or qq[:200]
    return qq


def _normalize_candidate(raw: dict[str, Any], *, provider: str) -> dict[str, Any]:
    link = str(raw.get("link") or raw.get("url") or "").strip()
    return {
        "link": link,
        "title": str(raw.get("title") or raw.get("alt") or "").strip(),
        "thumbnail": str(raw.get("thumbnail") or link).strip(),
        "context": str(raw.get("context") or provider).strip(),
        "provider": provider,
        "source_url": str(raw.get("source_url") or raw.get("context") or link).strip(),
        "license": str(raw.get("license") or "").strip(),
        "author": str(raw.get("author") or "").strip(),
        "width": int(raw.get("width") or 0) or None,
        "height": int(raw.get("height") or 0) or None,
    }


def _pexels_search(*, q: str, num: int, orientation: Orientation) -> list[dict[str, Any]]:
    key = _getenv("PEXELS_API_KEY")
    if not key:
        return []
    params: dict[str, Any] = {"query": q, "per_page": num, "locale": "en-US" if re.fullmatch(r"[\x20-\x7E]+", q) else "vi-VN"}
    if orientation in ("landscape", "portrait"):
        params["orientation"] = orientation
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params=params,
            timeout=25,
        )
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out: list[dict[str, Any]] = []
    for ph in (r.json() or {}).get("photos") or []:
        src = str((ph.get("src") or {}).get("large") or (ph.get("src") or {}).get("medium") or "").strip()
        if not src or is_blocked_image_url(src):
            continue
        out.append(
            _normalize_candidate(
                {
                    "link": src,
                    "title": ph.get("alt"),
                    "thumbnail": (ph.get("src") or {}).get("medium") or src,
                    "source_url": ph.get("url"),
                    "author": ph.get("photographer"),
                    "license": "Pexels License",
                    "width": ph.get("width"),
                    "height": ph.get("height"),
                },
                provider="pexels",
            )
        )
    return out


def _unsplash_search(*, q: str, num: int, orientation: Orientation) -> list[dict[str, Any]]:
    key = _getenv("UNSPLASH_ACCESS_KEY") or _getenv("UNSPLASH_API_KEY")
    if not key:
        return []
    params: dict[str, Any] = {"query": q, "per_page": num, "lang": "vi"}
    if orientation in ("landscape", "portrait"):
        params["orientation"] = orientation
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {key}"},
            params=params,
            timeout=25,
        )
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out: list[dict[str, Any]] = []
    for ph in (r.json() or {}).get("results") or []:
        urls = ph.get("urls") or {}
        src = str(urls.get("regular") or urls.get("small") or "").strip()
        if not src or is_blocked_image_url(src):
            continue
        user = ph.get("user") or {}
        out.append(
            _normalize_candidate(
                {
                    "link": src,
                    "title": ph.get("alt_description") or ph.get("description"),
                    "thumbnail": urls.get("small") or src,
                    "source_url": (ph.get("links") or {}).get("html") or src,
                    "author": user.get("name"),
                    "license": "Unsplash License",
                    "width": ph.get("width"),
                    "height": ph.get("height"),
                },
                provider="unsplash",
            )
        )
    return out


def _pixabay_search(*, q: str, num: int, orientation: Orientation) -> list[dict[str, Any]]:
    key = _getenv("PIXABAY_API_KEY")
    if not key:
        return []
    params: dict[str, Any] = {
        "key": key,
        "q": q,
        "per_page": num,
        "image_type": "photo",
        "lang": "vi",
        "safesearch": "true",
    }
    if orientation == "landscape":
        params["orientation"] = "horizontal"
    elif orientation == "portrait":
        params["orientation"] = "vertical"
    try:
        r = requests.get("https://pixabay.com/api/", params=params, timeout=25)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out: list[dict[str, Any]] = []
    for ph in (r.json() or {}).get("hits") or []:
        src = str(ph.get("largeImageURL") or ph.get("webformatURL") or "").strip()
        if not src or is_blocked_image_url(src):
            continue
        out.append(
            _normalize_candidate(
                {
                    "link": src,
                    "title": ph.get("tags"),
                    "thumbnail": ph.get("previewURL") or src,
                    "source_url": ph.get("pageURL") or src,
                    "author": ph.get("user"),
                    "license": "Pixabay License",
                    "width": ph.get("imageWidth"),
                    "height": ph.get("imageHeight"),
                },
                provider="pixabay",
            )
        )
    return out


def _google_cse_search(
    *,
    q: str,
    num: int,
    db: Session | None = None,
    user: User | None = None,
) -> list[dict[str, Any]]:
    def _run() -> list[dict[str, Any]]:
        try:
            items = google_cse_image_search(q=q, num=num)
        except ValueError:
            return []
        return [
            _normalize_candidate(
                {**it, "license": "Google CSE result — verify usage rights", "source_url": it.get("context") or it.get("link")},
                provider="google_cse",
            )
            for it in items
            if str(it.get("link") or "").strip()
        ]

    if db is not None and user is not None:
        from app.services.cost_control.module_gates import content_ai_cse_gate

        with content_ai_cse_gate(db, user, action="image_search"):
            return _run()
    return _run()


def find_images_for_query(
    *,
    q: str,
    num: int = 12,
    orientation: Orientation = "any",
    db: Session | None = None,
    user: User | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Tìm ảnh qua API hợp lệ theo thứ tự ưu tiên.
    Không dùng Bing scrape hay SerpAPI scrape.
    """
    qq = _normalize_query(q)
    if not qq:
        return [], "none"
    n = max(1, min(int(num or 12), 20))
    providers = (
        ("google_cse", lambda: _google_cse_search(q=qq, num=n, db=db, user=user)),
        ("pexels", lambda: _pexels_search(q=qq, num=n, orientation=orientation)),
        ("unsplash", lambda: _unsplash_search(q=qq, num=n, orientation=orientation)),
        ("pixabay", lambda: _pixabay_search(q=qq, num=n, orientation=orientation)),
    )
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    first_source = "none"
    for name, fn in providers:
        batch = fn()
        if not batch:
            continue
        if first_source == "none":
            first_source = name
        for it in batch:
            link = str(it.get("link") or "")
            if not link or link in seen:
                continue
            seen.add(link)
            merged.append(it)
        if len(merged) >= n:
            break
    if not merged:
        raise ValueError(
            "Không tìm thấy ảnh — cấu hình GOOGLE_API_KEY+GOOGLE_CSE_ID hoặc PEXELS/UNSPLASH/PIXABAY API key trong env.local."
        )
    return merged[:n], first_source


def find_images_merged_all_providers(
    *,
    q: str,
    num: int = 16,
    orientation: Orientation = "any",
    db: Session | None = None,
    user: User | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Gộp kết quả từ mọi provider API (không dừng ở provider đầu)."""
    qq = _normalize_query(q)
    if not qq:
        return [], "none"
    n = max(1, min(int(num or 16), 24))
    batches = (
        _google_cse_search(q=qq, num=n, db=db, user=user),
        _pexels_search(q=qq, num=n, orientation=orientation),
        _unsplash_search(q=qq, num=n, orientation=orientation),
        _pixabay_search(q=qq, num=n, orientation=orientation),
    )
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    providers: list[str] = []
    for batch in batches:
        if not batch:
            continue
        prov = str(batch[0].get("provider") or "").strip()
        if prov and prov not in providers:
            providers.append(prov)
        for it in batch:
            link = str(it.get("link") or "")
            if not link or link in seen:
                continue
            seen.add(link)
            merged.append(it)
    if not merged:
        raise ValueError(f"Không tìm thấy ảnh cho: {qq}")
    return merged, "+".join(providers) if providers else "none"


def build_slot_image_query(
    *,
    keyword: str,
    title: str = "",
    section_heading: str = "",
    outline: str = "",
    section_content: str = "",
    brand_name: str = "",
) -> str:
    """Tạo query tìm ảnh từ keyword / title / H2."""
    q = build_image_search_query_for_section(
        section_heading=section_heading or _first_h2_from_outline(outline),
        section_content=section_content,
        main_keyword=keyword,
        brand_name=brand_name,
    )
    if q:
        return q
    parts = [p for p in (keyword, title.split("|", 1)[0].strip() if title else "", section_heading) if p]
    return " ".join(parts)[:120] or keyword


def _first_h2_from_outline(outline: str) -> str:
    for m in re.finditer(r"^##\s+(.+?)\s*$", outline or "", flags=re.M):
        t = m.group(1).strip()
        if t:
            return t
    return ""


def _first_h2_from_html(content_html: str) -> str:
    m = re.search(r"<h2[^>]*>(.*?)</h2>", content_html or "", flags=re.I | re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:120]


def _plain_from_html(content_html: str, *, max_len: int = 400) -> str:
    raw = str(content_html or "")[:200_000]
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", raw, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _resolve_section_context(
    *,
    section_heading: str,
    outline: str,
    content_html: str,
) -> tuple[str, str]:
    ctxs = extract_image_contexts_from_article(article_html=content_html, outline=outline)
    if ctxs:
        c = ctxs[0]
        heading = str(c.get("heading") or "").strip()
        content = str(c.get("content") or "").strip()
        if heading or content:
            return heading or section_heading, content
    heading = (section_heading or "").strip() or _first_h2_from_outline(outline) or _first_h2_from_html(content_html)
    return heading, _plain_from_html(content_html)


def _unique_queries(*queries: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        qq = _normalize_query(q)
        if len(qq) < 3:
            continue
        key = qq.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(qq)
    return out


def _english_stock_queries(
    *,
    keyword: str,
    title: str,
    heading: str,
    topic: str,
) -> list[str]:
    """Truy vấn tiếng Anh cho Pexels/Unsplash — stock photo hiểu tốt hơn."""
    kw = (keyword or "").lower()
    head = (heading or title or "").lower()
    out: list[str] = []
    if "thuật toán" in kw and "google" in kw:
        out.extend(
            [
                "search engine ranking algorithm diagram",
                "SEO algorithm infographic analytics chart",
                "website ranking dashboard illustration",
            ]
        )
    elif "thuật toán" in kw:
        out.append("computer algorithm flowchart diagram")
    if topic == "technical_seo" or "kỹ thuật" in kw or "audit" in head:
        out.append("SEO technical audit dashboard website analytics")
    elif topic == "content_seo" or "nội dung" in kw or "viết bài" in head:
        out.append("SEO content marketing blog keyword research")
    if "seo" in kw or "seo" in head or "tối ưu" in kw:
        out.append("search engine optimization marketing illustration")
    return out


def _build_contextual_queries(
    *,
    keyword: str,
    title: str,
    heading: str,
    section_content: str,
    outline: str,
    manual_query: str,
) -> list[str]:
    kw = _normalize_query(keyword)
    manual = (manual_query or "").strip()
    if manual and _normalize_query(manual).lower() != kw.lower():
        return _unique_queries(manual)

    topic = detect_article_topic(main_keyword=kw, title=title, article_text=section_content)
    primary = build_slot_image_query(
        keyword=kw,
        title=title,
        section_heading=heading,
        outline=outline,
        section_content=section_content,
    )
    english = _english_stock_queries(keyword=kw, title=title, heading=heading, topic=topic)
    return _unique_queries(*english, primary)


def _fetch_multi_query_pool(
    queries: list[str],
    *,
    per_query: int = 14,
    db: Session | None = None,
    user: User | None = None,
) -> tuple[list[dict[str, Any]], str]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    sources: list[str] = []
    for q in queries[:5]:
        try:
            batch, src = find_images_merged_all_providers(q=q, num=per_query, db=db, user=user)
        except ValueError:
            continue
        if src and src not in sources:
            sources.append(src)
        for it in batch:
            link = str(it.get("link") or "")
            if not link or link in seen:
                continue
            seen.add(link)
            merged.append(it)
    return merged, "+".join(sources) if sources else "none"


def _rank_contextual_pool(
    items: list[dict[str, Any]],
    *,
    terms: list[str],
    primary_keyword: str,
    want: int,
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for it in items:
        if is_generic_brand_noise_image(it, primary_keyword):
            continue
        sc = score_image_relevance(it, terms)
        if sc < -50:
            continue
        row = {k: v for k, v in it.items() if not str(k).startswith("_")}
        row["relevance_score"] = round(sc, 1)
        pool.append(row)
    pool.sort(key=lambda x: -float(x.get("relevance_score") or 0))

    min_score = max(MIN_RELEVANCE_SCORE * 0.65, 22.0)
    good = [r for r in pool if float(r.get("relevance_score") or 0) >= min_score]
    if len(good) >= want:
        return good[:want]
    if pool:
        return [r for r in pool if float(r.get("relevance_score") or 0) >= 10][:want] or pool[:want]

    fallback: list[dict[str, Any]] = []
    for it in items:
        if is_generic_brand_noise_image(it, primary_keyword):
            continue
        sc = score_image_relevance(it, terms)
        row = {k: v for k, v in it.items() if not str(k).startswith("_")}
        row["relevance_score"] = round(sc, 1)
        fallback.append(row)
    fallback.sort(key=lambda x: -float(x.get("relevance_score") or 0))
    return fallback[:want]


def search_contextual_images(
    *,
    primary_keyword: str,
    title: str = "",
    outline: str = "",
    content_html: str = "",
    section_heading: str = "",
    manual_query: str = "",
    num: int = 8,
    db: Session | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """Tìm ảnh theo ngữ cảnh bài viết, xếp hạng relevance."""
    kw = _normalize_query(primary_keyword)
    if not kw and not (manual_query or "").strip():
        raise ValueError("Thiếu từ khóa hoặc ngữ cảnh để tìm ảnh.")

    title_clean = (title or "").split("|", 1)[0].strip()
    heading, snippet = _resolve_section_context(
        section_heading=section_heading,
        outline=outline,
        content_html=content_html,
    )
    queries = _build_contextual_queries(
        keyword=kw or manual_query,
        title=title_clean,
        heading=heading,
        section_content=snippet,
        outline=outline,
        manual_query=manual_query,
    )
    if not queries:
        raise ValueError("Thiếu từ khóa hoặc ngữ cảnh để tìm ảnh.")

    want = max(1, min(int(num or 8), 12))
    items, source = _fetch_multi_query_pool(queries, per_query=max(12, want * 2), db=db, user=user)
    if not items:
        raise ValueError("Không tìm thấy ảnh phù hợp — thử đổi từ khóa hoặc bổ sung outline.")

    terms = [kw or manual_query, title_clean, heading, snippet[:200], queries[0]]
    ranked = _rank_contextual_pool(items, terms=terms, primary_keyword=kw or manual_query, want=want)
    return {
        "items": ranked,
        "source": source,
        "query": queries[0],
        "queries": queries,
        "heading": heading,
    }


def find_best_for_slot(
    *,
    keyword: str,
    title: str = "",
    section_heading: str = "",
    section_content: str = "",
    outline: str = "",
    brand_name: str = "",
    orientation: Orientation = "any",
    per_query: int = 15,
    db=None,
    user=None,
) -> tuple[dict[str, Any] | None, str, str]:
    """Trả (candidate, provider, query)."""
    query = build_slot_image_query(
        keyword=keyword,
        title=title,
        section_heading=section_heading,
        outline=outline,
        section_content=section_content,
        brand_name=brand_name,
    )
    try:
        items, source = find_images_for_query(
            q=query, num=per_query, orientation=orientation, db=db, user=user
        )
    except ValueError:
        return None, "", query
    terms = [keyword, title.split("|", 1)[0].strip() if title else "", section_heading]
    ranked = sorted(items, key=lambda it: -score_image_relevance(it, terms))
    picked = pick_best_image_candidate(
        ranked,
        primary_keyword=keyword,
        title=title,
        section_heading=section_heading,
        section_content=section_content,
    )
    return picked, source, query


def image_providers_status() -> dict[str, Any]:
    return {
        "google_cse": bool(_getenv("GOOGLE_API_KEY") or _getenv("GOOGLE_CSE_API_KEY"))
        and bool(_getenv("GOOGLE_CSE_ID") or _getenv("GOOGLE_SEARCH_ENGINE_ID")),
        "pexels": bool(_getenv("PEXELS_API_KEY")),
        "unsplash": bool(_getenv("UNSPLASH_ACCESS_KEY") or _getenv("UNSPLASH_API_KEY")),
        "pixabay": bool(_getenv("PIXABAY_API_KEY")),
    }
