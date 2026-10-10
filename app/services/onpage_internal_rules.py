"""
On-page + internal-link site checks for Technical Analysis (/tool).

Issue contract: severity + confidence + evidence + affected_urls + remediation.
Do not emit when the crawl graph / HTML does not actually prove the problem.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.services.index_crawl_rules import ensure_crawl_index_contract, redirect_hops, redirect_loop_slice
from app.services.internal_link_graph import build_link_graph
from app.services.seo_normalize import normalize_url_safe

MIN_PAGES_FOR_ORPHAN = 3
MIN_PAGES_FOR_DEPTH = 8
DEEP_CRAWL_DEPTH = 4
MIN_DUPLICATE_TEXT_LEN = 4

_HREFLANG_CODE = re.compile(r"^(x-default|[a-z]{2}(-[a-z]{2,8})?)$", re.I)

_TYPE_ALIASES: dict[str, str] = {
    "missing_canonical": "canonical_missing_high_value",
    "internal_link_broken": "broken_internal_link",
}

# If the stronger type exists for the same URL, drop the weaker one.
_WEAKER_THAN: dict[str, tuple[str, ...]] = {
    "internal_link_redirect": ("redirect_chain", "redirect_loop"),
    "redirect_chain": ("redirect_loop",),
    "crawl_http_3xx": ("internal_link_redirect", "redirect_chain", "redirect_loop"),
    "crawl_http_4xx": ("broken_internal_link",),
    "broken_internal_http_error": ("broken_internal_link",),
    "missing_canonical": ("canonical_missing_high_value",),
}

_REMEDIATION: dict[str, str] = {
    "duplicate_title": "Khác biệt hóa title theo từng URL — mỗi trang một title mô tả intent riêng.",
    "duplicate_h1": "Mỗi URL nên có H1 riêng; đổi H1 trùng hoặc canonical/301 các bản duplicate.",
    "duplicate_meta_description": "Viết meta description độc nhất cho từng URL; tránh copy nguyên template.",
    "internal_link_redirect": "Sửa href nội bộ trỏ thẳng URL 200 cuối, không qua 301/302 trung gian.",
    "orphan_page": "Thêm internal link từ menu, category hoặc bài liên quan tới URL này.",
    "crawl_depth_deep": "Thêm link từ trang nông (home/category) để giảm số click tới URL sâu.",
    "missing_viewport": 'Thêm <meta name="viewport" content="width=device-width, initial-scale=1"> trong <head>.',
    "hreflang_invalid_code": "Sửa hreflang đúng BCP47 (ví dụ en, vi, en-US) hoặc x-default.",
    "hreflang_missing_self": "Thêm link rel=alternate hreflang trỏ về chính URL hiện tại trong cụm ngôn ngữ.",
    "hreflang_missing_href": "Mỗi thẻ hreflang phải có href tuyệt đối hợp lệ.",
    "images_broken_src": "Sửa src ảnh trống/javascript:/# — dùng URL tĩnh hoặc bỏ thẻ img hỏng.",
    "title_too_short": "Title nên đủ mô tả (thường ≥ 20–30 ký tự) và chứa chủ đề trang.",
    "meta_description_too_long": "Rút meta description khoảng 120–160 ký tự để tránh cắt snippet.",
}


def _url_key(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        return normalize_url_safe(raw).strip().lower().rstrip("/")
    except Exception:
        return raw.lower().rstrip("/")


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def is_valid_hreflang_code(code: str) -> bool:
    return bool(_HREFLANG_CODE.match((code or "").strip()))


def internal_redirect_is_material(start_url: str, chain: list[Any] | None) -> bool:
    """True when an internal href actually lands on a different URL (not slash/www-only)."""
    urls = [str(u).strip() for u in (chain or []) if u and str(u).strip()]
    if redirect_loop_slice(urls):
        return False
    hops = redirect_hops(urls)
    if hops < 1:
        return False
    start_k = _url_key(start_url or (urls[0] if urls else ""))
    final_k = _url_key(urls[-1] if urls else "")
    if not start_k or not final_k:
        return False
    return start_k != final_k


def _wrap(issue: dict[str, Any]) -> dict[str, Any] | None:
    itype = str(issue.get("type") or "")
    if not (issue.get("remediation") or "").strip() and _REMEDIATION.get(itype):
        issue["remediation"] = _REMEDIATION[itype]
    return ensure_crawl_index_contract(issue)


def build_duplicate_content_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Site-level duplicate title / H1 / meta — chỉ khi ≥2 URL 200 cùng text thật."""
    titles: dict[str, list[str]] = defaultdict(list)
    h1s: dict[str, list[str]] = defaultdict(list)
    metas: dict[str, list[str]] = defaultdict(list)
    title_raw: dict[str, str] = {}
    h1_raw: dict[str, str] = {}
    meta_raw: dict[str, str] = {}

    for row in rows:
        if int(row.get("status") or 0) != 200:
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        title = str(row.get("title") or "").strip()
        tn = _norm_text(title)
        if tn and len(tn) >= MIN_DUPLICATE_TEXT_LEN:
            titles[tn].append(url)
            title_raw.setdefault(tn, title)
        h1_list = row.get("h1s") or row.get("h1") or []
        if isinstance(h1_list, str):
            h1_list = [h1_list]
        primary_h1 = ""
        if isinstance(h1_list, list) and h1_list:
            primary_h1 = str(h1_list[0] or "").strip()
        hn = _norm_text(primary_h1)
        if hn and len(hn) >= MIN_DUPLICATE_TEXT_LEN:
            h1s[hn].append(url)
            h1_raw.setdefault(hn, primary_h1)
        meta = str(row.get("meta_description") or "").strip()
        mn = _norm_text(meta)
        if mn and len(mn) >= 12:
            metas[mn].append(url)
            meta_raw.setdefault(mn, meta)

    out: list[dict[str, Any]] = []

    def _cluster_issue(itype: str, key: str, urls: list[str], sample: str, message: str) -> None:
        uniq = list(dict.fromkeys(u for u in urls if u))
        if len(uniq) < 2:
            return
        issue = {
            "type": itype,
            "severity": "medium",
            "message": message,
            "url": uniq[0],
            "affected_urls": uniq[:30],
            "confidence": 0.86 if len(uniq) >= 3 else 0.78,
            "evidence": [
                {"kind": "url", "url": uniq[0]},
                {"kind": "duplicate_urls", "urls": uniq[:12]},
                {"kind": "duplicate_count", "value": len(uniq)},
                {"kind": "sample_text", "value": sample[:180]},
            ],
            "source": "crawl",
            "detected_from": [f"parsed.{itype}"],
            "checklist_group": "Onpage",
            "remediation": _REMEDIATION[itype],
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)

    for key, urls in titles.items():
        sample = title_raw.get(key, key)
        _cluster_issue(
            "duplicate_title",
            key,
            urls,
            sample,
            f"Trùng thẻ Title trên {len(dict.fromkeys(urls))} URL: {sample[:80]}",
        )
    for key, urls in h1s.items():
        sample = h1_raw.get(key, key)
        _cluster_issue(
            "duplicate_h1",
            key,
            urls,
            sample,
            f"Trùng H1 trên {len(dict.fromkeys(urls))} URL: {sample[:80]}",
        )
    for key, urls in metas.items():
        sample = meta_raw.get(key, key)
        _cluster_issue(
            "duplicate_meta_description",
            key,
            urls,
            sample,
            f"Trùng meta description trên {len(dict.fromkeys(urls))} URL.",
        )
    return out


