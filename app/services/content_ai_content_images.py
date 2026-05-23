from __future__ import annotations

import re
from html import escape, unescape
from typing import Any

from app.services.content_ai_project_store import _resolve_project_content
from app.services.google_cse_images import import_remote_image_url
from app.services.content_image_context import (
    build_image_prompt_for_section,
    build_image_search_query_for_section,
    build_seo_image_generation_prompt,
    choose_image_placement,
    get_default_content_ai_image_style,
    suggest_image_alt_text,
    suggest_image_caption,
)
from app.services.image_relevance import (
    pick_best_image_candidate,
    score_image_relevance,
)
from app.services.web_image_search import search_web_images

MAX_INLINE_IMAGES = 4
MIN_WORDS_FOR_INLINE = 250


def _strip_html_text(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(s)).strip()


def extract_h2_headings(html: str, outline: str = "") -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", html or "", flags=re.I | re.S):
        t = _strip_html_text(m.group(1))
        if t and t not in out:
            out.append(t)
    for m in re.finditer(r"^##\s+(.+?)\s*$", outline or "", flags=re.M):
        t = m.group(1).strip()
        if t and t not in out:
            out.append(t)
    return out[:8]


def collect_context_terms(
    *,
    primary_keyword: str,
    title: str,
    secondary_keywords: list[str] | None,
    content_html: str,
) -> list[str]:
    terms: list[str] = []
    for raw in (
        primary_keyword,
        title.split("|", 1)[0].strip() if title else "",
        *(secondary_keywords or []),
    ):
        t = re.sub(r"\s+", " ", str(raw or "").strip())
        if t and t.lower() not in {x.lower() for x in terms}:
            terms.append(t)
    text = _strip_html_text(content_html)
    if text:
        snippet = text[:280]
        if snippet and snippet.lower() not in {x.lower() for x in terms}:
            terms.append(snippet)
    return terms


def _figure_snippet(
    url: str,
    alt: str,
    caption: str = "",
    *,
    width: int | None = None,
    height: int | None = None,
) -> str:
    if width or height:
        from app.services.content_ai_image_output import figure_snippet_seo

        return figure_snippet_seo(url, alt, width=width, height=height, caption=caption)
    alt_esc = escape(str(alt or "").strip()[:200])
    cap = str(caption or "").strip()[:200]
    cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
    return (
        f'<figure class="editor-image content-ai-inline-image">'
        f'<img src="{url}" alt="{alt_esc}" loading="lazy" decoding="async" />{cap_html}</figure>'
    )


_FAKE_IMG_SRC_RE = re.compile(
    r"^(#|javascript:|data:text|about:blank|placeholder|example\.com|your[-_]?image|"
    r"image[-_]?url|/path/to/|\[.*\]|insert[-_]?image|ảnh[-_]?minh[-_]?họa)",
    re.I,
)

_VALID_CONTENT_IMG_PREFIXES = (
    "/api/user-files/",
    "/static/uploads/",
)


def collect_allowed_urls_from_project(project: dict[str, Any] | None) -> list[str]:
    """URL ảnh đã upload / gallery — được giữ khi sanitize."""
    if not project:
        return []
    out: list[str] = []
    for raw in (
        str(project.get("featured_image") or "").strip(),
        *(
            str(u or "").strip()
            for u in (project.get("gallery_images") or [])
            if str(u or "").strip()
        ),
    ):
        if raw and raw not in out:
            out.append(raw)
    return out


def is_valid_content_image_src(src: str, *, allowed_urls: set[str] | None = None) -> bool:
    """URL ảnh hợp lệ trong editor (upload hệ thống hoặc trong danh sách cho phép)."""
    raw = str(src or "").strip().strip('"\'')
    if not raw or raw == "#":
        return False
    low = raw.casefold()
    if _FAKE_IMG_SRC_RE.search(low):
        return False
    if allowed_urls and raw in allowed_urls:
        return True
    return any(low.startswith(pref) for pref in _VALID_CONTENT_IMG_PREFIXES)


