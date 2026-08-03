from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def _to_int(v: object) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _is_decorative_image(tag) -> bool:
    role = str(tag.get("role") or "").strip().lower()
    aria_hidden = str(tag.get("aria-hidden") or "").strip().lower()
    w = _to_int(tag.get("width"))
    h = _to_int(tag.get("height"))
    classes = tag.get("class") or []
    if isinstance(classes, str):
        class_tokens = classes.lower().split()
    else:
        class_tokens = [str(c).lower() for c in classes if c]
    class_str = " ".join(class_tokens)
    has_iconish_class = any(tok in class_str for tok in ("icon", "logo", "avatar", "sprite"))
    return role == "presentation" or aria_hidden == "true" or (w > 0 and h > 0 and w <= 48 and h <= 48) or has_iconish_class


def _heading_texts(soup: BeautifulSoup, tag: str, *, limit: int = 30) -> list[str]:
    out: list[str] = []
    for node in soup.find_all(tag)[:limit]:
        text = node.get_text(" ", strip=True)
        if text:
            out.append(text[:500])
    return out


def _nearest_section_heading(tag) -> str:
    """Heading gần nhất (H1/H2/H3) phía trên ảnh/link — dùng làm vị trí ngữ cảnh."""
    node = tag
    for _ in range(12):
        if node is None:
            break
        prev = node.find_previous(["h1", "h2", "h3"])
        if prev is not None:
            text = prev.get_text(" ", strip=True)
            if text:
                return text[:200]
        node = getattr(node, "parent", None)
    return ""


def _first_meaningful_paragraph(soup: BeautifulSoup) -> str:
    for node in soup.find_all("p"):
        text = node.get_text(" ", strip=True)
        if len(text) >= 40:
            return text[:2000]
    return ""


def extract_intro_text(soup: BeautifulSoup) -> dict[str, Any]:
    """Đoạn mở bài — ưu tiên p đầu tiên sau H1, fallback p đầu tiên trong body."""
    h1 = soup.find("h1")
    intro = ""
    position = "first_paragraph"
    if h1 is not None:
        for node in h1.find_all_next("p"):
            text = node.get_text(" ", strip=True)
            if len(text) >= 40:
                intro = text[:2000]
                position = "after_h1"
                break
    if not intro:
        intro = _first_meaningful_paragraph(soup)
    return {
        "text": intro,
        "length": len(intro),
        "position": position,
        "word_count": len([w for w in intro.split() if w]) if intro else 0,
    }


def extract_content_sections(soup: BeautifulSoup, *, limit: int = 12) -> list[dict[str, Any]]:
    """Các section theo H2/H3 kèm đoạn text mẫu."""
    sections: list[dict[str, Any]] = []
    for heading in soup.find_all(["h2", "h3"])[:limit]:
        level = heading.name
        title = heading.get_text(" ", strip=True)[:300]
        if not title:
            continue
        parts: list[str] = []
        wc = 0
        for node in heading.find_all_next():
            if node.name in ("h1", "h2", "h3") and node is not heading:
                break
            if node.name == "p":
                text = node.get_text(" ", strip=True)
                if text:
                    parts.append(text[:600])
                    wc += len(text.split())
            if wc >= 120:
                break
        sections.append(
            {
                "heading": title,
                "level": level,
                "text": " ".join(parts)[:1200],
                "word_count": wc,
            }
        )
    return sections


