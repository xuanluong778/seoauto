"""
Post-process HTML sau chèn internal link (Content AI).
Chỉ giữ URL user đã chọn; gỡ template «tham khảo thêm»; dedupe; rải link.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString

from app.services.wp_internal_link_apply import (
    _build_allowed_url_norms,
    _collect_job_intent_slugs,
    norm_url_for_compare,
    url_matches_allowed,
)
from app.services.wp_internal_link_scoring import is_bad_anchor

def _fold_vn(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


_BANNED_LINK_PHRASES = (
    "ban co the tham khao them",
    "ban cung co the tim hieu them",
    "tham khao them",
    "xem them",
    "tim hieu them",
    "de biet them thong tin chi tiet",
    "de biet them thong tin",
    "de biet them",
    "click vao day",
    "click here",
    "de nam ro hon, xem them",
    "neu ban can them thong tin",
    "trong phan",
    "ban co the doc them",
    "de hieu ro hon noi dung lien quan",
    "co the tham khao",
    "co the xem them",
)


def _paragraph_has_banned_template(text: str) -> bool:
    folded = _fold_vn(text)
    return any(p in folded for p in _BANNED_LINK_PHRASES)

_STOP_WORDS = frozenset(
    "tai nha tai nha va va hoac neu khi can cho voi ve theo trong mot cac ban".split()
)


def _selected_links_to_jobs(selected_links: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for raw in selected_links or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("target_url") or raw.get("url") or raw.get("link") or "").strip()
        anchor = str(raw.get("anchor_text") or raw.get("title") or "").strip()
        if url:
            jobs.append({"target_url": url, "link": url, "url": url, "anchor_text": anchor})
    return jobs


def _allowed_norms(selected_links: list[dict[str, Any]] | None) -> set[str]:
    jobs = _selected_links_to_jobs(selected_links)
    return _build_allowed_url_norms(jobs=jobs)


def _is_http_href(href: str) -> bool:
    h = str(href or "").strip().lower()
    return h.startswith("http://") or h.startswith("https://") or h.startswith("//")


def _unwrap_anchor(a: Any) -> None:
    """Gỡ thẻ <a>, giữ text anchor."""
    if a is None:
        return
    text = a.get_text() or ""
    a.replace_with(NavigableString(text))


def validate_allowed_urls(
    html: str,
    selected_links: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Kiểm tra mọi link http(s) trong HTML có nằm trong selected_links (theo slug/host)."""
    allowed = _allowed_norms(selected_links)
    issues: list[str] = []
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not _is_http_href(href):
            continue
        u = norm_url_for_compare(href)
        if allowed and not url_matches_allowed(u, allowed):
            issues.append(f"URL không trong danh sách đã chọn: {href[:80]}")
    return {"ok": len(issues) == 0, "issues": issues}


def remove_unselected_urls(
    html: str,
    selected_links: list[dict[str, Any]] | None,
) -> tuple[str, int]:
    """Gỡ <a> trỏ URL không thuộc selected_links (giữ text)."""
    allowed = _allowed_norms(selected_links)
    if not allowed:
        return html, 0
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    removed = 0
    for a in list(soup.find_all("a", href=True)):
        href = str(a.get("href") or "").strip()
        if not _is_http_href(href):
            continue
        u = norm_url_for_compare(href)
        if not url_matches_allowed(u, allowed):
            _unwrap_anchor(a)
            removed += 1
    return str(soup), removed


def remove_template_link_sentences(html: str) -> tuple[str, int]:
    """
    Gỡ link trong đoạn có câu mẫu «tham khảo thêm», «xem thêm», …
    Giữ phần chữ anchor dạng text thường (không còn <a>).
    """
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    fixed = 0
    for tag in list(soup.find_all(["p", "li"])):
        txt = tag.get_text(" ", strip=True)
        if not tag.find("a", href=True) or not _paragraph_has_banned_template(txt):
            continue
        for a in list(tag.find_all("a", href=True)):
            _unwrap_anchor(a)
            fixed += 1
    return str(soup), fixed


def dedupe_internal_links(
    html: str,
    selected_links: list[dict[str, Any]] | None,
) -> tuple[str, int]:
    """Mỗi URL đích (chuẩn hóa) chỉ giữ lần chèn đầu tiên."""
    allowed = _allowed_norms(selected_links)
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    seen: set[str] = set()
    removed = 0
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not _is_http_href(href):
            continue
        u = norm_url_for_compare(href)
        if allowed and not url_matches_allowed(u, allowed):
            continue
        if not u:
            continue
        if u in seen:
            _unwrap_anchor(a)
            removed += 1
        else:
            seen.add(u)
    return str(soup), removed