def sanitize_invalid_content_images(
    html: str,
    *,
    allowed_urls: list[str] | None = None,
) -> tuple[str, int]:
    """
    Gỡ <img>/<figure> do LLM bịa src (gây icon ảnh lỗi trên preview).
    Giữ figcaption thành đoạn <p> nếu có chú thích.
    """
    raw = str(html or "").strip()
    if not raw or not re.search(r"<img\b", raw, flags=re.I):
        return raw, 0
    from bs4 import BeautifulSoup

    allowed: set[str] = set()
    for u in allowed_urls or []:
        t = str(u or "").strip()
        if t:
            allowed.add(t)

    soup = BeautifulSoup(raw, "html.parser")
    removed = 0

    for fig in list(soup.find_all("figure")):
        img = fig.find("img")
        if img is None:
            continue
        src = str(img.get("src") or "").strip()
        if is_valid_content_image_src(src, allowed_urls=allowed):
            continue
        cap = fig.find("figcaption")
        cap_text = cap.get_text(" ", strip=True) if cap else ""
        alt = str(img.get("alt") or "").strip()
        text_keep = cap_text or alt
        if text_keep:
            new_p = soup.new_tag("p")
            new_p.append(text_keep)
            fig.replace_with(new_p)
        else:
            fig.decompose()
        removed += 1

    for img in list(soup.find_all("img")):
        src = str(img.get("src") or "").strip()
        if is_valid_content_image_src(src, allowed_urls=allowed):
            continue
        alt = str(img.get("alt") or "").strip()
        parent = img.parent
        img.decompose()
        removed += 1
        if parent and getattr(parent, "name", None) == "figure":
            if not parent.get_text(strip=True) and alt:
                parent.append(alt)
            if not parent.get_text(strip=True):
                parent.decompose()

    return str(soup), removed


def prepare_content_html_for_images(content: str, outline: str = "") -> str:
    """Chuẩn hóa HTML để có điểm neo chèn ảnh (h2 từ outline / markdown)."""
    html = str(content or "").strip()
    if not html:
        return html
    if not re.search(r"<\s*[a-z][^>]*>", html, flags=re.I):
        blocks = [b.strip() for b in re.split(r"\n{2,}", html) if b.strip()]
        parts: list[str] = []
        for b in blocks:
            if re.match(r"^#{1,6}\s+", b):
                hm = re.match(r"^(#+)", b)
                level = len(hm.group(1)) if hm else 2
                text = re.sub(r"^#+\s*", "", b).strip()
                tag = "h2" if level <= 2 else "h3"
                parts.append(f"<{tag}>{escape(text)}</{tag}>")
            elif re.match(r"^[-*]\s+", b):
                items = re.findall(r"^[-*]\s+(.+)$", b, flags=re.M)
                lis = "".join(f"<li>{escape(x)}</li>" for x in items)
                parts.append(f"<ul>{lis}</ul>")
            else:
                parts.append(f"<p>{escape(b)}</p>")
        html = "\n".join(parts)
    if not re.search(r"<h2\b", html, flags=re.I):
        html = re.sub(
            r"^##\s+(.+?)\s*$",
            lambda m: f"<h2>{escape(m.group(1).strip())}</h2>",
            html,
            flags=re.M,
        )
    h2s = extract_h2_headings(html, outline)
    if h2s and not re.search(r"<h2\b", html, flags=re.I):
        for h2 in reversed(h2s[:6]):
            safe = re.escape(h2)
            html = re.sub(
                rf"(<h3\b[^>]*>\s*{safe}\s*</h3>)",
                rf"<h2>{escape(h2)}</h2>\1",
                html,
                count=1,
                flags=re.I,
            )
    return html


def _paragraph_end_positions(html: str) -> list[int]:
    return [m.end() for m in re.finditer(r"</p>", html, flags=re.I)]


_NEARBY_IMAGE_GAP = 450
_UNSAFE_AFTER_H2_RE = re.compile(
    r"<(table|blockquote|ul\s+class=[\"'][^\"']*faq|section\b[^>]*\bfaq)",
    re.I,
)


