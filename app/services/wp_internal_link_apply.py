"""
Apply internal links (WordPress related + custom) for Content AI — nhánh A.
"""
from __future__ import annotations

import html as py_html
import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, NavigableString

from app.services.llm_content_writer import (
    generate_contextual_internal_link_paragraph,
    rewrite_html_insert_internal_links,
)
from app.services.wp_internal_link_scoring import (
    assign_links_to_paragraphs,
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

_FAQ_HEADING_RE = re.compile(
    r"faq|câu\s*hỏi|hỏi\s*đáp|questions?\s*and\s*answers|q\s*&\s*a|thường\s*gặp",
    re.I,
)
_EXCLUDED_PARA_RE = re.compile(
    r"liên hệ|hotline|zalo|đặt lịch|đăng ký ngay|báo giá|tư vấn miễn phí|"
    r"hỗ trợ khách hàng|chăm sóc khách|liên hệ ngay|gọi ngay|"
    r"phạm vi hỗ trợ|phản hồi và phục vụ|thời gian phản hồi|"
    r"contact us|call now|customer support|cta",
    re.I,
)
_RULE_TEMPLATE_PARA_RE = re.compile(
    r"^(nếu bạn đang tìm dịch vụ cùng lĩnh vực|để nắm rõ hơn quy trình|"
    r"bạn cũng có thể tìm hiểu thêm|tham khảo thêm)",
    re.I,
)
_SUPPORT_HEADING_RE = re.compile(
    r"phản hồi|phục vụ|hỗ trợ|liên hệ|cam kết|đánh giá khách|"
    r"customer service|support|hotline|zalo",
    re.I,
)
_MIN_PARA_CHARS = 48
_MIN_PARA_GAP = 3
_DUPLICATE_CONTEXT_OPENING_RE = re.compile(
    r"trong phần «|bạn có thể đọc thêm|để hiểu rõ hơn nội dung liên quan",
    re.I,
)
def _fold_vn_ascii(s: str) -> str:
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


def _opening_is_banned_template(text: str) -> bool:
    folded = _fold_vn_ascii(str(text or "")[:160])
    banned = (
        "ban co the tham khao",
        "tham khao them",
        "xem them",
        "tim hieu them",
        "de biet them",
        "click vao day",
        "ban co the doc them",
    )
    return any(p in folded for p in banned)


class _ContextInsertState:
    """Theo dõi template/section đã dùng — tránh lặp câu và dồn link."""

    __slots__ = (
        "used_template_ids",
        "used_section_headings",
        "inserted_positions",
        "used_openings",
        "insert_count",
    )

    def __init__(self) -> None:
        self.used_template_ids: set[int] = set()
        self.used_section_headings: set[str] = set()
        self.inserted_positions: set[int] = set()
        self.used_openings: set[str] = set()
        self.insert_count = 0

    def record_insert(self, *, position: int, opening_key: str, template_id: int, section: str) -> None:
        self.insert_count += 1
        self.inserted_positions.add(position)
        self.used_template_ids.add(template_id)
        if opening_key:
            self.used_openings.add(opening_key[:48].casefold())
        sec = re.sub(r"\s+", " ", str(section or "").strip())[:80]
        if sec:
            self.used_section_headings.add(sec.casefold())


def norm_url_for_compare(url: str) -> str:
    """Chuẩn hóa URL: bỏ www, slash cuối, query/hash; hỗ trợ https://, //host/path, host/path."""
    raw = str(url or "").strip().strip('"\'')
    if not raw or raw == "#":
        return ""
    try:
        if raw.startswith("//"):
            raw = f"https:{raw}"
        if "://" not in raw:
            if raw.startswith("/"):
                path = re.sub(r"/{2,}", "/", unquote(raw)).rstrip("/").lower()
                return path
            if "." in raw.split("/")[0]:
                host, _, rest = raw.partition("/")
                host = host.lower().removeprefix("www.")
                path = re.sub(r"/{2,}", "/", unquote(f"/{rest}" if rest else "")).rstrip("/").lower()
                return f"{host}{path}"
            raw = f"https://{raw.lstrip('/')}"
        p = urlparse(raw)
        netloc = (p.netloc or "").lower().removeprefix("www.")
        path = re.sub(r"/{2,}", "/", unquote(p.path or "")).rstrip("/").lower()
        return f"{netloc}{path}"
    except Exception:
        return raw.lower().removeprefix("www.").rstrip("/")


def url_matches_allowed(href_norm: str, allowed_norm: set[str]) -> bool:
    if not href_norm or not allowed_norm:
        return True
    if href_norm in allowed_norm:
        return True
    href_slug = href_norm.rsplit("/", 1)[-1] if "/" in href_norm else href_norm
    for a in allowed_norm:
        if href_norm == a or href_norm.endswith(a) or a.endswith(href_norm):
            return True
        a_slug = a.rsplit("/", 1)[-1] if "/" in a else a
        if href_slug and a_slug and href_slug == a_slug:
            return True
    return False


def _iter_allowed_url_raws(
    *,
    allowed_urls: set[str] | None = None,
    jobs: list[dict[str, Any]] | None = None,
    expected_inserts: list[dict] | None = None,
) -> list[str]:
    """Mọi URL thô từ jobs / updates / danh sách đã chọn."""
    out: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        t = str(raw or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)

    for u in allowed_urls or set():
        push(str(u))
    for j in jobs or []:
        if not isinstance(j, dict):
            continue
        for key in ("target_url", "url", "link"):
            push(str(j.get(key) or ""))
    for ins in expected_inserts or []:
        if not isinstance(ins, dict):
            continue
        for key in ("target_url", "url", "link", "href"):
            push(str(ins.get(key) or ""))
    return out


def _collect_job_intent_slugs(
    *,
    allowed_urls: set[str] | None = None,
    jobs: list[dict[str, Any]] | None = None,
    expected_inserts: list[dict] | None = None,
) -> set[str]:
    """Slug đích (path cuối) của link user chọn / đã chèn — dùng để verify, không quét mọi link cùng host."""
    slugs: set[str] = set()
    for raw in _iter_allowed_url_raws(
        allowed_urls=allowed_urls,
        jobs=jobs,
        expected_inserts=expected_inserts,
    ):
        n = norm_url_for_compare(raw)
        if n and "/" in n:
            slug = n.rsplit("/", 1)[-1]
            if slug:
                slugs.add(slug)
    return slugs


def _build_allowed_url_norms(
    *,
    allowed_urls: set[str] | None = None,
    jobs: list[dict[str, Any]] | None = None,
    expected_inserts: list[dict] | None = None,
) -> set[str]:
    """Gộp mọi URL đã chọn / đã chèn (chuẩn hóa một lần)."""
    norms: set[str] = set()
    for raw in _iter_allowed_url_raws(
        allowed_urls=allowed_urls,
        jobs=jobs,
        expected_inserts=expected_inserts,
    ):
        n = norm_url_for_compare(raw)
        if n:
            norms.add(n)
    return norms


def _expand_allowed_norms_with_html_hrefs(
    norms: set[str],
    html: str,
    *,
    intent_slugs: set[str] | None = None,
) -> set[str]:
    """Bổ sung biến thể href thực tế trong HTML (www, slash, http/https) nếu cùng slug đã chọn."""
    if not norms and not intent_slugs:
        return norms
    slugs = intent_slugs or {n.rsplit("/", 1)[-1] for n in norms if "/" in n and n.rsplit("/", 1)[-1]}
    if not slugs:
        return norms
    out = set(norms)
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    for a in soup.find_all("a", href=True):
        u = norm_url_for_compare(str(a.get("href") or ""))
        if not u:
            continue
        uslug = u.rsplit("/", 1)[-1] if "/" in u else u
        if uslug in slugs or url_matches_allowed(u, out):
            out.add(u)
    return out


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


def _is_support_heading(tag: Any) -> bool:
    if getattr(tag, "name", None) not in {"h2", "h3", "h4"}:
        return False
    return bool(_SUPPORT_HEADING_RE.search(str(tag.get_text(" ", strip=True) or "")))


def _tag_in_support_section(tag: Any, faq_ids: set[int]) -> bool:
    if _tag_in_faq(tag, faq_ids):
        return True
    node: Any = tag
    for _ in range(12):
        if node is None:
            break
        if getattr(node, "name", None) in {"h2", "h3"} and _is_support_heading(node):
            return True
        node = getattr(node, "parent", None)
    h2 = tag.find_previous(["h2", "h3"]) if hasattr(tag, "find_previous") else None
    if h2 is not None and _is_support_heading(h2):
        return True
    return False


def _is_excluded_body_paragraph(tag: Any, faq_ids: set[int]) -> bool:
    if getattr(tag, "name", None) != "p":
        return True
    if _tag_in_heading_block(tag) or _tag_in_faq(tag, faq_ids) or _tag_in_support_section(tag, faq_ids):
        return True
    if _is_reference_append_paragraph(tag):
        return True
    txt = re.sub(r"\s+", " ", str(tag.get_text(" ", strip=True) or ""))
    if len(txt) < _MIN_PARA_CHARS:
        return True
    if _EXCLUDED_PARA_RE.search(txt):
        return True
    if _RULE_TEMPLATE_PARA_RE.search(txt):
        return True
    return False


def _collect_eligible_paragraphs(soup: BeautifulSoup, *, faq_ids: set[int]) -> list[dict[str, Any]]:
    """Danh sách đoạn <p> hợp lệ để gán/chèn internal link."""
    out: list[dict[str, Any]] = []
    pos = 0
    for p in soup.find_all("p"):
        if _is_excluded_body_paragraph(p, faq_ids):
            continue
        if p.find("a"):
            continue
        text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(text) < _MIN_PARA_CHARS:
            continue
        h2 = p.find_previous("h2")
        section_heading = ""
        if h2 is not None and not _is_faq_heading(h2):
            section_heading = h2.get_text(" ", strip=True)
        out.append(
            {
                "paragraph_id": id(p),
                "tag": p,
                "position": pos,
                "text": text,
                "section_heading": section_heading,
                "section_key": _section_key_for(p),
            }
        )
        pos += 1
    return out


def validate_internal_link_output(
    html: str,
    *,
    jobs: list[dict[str, Any]],
    allowed_urls: set[str] | None = None,
    current_url: str | None = None,
    expected_inserts: list[dict] | None = None,
    min_para_gap: int = _MIN_PARA_GAP,
) -> dict[str, Any]:
    """Validate HTML sau chèn LLM/rule: phân bổ, 1 link/đoạn, URL hợp lệ, vùng cấm."""
    issues: list[str] = []
    raw = str(html or "").strip()
    if not raw:
        return {"ok": False, "issues": ["HTML rỗng."]}
    soup = BeautifulSoup(raw, "html.parser")
    faq_ids = _faq_region_tag_ids(soup)
    cur_norm = norm_url_for_compare(str(current_url or ""))
    intent_slugs = _collect_job_intent_slugs(
        allowed_urls=allowed_urls,
        jobs=jobs,
        expected_inserts=expected_inserts,
    )
    allowed_norm = _build_allowed_url_norms(
        allowed_urls=allowed_urls,
        jobs=jobs,
        expected_inserts=expected_inserts,
    )
    allowed_norm = _expand_allowed_norms_with_html_hrefs(
        allowed_norm, raw, intent_slugs=intent_slugs
    )
    job_hosts = {n.split("/")[0] for n in allowed_norm if n and "/" in n}

    url_counts: dict[str, int] = {}
    link_para_positions: list[int] = []
    eligible = _collect_eligible_paragraphs(soup, faq_ids=faq_ids)
    pos_by_id = {int(e["paragraph_id"]): int(e["position"]) for e in eligible}
    total_eligible = max(1, len(eligible))

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        u = norm_url_for_compare(href)
        if not u:
            continue
        url_counts[u] = url_counts.get(u, 0) + 1
        if allowed_norm and job_hosts and intent_slugs:
            host = u.split("/")[0] if "/" in u else u
            uslug = u.rsplit("/", 1)[-1] if "/" in u else u
            if (
                host in job_hosts
                and uslug in intent_slugs
                and not url_matches_allowed(u, allowed_norm)
            ):
                issues.append(f"URL không nằm trong danh sách đã chọn: {href[:70]}")
        if cur_norm and u == cur_norm:
            issues.append(f"Link trỏ về chính bài đang soạn: {href[:80]}")
        anchor_txt = a.get_text(" ", strip=True)
        if is_bad_anchor(anchor_txt):
            issues.append(f"Anchor không nên dùng: «{anchor_txt[:40]}»")
        if _tag_in_faq(a, faq_ids):
            issues.append(f"Link trong vùng FAQ: {href[:60]}")
        if _tag_in_heading_block(a):
            issues.append(f"Link trong heading: {href[:60]}")

    for u, cnt in url_counts.items():
        if cnt > 1:
            issues.append(f"URL đích xuất hiện {cnt} lần trong bài (tối đa 1).")

    for p in soup.find_all("p"):
        anchors = p.find_all("a", href=True)
        internal = []
        if allowed_norm:
            internal = [
                a
                for a in anchors
                if url_matches_allowed(
                    norm_url_for_compare(str(a.get("href") or "")),
                    allowed_norm,
                )
            ]
        if len(internal) > 1:
            issues.append(f"Một đoạn văn có {len(internal)} internal link (tối đa 1).")
        if len(internal) == 1:
            if _tag_in_faq(p, faq_ids):
                issues.append("Internal link nằm trong vùng FAQ.")
            elif _tag_in_support_section(p, faq_ids) and not _is_valid_context_link_paragraph(p):
                issues.append("Internal link nằm trong section hỗ trợ/liên hệ (không phù hợp).")
            elif _is_excluded_body_paragraph(p, faq_ids) and not _is_valid_context_link_paragraph(p):
                issues.append("Internal link nằm trong đoạn bị loại (CTA/đoạn ngắn/template).")
            pid = id(p)
            if pid in pos_by_id:
                link_para_positions.append(pos_by_id[pid])

    link_para_positions.sort()
    for i in range(1, len(link_para_positions)):
        if link_para_positions[i] - link_para_positions[i - 1] < min_para_gap:
            issues.append("Hai internal link nằm quá gần nhau (đoạn liên tiếp hoặc cách < 2 đoạn).")
            break

    prev_open = ""
    for p in soup.find_all("p"):
        if not p.find("a", href=True):
            continue
        open_key = p.get_text(" ", strip=True)[:36].casefold()
        if prev_open and open_key and open_key == prev_open:
            issues.append("Hai đoạn internal link liên tiếp có câu mở đầu giống hệt nhau.")
            break
        if _DUPLICATE_CONTEXT_OPENING_RE.search(p.get_text(" ", strip=True)) and prev_open:
            if open_key[:24] == prev_open[:24]:
                issues.append("Câu chèn link bị lặp template — cần đa dạng ngữ cảnh.")
                break
        prev_open = open_key

    if len(link_para_positions) >= 3:
        span = link_para_positions[-1] - link_para_positions[0]
        if span < max(2, int(total_eligible * 0.2)):
            issues.append("Internal link bị dồn vào một cụm đoạn (không rải đều).")
        last_third_start = int(total_eligible * 0.67)
        in_last = sum(1 for x in link_para_positions if x >= last_third_start)
        if in_last > max(1, len(link_para_positions) // 2) and len(link_para_positions) >= 2:
            issues.append("Quá nhiều internal link dồn ở cuối bài.")

    for job in jobs or []:
        url = str(job.get("target_url") or job.get("url") or job.get("link") or "").strip()
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


def verify_internal_links_html(
    html: str,
    *,
    jobs: list[dict[str, Any]],
    current_url: str | None = None,
    expected_inserts: list[dict] | None = None,
    allowed_urls: set[str] | None = None,
) -> dict[str, Any]:
    """Alias — dùng validate_internal_link_output."""
    allowed_raw: set[str] = set(str(u).strip() for u in (allowed_urls or set()) if str(u or "").strip())
    for j in jobs or []:
        if not isinstance(j, dict):
            continue
        for key in ("target_url", "url", "link"):
            v = str(j.get(key) or "").strip()
            if v:
                allowed_raw.add(v)
    for ins in expected_inserts or []:
        if isinstance(ins, dict):
            for key in ("target_url", "url", "link", "href"):
                v = str(ins.get(key) or "").strip()
                if v:
                    allowed_raw.add(v)
    return validate_internal_link_output(
        html,
        jobs=jobs,
        allowed_urls=allowed_raw,
        current_url=current_url,
        expected_inserts=expected_inserts,
    )


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
    for row in _collect_eligible_paragraphs(soup, faq_ids=faq_ids):
        pos[int(row["paragraph_id"])] = int(row["position"])
    return pos


def _build_link_placements(
    soup: BeautifulSoup,
    jobs: list[dict[str, Any]],
    *,
    faq_ids: set[int],
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
) -> list[dict[str, Any]]:
    paragraphs = _collect_eligible_paragraphs(soup, faq_ids=faq_ids)
    if not paragraphs or not jobs:
        return []
    para_meta = [
        {
            "paragraph_id": int(p["paragraph_id"]),
            "position": int(p["position"]),
            "text": str(p["text"] or ""),
            "section_heading": str(p.get("section_heading") or ""),
        }
        for p in paragraphs
    ]
    return assign_links_to_paragraphs(
        jobs,
        para_meta,
        min_para_gap=_MIN_PARA_GAP,
        article_primary_keyword=article_primary_keyword,
        article_secondary_keywords=article_secondary_keywords,
    )


def _find_paragraph_by_id(soup: BeautifulSoup, paragraph_id: int) -> Any | None:
    for p in soup.find_all("p"):
        if id(p) == paragraph_id:
            return p
    return None


def _inject_inline_in_paragraph(
    para: Any,
    *,
    target_url: str,
    anchor_text: str,
) -> bool:
    raw_anchor = str(anchor_text or "").strip()
    url = str(target_url or "").strip()
    if not raw_anchor or not url or para is None:
        return False
    if para.find("a"):
        return False
    au_nfc = unicodedata.normalize("NFC", raw_anchor)
    min_len = 4 if len(au_nfc) <= 12 else 8
    for node in list(para.descendants):
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
        return True
    return False


def _inject_job_at_placement(
    soup: BeautifulSoup,
    placement: dict[str, Any],
    *,
    per_para_count: dict[int, int],
    faq_ids: set[int],
    section_insert_counts: dict[str, int],
    used_append_keys: set[str],
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    use_llm_inner: bool = False,
    ctx: _ContextInsertState | None = None,
) -> tuple[bool, dict[str, str] | None]:
    """Chèn 1 job tại paragraph đã gán — inline trước, đoạn ngữ cảnh sau (không gom Tham khảo thêm)."""
    job = placement.get("job") or {}
    url = str(job.get("target_url") or "").strip()
    anchor = str(job.get("anchor_text") or "").strip()
    title = str(job.get("title") or anchor).strip()
    pid = int(placement.get("paragraph_id") or 0)
    para = _find_paragraph_by_id(soup, pid)
    if not url or not anchor or para is None:
        return False, None

    if per_para_count.get(pid, 0) >= 1:
        return False, None

    pos = int(placement.get("position") or 0)
    sec_heading = str(placement.get("section_heading") or "")
    if placement.get("anchor_inline") or _inject_inline_in_paragraph(para, target_url=url, anchor_text=anchor):
        per_para_count[pid] = per_para_count.get(pid, 0) + 1
        sec = _section_key_for(para)
        section_insert_counts[sec] = section_insert_counts.get(sec, 0) + 1
        if ctx:
            ctx.record_insert(position=pos, opening_key="inline", template_id=-1, section=sec_heading)
        return True, {"target_url": url, "anchor_text": anchor, "method": "inline_assigned"}

    if not _paragraph_near_link_block(para, gap=2):
        if _append_link_weave_to_paragraph(
            para,
            target_url=url,
            anchor_text=anchor,
            title=title,
            section_heading=sec_heading,
            position=pos,
            ctx=ctx,
        ):
            per_para_count[pid] = per_para_count.get(pid, 0) + 1
            sec = _section_key_for(para)
            section_insert_counts[sec] = section_insert_counts.get(sec, 0) + 1
            return True, {"target_url": url, "anchor_text": anchor, "method": "weave_in_paragraph"}

    if _paragraph_near_link_block(para, gap=2):
        return False, None

    inner = _rule_context_paragraph_inner(
        target_url=url,
        anchor_text=anchor,
        title=title,
        section_heading=sec_heading,
        position=pos,
        ctx=ctx,
        as_new_paragraph=True,
    )
    if use_llm_inner:
        try:
            inner = generate_contextual_internal_link_paragraph(
                anchor_text=anchor,
                target_url=url,
                target_title=title,
                section_heading=sec_heading,
                article_primary_keyword=article_primary_keyword,
                article_secondary_keywords=article_secondary_keywords,
                template_variant=ctx.insert_count if ctx else 0,
            )
        except Exception:
            pass
    if _is_bare_link_paragraph(BeautifulSoup(inner, "html.parser")):
        inner = _rule_context_paragraph_inner(
            target_url=url,
            anchor_text=anchor,
            title=title,
            section_heading=sec_heading,
            position=pos,
            ctx=ctx,
            as_new_paragraph=True,
        )

    sk = f"p:{pid}"
    if sk in used_append_keys:
        return False, None
    ns = para.find_next_sibling()
    if ns is not None and (_is_reference_append_paragraph(ns) or _is_bare_link_paragraph(ns) or ns.find("a")):
        return False, None
    new_p = _insert_paragraph_after(
        soup,
        para,
        target_url=url,
        anchor_text=anchor,
        lead_idx=len(used_append_keys),
        inner_html=inner,
    )
    if new_p is None:
        return False, None
    _mark_append_vicinity(used_append_keys, para, new_ref=new_p)
    per_para_count[pid] = per_para_count.get(pid, 0) + 1
    sec = _section_key_for(para)
    section_insert_counts[sec] = section_insert_counts.get(sec, 0) + 1
    return True, {"target_url": url, "anchor_text": anchor, "method": "context_after_assigned"}


def _distributed_rule_insert_jobs(
    soup: BeautifulSoup,
    jobs: list[dict[str, Any]],
    *,
    faq_ids: set[int],
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    use_llm_inner: bool = False,
    ctx: _ContextInsertState | None = None,
) -> tuple[list[dict], list[dict[str, str]]]:
    placements = _build_link_placements(
        soup,
        jobs,
        faq_ids=faq_ids,
        article_primary_keyword=article_primary_keyword,
        article_secondary_keywords=article_secondary_keywords,
    )
    per_para_count: dict[int, int] = {}
    section_insert_counts: dict[str, int] = {}
    used_append_keys: set[str] = set()
    if ctx is None:
        ctx = _ContextInsertState()
    updates: list[dict] = []
    link_results: list[dict[str, str]] = []
    placed_urls: set[str] = set()

    for pl in placements:
        job = pl.get("job") or {}
        url = str(job.get("target_url") or "").strip()
        un = norm_url_for_compare(url)
        if un in placed_urls:
            continue
        ok, upd = _inject_job_at_placement(
            soup,
            pl,
            per_para_count=per_para_count,
            faq_ids=faq_ids,
            section_insert_counts=section_insert_counts,
            used_append_keys=used_append_keys,
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            use_llm_inner=use_llm_inner,
            ctx=ctx,
        )
        if ok and upd:
            placed_urls.add(un)
            updates.append({**upd, "target_title": str(job.get("title") or ""), "source": str(job.get("source") or "rule")})
            link_results.append(
                _result_row(
                    anchor_text=str(upd.get("anchor_text") or ""),
                    target_url=url,
                    source=str(job.get("source") or "rule"),
                    status="inserted",
                    reason=str(upd.get("method") or "distributed_rule"),
                )
            )

    remaining = [j for j in jobs if norm_url_for_compare(str(j.get("target_url") or "")) not in placed_urls]
    for job in remaining:
        url = str(job.get("target_url") or "").strip()
        anchor = str(job.get("anchor_text") or "").strip()
        title = str(job.get("title") or anchor).strip()
        ok, upd = _inject_append_context_paragraph(
            soup,
            target_url=url,
            anchor_text=anchor,
            title=title,
            used_append_keys=used_append_keys,
            faq_ids=faq_ids,
            section_insert_counts=section_insert_counts,
            para_positions=_paragraph_positions(soup, faq_ids=faq_ids),
            contextual_inner_html=_rule_context_paragraph_inner(
                target_url=url, anchor_text=anchor, title=title
            ),
        )
        if ok and upd:
            placed_urls.add(norm_url_for_compare(url))
            updates.append({**upd, "target_title": title, "source": str(job.get("source") or "rule")})
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=str(job.get("source") or "rule"),
                    status="inserted",
                    reason="append_last_resort",
                )
            )
        else:
            link_results.append(
                _result_row(
                    anchor_text=anchor,
                    target_url=url,
                    source=str(job.get("source") or "rule"),
                    status="skipped",
                    reason="Không tìm được đoạn phù hợp để chèn.",
                )
            )
    return updates, link_results


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
        if txt.startswith(lead):
            return True
    if _opening_is_banned_template(txt):
        return True
    return bool(
        re.match(
            r"^(tham\s*khảo\s*thêm|tìm\s*hiểu\s*thêm\s*về|để\s*nắm\s*rõ\s*hơn|xem\s+thêm)\b",
            txt,
            re.I,
        )
    )