def enforce_link_distribution(
    html: str,
    *,
    min_para_gap: int = 3,
    selected_links: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Gỡ link dư khi hai đoạn <p> có internal link quá gần nhau."""
    allowed = _allowed_norms(selected_links)
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    paras = soup.find_all("p")
    link_positions: list[tuple[int, Any]] = []
    for i, p in enumerate(paras):
        for a in p.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not _is_http_href(href):
                continue
            u = norm_url_for_compare(href)
            if allowed and not url_matches_allowed(u, allowed):
                continue
            link_positions.append((i, a))
            break

    removed = 0
    last_pos = -min_para_gap - 1
    for pos, anchor_tag in link_positions:
        if pos - last_pos < min_para_gap:
            _unwrap_anchor(anchor_tag)
            removed += 1
        else:
            last_pos = pos
    return str(soup), removed


def _anchor_context_overlap(paragraph_text: str, anchor: str) -> bool:
    """Anchor có ít nhất một từ có nghĩa xuất hiện trong đoạn (ngoài chính anchor)."""
    para = re.sub(r"\s+", " ", str(paragraph_text or "").casefold())
    anc = re.sub(r"\s+", " ", str(anchor or "").casefold()).strip()
    if not anc or len(anc) < 4:
        return False
    if anc in para:
        return True
    words = [w for w in re.findall(r"[a-z0-9à-ỹ]{3,}", anc) if w not in _STOP_WORDS]
    if not words:
        return len(anc) >= 8 and any(c in para for c in anc.split()[:3])
    hits = sum(1 for w in words if w in para)
    return hits >= max(1, min(2, len(words) // 2))


def validate_anchor_context(
    html: str,
    selected_links: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Anchor phải liên quan đoạn văn chứa link."""
    allowed = _allowed_norms(selected_links)
    issues: list[str] = []
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not _is_http_href(href):
            continue
        u = norm_url_for_compare(href)
        if allowed and not url_matches_allowed(u, allowed):
            continue
        anchor = a.get_text(" ", strip=True)
        if is_bad_anchor(anchor):
            issues.append(f"Anchor không phù hợp: «{anchor[:40]}»")
            continue
        parent = a.find_parent("p") or a.find_parent("li")
        if parent is None:
            issues.append(f"Link không nằm trong đoạn văn: {href[:50]}")
            continue
        para_txt = parent.get_text(" ", strip=True)
        if _paragraph_has_banned_template(para_txt):
            issues.append(f"Câu mẫu dẫn link (cần gỡ): «{para_txt[:55]}…»")
            continue
        if not _anchor_context_overlap(para_txt, anchor):
            issues.append(f"Anchor không khớp ngữ cảnh đoạn: «{anchor[:35]}»")
    return {"ok": len(issues) == 0, "issues": issues}


def postprocess_internal_links_html(
    html: str,
    selected_links: list[dict[str, Any]] | None,
    *,
    min_para_gap: int = 3,
) -> tuple[str, dict[str, Any]]:
    """
    Pipeline sau LLM/rule: gỡ URL lạ → template → dedupe → rải đều.
    Trả (html, stats).
    """
    raw = str(html or "").strip()
    stats: dict[str, Any] = {
        "removed_unselected": 0,
        "removed_template": 0,
        "deduped": 0,
        "distribution_trimmed": 0,
    }
    if not raw:
        return raw, stats

    out, n1 = remove_unselected_urls(raw, selected_links)
    stats["removed_unselected"] = n1

    out, n2 = remove_template_link_sentences(out)
    stats["removed_template"] = n2

    out, n3 = dedupe_internal_links(out, selected_links)
    stats["deduped"] = n3

    out, n4 = enforce_link_distribution(
        out, min_para_gap=min_para_gap, selected_links=selected_links
    )
    stats["distribution_trimmed"] = n4

    val_urls = validate_allowed_urls(out, selected_links)
    val_ctx = validate_anchor_context(out, selected_links)
    stats["validate_urls"] = val_urls
    stats["validate_context"] = val_ctx
    stats["ok"] = val_urls.get("ok", True) and val_ctx.get("ok", True)

    return out, stats