def _fold_heading_ascii(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


def _is_faq_or_skip_heading(heading: str) -> bool:
    from app.services.content_ai_image_output import is_faq_heading

    return is_faq_heading(heading)


def _h2_insert_position_unsafe(html: str, pos: int) -> bool:
    window = html[pos : pos + 900]
    if _UNSAFE_AFTER_H2_RE.search(window):
        return True
    if re.search(r"<h2\b", window, flags=re.I):
        inner = window[: window.lower().find("<h2")]
        if _UNSAFE_AFTER_H2_RE.search(inner):
            return True
    return False


def _has_image_near_position(html: str, pos: int, gap: int = _NEARBY_IMAGE_GAP) -> bool:
    chunk = html[max(0, pos - gap) : pos + gap]
    return bool(re.search(r"<(?:img|figure)\b", chunk, flags=re.I))


def resolve_smart_inline_h2_index(
    html: str,
    *,
    preferred_index: int | None = None,
    section_heading: str = "",
    outline: str = "",
) -> tuple[int, str]:
    """
    Chọn H2 hợp lệ để chèn inline: tránh FAQ, table/blockquote ngay sau H2, vùng đã có ảnh.
    Trả (h2_index, reason).
    """
    h2s = extract_h2_headings(html, outline)
    if not h2s:
        return 0, "no_h2"

    h2_matches = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html, flags=re.I | re.S))
    if not h2_matches:
        return 0, "no_h2_tags"

    candidates: list[int] = []
    pref = int(preferred_index) if preferred_index is not None else -1
    if section_heading:
        for i, h in enumerate(h2s):
            if h.strip().lower() == section_heading.strip().lower():
                pref = i
                break

    order: list[int] = []
    if 0 <= pref < len(h2s):
        order.append(pref)
    for i in range(len(h2s)):
        if i not in order:
            order.append(i)

    for idx in order:
        if _is_faq_or_skip_heading(h2s[idx]):
            continue
        if idx >= len(h2_matches):
            continue
        pos = h2_matches[idx].end()
        if _h2_insert_position_unsafe(html, pos):
            continue
        if _has_image_near_position(html, pos):
            continue
        candidates.append(idx)

    if candidates:
        return candidates[0], "h2_smart"
    for idx in order:
        if _is_faq_or_skip_heading(h2s[idx]):
            continue
        if idx < len(h2_matches):
            return idx, "h2_relaxed"
    return max(0, min(pref, len(h2s) - 1)), "h2_fallback"


def inject_image_smart_into_content_html(
    html: str,
    insert: dict[str, Any],
    *,
    outline: str = "",
) -> tuple[str, dict[str, Any]]:
    """
    Chèn một ảnh inline thông minh. Trả (html_mới, meta) với placement_used.
    """
    ins = dict(insert)
    mode_skip = str(ins.get("mode") or "inline").lower()
    if mode_skip == "append":
        url = str(ins.get("url") or "").strip()
        alt = str(ins.get("alt") or "").strip()
        cap = str(ins.get("caption") or "").strip()
        return (html or "") + _figure_snippet(url, alt, cap), {"placement": "append"}

    h2_idx, reason = resolve_smart_inline_h2_index(
        html,
        preferred_index=ins.get("h2_index"),
        section_heading=str(ins.get("section_heading") or ""),
        outline=outline,
    )
    ins["h2_index"] = h2_idx
    before = html
    new_html = inject_images_into_content_html(html, [ins])
    meta = {"placement": "inline", "h2_index": h2_idx, "placement_reason": reason}
    url = str(ins.get("url") or "").strip()
    if url and new_html == before:
        alt = str(ins.get("alt") or "").strip()
        cap = str(ins.get("caption") or "").strip()
        new_html = (html or "") + _figure_snippet(url, alt, cap)
        meta = {"placement": "append", "placement_reason": "no_safe_h2"}
    return new_html, meta


