"""
Apply internal links (WordPress related + custom) for Content AI — nhánh A.
"""
from __future__ import annotations

import html as py_html
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString

from app.services.llm_content_writer import rewrite_html_insert_internal_links
from app.services.wp_internal_link_scoring import (
    is_bad_anchor,
    sanitize_anchor,
)

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_VALID_LINK_TYPES = {
    "money_page",
    "blog",
    "category",
    "service",
    "course",
    "manual",
}
_VALID_PRIORITIES = set(_PRIORITY_ORDER.keys())


def norm_url_for_compare(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://x.local/{raw.lstrip('/')}")
        path = re.sub(r"/{2,}", "/", p.path or "/").rstrip("/")
        return f"{(p.netloc or '').lower()}{path.lower()}"
    except Exception:
        return raw.lower().rstrip("/")


def norm_anchor_cmp(s: str) -> str:
    t = unicodedata.normalize("NFC", str(s or "").strip())
    return re.sub(r"\s+", " ", t).casefold()


def is_valid_http_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    try:
        p = urlparse(raw if "://" in raw else f"https://{raw}")
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def href_matches_job(href: str, job_url: str) -> bool:
    return norm_url_for_compare(href) == norm_url_for_compare(job_url)


def verify_llm_internal_links_html(html: str, jobs: list[dict]) -> bool:
    if not jobs:
        return False
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    for it in jobs:
        url = str(it.get("url") or "").strip()
        anchor_raw = str(it.get("anchor_text") or "").strip() or str(it.get("title") or "").strip()
        if not url or not anchor_raw:
            return False
        want = norm_anchor_cmp(anchor_raw)
        found = False
        for a in soup.find_all("a", href=True):
            if not href_matches_job(str(a.get("href") or ""), url):
                continue
            got = norm_anchor_cmp(a.get_text(" ", strip=True))
            if got == want or (len(want) >= 10 and want in got) or (len(got) >= 10 and got in want):
                found = True
                break
        if not found:
            return False
    return True


def _result_row(
    *,
    anchor_text: str,
    target_url: str,
    source: str,
    status: str,
    reason: str = "",
    link_type: str = "",
    priority: str = "",
) -> dict[str, str]:
    return {
        "anchor_text": anchor_text,
        "target_url": target_url,
        "source": source,
        "status": status,
        "reason": reason,
        "link_type": link_type,
        "priority": priority,
    }


def _normalize_custom_item(raw: dict) -> dict[str, Any]:
    return {
        "target_url": str(raw.get("target_url") or raw.get("link") or "").strip(),
        "anchor_text": str(raw.get("anchor_text") or "").strip(),
        "link_type": str(raw.get("link_type") or "manual").strip().lower() or "manual",
        "priority": str(raw.get("priority") or "medium").strip().lower() or "medium",
        "max_insert": max(1, min(int(raw.get("max_insert") or 1), 3)),
    }


def _normalize_wp_post(raw: dict) -> dict[str, Any]:
    return {
        "target_url": str(raw.get("link") or raw.get("target_url") or "").strip(),
        "anchor_text": str(raw.get("anchor_text") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "link_type": "blog",
        "priority": "medium",
        "max_insert": 1,
        "source": "wp",
    }


def _urls_present_in_html(soup: BeautifulSoup) -> set[str]:
    out: set[str] = set()
    for a in soup.find_all("a", href=True):
        u = norm_url_for_compare(str(a.get("href") or ""))
        if u:
            out.add(u)
    return out


def verify_internal_links_html(
    html: str,
    *,
    jobs: list[dict[str, Any]],
    current_url: str | None = None,
    expected_inserts: list[dict] | None = None,
) -> dict[str, Any]:
    """Kiểm tra HTML sau chèn: trùng URL, anchor xấu, FAQ, 1 link/đoạn, self-link."""
    issues: list[str] = []
    raw = str(html or "").strip()
    if not raw:
        return {"ok": False, "issues": ["HTML rỗng."]}
    soup = BeautifulSoup(raw, "html.parser")
    faq_ids = _faq_region_tag_ids(soup)
    cur_norm = norm_url_for_compare(str(current_url or ""))

    url_counts: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        u = norm_url_for_compare(href)
        if not u:
            continue
        url_counts[u] = url_counts.get(u, 0) + 1
        if cur_norm and u == cur_norm:
            issues.append(f"Link trỏ về chính bài đang soạn: {href[:80]}")
        anchor_txt = a.get_text(" ", strip=True)
        if is_bad_anchor(anchor_txt):
            issues.append(f"Anchor không nên dùng: «{anchor_txt[:40]}»")
        if _tag_in_faq(a, faq_ids):
            issues.append(f"Link trong vùng FAQ: {href[:60]}")

    for u, cnt in url_counts.items():
        if cnt > 1:
            issues.append(f"URL đích xuất hiện {cnt} lần trong bài (nên tối đa 1).")

    for p in soup.find_all("p"):
        n = len(p.find_all("a", href=True))
        if n > 1:
            issues.append(f"Một đoạn văn có {n} link (tối đa 1).")

    for job in jobs or []:
        url = str(job.get("target_url") or job.get("url") or "").strip()
        anchor = str(job.get("anchor_text") or "").strip()
        if not url:
            continue
        u = norm_url_for_compare(url)
        if expected_inserts and u not in url_counts:
            issues.append(f"Thiếu link đã chèn cho URL: {url[:70]}")
        if anchor and is_bad_anchor(anchor):
            issues.append(f"Anchor job không hợp lệ: «{anchor[:40]}»")

    deduped = list(dict.fromkeys(issues))
    return {"ok": len(deduped) == 0, "issues": deduped}


def _prepare_jobs(
    *,
    custom_links: list[dict] | None,
    selected_posts: list[dict] | None,
    current_url: str | None,
    content_html: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    results: list[dict[str, str]] = []
    cur_norm = norm_url_for_compare(str(current_url or ""))
    used_urls: set[str] = set()
    used_anchors: set[str] = set()
    custom_jobs: list[dict[str, Any]] = []
    wp_jobs: list[dict[str, Any]] = []

    def _skip_row(
        *,
        anchor: str,
        url: str,
        source: str,
        reason: str,
        link_type: str = "",
        priority: str = "",
    ) -> None:
        results.append(
            _result_row(
                anchor_text=anchor,
                target_url=url,
                source=source,
                status="skipped",
                reason=reason,
                link_type=link_type,
                priority=priority,
            )
        )

    for raw in custom_links or []:
        if not isinstance(raw, dict):
            continue
        it = _normalize_custom_item(raw)
        url, anchor = it["target_url"], it["anchor_text"]
        anchor = sanitize_anchor(anchor, post={"title": anchor, "link": url}, content_html=content_html)
        lt = it["link_type"] if it["link_type"] in _VALID_LINK_TYPES else "manual"
        pr = it["priority"] if it["priority"] in _VALID_PRIORITIES else "medium"
        if not url or not anchor:
            _skip_row(anchor=anchor, url=url, source="custom", reason="Thiếu target_url hoặc anchor_text.", link_type=lt, priority=pr)
            continue
        if not is_valid_http_url(url):
            _skip_row(anchor=anchor, url=url, source="custom", reason="URL không hợp lệ (cần http/https).", link_type=lt, priority=pr)
            continue
        u_norm, a_norm = norm_url_for_compare(url), norm_anchor_cmp(anchor)
        if cur_norm and u_norm == cur_norm:
            _skip_row(anchor=anchor, url=url, source="custom", reason="Trùng URL bài đang soạn (current_url).", link_type=lt, priority=pr)
            continue
        if u_norm in used_urls:
            _skip_row(anchor=anchor, url=url, source="custom", reason="target_url trùng link khác.", link_type=lt, priority=pr)
            continue
        if a_norm in used_anchors:
            _skip_row(anchor=anchor, url=url, source="custom", reason="anchor_text trùng link khác.", link_type=lt, priority=pr)
            continue
        used_urls.add(u_norm)
        used_anchors.add(a_norm)
        custom_jobs.append({**it, "link_type": lt, "priority": pr, "source": "custom", "title": anchor[:120]})

    for raw in selected_posts or []:
        if not isinstance(raw, dict):
            continue
        it = _normalize_wp_post(raw)
        url = it["target_url"]
        title = it["title"] or it["anchor_text"]
        anchor = sanitize_anchor(
            it["anchor_text"] or it["title"],
            post={**raw, "title": title, "link": url},
            content_html=content_html,
        )
        if not url or not anchor:
            _skip_row(anchor=anchor, url=url, source="wp", reason="Thiếu link hoặc anchor/title.")
            continue
        if not is_valid_http_url(url):
            _skip_row(anchor=anchor, url=url, source="wp", reason="URL WordPress không hợp lệ.")
            continue
        u_norm, a_norm = norm_url_for_compare(url), norm_anchor_cmp(anchor)
        if cur_norm and u_norm == cur_norm:
            _skip_row(anchor=anchor, url=url, source="wp", reason="Trùng URL bài đang soạn.")
            continue
        if u_norm in used_urls:
            _skip_row(anchor=anchor, url=url, source="wp", reason="target_url trùng link khác.")
            continue
        if a_norm in used_anchors:
            _skip_row(anchor=anchor, url=url, source="wp", reason="anchor_text trùng link khác.")
            continue
        used_urls.add(u_norm)
        used_anchors.add(a_norm)
        wp_jobs.append({**it, "anchor_text": anchor, "title": title, "source": "wp"})

    custom_jobs.sort(key=lambda j: _PRIORITY_ORDER.get(str(j.get("priority") or "medium"), 1))
    return custom_jobs + wp_jobs, results


def _tag_in_heading_block(tag: Any) -> bool:
    parent = tag
    for _ in range(8):
        if parent is None:
            break
        if getattr(parent, "name", "") in {"h1", "h2", "h3"}:
            return True
        parent = getattr(parent, "parent", None)
    return False


_FAQ_HEADING_RE = re.compile(
    r"faq|câu\s*hỏi|hỏi\s*đáp|questions?\s*and\s*answers|q\s*&\s*a|thường\s*gặp",
    re.I,
)


def _is_faq_heading(tag: Any) -> bool:
    if getattr(tag, "name", None) not in {"h2", "h3", "h4"}:
        return False
    return bool(_FAQ_HEADING_RE.search(str(tag.get_text(" ", strip=True) or "")))


def _faq_region_tag_ids(soup: BeautifulSoup) -> set[int]:
    """Mọi node từ tiêu đề FAQ đến trước H2 kế tiếp."""
    ids: set[int] = set()
    for h in soup.find_all(["h2", "h3"]):
        if not _is_faq_heading(h):
            continue
        ids.add(id(h))
        for sib in h.find_next_siblings():
            if getattr(sib, "name", None) == "h2":
                break
            ids.add(id(sib))
            for desc in sib.descendants:
                if getattr(desc, "name", None):
                    ids.add(id(desc))
    return ids


def _tag_in_faq(tag: Any, faq_ids: set[int]) -> bool:
    if not faq_ids:
        return False
    node: Any = tag
    for _ in range(14):
        if node is None:
            break
        if id(node) in faq_ids:
            return True
        node = getattr(node, "parent", None)
    return False


def _section_key_for(tag: Any) -> str:
    h2 = tag.find_previous("h2") if hasattr(tag, "find_previous") else None
    if h2 is not None:
        if _is_faq_heading(h2):
            return "faq"
        return f"h2:{id(h2)}"
    h3 = tag.find_previous("h3") if hasattr(tag, "find_previous") else None
    if h3 is not None and _is_faq_heading(h3):
        return "faq"
    return "intro"


def _paragraph_positions(soup: BeautifulSoup, *, faq_ids: set[int]) -> dict[int, int]:
    pos: dict[int, int] = {}
    idx = 0
    for p in soup.find_all("p"):
        if _tag_in_faq(p, faq_ids) or _tag_in_heading_block(p):
            continue
        pos[id(p)] = idx
        idx += 1
    return pos


_APPEND_LEADS = (
    "Tham khảo thêm:",
    "Bạn cũng có thể tìm hiểu thêm về",
    "Để nắm rõ hơn, xem thêm",
)


def _is_reference_append_paragraph(tag: Any) -> bool:
    if getattr(tag, "name", None) != "p":
        return False
    txt = str(tag.get_text(" ", strip=True) or "")
    for lead in _APPEND_LEADS:
        if txt.startswith(lead) or lead.rstrip(":") in txt[:80]:
            return True
    return bool(re.search(r"tham\s*khảo\s*thêm|tìm\s*hiểu\s*thêm\s*về|nắm\s*rõ\s*hơn", txt, re.I))


def _mark_append_vicinity(used_append_keys: set[str], node: Any, new_ref: Any | None = None) -> None:
    """Khóa đoạn gốc và đoạn tham khảo vừa chèn — không dùng find_next_sibling (tránh nhầm <p> section khác)."""
    used_append_keys.add(f"p:{id(node)}")
    if new_ref is not None and getattr(new_ref, "name", None) == "p":
        used_append_keys.add(f"p:{id(new_ref)}")


def _inject_one_strict(
    soup: BeautifulSoup,
    *,
    target_url: str,
    anchor_text: str,
    per_para_count: dict[int, int],
    max_links_per_para: int = 1,
    allow_first_paragraph: bool = False,
    faq_ids: set[int] | None = None,
    section_insert_counts: dict[str, int] | None = None,
    para_positions: dict[int, int] | None = None,
) -> tuple[bool, dict[str, str] | None]:
    raw_anchor = str(anchor_text or "").strip()
    url = str(target_url or "").strip()
    if not raw_anchor or not url:
        return False, None
    au_nfc = unicodedata.normalize("NFC", raw_anchor)
    min_len = 4 if len(au_nfc) <= 12 else 8
    faq_ids = faq_ids or set()
    sec_counts = section_insert_counts if section_insert_counts is not None else {}
    positions = para_positions or {}
    first_p = soup.find("p")
    scored: list[tuple[int, int, int, Any, str]] = []
    for tag in soup.find_all(["p", "li"]):
        if not allow_first_paragraph and first_p is not None and tag is first_p:
            continue
        if _tag_in_heading_block(tag):
            continue
        if _tag_in_faq(tag, faq_ids):
            continue
        sec = _section_key_for(tag)
        if sec == "faq":
            continue
        if tag.find("a"):
            continue
        if _is_reference_append_paragraph(tag):
            continue
        txt = re.sub(r"\s+", " ", str(tag.get_text(" ", strip=True) or ""))
        if not txt:
            continue
        twork = unicodedata.normalize("NFC", txt)
        idx = twork.casefold().find(au_nfc.casefold())
        if idx < 0:
            continue
        scored.append(
            (
                sec_counts.get(sec, 0),
                positions.get(id(tag), 9999),
                -(10 if idx >= 0 else 0),
                tag,
                sec,
            )
        )
    scored.sort(key=lambda x: (x[0], x[1], -x[2]))

    for _sec_pen, _pos, _neg_overlap, tag, sec in scored:
        pid = id(tag)
        if per_para_count.get(pid, 0) >= max_links_per_para:
            continue
        for node in list(tag.descendants):
            if not isinstance(node, NavigableString):
                continue
            parent = getattr(node, "parent", None)
            if parent and getattr(parent, "name", "") == "a":
                continue
            text = str(node)
            twork = unicodedata.normalize("NFC", text)
            idx = twork.casefold().find(au_nfc.casefold())
            if idx < 0 or len(au_nfc) < min_len:
                continue
            match = twork[idx : idx + len(au_nfc)]
            before, after = twork[:idx], twork[idx + len(au_nfc) :]
            frag = BeautifulSoup(
                f"{py_html.escape(before)}<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(match)}</a>{py_html.escape(after)}",
                "html.parser",
            )
            node.replace_with(*list(frag.contents))
            per_para_count[pid] = per_para_count.get(pid, 0) + 1
            sec_counts[sec] = sec_counts.get(sec, 0) + 1
            return True, {"target_url": url, "anchor_text": match}
    return False, None


def _anchor_in_html(soup: BeautifulSoup, anchor: str) -> bool:
    body = unicodedata.normalize("NFC", soup.get_text(" ", strip=True))
    au = unicodedata.normalize("NFC", str(anchor or "").strip())
    return bool(au) and au.casefold() in body.casefold()


def _topic_terms(anchor: str, title: str = "") -> list[str]:
    raw = f"{anchor} {title}".lower()
    terms = [w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", raw)]
    stop = {"cho", "cua", "của", "và", "theo", "khi", "này", "đó", "các", "một", "những"}
    return [t for t in terms if t not in stop][:12]


def _score_node_text(text: str, terms: list[str]) -> int:
    low = str(text or "").lower()
    return sum(1 for t in terms if t in low)


def _insert_paragraph_after(
    soup: BeautifulSoup,
    after_node: Any,
    *,
    target_url: str,
    anchor_text: str,
    lead_idx: int,
) -> Any | None:
    if after_node is None:
        return None
    lead = _APPEND_LEADS[lead_idx % len(_APPEND_LEADS)]
    safe_url = py_html.escape(str(target_url or "").strip(), quote=True)
    safe_anchor = py_html.escape(str(anchor_text or "").strip())
    if lead.endswith("về") or lead.endswith("thêm"):
        inner = f'{py_html.escape(lead)} <a href="{safe_url}">{safe_anchor}</a>.'
    else:
        inner = f'{py_html.escape(lead)} <a href="{safe_url}">{safe_anchor}</a> — phù hợp ngữ cảnh chủ đề đang trình bày.'
    new_p = soup.new_tag("p")
    new_p.append(BeautifulSoup(inner, "html.parser"))
    after_node.insert_after(new_p)
    return new_p


def _inject_append_context_paragraph(
    soup: BeautifulSoup,
    *,
    target_url: str,
    anchor_text: str,
    title: str = "",
    used_append_keys: set[str],
    allow_first_paragraph: bool = False,
    faq_ids: set[int] | None = None,
    section_insert_counts: dict[str, int] | None = None,
    para_positions: dict[int, int] | None = None,
) -> tuple[bool, dict[str, str] | None]:
    """Chèn thêm một đoạn <p> ngắn — không sửa nội dung gốc."""
    anchor = str(anchor_text or "").strip()
    url = str(target_url or "").strip()
    if not anchor or not url:
        return False, None
    faq_ids = faq_ids or set()
    sec_counts = section_insert_counts if section_insert_counts is not None else {}
    positions = para_positions or {}
    terms = _topic_terms(anchor, title)
    candidates: list[tuple[int, int, int, Any, str, str]] = []
    section_order = 0

    def _eligible_paragraphs_in_section(h2: Any) -> list[Any]:
        out: list[Any] = []
        for sib in h2.find_next_siblings():
            if getattr(sib, "name", None) == "h2":
                break
            if _tag_in_faq(sib, faq_ids):
                continue
            if sib.name == "p" and not _tag_in_heading_block(sib):
                if _is_reference_append_paragraph(sib) or sib.find("a"):
                    continue
                out.append(sib)
        return out

    for h2 in soup.find_all("h2"):
        if _is_faq_heading(h2) or _tag_in_faq(h2, faq_ids):
            continue
        sec = f"h2:{id(h2)}"
        section_ps = _eligible_paragraphs_in_section(h2)
        if not section_ps:
            continue
        best_p: Any | None = None
        best_topic = -1
        for p in section_ps:
            sk = f"p:{id(p)}"
            if sk in used_append_keys:
                continue
            topic_p = _score_node_text(p.get_text(" ", strip=True), terms) + _score_node_text(
                h2.get_text(" ", strip=True), terms
            )
            if topic_p > best_topic:
                best_topic = topic_p
                best_p = p
        if best_p is None:
            continue
        sk = f"p:{id(best_p)}"
        candidates.append(
            (sec_counts.get(sec, 0), section_order, -max(best_topic, 0), best_p, sk, sec)
        )
        section_order += 1

    if not candidates:
        for p in reversed(soup.find_all("p")):
            if _tag_in_heading_block(p) or _tag_in_faq(p, faq_ids) or p.find("a"):
                continue
            if _is_reference_append_paragraph(p):
                continue
            sec = _section_key_for(p)
            if sec == "faq":
                continue
            sk = f"p:{id(p)}"
            if sk not in used_append_keys:
                candidates.append((sec_counts.get(sec, 0), 9999, -1, p, sk, sec))
                break

    strong = [c for c in candidates if c[2] < 0]
    pool = strong if strong else candidates
    pool.sort(key=lambda x: (x[0], x[1], -x[2]))
    candidates = pool
    for _sec_pen, _pos, _neg_topic, node, sk, sec in candidates:
        if sk in used_append_keys:
            continue
        new_p = _insert_paragraph_after(
            soup,
            node,
            target_url=url,
            anchor_text=anchor,
            lead_idx=len(used_append_keys),
        )
        if new_p is not None:
            _mark_append_vicinity(used_append_keys, node, new_ref=new_p)
            sec_counts[sec] = sec_counts.get(sec, 0) + 1
            return True, {"target_url": url, "anchor_text": anchor, "method": "append_paragraph"}
    return False, None


def _strip_links_from_faq_region(html: str) -> str:
    """Gỡ thẻ <a> trong khối FAQ (phòng LLM chèn nhầm)."""
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    faq_ids = _faq_region_tag_ids(soup)
    if not faq_ids:
        return str(soup)
    for a in soup.find_all("a", href=True):
        if _tag_in_faq(a, faq_ids):
            a.unwrap()
    return str(soup)


def _llm_change_acceptable(original_html: str, new_html: str, *, max_growth: float = 1.22) -> bool:
    o = len(str(original_html or "").strip())
    n = len(str(new_html or "").strip())
    if o <= 0:
        return True
    return n <= int(o * max_growth) + 800


def _try_llm_single(
    *,
    content_html: str,
    target_url: str,
    anchor_text: str,
    title: str,
    article_primary_keyword: str,
    article_secondary_keywords: str,
) -> tuple[str, bool, str]:
    job = {"url": target_url, "title": title or anchor_text, "anchor_text": anchor_text}
    try:
        out = rewrite_html_insert_internal_links(
            content_html=content_html,
            link_jobs=[job],
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            minimal=True,
        )
        if not _llm_change_acceptable(content_html, out):
            return content_html, False, "LLM thay đổi quá nhiều nội dung — đã bỏ qua (dùng chèn đoạn ngắn)."
        if out.strip() and verify_llm_internal_links_html(out, [job]):
            return _strip_links_from_faq_region(out), True, ""
        return content_html, False, "LLM không chèn đủ anchor/URL hoặc verify thất bại."
    except Exception as exc:
        return content_html, False, str(exc)[:400]


def apply_merged_internal_links(
    *,
    content_html: str,
    custom_links: list[dict] | None,
    selected_posts: list[dict] | None,
    current_url: str | None,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    use_llm_rewrite: bool = True,
    llm_available: bool = False,
    legacy_inject_fn: Any = None,
    target_website: str = "",
    apply_mode: str = "full",
    append_lead: str = "Tham khảo thêm:",
    confirmed_append_urls: list[str] | None = None,
) -> dict[str, Any]:
    mode = str(apply_mode or "full").strip().lower()
    confirmed_set = {
        norm_url_for_compare(u)
        for u in (confirmed_append_urls or [])
        if str(u or "").strip()
    }

    if mode == "append_only":
        jobs, link_results = _prepare_jobs(
            custom_links=custom_links,
            selected_posts=selected_posts,
            current_url=current_url,
            content_html=content_html,
        )
        soup = BeautifulSoup(str(content_html or "").strip(), "html.parser")
        faq_ids = _faq_region_tag_ids(soup)
        para_pos = _paragraph_positions(soup, faq_ids=faq_ids)
        section_insert_counts: dict[str, int] = {}
        updates: list[dict] = []
        used_append_keys: set[str] = set()
        lead_idx = 0
        if str(append_lead or "").strip() in _APPEND_LEADS:
            try:
                lead_idx = _APPEND_LEADS.index(str(append_lead).strip())
            except ValueError:
                lead_idx = 0
        for job in jobs:
            url = str(job.get("target_url") or "").strip()
            if confirmed_set and norm_url_for_compare(url) not in confirmed_set:
                link_results.append(
                    _result_row(
                        anchor_text=str(job.get("anchor_text") or ""),
                        target_url=url,
                        source=str(job.get("source") or "wp"),
                        status="skipped",
                        reason="Không được chọn trong popup Tham khảo thêm.",
                    )
                )
                continue
            anchor = str(job.get("anchor_text") or "").strip()
            title = str(job.get("title") or anchor).strip()
            source = str(job.get("source") or "wp")
            ok, upd = _inject_append_context_paragraph(
                soup,
                target_url=url,
                anchor_text=anchor,
                title=title,
                used_append_keys=used_append_keys,
                allow_first_paragraph=source == "custom",
                faq_ids=faq_ids,
                section_insert_counts=section_insert_counts,
                para_positions=para_pos,
            )
            if ok and upd:
                updates.append({**upd, "target_title": title, "group": source, "source": source})
                link_results.append(
                    _result_row(
                        anchor_text=anchor,
                        target_url=url,
                        source=source,
                        status="inserted",
                        reason="append_paragraph",
                    )
                )
            else:
                link_results.append(
                    _result_row(
                        anchor_text=anchor,
                        target_url=url,
                        source=source,
                        status="skipped",
                        reason="Không chèn được đoạn Tham khảo thêm (tránh FAQ / tránh dồn sát link khác).",
                    )
                )
        lines = ["Source\tDestination\tAnchor Text"]
        source_url = str(current_url or "").strip()
        for u in updates:
            lines.append(f"{source_url}\t{u.get('target_url', '')}\t{u.get('anchor_text', '')}")
        verification = verify_internal_links_html(
            str(soup),
            jobs=jobs,
            current_url=current_url,
            expected_inserts=updates if updates else None,
        )
        return {
            "content_html": str(soup),
            "inserted_links": len(updates),
            "updates": updates,
            "link_results": link_results,
            "screaming_frog_tsv": "\n".join(lines),
            "used_llm_rewrite": False,
            "insert_mode": "append_only",
            "pending_append_offers": [],
            "verification": verification,
            "error": "" if updates else "Không chèn được đoạn Tham khảo thêm.",
        }

    jobs, link_results = _prepare_jobs(
        custom_links=custom_links,
        selected_posts=selected_posts,
        current_url=current_url,
        content_html=content_html,
    )
    if not jobs:
        return {
            "content_html": content_html,
            "inserted_links": 0,
            "updates": [],
            "link_results": link_results,
            "screaming_frog_tsv": "",
            "used_llm_rewrite": False,
            "pending_append_offers": [],
            "error": "Không có link hợp lệ để chèn.",
        }

    soup = BeautifulSoup(str(content_html or "").strip(), "html.parser")
    faq_ids = _faq_region_tag_ids(soup)
    para_pos = _paragraph_positions(soup, faq_ids=faq_ids)
    section_insert_counts: dict[str, int] = {}
    updates: list[dict] = []
    per_para_count: dict[int, int] = {}
    used_llm_any = False
    wp_pending_legacy: list[dict] = []
    pending_append_offers: list[dict[str, str]] = []

    used_append_keys: set[str] = set()
    jobs_to_process = list(jobs)
    use_llm = bool(use_llm_rewrite) and bool(llm_available)
    urls_in_article = _urls_present_in_html(soup)

    for job in jobs_to_process:
        url = str(job.get("target_url") or "").strip()
        anchor = str(job.get("anchor_text") or "").strip()
        title = str(job.get("title") or anchor).strip()
        source = str(job.get("source") or "wp")
        lt = str(job.get("link_type") or "")
        pr = str(job.get("priority") or "")
        max_ins = max(1, min(int(job.get("max_insert") or 1), 3))
        inserted_any = False
        url_norm = norm_url_for_compare(url)

        if url_norm and url_norm in urls_in_article:
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=source,
                    status="skipped",
                    reason="URL đích đã có trong bài — không chèn trùng.",
                    link_type=lt,
                    priority=pr,
                )
            )
            continue

        allow_first = source == "custom"
        for _ in range(max_ins):
            ok, upd = _inject_one_strict(
                soup,
                target_url=url,
                anchor_text=anchor,
                per_para_count=per_para_count,
                allow_first_paragraph=allow_first,
                faq_ids=faq_ids,
                section_insert_counts=section_insert_counts,
                para_positions=para_pos,
            )
            if ok and upd:
                inserted_any = True
                updates.append({**upd, "target_title": title, "group": lt or source, "source": source})

        if inserted_any:
            urls_in_article.add(url_norm)
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=source,
                    status="inserted",
                    reason="inline",
                    link_type=lt,
                    priority=pr,
                )
            )
            continue

        in_body = _anchor_in_html(soup, anchor)
        llm_failed_reason = ""
        if use_llm:
            new_html, llm_ok, llm_reason = _try_llm_single(
                content_html=str(soup),
                target_url=url,
                anchor_text=anchor,
                title=title,
                article_primary_keyword=article_primary_keyword,
                article_secondary_keywords=article_secondary_keywords,
            )
            if llm_ok:
                soup = BeautifulSoup(new_html, "html.parser")
                faq_ids = _faq_region_tag_ids(soup)
                para_pos = _paragraph_positions(soup, faq_ids=faq_ids)
                used_llm_any = True
                urls_in_article = _urls_present_in_html(soup)
                urls_in_article.add(url_norm)
                updates.append(
                    {
                        "target_url": url,
                        "anchor_text": anchor,
                        "target_title": title,
                        "group": lt or source,
                        "source": source,
                    }
                )
                link_results.append(
                    _result_row(
                        anchor_text=anchor,
                        target_url=url,
                        source=source,
                        status="inserted",
                        reason="llm_minimal",
                        link_type=lt,
                        priority=pr,
                    )
                )
                continue
            llm_failed_reason = llm_reason or "LLM không chèn được — thử rule-based."

        if not in_body:
            if url_norm in confirmed_set:
                ok_append, upd_append = _inject_append_context_paragraph(
                    soup,
                    target_url=url,
                    anchor_text=anchor,
                    title=title,
                    used_append_keys=used_append_keys,
                    allow_first_paragraph=allow_first,
                    faq_ids=faq_ids,
                    section_insert_counts=section_insert_counts,
                    para_positions=para_pos,
                )
                if ok_append and upd_append:
                    urls_in_article.add(url_norm)
                    updates.append({**upd_append, "target_title": title, "group": lt or source, "source": source})
                    link_results.append(
                        _result_row(
                            anchor_text=anchor,
                            target_url=url,
                            source=source,
                            status="inserted",
                            reason="append_paragraph" + (f" ({llm_failed_reason})" if llm_failed_reason else ""),
                            link_type=lt,
                            priority=pr,
                        )
                    )
                    continue
            pending_append_offers.append(
                {
                    "target_url": url,
                    "anchor_text": anchor,
                    "title": title,
                    "preview": f'Tham khảo thêm: <a href="{url}">{anchor}</a>.',
                    "reason": "anchor_not_in_body",
                }
            )
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=source,
                    status="needs_confirm",
                    reason="Không có cụm anchor trong bài — chọn chèn dạng «Tham khảo thêm».",
                    link_type=lt,
                    priority=pr,
                )
            )
            continue

        ok_append, upd_append = _inject_append_context_paragraph(
            soup,
            target_url=url,
            anchor_text=anchor,
            title=title,
            used_append_keys=used_append_keys,
            allow_first_paragraph=allow_first,
            faq_ids=faq_ids,
            section_insert_counts=section_insert_counts,
            para_positions=para_pos,
        )
        if ok_append and upd_append:
            urls_in_article.add(url_norm)
            updates.append({**upd_append, "target_title": title, "group": lt or source, "source": source})
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=source,
                    status="inserted",
                    reason="append_paragraph" + (f" ({llm_failed_reason})" if llm_failed_reason else ""),
                    link_type=lt,
                    priority=pr,
                )
            )
            continue

        reason = (
            "Anchor có trong bài nhưng không chèn được (đoạn đã có link, trong H1–H3/FAQ, hoặc đã đủ 1 link/đoạn)."
            if in_body
            else "Không chèn được inline hoặc đoạn tham khảo."
        )
        if source != "custom":
            wp_pending_legacy.append({"link": url, "title": title, "anchor_text": anchor})
            continue

        link_results.append(
            _result_row(
                anchor_text=anchor,
                target_url=url,
                source=source,
                status="skipped",
                reason=reason,
                link_type=lt,
                priority=pr,
            )
        )

    if wp_pending_legacy and legacy_inject_fn is not None:
        out_html, legacy_updates = legacy_inject_fn(
            content_html=str(soup),
            selected_posts=wp_pending_legacy,
            target_website=target_website,
            max_links_per_section=1,
        )
        soup = BeautifulSoup(out_html, "html.parser")
        for u in legacy_updates:
            updates.append({**u, "source": "wp"})
            link_results.append(
                _result_row(
                    anchor_text=str(u.get("anchor_text") or ""),
                    target_url=str(u.get("target_url") or ""),
                    source="wp",
                    status="inserted",
                )
            )
        inserted_urls = {norm_url_for_compare(str(u.get("target_url") or "")) for u in legacy_updates}
        for job in wp_pending_legacy:
            if norm_url_for_compare(job["link"]) not in inserted_urls:
                link_results.append(
                    _result_row(
                        anchor_text=job["anchor_text"],
                        target_url=job["link"],
                        source="wp",
                        status="skipped",
                        reason="Không chèn được bằng rule-based/legacy.",
                    )
                )

    source_url = str(current_url or "").strip()
    lines = ["Source\tDestination\tAnchor Text"]
    for u in updates:
        lines.append(f"{source_url}\t{u.get('target_url', '')}\t{u.get('anchor_text', '')}")

    verification = verify_internal_links_html(
        str(soup),
        jobs=jobs,
        current_url=current_url,
        expected_inserts=updates if updates else None,
    )

    return {
        "content_html": str(soup),
        "inserted_links": len(updates),
        "updates": updates,
        "link_results": link_results,
        "screaming_frog_tsv": "\n".join(lines),
        "used_llm_rewrite": used_llm_any,
        "insert_mode": "minimal",
        "pending_append_offers": pending_append_offers,
        "verification": verification,
        "error": "" if (updates or pending_append_offers) else "Không chèn được internal link nào.",
    }
