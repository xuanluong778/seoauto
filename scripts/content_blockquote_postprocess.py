"""
Auto-insert expert blockquotes into Content AI article HTML after generation.

Config (env.local):
  CONTENT_BLOCKQUOTE_ENABLED=1
  CONTENT_BLOCKQUOTE_MODE=auto_by_word_count
  CONTENT_BLOCKQUOTE_RANDOM=1
  CONTENT_BLOCKQUOTE_MAX=4
"""

from __future__ import annotations

import os
import random
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.llm_content_writer import _count_words_html, _count_words_vi

FAQ_HEADING_RE = re.compile(
    r"\b(faq|câu hỏi thường gặp|cau hoi thuong gap|hỏi đáp|hoi dap|questions?\s*&\s*answers?)\b",
    re.I,
)
SHORTCODE_RE = re.compile(r"\[[^\]]{2,120}\]")
MIN_SOURCE_PARA_WORDS = 40
FORBIDDEN_ANCESTOR_TAGS = frozenset(
    {"table", "ul", "ol", "blockquote", "pre", "code", "thead", "tbody", "tfoot", "tr", "figure", "dl"}
)


def blockquote_postprocess_enabled() -> bool:
    raw = (os.getenv("CONTENT_BLOCKQUOTE_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def blockquote_max_total() -> int:
    try:
        return max(0, min(4, int(os.getenv("CONTENT_BLOCKQUOTE_MAX", "4"))))
    except ValueError:
        return 4


def target_blockquote_count(word_count: int, *, rng: random.Random) -> int:
    """Số blockquote cần có trong bài (trước khi trừ blockquote sẵn có)."""
    if word_count < 1000:
        n = 1
    elif word_count < 1500:
        n = 2
    elif word_count < 2000:
        n = 3
    else:
        n = rng.randint(3, 4)
    return min(n, blockquote_max_total())


def _is_faq_heading(tag: Tag) -> bool:
    return bool(FAQ_HEADING_RE.search(tag.get_text(" ", strip=True)))


def _is_in_faq_section(p: Tag) -> bool:
    """Đoạn nằm dưới heading FAQ và chưa gặp H2 mới."""
    seen_faq = False
    for prev in p.find_all_previous(["h2", "h3", "h4"]):
        if prev.name == "h2" and seen_faq:
            return False
        if _is_faq_heading(prev):
            seen_faq = True
    return seen_faq


def _has_forbidden_ancestor(tag: Tag) -> bool:
    for parent in tag.parents:
        name = str(getattr(parent, "name", "") or "").lower()
        if name in FORBIDDEN_ANCESTOR_TAGS:
            return True
    return False


def _paragraph_plain(p: Tag) -> str:
    text = p.get_text(" ", strip=True)
    text = SHORTCODE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_insert_paragraph(p: Tag) -> bool:
    if not isinstance(p, Tag) or str(p.name or "").lower() != "p":
        return False
    if _has_forbidden_ancestor(p):
        return False
    if _is_in_faq_section(p):
        return False
    text = _paragraph_plain(p)
    if not text or _count_words_vi(text) < MIN_SOURCE_PARA_WORDS:
        return False
    if SHORTCODE_RE.search(text) and _count_words_vi(SHORTCODE_RE.sub(" ", text)) < 20:
        return False
    prev = p.find_previous_sibling()
    if prev is not None and str(getattr(prev, "name", "") or "").lower() == "blockquote":
        return False
    nxt = p.find_next_sibling()
    if nxt is not None and str(getattr(nxt, "name", "") or "").lower() == "blockquote":
        return False
    return True


def _extract_highlight_sentence(para_text: str, *, max_words: int = 38) -> str:
    text = re.sub(r"\s+", " ", str(para_text or "").strip())
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", text)
    sentences = [s.strip() for s in parts if s.strip() and _count_words_vi(s) >= 8]
    if not sentences:
        sentences = [text]
    scored: list[tuple[float, str]] = []
    for s in sentences:
        w = _count_words_vi(s)
        if w < 8:
            continue
        score = min(w, 32) - abs(w - 22) * 0.15
        scored.append((score, s))
    pick = max(scored, key=lambda x: x[0])[1] if scored else sentences[0]
    words = re.findall(r"[\wà-ỹÀ-Ỹ]+", pick, flags=re.I)
    if len(words) > max_words:
        pick = " ".join(words[:max_words]).strip() + "…"
    return pick


def _build_blockquote_element(soup: BeautifulSoup, quote_text: str) -> Tag:
    bq = soup.new_tag("blockquote")
    p = soup.new_tag("p")
    p.string = quote_text.strip()
    bq.append(p)
    return bq


def _pick_paragraphs_by_zones(candidates: list[Tag], need: int, rng: random.Random) -> list[Tag]:
    if not candidates or need <= 0:
        return []
    need = min(need, len(candidates))
    if need == 1:
        return [rng.choice(candidates)]

    zones: list[list[Tag]] = [[] for _ in range(need)]
    total = len(candidates)
    for i, p in enumerate(candidates):
        zi = min(need - 1, int(i * need / total))
        zones[zi].append(p)

    chosen: list[Tag] = []
    used_ids: set[int] = set()
    for zone in zones:
        pool = [p for p in zone if id(p) not in used_ids]
        if not pool:
            pool = [p for p in candidates if id(p) not in used_ids]
        if not pool:
            break
        pick = rng.choice(pool)
        chosen.append(pick)
        used_ids.add(id(pick))
    return chosen


def postprocess_content_blockquotes(
    html: str,
    *,
    enable: bool | None = None,
    max_total: int | None = None,
    seed: int | None = None,
) -> str:
    """
    Chèn blockquote sau các đoạn <p> hợp lệ, phân bổ đều theo số từ bài viết.
    """
    raw = str(html or "").strip()
    if not raw:
        return raw
    if enable is None:
        enable = blockquote_postprocess_enabled()
    if not enable:
        return raw
    mode = (os.getenv("CONTENT_BLOCKQUOTE_MODE", "auto_by_word_count") or "auto_by_word_count").strip().lower()
    if mode not in {"", "auto_by_word_count", "auto"}:
        return raw

    cap = blockquote_max_total() if max_total is None else max(0, min(4, int(max_total)))
    if cap <= 0:
        return raw

    use_random = (os.getenv("CONTENT_BLOCKQUOTE_RANDOM", "1") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    rng = random.Random(seed if seed is not None else (hash(raw) & 0xFFFFFFFF))

    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return raw

    existing = len(soup.find_all("blockquote"))
    if existing >= cap:
        return raw

    word_count = _count_words_html(raw)
    target = target_blockquote_count(word_count, rng=rng) if use_random else target_blockquote_count(word_count, rng=random.Random(0))
    to_insert = min(target - existing, cap - existing)
    if to_insert <= 0:
        return raw

    candidates = [p for p in soup.find_all("p") if _is_valid_insert_paragraph(p)]
    if not candidates:
        return raw

    picks = _pick_paragraphs_by_zones(candidates, to_insert, rng)
    if not picks:
        return raw

    # Insert bottom-up so indices stay valid
    for p in reversed(picks):
        quote = _extract_highlight_sentence(_paragraph_plain(p))
        if not quote:
            continue
        bq = _build_blockquote_element(soup, quote)
        p.insert_after(bq)

    body = soup.body
    if body:
        return "".join(str(x) for x in body.contents).strip() or str(soup)
    return str(soup).strip()


def postprocess_stats(html: str) -> dict[str, Any]:
    raw = str(html or "").strip()
    wc = _count_words_html(raw)
    try:
        soup = BeautifulSoup(raw, "html.parser")
        bq_count = len(soup.find_all("blockquote"))
    except Exception:
        bq_count = len(re.findall(r"<blockquote[\s>]", raw, flags=re.I))
    return {
        "word_count": wc,
        "blockquote_count": bq_count,
        "target_blockquotes": target_blockquote_count(wc, rng=random.Random(0)),
    }
