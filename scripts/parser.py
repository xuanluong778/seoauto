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


def parse_page_seo_data(html: str) -> dict:
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

    h1_count = len(soup.find_all("h1"))

    # Remove non-content blocks before text extraction for cleaner word count.
    for tag in soup(["script", "style"]):
        tag.decompose()
    text_content = soup.get_text(separator=" ", strip=True)
    word_count = len([word for word in text_content.split() if word])

    images = soup.find_all("img")
    images_total = len(images)
    images_missing_alt = 0
    for image in images:
        if _is_decorative_image(image):
            continue
        alt_text = image.get("alt")
        if alt_text is None or not str(alt_text).strip():
            images_missing_alt += 1

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "h1_count": h1_count,
        "word_count": word_count,
        "visible_text": text_content[:4000],
        "images_total": images_total,
        "images_missing_alt": images_missing_alt,
    }