def build_graph_link_issues(
    pages: list[dict[str, Any]],
    *,
    entry_urls: list[str] | None = None,
    min_pages_orphan: int = MIN_PAGES_FOR_ORPHAN,
    min_pages_depth: int = MIN_PAGES_FOR_DEPTH,
    deep_depth: int = DEEP_CRAWL_DEPTH,
) -> list[dict[str, Any]]:
    """Orphan + crawl depth — chỉ khi graph đủ trang và có cạnh nội bộ thật."""
    crawled = [p for p in pages if str(p.get("url") or "").strip()]
    n = len(crawled)
    if n < min_pages_orphan:
        return []
    graph = build_link_graph(crawled, entry_urls=entry_urls)
    nodes = dict(graph.get("nodes") or {})
    edge_count = sum(len(v.get("outgoing") or []) for v in nodes.values())
    if edge_count < 1:
        return []

    status_by_key: dict[str, int] = {}
    url_by_key: dict[str, str] = {}
    for p in crawled:
        u = str(p.get("url") or "")
        k = _url_key(u)
        if not k:
            continue
        status_by_key[k] = int(p.get("status") or 0)
        url_by_key[k] = u

    out: list[dict[str, Any]] = []
    orphans = [str(u) for u in (graph.get("orphan_urls") or []) if u]
    for u in orphans:
        k = _url_key(u)
        if status_by_key.get(k) != 200:
            continue
        display = url_by_key.get(k, u)
        node = nodes.get(u) or nodes.get(display) or {}
        incoming = list(node.get("incoming") or [])
        if incoming:
            continue
        issue = {
            "type": "orphan_page",
            "severity": "medium",
            "message": f"Trang không nhận internal link từ URL khác trong crawl (orphan): {display}",
            "url": display,
            "affected_urls": [display],
            "confidence": 0.8 if n >= 6 else 0.68,
            "evidence": [
                {"kind": "url", "url": display},
                {"kind": "in_degree", "value": 0},
                {"kind": "crawled_page_count", "value": n},
                {"kind": "graph_edge_count", "value": edge_count},
            ],
            "source": "crawl",
            "detected_from": ["internal_link_graph", "in_degree"],
            "checklist_group": "GSC",
            "remediation": _REMEDIATION["orphan_page"],
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)

    if n < min_pages_depth:
        return out
    depth_map = dict(graph.get("crawl_depth") or {})
    for raw_u, depth in depth_map.items():
        if depth is None:
            continue
        try:
            d = int(depth)
        except (TypeError, ValueError):
            continue
        if d < deep_depth:
            continue
        k = _url_key(str(raw_u))
        if status_by_key.get(k) != 200:
            continue
        display = url_by_key.get(k, str(raw_u))
        node = nodes.get(raw_u) or {}
        in_deg = len(node.get("incoming") or [])
        if in_deg < 1:
            continue
        issue = {
            "type": "crawl_depth_deep",
            "severity": "low",
            "message": f"URL nằm sâu trong site (crawl depth={d} từ trang vào): {display}",
            "url": display,
            "affected_urls": [display],
            "confidence": 0.74,
            "evidence": [
                {"kind": "url", "url": display},
                {"kind": "crawl_depth", "value": d},
                {"kind": "in_degree", "value": in_deg},
                {"kind": "crawled_page_count", "value": n},
            ],
            "source": "crawl",
            "detected_from": ["internal_link_graph", "crawl_depth"],
            "checklist_group": "GSC",
            "remediation": _REMEDIATION["crawl_depth_deep"],
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)
    return out