def _is_valid_context_link_paragraph(tag: Any) -> bool:
    """Đoạn có link nhưng là câu ngữ cảnh đầy đủ (không phải template/append)."""
    if getattr(tag, "name", None) != "p":
        return False
    if not tag.find("a", href=True) or _is_bare_link_paragraph(tag):
        return False
    if _is_reference_append_paragraph(tag):
        return False
    return len(str(tag.get_text(" ", strip=True) or "")) >= 52


def _is_bare_link_paragraph(tag: Any) -> bool:
    """Đoạn chỉ có (gần như) một link — thiếu câu ngữ cảnh."""
    if getattr(tag, "name", None) != "p":
        return False
    anchors = tag.find_all("a", href=True)
    if len(anchors) != 1:
        return False
    txt = re.sub(r"\s+", " ", tag.get_text(" ", strip=True) or "").strip()
    anchor_txt = anchors[0].get_text(" ", strip=True)
    if not txt or not anchor_txt:
        return False
    rest = txt.replace(anchor_txt, "").strip(" .,;:-—")
    if len(rest) >= 28:
        return False
    if re.search(r"\b(nếu bạn|khách hàng|có thể|tham khảo|dịch vụ|quy trình|để nắm)\b", rest, re.I):
        return len(rest) < 14
    return len(rest) < 12 or (len(txt) - len(anchor_txt) < 15)