def inject_images_into_content_html(
    html: str,
    inserts: list[dict[str, Any]],
) -> str:
    """Chèn figure sau h2 (h2_index) hoặc sau đoạn văn (paragraph_index)."""
    if not html or not inserts:
        return html
    h2_matches = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html, flags=re.I | re.S))
    para_ends = _paragraph_end_positions(html)

    for ins in sorted(
        inserts,
        key=lambda x: (-int(x.get("h2_index") or -1), -int(x.get("paragraph_index") or -1)),
    ):
        url = str(ins.get("url") or "").strip()
        if not url:
            continue
        pos = -1
        if "paragraph_index" in ins and para_ends:
            pi = int(ins.get("paragraph_index") or 0)
            if 0 <= pi < len(para_ends):
                pos = para_ends[pi]
        elif h2_matches:
            idx = int(ins.get("h2_index") or 0)
            if 0 <= idx < len(h2_matches):
                pos = h2_matches[idx].end()
        if pos < 0:
            continue
        window = html[pos : pos + 600]
        if re.search(r"<img\b", window, flags=re.I):
            continue
        alt = str(ins.get("alt") or "").strip()
        caption = str(ins.get("caption") or "").strip()
        iw = ins.get("width")
        ih = ins.get("height")
        html = html[:pos] + _figure_snippet(
            url, alt, caption, width=int(iw) if iw else None, height=int(ih) if ih else None
        ) + html[pos:]
    return html


def count_content_images(html: str) -> int:
    return len(re.findall(r"<img\b", html or "", flags=re.I))


def _search_candidates_for_slot(
    *,
    primary_keyword: str,
    title: str,
    section_heading: str = "",
    section_content: str = "",
    brand_name: str = "",
    per_query: int = 15,
) -> tuple[list[dict[str, Any]], str, str]:
    """Tìm ảnh cho 1 vị trí (featured hoặc 1 mục H2)."""
    query = build_image_search_query_for_section(
        section_heading=section_heading,
        section_content=section_content,
        main_keyword=primary_keyword,
        brand_name=brand_name,
    )
    terms = [
        primary_keyword,
        title.split("|", 1)[0].strip() if title else "",
        section_heading,
        (section_content or "")[:200],
    ]
    try:
        items, source = search_web_images(q=query, num=per_query)
    except ValueError:
        return [], "", query
    ranked = sorted(items, key=lambda it: -score_image_relevance(it, terms))
    return ranked, source, query


def _image_strategy() -> str:
    import os
    from pathlib import Path

    from dotenv import dotenv_values

    env = Path(__file__).resolve().parents[2] / "env.local"
    raw = (os.getenv("CONTENT_AI_IMAGE_STRATEGY") or "").strip().lower()
    if not raw and env.is_file():
        raw = str((dotenv_values(env) or {}).get("CONTENT_AI_IMAGE_STRATEGY") or "").strip().lower()
    if raw in ("ai", "web", "hybrid"):
        return raw
    return "hybrid"


def _generate_slot_image_ai(
    *,
    primary_keyword: str,
    title: str,
    section_heading: str,
    section_content: str = "",
    brand_name: str = "",
    target_audience: str = "",
    industry: str = "",
    image_style: str = "",
    stem: str,
) -> tuple[str, str]:
    from app.services.content_ai_thumbnail import (
        _openai_generate_image_bytes,
        _save_image_bytes,
    )

    style = image_style or get_default_content_ai_image_style()
    prompt = build_seo_image_generation_prompt(
        main_keyword=primary_keyword,
        article_title=title,
        section_heading=section_heading or title,
        section_summary=section_content,
        brand_name=brand_name,
        target_audience=target_audience,
        industry=industry,
        image_style=style,
        language="vi",
        include_brand_logo=False,
    )
    image_bytes = _openai_generate_image_bytes(prompt=prompt)
    local_url = _save_image_bytes(image_bytes, stem=stem)
    return local_url, prompt[:200]