def _extract_images(soup: BeautifulSoup, *, limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, image in enumerate(soup.find_all("img")[:limit], start=1):
        decorative = _is_decorative_image(image)
        alt_raw = image.get("alt")
        alt_text = "" if alt_raw is None else str(alt_raw).strip()
        missing_alt = (not decorative) and alt_text == ""
        w = _to_int(image.get("width"))
        h = _to_int(image.get("height"))
        missing_size = w <= 0 or h <= 0
        section_heading = _nearest_section_heading(image)
        rows.append(
            {
                "src": str(image.get("src") or image.get("data-src") or "").strip()[:500],
                "alt": alt_text,
                "missing_alt": missing_alt,
                "missing_size": missing_size,
                "decorative": decorative,
                "position": index,
                "section_heading": section_heading,
                "context": section_heading or f"img #{index}",
            }
        )
    return rows


def _extract_links(soup: BeautifulSoup, base_url: str = "", *, limit: int = 80) -> list[dict[str, Any]]:
    host = ""
    if base_url:
        try:
            host = (urlparse(base_url).netloc or "").lower().lstrip("www.")
        except Exception:
            host = ""
    rows: list[dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True)[:limit]:
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        abs_href = href
        if base_url and not href.startswith(("http://", "https://")):
            try:
                abs_href = urljoin(base_url, href)
            except Exception:
                abs_href = href
        anchor_text = anchor.get_text(" ", strip=True)[:300]
        is_internal = True
        if abs_href.startswith(("http://", "https://")) and host:
            try:
                link_host = (urlparse(abs_href).netloc or "").lower().lstrip("www.")
                is_internal = bool(link_host) and (link_host == host or link_host.endswith("." + host))
            except Exception:
                is_internal = False
        section_heading = _nearest_section_heading(anchor)
        rows.append(
            {
                "href": abs_href[:500],
                "anchor": anchor_text,
                "is_internal": is_internal,
                "section_heading": section_heading,
                "context": section_heading or anchor_text[:80] or abs_href[:80],
            }
        )
    return rows


def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = (meta_tag.get("content") or "").strip() if meta_tag else ""

    h1_count = len(soup.find_all("h1"))

    return {
        "title": title,
        "meta_description": meta_description,
        "h1_count": h1_count,
    }


def parse_page_seo_data(html: str, *, base_url: str = "") -> dict:
    safe_html = html if isinstance(html, str) else ""
    soup = BeautifulSoup(safe_html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_tag = soup.find("meta", attrs={"name": "description"})
    if not meta_tag:
        meta_tag = soup.find("meta", attrs={"property": "og:description"})
    meta_description = (meta_tag.get("content") or "").strip() if meta_tag else ""

    canonical_tag = soup.find("link", rel=lambda rel: rel and "canonical" in str(rel).lower())
    canonical = (canonical_tag.get("href") or "").strip() if canonical_tag else ""

    h1_texts = _heading_texts(soup, "h1")
    h2_texts = _heading_texts(soup, "h2")
    h3_texts = _heading_texts(soup, "h3")
    h1_count = len(h1_texts)
    h2_count = len(h2_texts)

    image_rows = _extract_images(soup)
    images_total = len(image_rows)
    images_missing_alt = sum(1 for row in image_rows if row.get("missing_alt"))
    images_missing_size = sum(1 for row in image_rows if row.get("missing_size") and not row.get("decorative"))
    link_rows = _extract_links(soup, base_url)

    intro_pkg = extract_intro_text(soup)
    content_sections = extract_content_sections(soup)

    # Remove non-content blocks before text extraction for cleaner word count.
    for tag in soup(["script", "style"]):
        tag.decompose()
    text_content = soup.get_text(separator=" ", strip=True)
    word_count = len([word for word in text_content.split() if word])

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "h1_count": h1_count,
        "h2_count": h2_count,
        "h1_texts": h1_texts,
        "h2_texts": h2_texts,
        "h3_texts": h3_texts,
        "headings": {"h1": h1_texts, "h2": h2_texts, "h3": h3_texts},
        "word_count": word_count,
        "visible_text": text_content[:4000],
        "intro": intro_pkg,
        "intro_text": str(intro_pkg.get("text") or ""),
        "content_sections": content_sections,
        "images_total": images_total,
        "images_missing_alt": images_missing_alt,
        "images_missing_size": images_missing_size,
        "images": image_rows,
        "links": link_rows,
    }