def _pick_context_template_id(
    *,
    target_url: str,
    position: int,
    section_heading: str,
    ctx: _ContextInsertState | None,
    n_templates: int = 8,
) -> int:
    base = hash(f"{target_url}|{position}|{section_heading}|{ctx.insert_count if ctx else 0}") % n_templates
    if not ctx:
        return base
    for off in range(n_templates):
        idx = (base + off) % n_templates
        if idx not in ctx.used_template_ids:
            return idx
    return (base + ctx.insert_count) % n_templates


def _rule_context_paragraph_inner(
    *,
    target_url: str,
    anchor_text: str,
    title: str = "",
    section_heading: str = "",
    paragraph_text: str = "",
    position: int = 0,
    ctx: _ContextInsertState | None = None,
    as_new_paragraph: bool = True,
) -> str:
    safe_url = py_html.escape(str(target_url or "").strip(), quote=True)
    safe_anchor = py_html.escape(str(anchor_text or "").strip())
    topic_raw = (title or anchor_text or "chủ đề liên quan").strip()[:80]
    topic = py_html.escape(topic_raw)
    h2_raw = str(section_heading or "").strip()[:100]
    h2 = py_html.escape(h2_raw) if h2_raw else ""
    tid = _pick_context_template_id(
        target_url=target_url,
        position=position,
        section_heading=h2_raw,
        ctx=ctx,
    )
    link = f'<a href="{safe_url}">{safe_anchor}</a>'
    wrap_open = "<p>" if as_new_paragraph else ""
    wrap_close = "</p>" if as_new_paragraph else ""

    templates_h2 = [
        f"{wrap_open}Trong hạng mục {h2}, {link} mô tả quy trình và phạm vi xử lý phù hợp với tình huống vừa nêu.{wrap_close}",
        f"{wrap_open}Phần {h2} thường đi kèm nhu cầu cụ thể — {link} là hướng dẫn chi tiết cùng chủ đề dịch vụ.{wrap_close}",
        f"{wrap_open}Khi triển khai {h2}, {link} giúp đối chiếu bước làm và lưu ý kỹ thuật quan trọng.{wrap_close}",
        f"{wrap_open}Nội dung {h2} ở trên có thể bổ sung bằng {link} về cùng lĩnh vực, tránh bỏ sót hạng mục.{wrap_close}",
        f"{wrap_open}Với {h2}, {link} là tài liệu liên quan trực tiếp trên cùng hệ thống dịch vụ.{wrap_close}",
    ]
    templates_body = [
        f"{wrap_open}Trong bối cảnh vừa mô tả, {link} hỗ trợ kiểm tra và xử lý theo quy trình chuẩn.{wrap_close}",
        f"{wrap_open}Các triệu chứng trên thường cần đánh giá kỹ — {link} nêu rõ cách xử lý cùng lĩnh vực.{wrap_close}",
        f"{wrap_open}Đây là lúc {link} phù hợp để đối chiếu phương án và tránh sai sót khi triển khai.{wrap_close}",
        f"{wrap_open}Dịch vụ {link} bổ sung góc nhìn thực tế cho cùng nhóm vấn đề kỹ thuật.{wrap_close}",
        f"{wrap_open}Với nhu cầu vừa nêu, {link} là hướng xử lý phù hợp trên cùng hệ thống.{wrap_close}",
        f"{wrap_open}Kỹ thuật viên thường đối chiếu thêm {link} trước khi chốt phương án sửa chữa.{wrap_close}",
    ]
    weave_templates = [
        f", phù hợp để kiểm tra qua {link} trong cùng hệ thống dịch vụ.",
        f" — {link} mô tả quy trình xử lý tương ứng.",
        f"; {link} là lựa chọn hợp lý khi cần xử lý cùng nhóm lỗi.",
        f", và {link} giúp đối chiếu các bước triển khai chi tiết.",
        f" nên {link} bổ sung hướng dẫn kỹ thuật cùng chủ đề.",
        f", khi đó {link} hỗ trợ xử lý theo quy trình chuẩn.",
        f"; dịch vụ {link} phù hợp với tình huống vừa nêu.",
        f" — {link} là hướng dẫn chi tiết cùng lĩnh vực.",
    ]

    if not as_new_paragraph:
        inner = weave_templates[tid % len(weave_templates)]
        if ctx:
            ctx.record_insert(
                position=position,
                opening_key=inner[:32],
                template_id=tid,
                section=h2_raw,
            )
        return inner

    pool = templates_h2 if h2 else templates_body
    inner = pool[tid % len(pool)]
    if ctx:
        ctx.record_insert(
            position=position,
            opening_key=inner[:40],
            template_id=tid,
            section=h2_raw,
        )
    return inner


