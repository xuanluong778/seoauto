"""Post-process Content AI HTML — dedupe related-articles box + hotline phones."""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

_RELATED_MARKER_RE = re.compile(r"bài\s*liên\s*quan|bai\s*lien\s*quan", re.I)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)[\s.\-]*(?:3|5|7|8|9)[\s.\-]*(?:\d[\s.\-]*){8}(?!\d)",
    re.IGNORECASE,
)
_TEL_HREF_RE = re.compile(r"^tel:", re.I)
_TRAILING_CTA_NOISE_RE = re.compile(
    r"(?:\s*(?:gọi|goi|hotline|liên hệ|lien he|điện thoại|dien thoai|sđt|sdt)\s*[:\-–—]?\s*)+$",
    re.I,
)


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if len(digits) == 9 and digits and digits[0] in "35789":
        digits = "0" + digits
    return digits if len(digits) >= 10 else ""


def _normalize_url(url: str) -> str:
    u = str(url or "").strip().rstrip("/")
    if not u or u == "#":
        return ""
    try:
        p = urlparse(u)
        host = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return f"{host}{path}".lower()
    except Exception:
        return u.lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())


def _is_related_box_tag(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    if tag.name == "blockquote":
        return bool(_RELATED_MARKER_RE.search(tag.get_text(" ", strip=True)))
    if tag.name in ("h2", "h3", "h4"):
        return bool(_RELATED_MARKER_RE.fullmatch(tag.get_text(" ", strip=True) or "")) or bool(
            _RELATED_MARKER_RE.search(tag.get_text(" ", strip=True) or "")
            and len(tag.get_text(" ", strip=True)) < 80
        )
    return False


def _related_section_nodes(soup: BeautifulSoup) -> list[Tag]:
    """Collect blockquote boxes and heading-led related sections."""
    found: list[Tag] = []
    seen_ids: set[int] = set()

    for bq in soup.find_all("blockquote"):
        if _is_related_box_tag(bq) and id(bq) not in seen_ids:
            found.append(bq)
            seen_ids.add(id(bq))

    for heading in list(soup.find_all(["h2", "h3", "h4"])):
        if id(heading) in seen_ids:
            continue
        title = heading.get_text(" ", strip=True) or ""
        if not _RELATED_MARKER_RE.search(title) or len(title) > 120:
            continue
        wrapper = soup.new_tag("div")
        wrapper["data-related-section"] = "1"
        parent = heading.parent
        if parent is None:
            continue
        siblings = list(parent.children)
        try:
            start = siblings.index(heading)
        except ValueError:
            continue
        heading.extract()
        wrapper.append(heading)
        remove_nodes: list[Tag] = []
        for sib in siblings[start + 1 :]:
            if isinstance(sib, Tag) and sib.name in ("h2", "h3", "h4"):
                break
            if isinstance(sib, Tag):
                sib.extract()
                wrapper.append(sib)
                remove_nodes.append(sib)
        if len(wrapper.find_all("a", href=True)) or remove_nodes:
            parent.insert(start, wrapper)
            found.append(wrapper)
            seen_ids.add(id(wrapper))

    return found


def _extract_links(container: Tag) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in container.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href == "#" or _TEL_HREF_RE.match(href):
            continue
        title = str(a.get_text(" ", strip=True) or "").strip()
        key = _normalize_url(href) or _normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        links.append((href, title or href))
    return links


def _build_merged_related_blockquote(soup: BeautifulSoup, links: list[tuple[str, str]]) -> Tag:
    from bs4 import BeautifulSoup as BS

    if not links:
        inner = "<strong>Bài liên quan:</strong> (không có liên kết)."
    else:
        parts = [
            f'<a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a>'
            for href, title in links[:6]
        ]
        inner = f"<strong>Bài liên quan:</strong> {' · '.join(parts)}."
    html = (
        '<blockquote style="margin:12px 0; padding:10px 12px; border-left:3px solid rgba(69,211,255,0.9); '
        'background: rgba(2,6,23,0.14); border-radius: 10px;">'
        f"{inner}</blockquote>"
    )
    node = BS(html, "html.parser")
    return node.find("blockquote") or soup.new_tag("blockquote")


def dedupe_related_articles_boxes(html: str) -> str:
    """Keep a single related-articles box; merge unique links by URL/title."""
    raw = str(html or "").strip()
    if not raw:
        return raw
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return raw

    boxes = _related_section_nodes(soup)
    if len(boxes) <= 1:
        return raw

    merged_links: list[tuple[str, str]] = []
    seen_link: set[str] = set()
    for box in boxes:
        for href, title in _extract_links(box):
            key = _normalize_url(href) or _normalize_title(title)
            if key in seen_link:
                continue
            seen_link.add(key)
            merged_links.append((href, title))

    keeper = boxes[0]
    merged_bq = _build_merged_related_blockquote(soup, merged_links)
    keeper.replace_with(merged_bq)
    for extra in boxes[1:]:
        extra.decompose()

    body = soup.body
    if body:
        return "".join(str(x) for x in body.contents).strip() or str(soup)
    return str(soup).strip()


def has_related_articles_box(html: str) -> bool:
    raw = str(html or "").strip()
    if not raw:
        return False
    if _RELATED_MARKER_RE.search(raw):
        try:
            soup = BeautifulSoup(raw, "html.parser")
            return bool(_related_section_nodes(soup))
        except Exception:
            return True
    return False


def _iter_text_nodes(root: Tag) -> Iterable[NavigableString]:
    for node in root.descendants:
        if isinstance(node, NavigableString) and str(node).strip():
            if node.parent and isinstance(node.parent, Tag) and node.parent.name in ("script", "style"):
                continue
            yield node


def dedupe_hotline_phones(html: str) -> str:
    """Each normalized VN phone appears at most once — keep the last occurrence (end CTA)."""
    raw = str(html or "").strip()
    if not raw:
        return raw
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return raw

    occurrences: list[tuple[str, Tag | NavigableString, int, int, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not _TEL_HREF_RE.match(href):
            continue
        norm = _normalize_phone(href[4:])
        if norm:
            occurrences.append(("tel", a, 0, 0, norm))

    for node in _iter_text_nodes(soup):
        text = str(node)
        for m in _PHONE_RE.finditer(text):
            norm = _normalize_phone(m.group(0))
            if norm:
                occurrences.append(("text", node, m.start(), m.end(), norm))

    if not occurrences:
        return raw

    last_index: dict[str, int] = {}
    for i, (_kind, _node, _s, _e, norm) in enumerate(occurrences):
        last_index[norm] = i

    text_edits: dict[int, list[tuple[int, int]]] = {}
    for i, (kind, node, start, end, norm) in enumerate(occurrences):
        if last_index.get(norm) == i:
            continue
        if kind == "tel" and isinstance(node, Tag):
            text = node.get_text(" ", strip=True)
            node.replace_with(NavigableString(text or ""))
        elif kind == "text" and isinstance(node, NavigableString):
            text_edits.setdefault(id(node), []).append((start, end))

    for node in _iter_text_nodes(soup):
        spans = text_edits.get(id(node))
        if not spans:
            continue
        text = str(node)
        for start, end in sorted(spans, key=lambda x: x[0], reverse=True):
            text = text[:start] + text[end:]
        text = _TRAILING_CTA_NOISE_RE.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        node.replace_with(NavigableString(text))

    body = soup.body
    if body:
        return "".join(str(x) for x in body.contents).strip() or str(soup)
    return str(soup).strip()


def postprocess_content_ai_output(html: str) -> str:
    out = dedupe_related_articles_boxes(str(html or ""))
    out = dedupe_hotline_phones(out)
    return out