def _pick_and_download_for_slot(
    *,
    primary_keyword: str,
    title: str,
    section_heading: str,
    section_content: str = "",
    brand_name: str = "",
    target_audience: str = "",
    industry: str = "",
    image_style: str = "",
    stem: str,
    used_links: set[str],
    used_locals: set[str],
) -> tuple[str, str, str, str]:
    """Trả (local_url, remote_link, search_query, source)."""
    strategy = _image_strategy()
    query = build_image_search_query_for_section(
        section_heading=section_heading,
        section_content=section_content,
        main_keyword=primary_keyword,
        brand_name=brand_name,
    )

    if strategy != "ai":
        ranked, _source, query = _search_candidates_for_slot(
            primary_keyword=primary_keyword,
            title=title,
            section_heading=section_heading,
            section_content=section_content,
            brand_name=brand_name,
            per_query=15,
        )
        picked = (
            pick_best_image_candidate(
                ranked,
                primary_keyword=primary_keyword,
                title=title,
                section_heading=section_heading,
            )
            if ranked
            else None
        )
        if picked:
            link = str(picked.get("link") or "")
            if link in used_links:
                for alt in ranked:
                    alt_link = str(alt.get("link") or "")
                    if alt_link and alt_link not in used_links:
                        picked = alt
                        link = alt_link
                        break
            local_url = _try_download_item(picked, stem=stem, used_locals=used_locals)
            if local_url:
                return local_url, link, query, _source or "web_image_search"

    if strategy == "web":
        return "", "", query, ""

    try:
        local_url, prompt_used = _generate_slot_image_ai(
            primary_keyword=primary_keyword,
            title=title,
            section_heading=section_heading,
            section_content=section_content,
            brand_name=brand_name,
            target_audience=target_audience,
            industry=industry,
            image_style=image_style,
            stem=stem,
        )
        if local_url and local_url not in used_locals:
            return local_url, "openai-generated", prompt_used or query, "openai_image"
    except ValueError:
        pass
    return "", "", query, ""


def _try_download_item(
    it: dict[str, Any],
    *,
    stem: str,
    used_locals: set[str],
) -> str:
    candidates: list[str] = []
    for u in (str(it.get("thumbnail") or "").strip(), str(it.get("link") or "").strip()):
        if u and u not in candidates:
            candidates.append(u)
    for src in candidates:
        try:
            local_url = import_remote_image_url(src, stem=stem)
            if local_url in used_locals:
                continue
            return local_url
        except ValueError:
            continue
    return ""