def _paragraph_near_link_block(tag: Any, *, gap: int = 2) -> bool:
    """True nếu trong ±gap đoạn <p> liền kề đã có internal link."""
    if tag is None or not hasattr(tag, "find_previous"):
        return False
    sibs: list[Any] = []
    prev = tag
    for _ in range(gap):
        prev = prev.find_previous("p") if prev else None
        if prev is not None:
            sibs.append(prev)
    nxt = tag
    for _ in range(gap + 1):
        nxt = nxt.find_next_sibling("p") if nxt else None
        if nxt is not None:
            sibs.append(nxt)
    for s in sibs:
        if s and s.find("a", href=True):
            return True
        if s and _DUPLICATE_CONTEXT_OPENING_RE.search(str(s.get_text(" ", strip=True) or "")):
            return True
    return False


def _append_link_weave_to_paragraph(
    para: Any,
    *,
    target_url: str,
    anchor_text: str,
    title: str,
    section_heading: str,
    position: int,
    ctx: _ContextInsertState | None,
) -> bool:
    if para is None or para.find("a"):
        return False
    inner = _rule_context_paragraph_inner(
        target_url=target_url,
        anchor_text=anchor_text,
        title=title,
        section_heading=section_heading,
        position=position,
        ctx=ctx,
        as_new_paragraph=False,
    )
    frag = BeautifulSoup(inner, "html.parser")
    for child in list(frag.contents):
        para.append(child)
    return True


