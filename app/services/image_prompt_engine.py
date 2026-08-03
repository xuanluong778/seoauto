"""Professional image prompt builder for AI Visual Content Studio."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from app.services.content_image_context import (
    build_premium_3d_seo_illustration_prompt,
    detect_article_topic,
)
from app.services.image_style_presets import (
    PRESET_SEO_3D_PREMIUM,
    get_style_preset,
    normalize_style_preset,
)

_IMAGE_TYPES: dict[str, dict[str, str]] = {
    "hero_featured": {
        "label_vi": "Ảnh đại diện (Featured)",
        "composition_en": "Hero featured image for blog article, strong central subject, editorial cover quality.",
    },
    "inline_h2": {
        "label_vi": "Minh họa trong bài (H2)",
        "composition_en": "Section illustration placed after an H2 heading, supports the subsection topic clearly.",
    },
    "thumbnail": {
        "label_vi": "Thumbnail / Preview",
        "composition_en": "Compact thumbnail, readable at small size, one clear focal point.",
    },
    "social_cover": {
        "label_vi": "Ảnh bìa social",
        "composition_en": "Social media cover image, safe margins, bold composition for feed preview.",
    },
    "ads_creative": {
        "label_vi": "Creative quảng cáo",
        "composition_en": "Paid ads creative, conversion-focused layout, product or benefit visual.",
    },
}

_BRAND_TONES: dict[str, str] = {
    "professional": "Professional, trustworthy, calm confidence.",
    "friendly": "Friendly, approachable, warm and optimistic.",
    "bold": "Bold, energetic, high contrast, decisive.",
    "luxury": "Premium luxury, refined, subtle elegance.",
    "tech": "Modern tech-forward, innovative, clean digital aesthetic.",
    "neutral": "Balanced neutral brand tone, versatile marketing look.",
}


def _clean(text: str, *, max_len: int = 500) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    return s[:max_len].strip()


def _strip_html(text: str) -> str:
    s = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(s)).strip()


def extract_h2_list(html: str, outline: str = "") -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", html or "", flags=re.I | re.S):
        t = _strip_html(m.group(1))
        if t and t not in out:
            out.append(t)
    for m in re.finditer(r"^##\s+(.+?)\s*$", outline or "", flags=re.M):
        t = m.group(1).strip()
        if t and t not in out:
            out.append(t)
    return out[:12]


def section_snippet_for_h2(html: str, heading: str, *, max_chars: int = 400) -> str:
    if not html or not heading:
        return ""
    pat = re.compile(
        rf"<h2\b[^>]*>\s*{re.escape(heading)}\s*</h2>(.*?)(?=<h2\b|$)",
        flags=re.I | re.S,
    )
    m = pat.search(html)
    if not m:
        return ""
    return _strip_html(m.group(1))[:max_chars]


def normalize_image_type(raw: str | None) -> str:
    key = re.sub(r"[^a-z0-9_]", "", str(raw or "inline_h2").strip().lower())
    return key if key in _IMAGE_TYPES else "inline_h2"


def normalize_brand_tone(raw: str | None) -> str:
    key = re.sub(r"[^a-z0-9_]", "", str(raw or "professional").strip().lower())
    return key if key in _BRAND_TONES else "professional"


def list_image_types() -> list[dict[str, str]]:
    return [{"id": k, "label_vi": v["label_vi"]} for k, v in _IMAGE_TYPES.items()]


def build_professional_image_prompt(
    *,
    title: str = "",
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
    content_html: str = "",
    outline_content: str = "",
    section_heading: str = "",
    section_summary: str = "",
    target_audience: str = "",
    industry: str = "",
    brand_name: str = "",
    brand_tone: str = "professional",
    image_type: str = "inline_h2",
    style_preset: str = PRESET_SEO_3D_PREMIUM,
    aspect_ratio: str = "16:9",
    include_text: bool = False,
    text_hint: str = "",
    language: str = "vi",
    variation_index: int = 0,
) -> str:
    """
    Build a single high-quality image generation prompt from article + brand context.
    """
    preset_id = normalize_style_preset(style_preset)
    preset = get_style_preset(preset_id)
    itype = normalize_image_type(image_type)
    type_meta = _IMAGE_TYPES[itype]
    tone = _BRAND_TONES.get(normalize_brand_tone(brand_tone), _BRAND_TONES["professional"])

    kw = _clean(primary_keyword, max_len=120)
    ttl = _clean(title, max_len=200)
    h2 = _clean(section_heading, max_len=160)
    summary = _clean(section_summary or _strip_html(content_html)[:400], max_len=400)
    aud = _clean(target_audience, max_len=120)
    ind = _clean(industry, max_len=80)
    brand = _clean(brand_name, max_len=80)
    sec_kw = ", ".join(_clean(x, max_len=40) for x in (secondary_keywords or [])[:6] if _clean(x, max_len=40))

    topic = detect_article_topic(
        main_keyword=kw,
        title=ttl,
        article_text=_strip_html(content_html) + " " + (outline_content or ""),
    )

    if preset_id == PRESET_SEO_3D_PREMIUM and itype in ("inline_h2", "hero_featured", "thumbnail"):
        base = build_premium_3d_seo_illustration_prompt(
            main_keyword=kw,
            article_title=ttl,
            section_heading=h2 or ttl,
            section_summary=summary,
            brand_name=brand,
            industry=ind,
            target_audience=aud or "Vietnamese business owners and marketers",
        )
        parts = [base, type_meta["composition_en"], f"Brand tone: {tone}."]
        if brand:
            parts.append(f"Brand context: {brand} (visual mood only, no logo unless generic).")
        if include_text and text_hint:
            parts.append(f"Leave clean space for short Vietnamese text: {_clean(text_hint, max_len=80)}.")
        elif include_text and ttl:
            parts.append(f"Leave subtle space for headline area; topic: {ttl[:80]}.")
        else:
            parts.append("NO text, NO letters, NO watermarks, NO logos in the image.")
        if variation_index:
            parts.append(f"Visual variation #{variation_index + 1}: alternate angle and color accent.")
        return " ".join(parts)

    scene_subject = h2 or kw or ttl or "the article topic"
    parts = [
        f"Create a professional marketing image for a Vietnamese SEO blog.",
        type_meta["composition_en"],
        f"Article title: {ttl or 'N/A'}.",
        f"Main keyword: {kw or 'N/A'}.",
        f"Visual subject for this image: {scene_subject}.",
        f"Section context: {summary or 'General article illustration.'}.",
        f"Style preset ({preset['label_vi']}): {preset['rendering_en']}",
        f"Aspect ratio target: {aspect_ratio}.",
        f"Brand tone: {tone}",
    ]
    if aud:
        parts.append(f"Target audience: {aud}.")
    if ind:
        parts.append(f"Industry: {ind}.")
    if brand:
        parts.append(f"Brand: {brand} (mood only).")
    if sec_kw:
        parts.append(f"Related keywords: {sec_kw}.")
    parts.append(f"Article topic cluster: {topic}.")
    if include_text and text_hint:
        parts.append(
            f"Include minimal readable Vietnamese text in design: {_clean(text_hint, max_len=100)}. "
            "Typography must be crisp and legible."
        )
    elif include_text and ttl:
        parts.append(
            f"Include minimal Vietnamese headline text related to: {ttl[:90]}. Typography crisp."
        )
    else:
        parts.append(
            "CRITICAL: no text, no letters, no numbers, no watermarks, no UI mockup labels, no logos."
        )
    if variation_index:
        parts.append(
            f"Variation {variation_index + 1}: different camera angle, lighting, and accent color."
        )
    return " ".join(parts)


def build_studio_context_from_project(project: dict[str, Any]) -> dict[str, Any]:
    """Normalize project row into studio generation context."""
    html = str(project.get("content") or "")
    outline = str(project.get("outline_content") or "")
    h2s = extract_h2_list(html, outline)
    return {
        "title": str(project.get("title") or ""),
        "primary_keyword": str(project.get("primary_keyword") or ""),
        "secondary_keywords": project.get("secondary_keywords") or [],
        "content_html": html,
        "outline_content": outline,
        "h2_headings": h2s,
        "target_audience": str(project.get("target_audience") or ""),
        "industry": str(project.get("industry") or ""),
        "brand_name": str(project.get("brand_name") or project.get("target_website") or ""),
    }