def build_internal_redirect_issue(result: dict[str, Any]) -> dict[str, Any] | None:
    """Single-hop (or short) internal href that 3xx tới URL khác — không phải chain/loop."""
    u = str(result.get("url") or "").strip()
    chain = list(result.get("chain") or [])
    if not u or not internal_redirect_is_material(u, chain):
        return None
    hops = redirect_hops(chain)
    if hops >= 2:
        return None
    status = int(result.get("status") or 0)
    issue = {
        "type": "internal_link_redirect",
        "severity": "medium",
        "message": f"Liên kết nội bộ đi qua redirect ({hops} bước) tới URL khác: {u}",
        "url": u,
        "affected_urls": [u],
        "confidence": 0.84,
        "evidence": [
            {"kind": "url", "url": u},
            {"kind": "redirect_chain", "value": chain[:8]},
            {"kind": "hops", "value": hops},
            {"kind": "http_status", "value": status},
        ],
        "source": "crawl",
        "detected_from": ["internal_link_check", "redirect"],
        "checklist_group": "GSC",
        "error_kind": "redirect",
        "remediation": _REMEDIATION["internal_link_redirect"],
    }
    return _wrap(issue)


def evaluate_hreflang_page(url: str, parsed: dict[str, Any], status: int) -> list[dict[str, Any]]:
    """Chỉ báo khi trang đã khai hreflang — không đoán site thiếu đa ngữ."""
    if int(status or 0) != 200:
        return []
    tags = list(parsed.get("hreflang") or [])
    if not tags:
        return []
    page_k = _url_key(url)
    out: list[dict[str, Any]] = []
    invalid = []
    missing_href = []
    self_hit = False
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        code = str(tag.get("hreflang") or "").strip()
        href = str(tag.get("href") or "").strip()
        if not href:
            missing_href.append(code or "(empty)")
        if code and not is_valid_hreflang_code(code):
            invalid.append(code)
        if href and _url_key(href) == page_k:
            self_hit = True

    def _emit(itype: str, message: str, extra: list[dict[str, Any]], conf: float) -> None:
        issue = {
            "type": itype,
            "severity": "medium",
            "message": message,
            "url": url,
            "affected_urls": [url],
            "confidence": conf,
            "evidence": [
                {"kind": "url", "url": url},
                {"kind": "hreflang_tags", "value": tags[:12]},
                *extra,
            ],
            "source": "crawl",
            "detected_from": ["parsed.hreflang"],
            "checklist_group": "International",
            "remediation": _REMEDIATION[itype],
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)

    if invalid:
        _emit(
            "hreflang_invalid_code",
            f"hreflang không hợp lệ trên {url}: {', '.join(invalid[:6])}",
            [{"kind": "invalid_codes", "value": invalid[:8]}],
            0.88,
        )
    if missing_href:
        _emit(
            "hreflang_missing_href",
            f"Thẻ hreflang thiếu href trên {url}",
            [{"kind": "missing_href_codes", "value": missing_href[:8]}],
            0.9,
        )
    if len(tags) >= 1 and not self_hit:
        _emit(
            "hreflang_missing_self",
            f"Cụm hreflang không có bản tự trỏ (self) cho {url}",
            [{"kind": "self_hreflang", "value": False}],
            0.8,
        )
    return out


