"""Parse HTML → cấu trúc DOM (BeautifulSoup), không dùng regex cho title/H1/meta."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.seo_normalize import normalize_canonical, normalize_text


def _rel_has(rel_val: str | list | None, token: str) -> bool:
    if not rel_val:
        return False
    if isinstance(rel_val, list):
        parts = {str(p).strip().lower() for p in rel_val if p}
        return token.lower() in parts
    parts = {p.strip().lower() for p in str(rel_val).split() if p.strip()}
    return token.lower() in parts


def _to_int(v: object) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _is_decorative_image(img) -> bool:
    role = str(img.get("role") or "").strip().lower()
    aria_hidden = str(img.get("aria-hidden") or "").strip().lower()
    w = _to_int(img.get("width"))
    h = _to_int(img.get("height"))
    classes = img.get("class") or []
    if isinstance(classes, str):
        class_tokens = classes.lower().split()
    else:
        class_tokens = [str(c).lower() for c in classes if c]
    class_str = " ".join(class_tokens)
    has_iconish_class = any(tok in class_str for tok in ("icon", "logo", "avatar", "sprite"))
    return role == "presentation" or aria_hidden == "true" or (w > 0 and h > 0 and w <= 48 and h <= 48) or has_iconish_class


def parse_structured_html(html: str, base_url: str = "") -> dict[str, Any]:
    """
    Trả về dict tương thích pipeline + schema GSC-style (title, canonical, indexability…).
    """
    safe = html if isinstance(html, str) else ""
    soup = BeautifulSoup(safe, "html.parser")

    title_el = soup.find("title")
    title = normalize_text(title_el.get_text() if title_el else "")

    meta_desc = ""
    for name in ("description",):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content") is not None:
            meta_desc = normalize_text(m.get("content"))
            break
    if not meta_desc:
        m = soup.find("meta", attrs={"property": "og:description"})
        if m and m.get("content") is not None:
            meta_desc = normalize_text(m.get("content"))

    canonical_raw = ""
    for link in soup.find_all("link"):
        rel = link.get("rel")
        if _rel_has(rel, "canonical") and link.get("href"):
            canonical_raw = str(link.get("href") or "").strip()
            break
    canonical = normalize_canonical(canonical_raw, base_url) if canonical_raw else ""

    h1_texts = [normalize_text(h.get_text(" ", strip=True)) for h in soup.find_all("h1")]
    h1_texts = [x for x in h1_texts if x]

    h2_texts = [normalize_text(h.get_text(" ", strip=True)) for h in soup.find_all("h2")]
    h2_texts = [x for x in h2_texts if x][:80]

    robots_meta = ""
    rm = soup.find("meta", attrs={"name": "robots"})
    if rm and rm.get("content") is not None:
        robots_meta = normalize_text(rm.get("content"))
    if not robots_meta:
        rm = soup.find("meta", attrs={"name": "googlebot"})
        if rm and rm.get("content") is not None:
            robots_meta = normalize_text(rm.get("content"))

    images: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        src = normalize_text(img.get("src") or img.get("data-src") or "")
        if base_url and src and not src.startswith(("http://", "https://", "//", "data:")):
            src = urljoin(base_url if base_url.endswith("/") else base_url + "/", src)
        alt = img.get("alt")
        alt_s = "" if alt is None else normalize_text(str(alt))
        images.append({"src": src, "alt": alt_s})

    soup_copy = BeautifulSoup(str(soup), "html.parser")
    for tag in soup_copy(["script", "style", "noscript"]):
        tag.decompose()
    text_content = soup_copy.get_text(separator=" ", strip=True)
    word_count = len([w for w in text_content.split() if w])

    images_total = len(images)
    images_missing_alt = 0
    for img in soup.find_all("img"):
        if _is_decorative_image(img):
            continue
        alt = img.get("alt")
        if alt is None or not normalize_text(str(alt)):
            images_missing_alt += 1

    return {
        "url": base_url,
        "status": 0,
        "title": title,
        "meta_description": meta_desc,
        "h1": h1_texts,
        "h2": h2_texts,
        "h1_count": len(h1_texts),
        "images": images,
        "canonical": canonical,
        "robots_meta": robots_meta,
        "word_count": word_count,
        "visible_text": text_content[:4000],
        "images_total": images_total,
        "images_missing_alt": images_missing_alt,
    }


def structured_to_legacy_page_data(parsed: dict[str, Any], status: int) -> dict[str, Any]:
    """Tương thích `parse_page_seo_data` + `_build_page_issues` cũ."""
    return {
        "title": parsed.get("title") or "",
        "meta_description": parsed.get("meta_description") or "",
        "canonical": parsed.get("canonical") or "",
        "h1_count": int(parsed.get("h1_count") or 0),
        "word_count": int(parsed.get("word_count") or 0),
        "images_total": int(parsed.get("images_total") or 0),
        "images_missing_alt": int(parsed.get("images_missing_alt") or 0),
        "status": status,
        "h1": parsed.get("h1") or [],
        "robots_meta": parsed.get("robots_meta") or "",
    }