def _diversify_duplicate_context_paragraphs(soup: BeautifulSoup, ctx: _ContextInsertState | None) -> int:
    """Sửa các <p> liên tiếp mở đầu giống nhau (template cũ / trùng câu)."""
    fixed = 0
    prev_key = ""
    for p in list(soup.find_all("p")):
        a = p.find("a", href=True)
        if not a:
            prev_key = ""
            continue
        txt = p.get_text(" ", strip=True)
        key = txt[:42].casefold()
        is_dup_opening = (
            key == prev_key
            or (_DUPLICATE_CONTEXT_OPENING_RE.search(txt) and prev_key and key[:28] == prev_key[:28])
        )
        if not is_dup_opening:
            prev_key = key
            continue
        url = str(a.get("href") or "").strip()
        anchor = a.get_text(" ", strip=True)
        h2 = _section_heading_for_node(p)
        pos = 0
        inner = _rule_context_paragraph_inner(
            target_url=url,
            anchor_text=anchor,
            title=anchor,
            section_heading=h2,
            position=pos + fixed,
            ctx=ctx,
            as_new_paragraph=True,
        )
        frag = BeautifulSoup(inner, "html.parser")
        inner_p = frag.find("p")
        p.clear()
        if inner_p:
            for child in list(inner_p.contents):
                p.append(child)
        else:
            p.append(frag)
        fixed += 1
        prev_key = p.get_text(" ", strip=True)[:42].casefold()
    return fixed


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
        if _tag_in_faq(tag, faq_ids) or _tag_in_support_section(tag, faq_ids):
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
    inner_html: str | None = None,
) -> Any | None:
    if after_node is None:
        return None
    if inner_html and str(inner_html).strip():
        frag = BeautifulSoup(str(inner_html).strip(), "html.parser")
        inner_p = frag.find("p")
        if inner_p:
            new_p = soup.new_tag("p")
            for child in list(inner_p.contents):
                new_p.append(child)
            after_node.insert_after(new_p)
            return new_p
        inner = str(inner_html).strip()
    else:
        lead = _APPEND_LEADS[lead_idx % len(_APPEND_LEADS)]
        safe_url = py_html.escape(str(target_url or "").strip(), quote=True)
        safe_anchor = py_html.escape(str(anchor_text or "").strip())
        if lead.endswith("về") or lead.endswith("thêm"):
            inner = f'{py_html.escape(lead)} <a href="{safe_url}">{safe_anchor}</a>.'
        else:
            inner = (
                f'{py_html.escape(lead)} <a href="{safe_url}">{safe_anchor}</a> '
                "— phù hợp ngữ cảnh chủ đề đang trình bày."
            )
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
    contextual_inner_html: str | None = None,
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
        if _is_faq_heading(h2) or _tag_in_faq(h2, faq_ids) or _is_support_heading(h2):
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
        ns = node.find_next_sibling()
        if ns is not None and (_is_reference_append_paragraph(ns) or _is_bare_link_paragraph(ns)):
            continue
        new_p = _insert_paragraph_after(
            soup,
            node,
            target_url=url,
            anchor_text=anchor,
            lead_idx=len(used_append_keys),
            inner_html=contextual_inner_html,
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


def _section_heading_for_node(node: Any) -> str:
    h2 = node.find_previous("h2") if node is not None else None
    return h2.get_text(" ", strip=True) if h2 else ""


def _try_llm_context_paragraph(
    *,
    soup: BeautifulSoup,
    target_url: str,
    anchor_text: str,
    title: str,
    insert_after_node: Any,
    article_primary_keyword: str,
    article_secondary_keywords: str,
    used_append_keys: set[str],
    faq_ids: set[int] | None,
    section_insert_counts: dict[str, int] | None,
    para_positions: dict[int, int] | None,
    allow_first_paragraph: bool = False,
) -> tuple[bool, dict[str, str] | None, str]:
    """LLM viết 1 đoạn <p> có câu ngữ cảnh + link, chèn sau đoạn/section phù hợp."""
    url = str(target_url or "").strip()
    anchor = str(anchor_text or "").strip()
    if not url or not anchor or insert_after_node is None:
        return False, None, "Thiếu URL/anchor hoặc vị trí chèn."
    try:
        inner = generate_contextual_internal_link_paragraph(
            anchor_text=anchor,
            target_url=url,
            target_title=title or anchor,
            section_heading=_section_heading_for_node(insert_after_node),
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
        )
    except Exception as exc:
        return False, None, str(exc)[:300]
    if _is_bare_link_paragraph(BeautifulSoup(inner, "html.parser")):
        inner = _rule_context_paragraph_inner(target_url=url, anchor_text=anchor, title=title)
    ok, upd = _inject_append_context_paragraph(
        soup,
        target_url=url,
        anchor_text=anchor,
        title=title,
        used_append_keys=used_append_keys,
        allow_first_paragraph=allow_first_paragraph,
        faq_ids=faq_ids,
        section_insert_counts=section_insert_counts,
        para_positions=para_positions,
        contextual_inner_html=inner,
    )
    if ok:
        return True, upd, ""
    return False, None, "Không chèn được đoạn ngữ cảnh LLM."


def _repair_legacy_template_link_paragraphs(
    soup: BeautifulSoup,
    *,
    ctx: _ContextInsertState | None = None,
) -> int:
    """Sửa đoạn template cũ / trùng mở đầu thành câu ngữ cảnh đa dạng."""
    fixed = 0
    legacy_markers = (
        "nếu bạn đang tìm dịch vụ cùng lĩnh vực",
        "để nắm rõ hơn quy trình và phạm vi hỗ trợ",
        "bạn cũng có thể tìm hiểu thêm",
        "trong phần «",
        "bạn có thể đọc thêm",
        "để hiểu rõ hơn nội dung liên quan",
    )
    for p in list(soup.find_all("p")):
        a = p.find("a", href=True)
        if not a:
            continue
        low = p.get_text(" ", strip=True).casefold()
        if not any(m in low for m in legacy_markers) and not _RULE_TEMPLATE_PARA_RE.search(low):
            continue
        url = str(a.get("href") or "").strip()
        anchor = a.get_text(" ", strip=True)
        inner = _rule_context_paragraph_inner(
            target_url=url,
            anchor_text=anchor,
            title=anchor,
            section_heading=_section_heading_for_node(p),
            position=fixed,
            ctx=ctx,
            as_new_paragraph=True,
        )
        frag = BeautifulSoup(inner, "html.parser")
        inner_p = frag.find("p")
        p.clear()
        if inner_p:
            for child in list(inner_p.contents):
                p.append(child)
        else:
            p.append(frag)
        fixed += 1
    return fixed


def _repair_bare_link_paragraphs(
    soup: BeautifulSoup,
    *,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    use_llm: bool = False,
) -> int:
    fixed = 0
    for p in list(soup.find_all("p")):
        if not _is_bare_link_paragraph(p):
            continue
        a = p.find("a", href=True)
        if not a:
            continue
        url = str(a.get("href") or "").strip()
        anchor = a.get_text(" ", strip=True)
        h2 = _section_heading_for_node(p)
        inner = _rule_context_paragraph_inner(target_url=url, anchor_text=anchor, title=anchor)
        if use_llm:
            try:
                inner = generate_contextual_internal_link_paragraph(
                    anchor_text=anchor,
                    target_url=url,
                    target_title=anchor,
                    section_heading=h2,
                    article_primary_keyword=article_primary_keyword,
                    article_secondary_keywords=article_secondary_keywords,
                )
            except Exception:
                pass
        frag = BeautifulSoup(inner, "html.parser")
        inner_p = frag.find("p")
        p.clear()
        if inner_p:
            for child in list(inner_p.contents):
                p.append(child)
        else:
            p.append(frag)
        fixed += 1
    return fixed


def _try_llm_batch(
    *,
    content_html: str,
    jobs: list[dict[str, Any]],
    article_primary_keyword: str,
    article_secondary_keywords: str,
) -> tuple[str, bool, str, list[dict[str, str]]]:
    if not jobs:
        return content_html, False, "Không có job.", []
    link_jobs = [
        {
            "url": str(j.get("target_url") or "").strip(),
            "title": str(j.get("title") or j.get("anchor_text") or "").strip(),
            "anchor_text": str(j.get("anchor_text") or "").strip(),
        }
        for j in jobs
    ]
    link_jobs = [x for x in link_jobs if x["url"] and x["anchor_text"]]
    if not link_jobs:
        return content_html, False, "Job rỗng.", []

    soup0 = BeautifulSoup(str(content_html or "").strip(), "html.parser")
    faq_ids = _faq_region_tag_ids(soup0)
    placements = _build_link_placements(
        soup0,
        jobs,
        faq_ids=faq_ids,
        article_primary_keyword=article_primary_keyword,
        article_secondary_keywords=article_secondary_keywords,
    )
    allowed_raw = {str(x["url"]) for x in link_jobs if x.get("url")}

    try:
        out = rewrite_html_insert_internal_links(
            content_html=content_html,
            link_jobs=link_jobs,
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            minimal=True,
            placement_hints=placements,
        )
    except Exception as exc:
        out = content_html
        llm_err = str(exc)[:400]
    else:
        llm_err = ""

    use_llm_html = False
    if out.strip() and _llm_change_acceptable(content_html, out) and verify_llm_internal_links_html(out, link_jobs):
        out = _strip_links_from_faq_region(out)
        from app.services.wp_internal_link_postprocess import postprocess_internal_links_html

        sel = [{"target_url": x["url"], "anchor_text": x["anchor_text"]} for x in link_jobs]
        out, _ = postprocess_internal_links_html(out, sel)
        val = validate_internal_link_output(
            out,
            jobs=jobs,
            allowed_urls=allowed_raw,
            expected_inserts=link_jobs,
        )
        if val.get("ok"):
            use_llm_html = True

    if use_llm_html:
        inserted = [
            {
                "target_url": x["url"],
                "anchor_text": x["anchor_text"],
                "target_title": x.get("title") or x["anchor_text"],
            }
            for x in link_jobs
        ]
        return out, True, "", inserted

    reason = llm_err or "Validate LLM thất bại (dồn link / vi phạm phân bổ) — fallback rule."
    soup_fb = BeautifulSoup(str(content_html or "").strip(), "html.parser")
    faq_fb = _faq_region_tag_ids(soup_fb)
    updates, _ = _distributed_rule_insert_jobs(
        soup_fb,
        jobs,
        faq_ids=faq_fb,
        article_primary_keyword=article_primary_keyword,
        article_secondary_keywords=article_secondary_keywords,
        use_llm_inner=False,
    )
    if not updates:
        return content_html, False, reason, []
    val_fb = validate_internal_link_output(
        str(soup_fb),
        jobs=jobs,
        allowed_urls=allowed_raw,
        expected_inserts=updates,
    )
    if not val_fb.get("ok") and len(updates) >= 2:
        return content_html, False, f"{reason}; {val_fb.get('issues', [])[:2]}", []
    return str(soup_fb), True, reason, updates


def _try_llm_single(
    *,
    content_html: str,
    target_url: str,
    anchor_text: str,
    title: str,
    article_primary_keyword: str,
    article_secondary_keywords: str,
    placement_hints: list[dict[str, Any]] | None = None,
) -> tuple[str, bool, str]:
    job = {"url": target_url, "title": title or anchor_text, "anchor_text": anchor_text}
    jobs_full = [
        {
            "target_url": target_url,
            "anchor_text": anchor_text,
            "title": title or anchor_text,
        }
    ]
    allowed = {target_url}
    try:
        out = rewrite_html_insert_internal_links(
            content_html=content_html,
            link_jobs=[job],
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            minimal=True,
            placement_hints=placement_hints,
        )
        if not _llm_change_acceptable(content_html, out):
            return content_html, False, "LLM thay đổi quá nhiều nội dung — đã bỏ qua (dùng chèn đoạn ngắn)."
        if not out.strip() or not verify_llm_internal_links_html(out, [job]):
            return content_html, False, "LLM không chèn đủ anchor/URL hoặc verify thất bại."
        val = validate_internal_link_output(
            out,
            jobs=jobs_full,
            allowed_urls=allowed,
            expected_inserts=[job],
        )
        if not val.get("ok"):
            return content_html, False, "Validate phân bổ LLM thất bại."
        soup_chk = BeautifulSoup(_strip_links_from_faq_region(out), "html.parser")
        _repair_bare_link_paragraphs(
            soup_chk,
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            use_llm=True,
        )
        return str(soup_chk), True, ""
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
    preview_only: bool = False,
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
            ctx_inner = _rule_context_paragraph_inner(target_url=url, anchor_text=anchor, title=title)
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
                contextual_inner_html=ctx_inner,
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
        verify_allowed_append: set[str] = set()
        for j in jobs:
            if isinstance(j, dict):
                for key in ("target_url", "url", "link"):
                    v = str(j.get(key) or "").strip()
                    if v:
                        verify_allowed_append.add(v)
        for u in updates:
            if isinstance(u, dict):
                for key in ("target_url", "url", "link"):
                    v = str(u.get(key) or "").strip()
                    if v:
                        verify_allowed_append.add(v)
        from app.services.wp_internal_link_postprocess import postprocess_internal_links_html

        sel_append = [
            {
                "target_url": str(j.get("target_url") or j.get("link") or ""),
                "anchor_text": str(j.get("anchor_text") or ""),
            }
            for j in jobs
        ]
        pp_html, pp_stats = postprocess_internal_links_html(str(soup), sel_append)
        soup = BeautifulSoup(pp_html, "html.parser")
        verification = verify_internal_links_html(
            str(soup),
            jobs=jobs,
            current_url=current_url,
            expected_inserts=updates if updates else None,
            allowed_urls=verify_allowed_append,
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
            "postprocess": pp_stats,
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
    ctx_insert = _ContextInsertState()
    jobs_to_process = list(jobs)
    use_llm = bool(use_llm_rewrite) and bool(llm_available)
    urls_in_article = _urls_present_in_html(soup)
    remaining_after_inline: list[dict[str, Any]] = []

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

        remaining_after_inline.append(job)
        continue

    if use_llm and remaining_after_inline:
        batch_pool = [
            j
            for j in remaining_after_inline
            if norm_url_for_compare(str(j.get("target_url") or "")) not in urls_in_article
        ]
        if batch_pool:
            new_html, batch_ok, batch_reason, batch_ins = _try_llm_batch(
                content_html=str(soup),
                jobs=batch_pool,
                article_primary_keyword=article_primary_keyword,
                article_secondary_keywords=article_secondary_keywords,
            )
            if batch_ok:
                soup = BeautifulSoup(new_html, "html.parser")
                faq_ids = _faq_region_tag_ids(soup)
                para_pos = _paragraph_positions(soup, faq_ids=faq_ids)
                used_llm_any = True
                urls_in_article = _urls_present_in_html(soup)
                inserted_norms = set()
                for ins in batch_ins:
                    u = str(ins.get("target_url") or "").strip()
                    un = norm_url_for_compare(u)
                    if un:
                        inserted_norms.add(un)
                        urls_in_article.add(un)
                    updates.append(
                        {
                            **ins,
                            "group": "llm_batch",
                            "source": "llm_batch",
                        }
                    )
                    link_results.append(
                        _result_row(
                            anchor_text=str(ins.get("anchor_text") or ""),
                            target_url=u,
                            source="wp",
                            status="inserted",
                            reason="llm_batch_context",
                        )
                    )
                remaining_after_inline = [
                    j
                    for j in remaining_after_inline
                    if norm_url_for_compare(str(j.get("target_url") or "")) not in inserted_norms
                ]
            elif batch_reason:
                for j in remaining_after_inline[:1]:
                    pass  # batch fail → xử lý từng link bên dưới

    still_remaining = [
        j
        for j in remaining_after_inline
        if norm_url_for_compare(str(j.get("target_url") or "")) not in urls_in_article
    ]
    if still_remaining:
        placements_rem = _build_link_placements(
            soup,
            still_remaining,
            faq_ids=faq_ids,
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
        )
        placement_by_url = {
            norm_url_for_compare(str((pl.get("job") or {}).get("target_url") or "")): pl
            for pl in placements_rem
        }
        for job in still_remaining:
            url = str(job.get("target_url") or "").strip()
            anchor = str(job.get("anchor_text") or "").strip()
            title = str(job.get("title") or anchor).strip()
            source = str(job.get("source") or "wp")
            lt = str(job.get("link_type") or "")
            pr = str(job.get("priority") or "")
            url_norm = norm_url_for_compare(url)
            if url_norm in urls_in_article:
                continue
            pl = placement_by_url.get(url_norm)
            if pl:
                ok_pl, upd_pl = _inject_job_at_placement(
                    soup,
                    pl,
                    per_para_count=per_para_count,
                    faq_ids=faq_ids,
                    section_insert_counts=section_insert_counts,
                    used_append_keys=used_append_keys,
                    article_primary_keyword=article_primary_keyword,
                    article_secondary_keywords=article_secondary_keywords,
                    use_llm_inner=use_llm,
                    ctx=ctx_insert,
                )
                if ok_pl and upd_pl:
                    urls_in_article.add(url_norm)
                    updates.append({**upd_pl, "target_title": title, "group": lt or source, "source": source})
                    link_results.append(
                        _result_row(
                            anchor_text=anchor,
                            target_url=url,
                            source=source,
                            status="inserted",
                            reason=str(upd_pl.get("method") or "assigned_paragraph"),
                            link_type=lt,
                            priority=pr,
                        )
                    )
                    continue
            if use_llm and pl:
                hints = [pl]
                new_html, llm_ok, _ = _try_llm_single(
                    content_html=str(soup),
                    target_url=url,
                    anchor_text=anchor,
                    title=title,
                    article_primary_keyword=article_primary_keyword,
                    article_secondary_keywords=article_secondary_keywords,
                    placement_hints=hints,
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
                            reason="llm_minimal_assigned",
                            link_type=lt,
                            priority=pr,
                        )
                    )
                    continue

        leftover = [
            j
            for j in still_remaining
            if norm_url_for_compare(str(j.get("target_url") or "")) not in urls_in_article
        ]
        if leftover:
            fb_updates, fb_results = _distributed_rule_insert_jobs(
                soup,
                leftover,
                faq_ids=faq_ids,
                article_primary_keyword=article_primary_keyword,
                article_secondary_keywords=article_secondary_keywords,
                use_llm_inner=False,
                ctx=ctx_insert,
            )
            for upd in fb_updates:
                un = norm_url_for_compare(str(upd.get("target_url") or ""))
                if un:
                    urls_in_article.add(un)
                updates.append({**upd, "group": "distributed_rule", "source": upd.get("source") or "rule"})
            link_results.extend(fb_results)
            para_pos = _paragraph_positions(soup, faq_ids=faq_ids)

    for job in still_remaining:
        url = str(job.get("target_url") or "").strip()
        anchor = str(job.get("anchor_text") or "").strip()
        title = str(job.get("title") or anchor).strip()
        source = str(job.get("source") or "wp")
        lt = str(job.get("link_type") or "")
        pr = str(job.get("priority") or "")
        url_norm = norm_url_for_compare(url)
        if url_norm and url_norm in urls_in_article:
            continue
        allow_first = source == "custom"
        in_body = _anchor_in_html(soup, anchor)
        llm_failed_reason = ""

        if not in_body:
            if url_norm in confirmed_set:
                ctx_inner = _rule_context_paragraph_inner(target_url=url, anchor_text=anchor, title=title)
                if use_llm:
                    try:
                        ctx_inner = generate_contextual_internal_link_paragraph(
                            anchor_text=anchor,
                            target_url=url,
                            target_title=title,
                            article_primary_keyword=article_primary_keyword,
                            article_secondary_keywords=article_secondary_keywords,
                        )
                    except Exception:
                        pass
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
                    contextual_inner_html=ctx_inner,
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

        rule_inner = _rule_context_paragraph_inner(target_url=url, anchor_text=anchor, title=title)
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
            contextual_inner_html=rule_inner,
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
        if source != "custom" and not use_llm:
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

    faq_final = _faq_region_tag_ids(soup)
    ctx_final = _ContextInsertState()
    _repair_legacy_template_link_paragraphs(soup, ctx=ctx_final)
    _diversify_duplicate_context_paragraphs(soup, ctx_final)
    if use_llm or used_llm_any:
        _repair_bare_link_paragraphs(
            soup,
            article_primary_keyword=article_primary_keyword,
            article_secondary_keywords=article_secondary_keywords,
            use_llm=False,
        )

    from app.services.wp_internal_link_postprocess import postprocess_internal_links_html

    selected_for_pp = [
        {
            "target_url": str(j.get("target_url") or j.get("link") or j.get("url") or ""),
            "anchor_text": str(j.get("anchor_text") or ""),
        }
        for j in jobs
        if str(j.get("target_url") or j.get("link") or j.get("url") or "").strip()
    ]
    pp_html, pp_stats = postprocess_internal_links_html(str(soup), selected_for_pp)
    soup = BeautifulSoup(pp_html, "html.parser")

    verify_allowed: set[str] = set()
    for j in jobs:
        if not isinstance(j, dict):
            continue
        for key in ("target_url", "url", "link"):
            v = str(j.get(key) or "").strip()
            if v:
                verify_allowed.add(v)
    for u in updates:
        if not isinstance(u, dict):
            continue
        for key in ("target_url", "url", "link"):
            v = str(u.get(key) or "").strip()
            if v:
                verify_allowed.add(v)

    if preview_only:
        verification: dict[str, Any] = {"ok": True, "issues": [], "preview_skipped": True}
    else:
        verification = verify_internal_links_html(
            str(soup),
            jobs=jobs,
            current_url=current_url,
            expected_inserts=updates if updates else None,
            allowed_urls=verify_allowed,
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
        "postprocess": pp_stats,
        "error": "" if (updates or pending_append_offers) else "Không chèn được internal link nào.",
    }
