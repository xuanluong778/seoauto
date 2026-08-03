"""Context-aware image prompts, ALT text, and placement for Content AI articles."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

# CamelCase aliases (spec / JS interop)
extractImageContextsFromArticle = None  # set after defs
buildImagePromptForSection = None
buildSEOImageGenerationPrompt = None
suggestImageAltText = None
suggestImageCaption = None
chooseImagePlacement = None

_TECHNICAL_SEO_RE = re.compile(
    r"technical\s*seo|seo\s*kỹ\s*thuật|audit|core\s*web\s*vitals|lighthouse|"
    r"crawl|index(?:ing)?|sitemap|schema|structured\s*data|robots\.txt|"
    r"canonical|hreflang|javascript\s*seo|log\s*file|render|tốc\s*độ\s*web|"
    r"page\s*speed|web\s*vitals|https|ssl|redirect|404|site\s*health",
    re.I,
)
_CONTENT_SEO_RE = re.compile(
    r"content\s*seo|seo\s*nội\s*dung|viết\s*bài|blog|outline|dàn\s*bài|"
    r"keyword\s*research|nghiên\s*cứu\s*từ\s*khóa|meta\s*description|"
    r"title\s*tag|copywriting|chiến\s*lược\s*nội\s*dung|content\s*strategy|"
    r"editor|content\s*calendar|bài\s*viết\s*seo",
    re.I,
)

_VISUAL_THEMES: dict[str, str] = {
    "technical_seo": (
        "website SEO audit dashboard on laptop, technical crawl report, "
        "Core Web Vitals metrics chart, schema markup diagram, site speed performance graph, "
        "SEO specialist analyzing website health data in modern office"
    ),
    "content_seo": (
        "content marketer writing SEO blog post, keyword research notes, "
        "article outline on screen, content strategy whiteboard, "
        "editor optimizing blog for search intent in bright workspace"
    ),
    "general": (
        "professional photorealistic scene clearly related to the article topic, "
        "modern trustworthy business environment, natural lighting"
    ),
}

_IMAGE_STYLE_ALIASES: dict[str, str] = {
    "realistic": "realistic_business",
    "realistic_business": "realistic_business",
    "realistic business": "realistic_business",
    "business": "realistic_business",
    "3d": "premium_3d_seo",
    "3d_illustration": "premium_3d_seo",
    "3d illustration": "premium_3d_seo",
    "premium_3d": "premium_3d_seo",
    "premium_3d_seo": "premium_3d_seo",
    "premium 3d": "premium_3d_seo",
    "premium 3d seo": "premium_3d_seo",
    "flat": "flat_vector",
    "flat_vector": "flat_vector",
    "flat vector": "flat_vector",
    "vector": "flat_vector",
    "dashboard": "modern_dashboard",
    "modern_dashboard": "modern_dashboard",
    "modern dashboard": "modern_dashboard",
    "vietnamese": "vietnamese_business",
    "vietnamese_business": "vietnamese_business",
    "vietnamese business": "vietnamese_business",
    "vietnamese business context": "vietnamese_business",
}

_STYLE_RENDERING: dict[str, str] = {
    "realistic_business": (
        "Photorealistic professional business photography, natural lighting, "
        "shallow depth of field, premium blog and corporate website aesthetic."
    ),
    "3d_illustration": (
        "High-quality 3D illustration, soft global illumination, modern SaaS marketing look, "
        "polished materials, not childish or game-like."
    ),
    "premium_3d_seo": (
        "High-end 3D render, clean composition, soft lighting, professional SaaS look, "
        "modern Vietnamese business aesthetic, sharp details, no clutter."
    ),
    "flat_vector": (
        "Clean flat vector illustration, simple shapes, limited palette, editorial blog style, "
        "clear focal subject, plenty of negative space."
    ),
    "modern_dashboard": (
        "Modern software dashboard UI on screens, data charts and analytics panels, "
        "sleek dark or light interface, tech workspace context."
    ),
    "vietnamese_business": (
        "Contemporary Vietnamese business environment, Southeast Asian office or service setting, "
        "authentic professional context, modern urban Vietnam cues without stereotypes."
    ),
}


@lru_cache(maxsize=1)
def _env_local() -> dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "env.local"
    if not p.is_file():
        return {}
    return {str(k): str(v or "") for k, v in (dotenv_values(p) or {}).items() if k}


def get_default_content_ai_image_style() -> str:
    """Style mặc định từ CONTENT_AI_IMAGE_STYLE trong env.local."""
    raw = (os.getenv("CONTENT_AI_IMAGE_STYLE") or _env_local().get("CONTENT_AI_IMAGE_STYLE") or "").strip()
    return normalize_image_style(raw) if raw else "premium_3d_seo"


def normalize_image_style(image_style: str) -> str:
    raw = str(image_style or "").strip().lower()
    if not raw:
        return "realistic_business"
    for key in (raw, raw.replace("_", " "), raw.replace(" ", "_")):
        if key in _IMAGE_STYLE_ALIASES:
            return _IMAGE_STYLE_ALIASES[key]
    return "realistic_business"


def _premium_3d_visual_concept(
    *,
    main_keyword: str,
    article_title: str,
    section_heading: str,
    section_summary: str,
    topic: str,
) -> str:
    """Mô tả cảnh 3D theo chủ đề bài — bám layout workspace SEO premium."""
    heading = section_heading or article_title or main_keyword or "SEO overview"
    kw = main_keyword or article_title or "SEO"
    summary = _clean_label(section_summary, max_len=220)

    if topic == "technical_seo":
        base = (
            "A modern digital marketing workspace focused on technical SEO: analytics dashboard "
            "with crawl health charts, Core Web Vitals graphs, sitemap and schema markup panels, "
            "site speed metrics on a large monitor, and a subtle AI assistant interface "
            f"helping analyze the topic \"{heading}\" (article theme: {kw})."
        )
    elif topic == "content_seo":
        base = (
            "A modern digital marketing workspace for content SEO: search ranking charts, "
            "keyword research panels, editorial content planning board, blog outline on screen, "
            "SEO content calendar, and an AI writing assistant interface "
            f"supporting the section \"{heading}\" (article theme: {kw})."
        )
    else:
        base = (
            "A modern digital marketing workspace with SEO analytics dashboard, search ranking "
            "charts, content planning board, and AI assistant interface, clearly illustrating "
            f"\"{heading}\" (article theme: {kw})."
        )
    if summary and summary.lower() not in base.lower():
        base += f" Section context: {summary}."
    return base


def build_premium_3d_seo_illustration_prompt(
    *,
    main_keyword: str = "",
    article_title: str = "",
    section_heading: str = "",
    section_summary: str = "",
    brand_name: str = "",
    industry: str = "",
    target_audience: str = "",
    include_brand_logo: bool = False,
) -> str:
    """
    Prompt chuẩn ảnh hero/inline SEO blog — premium 3D illustration (16:9, tiếng Việt).
    """
    kw = _clean_label(main_keyword, max_len=90) or "SEO"
    title = _clean_label(article_title, max_len=120) or kw
    heading = _clean_label(section_heading, max_len=120) or title
    summary = _clean_label(section_summary, max_len=400)
    audience = _clean_label(target_audience, max_len=90) or (
        "business owners and marketers in Vietnam"
    )
    topic = detect_article_topic(
        main_keyword=kw,
        title=title or heading,
        article_text=summary,
    )
    visual = _premium_3d_visual_concept(
        main_keyword=kw,
        article_title=title,
        section_heading=heading,
        section_summary=summary,
        topic=topic,
    )
    brand_bit = ""
    if brand_name and not include_brand_logo:
        brand_bit = (
            f'\nBrand note: article for "{_clean_label(brand_name, max_len=60)}" — '
            "do not render logos, wordmarks, or readable brand text."
        )
    elif brand_name and include_brand_logo:
        brand_bit = f'\nBrand: "{_clean_label(brand_name, max_len=60)}" (only if a real logo asset exists).'

    industry_bit = ""
    ind = _clean_label(industry, max_len=80)
    if ind:
        industry_bit = f"\nIndustry context: {ind}."

    return (
        "Create a premium 3D illustration for a Vietnamese SEO blog article.\n\n"
        f"Topic: {title}\n"
        f"Main keyword: {kw}\n"
        f"Section: {heading}\n"
        f"Audience: {audience}.\n\n"
        "Visual concept:\n"
        f"{visual}\n\n"
        "Style:\n"
        "High-end 3D render, clean composition, soft lighting, professional SaaS look, "
        "modern Vietnamese business aesthetic, sharp details, no clutter.\n\n"
        "Brand feeling:\n"
        "Trustworthy, expert, practical, premium.\n\n"
        "Image requirements:\n"
        "16:9 ratio, blog hero image, no watermark, no random text, no distorted hands, "
        "no duplicated objects, no readable UI text or paragraphs on screens."
        f"{brand_bit}{industry_bit}"
    ).strip()


def _infer_industry(
    *,
    main_keyword: str,
    article_title: str,
    section_summary: str,
    industry: str,
) -> str:
    explicit = _clean_label(industry, max_len=80)
    if explicit:
        return explicit
    topic = detect_article_topic(
        main_keyword=main_keyword,
        title=article_title,
        article_text=section_summary,
    )
    return {
        "technical_seo": "Technical SEO and website optimization",
        "content_seo": "Content marketing and SEO copywriting",
        "general": "Digital marketing and online business",
    }.get(topic, "Digital marketing and online business")


def _build_visual_scene(
    *,
    main_keyword: str,
    article_title: str,
    section_heading: str,
    section_summary: str,
    topic: str,
) -> str:
    """Mô tả cảnh cụ thể theo chủ đề — tránh prompt chung chung."""
    kw = main_keyword or article_title or "SEO"
    heading = section_heading or article_title or kw
    summary = section_summary[:280] if section_summary else ""

    if topic == "technical_seo":
        base = (
            f"An SEO specialist analyzing a technical SEO dashboard on a laptop for the topic "
            f"\"{heading}\" (article theme: {kw}). The screen shows crawl status charts, "
            f"website speed metrics, sitemap and schema visualization, indexing health indicators, "
            f"modern analytics UI, professional office lighting."
        )
    elif topic == "content_seo":
        base = (
            f"A content strategist or SEO writer working on the section \"{heading}\" "
            f"(article theme: {kw}). Visible elements: keyword research notes, article outline, "
            f"blog editor on screen, content calendar or optimization checklist, bright modern workspace."
        )
    else:
        base = (
            f"A professional scene illustrating \"{heading}\" for a blog article about {kw}. "
            f"Clear connection to the industry topic, credible business environment."
        )

    if summary and summary.lower() not in base.lower():
        base += f" Context from the article section: {summary}."
    return base


def build_seo_image_generation_prompt(
    *,
    main_keyword: str = "",
    article_title: str = "",
    section_heading: str = "",
    section_summary: str = "",
    brand_name: str = "",
    industry: str = "",
    target_audience: str = "",
    image_style: str = "",
    language: str = "vi",
    include_brand_logo: bool = False,
) -> str:
    """
    Build a high-quality English image-generation prompt for OpenAI Images or similar models.

    Focus: correct SEO article context, professional blog imagery, no illegible text overlays.
    """
    kw = _clean_label(main_keyword, max_len=90)
    title = _clean_label(article_title, max_len=120)
    heading = _clean_label(section_heading, max_len=120)
    summary = _clean_label(section_summary, max_len=400)
    brand = _clean_label(brand_name, max_len=70)
    audience = _clean_label(target_audience, max_len=90)
    lang = _clean_label(language, max_len=10).lower() or "vi"
    style_key = normalize_image_style(image_style) if image_style else get_default_content_ai_image_style()

    if style_key in ("premium_3d_seo", "3d_illustration"):
        return build_premium_3d_seo_illustration_prompt(
            main_keyword=main_keyword,
            article_title=article_title,
            section_heading=section_heading,
            section_summary=section_summary,
            brand_name=brand_name,
            industry=industry,
            target_audience=target_audience,
            include_brand_logo=include_brand_logo,
        )[:3900]

    topic = detect_article_topic(
        main_keyword=kw,
        title=title or heading,
        article_text=summary,
    )
    industry_label = _infer_industry(
        main_keyword=kw,
        article_title=title,
        section_summary=summary,
        industry=industry,
    )
    scene = _build_visual_scene(
        main_keyword=kw,
        article_title=title,
        section_heading=heading,
        section_summary=summary,
        topic=topic,
    )
    style_block = _STYLE_RENDERING.get(style_key, _STYLE_RENDERING["realistic_business"])

    locale_bit = ""
    if lang.startswith("vi") or style_key == "vietnamese_business":
        locale_bit = (
            " Setting may reflect Vietnamese business context where appropriate "
            "(modern office, urban professional environment)."
        )

    audience_bit = f" Intended audience: {audience}." if audience else ""
    brand_bit = ""
    if brand:
        if include_brand_logo:
            brand_bit = f" Brand name reference (no invented logo unless provided): {brand}."
        else:
            brand_bit = (
                f" Article is for brand \"{brand}\" but do NOT render any logo, wordmark, "
                f"or readable brand text on the image."
            )

    constraints = (
        "Constraints: suitable for a professional website or SEO blog article hero/inline image; "
        "no paragraphs of text, no UI labels with readable words, no watermarks, no stock-photo clichés "
        "unrelated to the topic; no random celebrities; no wrong industry (stay within the stated field); "
        "no meme or entertainment imagery."
    )
    if not include_brand_logo:
        constraints += " Do not add company logos or trademark symbols."

    prompt = (
        f"Create a single high-quality image for an SEO blog article. "
        f"Main keyword / topic: {kw or 'SEO'}. "
        f"Article title: {title or heading or kw}. "
        f"Section focus: {heading or title or 'featured overview'}. "
        f"Industry: {industry_label}. "
        f"Visual scene: {scene} "
        f"Rendering style: {style_block}"
        f"{locale_bit}{audience_bit}{brand_bit} "
        f"{constraints}"
    )
    return re.sub(r"\s+", " ", prompt).strip()[:3900]


def _strip_html_text(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(s)).strip()


def _clean_label(text: str, *, max_len: int = 200) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    return s[:max_len].strip()


def detect_article_topic(
    *,
    main_keyword: str = "",
    title: str = "",
    article_text: str = "",
) -> str:
    """Return technical_seo | content_seo | general."""
    blob = " ".join(
        [
            str(main_keyword or ""),
            str(title or ""),
            str(article_text or "")[:2500],
        ]
    )
    tech = len(_TECHNICAL_SEO_RE.findall(blob))
    content = len(_CONTENT_SEO_RE.findall(blob))
    if tech >= 2 and tech >= content:
        return "technical_seo"
    if content >= 2 and content > tech:
        return "content_seo"
    if tech >= 1 and content == 0:
        return "technical_seo"
    if content >= 1 and tech == 0:
        return "content_seo"
    return "general"


def extract_image_contexts_from_article(
    article_html: str = "",
    article_text: str = "",
    *,
    outline: str = "",
) -> list[dict[str, Any]]:
    """
    Trích các block H2/H3 kèm đoạn văn ngay sau heading (ngữ cảnh chèn ảnh).
    """
    html = str(article_html or "").strip()
    if not html and article_text:
        if re.search(r"<\s*[a-z]", article_text, re.I):
            html = article_text
        else:
            parts: list[str] = []
            for block in re.split(r"\n{2,}", article_text):
                b = block.strip()
                if not b:
                    continue
                if re.match(r"^#{1,6}\s+", b):
                    level = len(re.match(r"^(#+)", b).group(1))
                    text = re.sub(r"^#+\s*", "", b).strip()
                    tag = "h2" if level <= 2 else "h3"
                    parts.append(f"<{tag}>{text}</{tag}>")
                else:
                    parts.append(f"<p>{b}</p>")
            html = "\n".join(parts)

    contexts: list[dict[str, Any]] = []
    if html:
        pattern = re.compile(
            r"<(h[23])\b[^>]*>(.*?)</\1>(.*?)(?=<h[23]\b|$)",
            re.I | re.S,
        )
        for idx, m in enumerate(pattern.finditer(html)):
            level = int(m.group(1)[1])
            heading = _strip_html_text(m.group(2))
            body_html = m.group(3) or ""
            paras = re.findall(r"<p\b[^>]*>(.*?)</p>", body_html, flags=re.I | re.S)
            body_parts = [_strip_html_text(p) for p in paras if _strip_html_text(p)]
            content = " ".join(body_parts)[:1200]
            if not heading:
                continue
            contexts.append(
                {
                    "index": idx,
                    "heading": heading,
                    "level": level,
                    "content": content,
                    "topic_hint": detect_article_topic(
                        article_text=content,
                        title=heading,
                    ),
                }
            )

    if not contexts and outline:
        for idx, m in enumerate(re.finditer(r"^#{2,3}\s+(.+?)\s*$", outline, flags=re.M)):
            heading = m.group(1).strip()
            if heading:
                contexts.append(
                    {
                        "index": idx,
                        "heading": heading,
                        "level": 2,
                        "content": "",
                        "topic_hint": "general",
                    }
                )

    if not contexts:
        plain = _strip_html_text(html or article_text)
        if plain:
            contexts.append(
                {
                    "index": 0,
                    "heading": "",
                    "level": 0,
                    "content": plain[:1200],
                    "topic_hint": detect_article_topic(article_text=plain),
                }
            )
    return contexts


def build_image_prompt_for_section(
    section_heading: str,
    section_content: str,
    main_keyword: str,
    brand_name: str = "",
    target_audience: str = "",
    *,
    article_title: str = "",
    industry: str = "",
    image_style: str = "",
    language: str = "vi",
) -> str:
    """Wrapper tương thích cũ — delegate tới build_seo_image_generation_prompt."""
    return build_seo_image_generation_prompt(
        main_keyword=main_keyword,
        article_title=article_title or section_heading,
        section_heading=section_heading,
        section_summary=section_content,
        brand_name=brand_name,
        industry=industry,
        target_audience=target_audience,
        image_style=image_style or get_default_content_ai_image_style(),
        language=language,
        include_brand_logo=False,
    )


def build_image_search_query_for_section(
    section_heading: str,
    section_content: str,
    main_keyword: str,
    *,
    brand_name: str = "",
) -> str:
    """Câu truy vấn ngắn (VI) cho Google CSE / web image search."""
    from app.services.image_relevance import build_llm_image_search_query

    kw = _clean_label(main_keyword, max_len=60)
    heading = _clean_label(section_heading, max_len=80)
    topic = detect_article_topic(main_keyword=kw, title=heading, article_text=section_content)

    topic_noun = {
        "technical_seo": "SEO audit dashboard website",
        "content_seo": "viết content SEO blog",
        "general": "minh họa",
    }.get(topic, "minh họa")

    llm_q = build_llm_image_search_query(
        primary_keyword=kw,
        title=heading or kw,
        section_heading=heading,
    )
    if llm_q and len(llm_q) >= 4:
        return llm_q[:120]

    parts = [p for p in (kw, heading, topic_noun) if p]
    return " ".join(parts)[:120] if parts else "ảnh minh họa SEO"


def suggest_image_alt_text(image_context: dict[str, Any], main_keyword: str) -> str:
    """ALT chuẩn SEO: tự nhiên, có biến thể từ khóa, không nhồi."""
    kw = _clean_label(main_keyword, max_len=70)
    heading = _clean_label(str(image_context.get("heading") or ""), max_len=90)
    content = _clean_label(str(image_context.get("content") or ""), max_len=120)

    if heading and kw:
        kw_low = kw.lower()
        head_low = heading.lower()
        if kw_low in head_low or head_low in kw_low:
            alt = heading
        else:
            alt = f"{heading} — {kw}"
    elif heading:
        alt = heading
    elif kw:
        alt = f"Minh họa {kw}"
    else:
        alt = "Minh họa bài viết"

    if content and len(alt) < 60:
        snippet = content.split(".")[0].strip()[:50]
        if snippet and snippet.lower() not in alt.lower():
            alt = f"{alt}, {snippet}"

    alt = re.sub(r"\s*[,—-]\s*[,—-]+", " — ", alt)
    alt = re.sub(r"\s+", " ", alt).strip()
    if len(alt) > 125:
        alt = alt[:122].rstrip(" ,—-") + "…"
    return alt


def suggest_image_caption(image_context: dict[str, Any]) -> str:
    """Caption ngắn, đúng ngữ cảnh (tuỳ chọn hiển thị)."""
    heading = _clean_label(str(image_context.get("heading") or ""), max_len=100)
    content = _clean_label(str(image_context.get("content") or ""), max_len=160)
    if heading:
        cap = f"Hình minh họa: {heading}"
    elif content:
        cap = content.split(".")[0].strip()
        if cap:
            cap = cap[0].upper() + cap[1:] if len(cap) > 1 else cap
    else:
        return ""
    if len(cap) > 140:
        cap = cap[:137].rstrip() + "…"
    return cap


def choose_image_placement(
    article_outline: str = "",
    article_html: str = "",
    *,
    max_images: int = 4,
    min_words_between: int = 120,
) -> list[dict[str, Any]]:
    """
    Chọn vị trí chèn ảnh (theo H2) kèm context từng section.
    """
    contexts = extract_image_contexts_from_article(
        article_html=article_html,
        outline=article_outline,
    )
    h2_contexts = [c for c in contexts if int(c.get("level") or 0) <= 2 and c.get("heading")]
    if not h2_contexts:
        h2_contexts = [c for c in contexts if c.get("heading")] or contexts

    max_n = max(0, min(int(max_images), 6))
    if not max_n or not h2_contexts:
        return []

    plain_len = len(_strip_html_text(article_html))
    if plain_len < min_words_between * 2:
        max_n = min(max_n, 1)

    if len(h2_contexts) <= max_n:
        chosen = h2_contexts
    else:
        step = len(h2_contexts) / max_n
        chosen = [h2_contexts[int(i * step)] for i in range(max_n)]

    h2_order: list[str] = []
    if article_html:
        for m in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", article_html, flags=re.I | re.S):
            t = _strip_html_text(m.group(1))
            if t:
                h2_order.append(t)

    placements: list[dict[str, Any]] = []
    used_h2_idx: set[int] = set()
    for ctx in chosen:
        heading = str(ctx.get("heading") or "").strip()
        h2_index = 0
        if h2_order and heading:
            for i, h in enumerate(h2_order):
                if h.lower() == heading.lower() and i not in used_h2_idx:
                    h2_index = i
                    used_h2_idx.add(i)
                    break
            else:
                for i, h in enumerate(h2_order):
                    if i not in used_h2_idx:
                        h2_index = i
                        used_h2_idx.add(i)
                        break
        placements.append(
            {
                "placement_type": "h2",
                "h2_index": h2_index,
                "paragraph_index": None,
                "context": dict(ctx),
            }
        )
    return placements


# CamelCase aliases
extractImageContextsFromArticle = extract_image_contexts_from_article
buildImagePromptForSection = build_image_prompt_for_section
buildSEOImageGenerationPrompt = build_seo_image_generation_prompt
buildPremium3dSeoIllustrationPrompt = build_premium_3d_seo_illustration_prompt
suggestImageAltText = suggest_image_alt_text
suggestImageCaption = suggest_image_caption
chooseImagePlacement = choose_image_placement