def enrich_project_with_context_images(
    project: dict[str, Any],
    *,
    max_inline: int | None = None,
    update_featured: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Tìm ảnh khớp ngữ cảnh (từ khóa + tiêu đề + H2), gán featured_image và chèn ảnh vào content HTML.
    """
    pk = str(project.get("primary_keyword") or "").strip()
    title = str(project.get("title") or "").strip()
    outline = str(project.get("outline_content") or "").strip()
    secondary = project.get("secondary_keywords") or []
    if not isinstance(secondary, list):
        secondary = []
    raw_content = _resolve_project_content(project)
    content = prepare_content_html_for_images(raw_content, outline)
    word_count = len(_strip_html_text(content).split()) if content else 0
    max_slots = max(0, min(int(max_inline or MAX_INLINE_IMAGES), 6))

    if not pk:
        raise ValueError("Cần từ khóa chính để tìm ảnh đúng ngữ cảnh.")

    brand_name = str(project.get("brand_name") or project.get("target_website") or "").strip()
    target_audience = str(project.get("target_audience") or "").strip()
    industry = str(project.get("industry") or "").strip()
    if pk and not brand_name:
        try:
            from app.services.content_ai_knowledge_context import get_relevant_knowledge_for_keyword

            kb = get_relevant_knowledge_for_keyword(
                pk,
                target_website=str(project.get("target_website") or ""),
            )
            if kb.get("found"):
                brand_name = str(kb.get("brand_name") or brand_name).strip()
                if not target_audience:
                    aud = str((kb.get("sections") or {}).get("audience") or "").strip()
                    if aud:
                        target_audience = aud[:400]
                if not industry and kb.get("image_context"):
                    industry = str(kb.get("image_context") or "")[:300]
        except Exception:
            pass
    image_style = get_default_content_ai_image_style()
    intro_content = _strip_html_text(content)[:500]

    stem = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        pk or title or "content-img",
    )[:40].strip("-") or "content-img"

    used_links: set[str] = set()
    used_locals: set[str] = set()
    gallery: list[str] = list(project.get("gallery_images") or [])
    if not isinstance(gallery, list):
        gallery = []

    existing_featured = str(project.get("featured_image") or "").strip()
    featured_local = existing_featured if existing_featured and not force else ""
    used_query = ""
    image_source = "web_image_search"

    if update_featured and not featured_local:
        local_url, link, used_query, src = _pick_and_download_for_slot(
            primary_keyword=pk,
            title=title,
            section_heading=title or pk,
            section_content=intro_content,
            brand_name=brand_name,
            target_audience=target_audience,
            industry=industry,
            image_style=image_style,
            stem=f"{stem}-feat",
            used_links=used_links,
            used_locals=used_locals,
        )
        if src:
            image_source = src
        if local_url:
            featured_local = local_url
            if link and link != "openai-generated":
                used_links.add(link)
            if local_url not in gallery:
                gallery.insert(0, local_url)
        if not featured_local and not existing_featured:
            raise ValueError(
                "Không tìm được ảnh đại diện phù hợp chủ đề. "
                "Kiểm tra OPENAI_API_KEY hoặc thêm PEXELS_API_KEY trong env.local."
            )
    elif update_featured and featured_local and featured_local not in gallery:
        gallery.insert(0, featured_local)

    inline_inserts: list[dict[str, Any]] = []
    existing_imgs = count_content_images(content)
    h2s = extract_h2_headings(content, outline)
    need_inline = force or existing_imgs < max(1, max_slots)
    placements_used: list[dict[str, Any]] = []

    if content and word_count >= MIN_WORDS_FOR_INLINE and need_inline and max_slots > 0:
        placements = choose_image_placement(
            article_outline=outline,
            article_html=content,
            max_images=max_slots,
        )
        if placements:
            placements_used = placements
            for pi, placement in enumerate(placements):
                ctx = placement.get("context") or {}
                h2 = str(ctx.get("heading") or "").strip()
                section_body = str(ctx.get("content") or "").strip()
                h2_index = int(placement.get("h2_index") or pi)
                local_url, link, q_used, src = _pick_and_download_for_slot(
                    primary_keyword=pk,
                    title=title,
                    section_heading=h2,
                    section_content=section_body,
                    brand_name=brand_name,
                    target_audience=target_audience,
                    industry=industry,
                    image_style=image_style,
                    stem=f"{stem}-s{pi + 1}",
                    used_links=used_links,
                    used_locals=used_locals,
                )
                if q_used and not used_query:
                    used_query = q_used
                if src:
                    image_source = src
                if local_url:
                    if link and link != "openai-generated":
                        used_links.add(link)
                    used_locals.add(local_url)
                    if local_url not in gallery:
                        gallery.append(local_url)
                    alt = suggest_image_alt_text(ctx, pk)
                    caption = suggest_image_caption(ctx)
                    inline_inserts.append(
                        {
                            "h2_index": h2_index,
                            "url": local_url,
                            "alt": alt,
                            "caption": caption,
                        }
                    )
        elif h2s:
            slots = min(max_slots, len(h2s))
            for hi in range(slots):
                h2 = h2s[hi]
                ctx = {"heading": h2, "content": ""}
                local_url, link, q_used, src = _pick_and_download_for_slot(
                    primary_keyword=pk,
                    title=title,
                    section_heading=h2,
                    section_content="",
                    brand_name=brand_name,
                    target_audience=target_audience,
                    industry=industry,
                    image_style=image_style,
                    stem=f"{stem}-s{hi + 1}",
                    used_links=used_links,
                    used_locals=used_locals,
                )
                if q_used and not used_query:
                    used_query = q_used
                if src:
                    image_source = src
                if local_url:
                    if link and link != "openai-generated":
                        used_links.add(link)
                    used_locals.add(local_url)
                    if local_url not in gallery:
                        gallery.append(local_url)
                    inline_inserts.append(
                        {
                            "h2_index": hi,
                            "url": local_url,
                            "alt": suggest_image_alt_text(ctx, pk),
                            "caption": suggest_image_caption(ctx),
                        }
                    )
        else:
            para_ends = _paragraph_end_positions(content)
            if len(para_ends) >= 2:
                n = min(slots, len(para_ends) - 1)
                step = max(1, len(para_ends) // (n + 1))
                indices = [min(i * step, len(para_ends) - 1) for i in range(1, n + 1)]
                for si, pi in enumerate(indices[:slots]):
                    ctx = {"heading": pk, "content": _strip_html_text(content)[:400]}
                    local_url, link, q_used, src = _pick_and_download_for_slot(
                        primary_keyword=pk,
                        title=title,
                        section_heading=pk,
                        section_content=ctx["content"],
                        brand_name=brand_name,
                        target_audience=target_audience,
                        industry=industry,
                        image_style=image_style,
                        stem=f"{stem}-p{si + 1}",
                        used_links=used_links,
                        used_locals=used_locals,
                    )
                    if q_used and not used_query:
                        used_query = q_used
                    if src:
                        image_source = src
                    if local_url:
                        if link and link != "openai-generated":
                            used_links.add(link)
                        used_locals.add(local_url)
                        if local_url not in gallery:
                            gallery.append(local_url)
                        inline_inserts.append(
                            {
                                "paragraph_index": pi,
                                "url": local_url,
                                "alt": suggest_image_alt_text(ctx, pk),
                                "caption": suggest_image_caption(ctx),
                            }
                        )

    new_content = content
    if inline_inserts:
        new_content = inject_images_into_content_html(content, inline_inserts)

    return {
        "featured_image": featured_local or existing_featured,
        "content": new_content,
        "gallery_images": gallery,
        "used_query": used_query,
        "image_source": image_source,
        "inline_images_count": len(inline_inserts),
        "content_images_total": count_content_images(new_content),
        "content_prepared": content != raw_content,
        "image_placements": len(placements_used),
    }


def auto_insert_images_to_project(
    project_id: str,
    *,
    user_id: int,
    max_inline: int | None = None,
    update_featured: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    from app.services.content_ai_project_store import (
        get_content_ai_project,
        update_content_ai_project_fields,
    )

    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise ValueError("Không tìm thấy dự án.")
    if not _resolve_project_content(project) and not str(project.get("outline_content") or "").strip():
        raise ValueError("Bài chưa có nội dung — hãy viết content trước khi chèn ảnh tự động.")
    if not str(project.get("primary_keyword") or "").strip():
        raise ValueError("Cần từ khóa chính (primary keyword) để tìm ảnh phù hợp.")

    enriched = enrich_project_with_context_images(
        project,
        max_inline=max_inline,
        update_featured=update_featured,
        force=force,
    )
    fields: dict[str, Any] = {
        "content": enriched["content"],
        "gallery_images": enriched["gallery_images"],
    }
    if enriched.get("featured_image"):
        fields["featured_image"] = enriched["featured_image"]
    updated = update_content_ai_project_fields(project_id, fields, user_id=user_id)
    if not updated:
        raise ValueError("Không cập nhật được dự án.")
    full = get_content_ai_project(project_id, user_id=user_id) or updated
    return {
        "ok": True,
        "project_id": project_id,
        "featured_image": enriched.get("featured_image") or "",
        "inline_images_count": enriched.get("inline_images_count") or 0,
        "content_images_total": enriched.get("content_images_total") or 0,
        "source": enriched.get("image_source") or "web_image_search",
        "query": enriched.get("used_query") or "",
        "project": full,
    }