def _rank(issue: dict[str, Any]) -> tuple[int, float]:
    sev = str(issue.get("severity") or "").lower()
    sev_n = {"critical": 4, "high": 3, "medium": 2, "warning": 2, "low": 1}.get(sev, 0)
    try:
        conf = float(issue.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return sev_n, conf


def dedupe_technical_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gộp (type, URL); bỏ type yếu khi type mạnh hơn đã có cùng URL."""
    normalized: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict) or raw.get("suppressed"):
            continue
        row = dict(raw)
        itype = str(row.get("type") or row.get("rule_id") or "")
        alias = _TYPE_ALIASES.get(itype)
        if alias:
            row["type"] = alias
            itype = alias
        if not itype:
            continue
        normalized.append(row)

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    cluster_keys: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []

    cluster_types = {"duplicate_title", "duplicate_h1", "duplicate_meta_description"}
    for row in normalized:
        itype = str(row.get("type") or "")
        if itype in cluster_types:
            urls = tuple(
                sorted(
                    {
                        _url_key(u)
                        for u in (row.get("affected_urls") or [row.get("url")])
                        if u and str(u).strip()
                    }
                )
            )
            key = (itype, urls)
            prev = cluster_keys.get(key)
            if prev is None or _rank(row) > _rank(prev):
                cluster_keys[key] = row
            continue
        ukey = _url_key(str(row.get("url") or ""))
        if not ukey:
            affected = [str(u) for u in (row.get("affected_urls") or []) if u]
            if len(affected) > 1:
                passthrough.append(row)
                continue
            ukey = _url_key(affected[0]) if affected else ""
        if not ukey:
            passthrough.append(row)
            continue
        key2 = (itype, ukey)
        prev = by_key.get(key2)
        if prev is None or _rank(row) > _rank(prev):
            by_key[key2] = row

    present: dict[str, set[str]] = defaultdict(set)
    for (itype, ukey), row in by_key.items():
        present[ukey].add(itype)

    kept_url: list[dict[str, Any]] = []
    for (itype, ukey), row in by_key.items():
        stronger = _WEAKER_THAN.get(itype) or ()
        if any(s in present.get(ukey, set()) for s in stronger):
            continue
        kept_url.append(row)

    return [*cluster_keys.values(), *kept_url, *passthrough]
