"""
Indexability & Crawlability cross-check rules for Technical Analysis.

Site-level checks (sitemap ↔ robots ↔ crawl) with evidence required before emitting issues.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from app.services.crawler import classify_http_status, robots_url_blocked
from app.services.seo_normalize import normalize_url_safe

MAX_SITEMAP_CROSS_CHECKS = 80
MAX_SITEMAP_STATUS_PROBES = 40

# Chỉ coi Disallow: / là chặn Google khi rule thuộc * hoặc họ Googlebot.
_GOOGLE_CRAWLER_AGENTS = frozenset(
    {
        "*",
        "googlebot",
        "googlebot-image",
        "googlebot-news",
        "googlebot-video",
        "googlebot-mobile",
        "storebot-google",
        "google-inspectiontool",
        "googleother",
    }
)


def parse_robots_agent_groups(body: str) -> list[dict[str, Any]]:
    """Parse robots.txt thành nhóm User-agent + Allow/Disallow (không gộp mọi Disallow mọi bot)."""
    groups: list[dict[str, Any]] = []
    agents: list[str] = []
    disallows: list[str] = []
    allows: list[str] = []
    saw_rule = False

    def _flush() -> None:
        nonlocal agents, disallows, allows, saw_rule
        if agents:
            groups.append(
                {
                    "agents": [a for a in agents if a],
                    "disallow": list(disallows),
                    "allow": list(allows),
                }
            )
        agents = []
        disallows = []
        allows = []
        saw_rule = False

    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if line == "":
                _flush()
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        lower = line.lower()
        if lower.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            if saw_rule:
                _flush()
            agents.append(agent)
            continue
        if lower.startswith("disallow:"):
            saw_rule = True
            disallows.append(line.split(":", 1)[1].strip())
            continue
        if lower.startswith("allow:"):
            saw_rule = True
            allows.append(line.split(":", 1)[1].strip())
            continue
        if lower.startswith("sitemap:"):
            continue
    _flush()
    return groups


def googlebot_disallow_all_agents(body: str) -> list[str]:
    """User-agent * / Googlebot có Disallow đúng ``/`` (chặn toàn site với Google)."""
    hit: list[str] = []
    for group in parse_robots_agent_groups(body):
        agents = [str(a or "").strip() for a in (group.get("agents") or [])]
        agents_l = {a.lower() for a in agents if a}
        if not (agents_l & _GOOGLE_CRAWLER_AGENTS):
            continue
        if any((d or "").strip() == "/" for d in (group.get("disallow") or [])):
            hit.extend(a for a in agents if a)
    return hit


def _norm_url_key(url: str) -> str:
    try:
        return normalize_url_safe(url).strip().lower().rstrip("/")
    except Exception:
        return (url or "").strip().lower().rstrip("/")


def _url_variants(url: str) -> set[str]:
    base = _norm_url_key(url)
    if not base:
        return set()
    out = {base}
    if base.endswith("/"):
        out.add(base.rstrip("/"))
    else:
        out.add(base + "/")
    return out


def _pages_lookup(pages_by_url: dict[str, dict]) -> dict[str, dict]:
    """Map normalized URL variants → page record."""
    out: dict[str, dict] = {}
    for raw_url, page in pages_by_url.items():
        for variant in _url_variants(raw_url):
            out.setdefault(variant, page)
    return out


def _has_noindex_signal(indexability: dict[str, Any]) -> tuple[bool, str]:
    meta = str(indexability.get("meta_robots_text") or "").lower()
    xr = str(indexability.get("x_robots_tag") or "").lower()
    if "noindex" in meta or "none" in meta:
        return True, "meta_robots"
    if "noindex" in xr or "none" in xr:
        return True, "x_robots_tag"
    reason = str(indexability.get("indexability_reason") or "").lower()
    if indexability.get("indexable") is False and ("noindex" in reason or "none" in reason):
        return True, "indexability_reason"
    return False, ""


def _canonical_differs_from_page(canonical_resolution: dict[str, Any], page_url: str) -> tuple[bool, str, str]:
    canonical = str(canonical_resolution.get("canonical_url") or "").strip()
    final = str(canonical_resolution.get("final_effective_url") or page_url).strip()
    if not canonical:
        return False, "", ""
    if _norm_url_key(canonical) == _norm_url_key(final):
        return False, "", ""
    return True, canonical, final


def _scheme_mismatch(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    if (pa.hostname or "").lower().replace("www.", "") != (pb.hostname or "").lower().replace("www.", ""):
        return False
    if pa.path.rstrip("/") != pb.path.rstrip("/"):
        return False
    return pa.scheme.lower() != pb.scheme.lower()


def _trailing_slash_mismatch(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    if pa.scheme.lower() != pb.scheme.lower():
        return False
    if (pa.hostname or "").lower() != (pb.hostname or "").lower():
        return False
    return pa.path.rstrip("/") == pb.path.rstrip("/") and pa.path != pb.path


def build_sitemap_indexability_issues(
    *,
    sitemap: dict[str, Any],
    pages: list[dict[str, Any]],
    robots: dict[str, Any],
    check_url_status: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Cross-check sitemap URLs vs crawl indexability, canonical, robots block.
    Returns raw issue dicts ready for _tech_issue() wrapping in analyzer.
    """
    sitemap_urls = [str(u).strip() for u in (sitemap.get("urls") or []) if str(u).strip()]
    if not sitemap_urls:
        return []

    pages_by_url = {str(p.get("url") or ""): p for p in pages if p.get("url")}
    lookup = _pages_lookup(pages_by_url)
    robots_body = str(robots.get("body_preview") or "")
    robots_status = int(robots.get("status") or 0)

    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _emit(issue_type: str, url: str, payload: dict[str, Any]) -> None:
        key = f"{issue_type}|{_norm_url_key(url)}"
        if key in seen:
            return
        seen.add(key)
        issues.append({"type": issue_type, "url": url, **payload})

    checked = 0
    for loc in sitemap_urls:
        if checked >= MAX_SITEMAP_CROSS_CHECKS:
            break
        checked += 1
        variants = _url_variants(loc)
        page = next((lookup[v] for v in variants if v in lookup), None)

        if page:
            idx = dict(page.get("indexability") or {})
            noindex, signal = _has_noindex_signal(idx)
            if noindex:
                evidence = [
                    {"kind": "sitemap_loc", "url": loc},
                    {"kind": "indexability_signal", "value": signal},
                ]
                if idx.get("meta_robots_text"):
                    evidence.append({"kind": "meta_robots", "value": idx["meta_robots_text"]})
                if idx.get("x_robots_tag"):
                    evidence.append({"kind": "x_robots_tag", "value": idx["x_robots_tag"]})
                _emit(
                    "sitemap_contains_noindex",
                    loc,
                    {
                        "severity": "high",
                        "message": f"Sitemap chứa URL noindex — tín hiệu mâu thuẫn: {loc}",
                        "confidence": 0.92,
                        "evidence": evidence,
                        "source": "sitemap",
                        "detected_from": ["sitemap.loc", f"indexability.{signal}"],
                        "checklist_group": "Sitemap",
                    },
                )

            cr = dict(page.get("canonical_resolution") or {})
            differs, canonical, final = _canonical_differs_from_page(cr, loc)
            if differs:
                evidence = [
                    {"kind": "sitemap_loc", "url": loc},
                    {"kind": "canonical_url", "url": canonical},
                    {"kind": "final_effective_url", "url": final},
                ]
                issue_type = "sitemap_contains_canonicalized_url"
                if _scheme_mismatch(canonical, final):
                    issue_type = "sitemap_contains_canonical_scheme_mismatch"
                elif _trailing_slash_mismatch(canonical, final):
                    issue_type = "sitemap_contains_canonical_slash_mismatch"
                _emit(
                    issue_type,
                    loc,
                    {
                        "severity": "medium",
                        "message": (
                            f"Sitemap liệt kê URL nhưng canonical trỏ sang URL khác: {loc} → {canonical}"
                        ),
                        "confidence": 0.88,
                        "evidence": evidence,
                        "source": "sitemap",
                        "detected_from": ["sitemap.loc", "canonical_resolution.canonical_url"],
                        "checklist_group": "Sitemap",
                    },
                )

        blocked = robots_url_blocked(loc, robots_body, robots_status=robots_status)
        if blocked is True:
            evidence = [
                {"kind": "sitemap_loc", "url": loc},
                {"kind": "robots_blocked", "value": True},
                {"kind": "robots_txt", "url": robots.get("url")},
            ]
            _emit(
                "sitemap_contains_robots_blocked",
                loc,
                {
                    "severity": "high",
                    "message": f"URL trong sitemap bị robots.txt chặn (Disallow): {loc}",
                    "confidence": 0.9,
                    "evidence": evidence,
                    "source": "robots",
                    "detected_from": ["sitemap.loc", "robots.txt Disallow"],
                    "checklist_group": "Sitemap",
                },
            )

    # Probe sitemap URLs chưa crawl — phát hiện 3xx/4xx/5xx trong sitemap
    not_crawled = [u for u in sitemap_urls if not any(v in lookup for v in _url_variants(u))]
    probed = 0
    for loc in not_crawled:
        if probed >= MAX_SITEMAP_STATUS_PROBES:
            break
        probed += 1
        result = check_url_status(loc)
        status = int(result.get("status") or 0)
        if status == 200:
            continue
        if status == 0 and not result.get("error_kind"):
            continue
        kind = result.get("error_kind") or classify_http_status(status) or "client_error"
        evidence = [
            {"kind": "sitemap_loc", "url": loc},
            {"kind": "http_status", "value": status},
            {"kind": "error_kind", "value": kind},
        ]
        if result.get("chain"):
            evidence.append({"kind": "redirect_chain", "value": result["chain"][:5]})
        sev = "high" if kind in ("server_error", "client_error", "forbidden") or status >= 400 else "medium"
        _emit(
            "sitemap_url_bad_status",
            loc,
            {
                "severity": sev,
                "message": f"Sitemap chứa URL trả HTTP {status} ({kind}): {loc}",
                "confidence": 0.86 if status else 0.72,
                "evidence": evidence,
                "source": "sitemap",
                "detected_from": ["sitemap.loc", "http_status"],
                "checklist_group": "Sitemap",
                "error_kind": kind,
            },
        )

    return issues


def internal_link_issue_type(result: dict[str, Any]) -> tuple[str, str]:
    """Map link check result → (issue_type, severity)."""
    status = int(result.get("status") or 0)
    kind = str(result.get("error_kind") or "")
    if kind == "redirect_loop":
        return "redirect_loop", "high"
    # 404/410 — luôn broken_internal_link, không gộp vào DNS/SSL/timeout/403/5xx
    if status in (404, 410):
        return "broken_internal_link", "high"
    mapping: dict[str, tuple[str, str]] = {
        "dns_error": ("internal_link_dns_error", "high"),
        "ssl_error": ("internal_link_ssl_error", "high"),
        "timeout": ("internal_link_timeout", "high"),
        "connection_error": ("internal_link_connection_error", "medium"),
        "forbidden": ("internal_link_forbidden", "high"),
        "unauthorized": ("internal_link_forbidden", "high"),
        "server_error": ("internal_link_server_error", "high"),
        "request_failed": ("internal_link_connection_error", "medium"),
    }
    if kind in mapping:
        return mapping[kind]
    if status >= 500:
        return "internal_link_server_error", "high"
    if status == 403:
        return "internal_link_forbidden", "high"
    if status >= 400:
        return "broken_internal_http_error", "high"
    return "broken_internal_http_error", "high"


def internal_link_issue_message(result: dict[str, Any]) -> str:
    """Human-readable message — phân biệt rõ 404/410 vs lỗi kết nối."""
    u = str(result.get("url") or "")
    status = int(result.get("status") or 0)
    kind = str(result.get("error_kind") or "")
    if status == 404:
        return f"Liên kết nội bộ trả 404 Not Found: {u}"
    if status == 410:
        return f"Liên kết nội bộ trả 410 Gone: {u}"
    if kind == "redirect_loop":
        return f"Liên kết nội bộ tạo vòng redirect (loop): {u}"
    if kind == "dns_error":
        return f"Liên kết nội bộ — lỗi DNS (không resolve host): {u}"
    if kind == "ssl_error":
        return f"Liên kết nội bộ — lỗi SSL/TLS: {u}"
    if kind == "timeout":
        return f"Liên kết nội bộ — timeout: {u}"
    if kind in ("forbidden", "unauthorized") or status == 403:
        return f"Liên kết nội bộ — HTTP 403 Forbidden/blocked: {u}"
    if kind == "server_error" or status >= 500:
        return f"Liên kết nội bộ — lỗi server HTTP {status}: {u}"
    if status >= 400:
        return f"Liên kết nội bộ lỗi HTTP {status}: {u}"
    if kind:
        return f"Liên kết nội bộ lỗi ({kind}): {u}"
    return f"Liên kết nội bộ không truy cập được: {u}"


def sitemap_missing_issue_type(sitemap: dict[str, Any]) -> tuple[str, str]:
    """sitemap_not_found (404) hoặc sitemap_unreachable (các lỗi khác)."""
    last_err = sitemap.get("last_error") or {}
    http_st = int(last_err.get("http_status") or 0)
    if http_st == 404:
        return (
            "sitemap_not_found",
            "Không tìm thấy sitemap.xml / sitemap_index (HTTP 404 — Sitemap / Technical-SEO.txt).",
        )
    return (
        "sitemap_unreachable",
        "sitemap.xml / sitemap_index không tồn tại hoặc không truy cập được (Sitemap / Technical-SEO.txt).",
    )


def robots_fetch_issue_type(robots: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (issue_type, severity, message_suffix) for robots.txt fetch failures."""
    status = int(robots.get("status") or 0)
    if status == 200:
        return None
    kind = str(robots.get("error_kind") or "")
    if kind == "dns_error":
        return "robots_dns_error", "high", "lỗi DNS"
    if kind == "ssl_error":
        return "robots_ssl_error", "high", "lỗi SSL/TLS"
    if kind == "timeout":
        return "robots_timeout", "high", "timeout"
    if status == 403:
        return "robots_forbidden", "high", "HTTP 403 Forbidden"
    if status >= 500:
        return "robots_server_error", "high", f"HTTP {status}"
    return "robots_unreachable", "high", "không truy cập được"


_WEAK_EVIDENCE_KINDS = frozenset({"description", "remediation_hint"})

_CRAWL_INDEX_REMEDIATION: dict[str, str] = {
    "crawl_http_3xx": "Rút gọn redirect: trỏ link nội bộ thẳng tới URL 200 cuối; chỉ giữ một bước 301 khi đổi URL.",
    "crawl_http_4xx": "Sửa hoặc gỡ URL 4xx: trả 200 nếu trang còn sống, 301 về URL mới, hoặc 410 nếu đã gỡ hẳn.",
    "crawl_http_5xx": "Sửa lỗi máy chủ (5xx): xem log, WAF, PHP/Node; URL quan trọng không được 502/503 với Googlebot.",
    "crawl_timeout": "Tăng timeout origin, giảm TTFB, kiểm tra DNS/firewall chặn crawler; thử lại URL bằng curl -I.",
    "crawl_connection_error": "Kiểm tra DNS, SSL, firewall; URL phải resolve và chấp nhận HTTPS từ crawler.",
    "crawl_page_non_200": "Đảm bảo URL crawl trả 200 kèm HTML; sửa redirect hoặc rule chặn bot.",
    "redirect_loop": "Phá vòng redirect: mỗi URL chỉ 301 một chiều tới bản canonical, không trỏ ngược lại.",
    "redirect_chain": "Trỏ link nội bộ thẳng tới URL cuối; rút chuỗi redirect còn tối đa một bước.",
    "crawled_url_robots_blocked": "Gỡ Disallow cho URL cần index, hoặc bỏ URL khỏi sitemap và noindex nếu cố ý chặn.",
    "soft_404_heuristic": "Nếu trang không tồn tại, trả 404/410 thật; nếu cần index, bỏ thông điệp 'not found' và bổ sung nội dung.",
    "meta_robots_noindex": "Gỡ noindex/none khỏi meta robots nếu URL cần index; giữ noindex cho staging/tham số trùng.",
    "x_robots_tag_noindex": "Gỡ noindex khỏi header X-Robots-Tag trên response 200; đồng bộ với meta robots.",
    "canonical_missing_high_value": "Thêm <link rel=\"canonical\" href=\"URL ưu tiên\"> tuyệt đối cho trang quan trọng.",
    "canonical_points_to_bad_status": "Sửa canonical về URL trả 200 indexable; không trỏ tới 3xx/4xx/5xx.",
    "canonical_points_to_non_indexable": "Canonical chỉ trỏ URL indexable (không noindex, không robots Disallow).",
    "canonical_self_mismatch": "Chuẩn hóa canonical khớp URL hiệu dụng sau redirect (thường self-canonical).",
    "canonical_cross_host": "Nếu đây là bản chính, canonical về cùng host; kiểm tra syndication/property GSC.",
    "canonical_scheme_mismatch": "Canonical dùng đúng scheme (https) khớp URL sau redirect.",
}


def evidence_is_technical(evidence: list[Any] | None) -> bool:
    """Bằng chứng kỹ thuật — không tính mô tả/cách sửa/URL định danh suông."""
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind in _WEAK_EVIDENCE_KINDS or kind == "url":
            continue
        if item.get("urls") or item.get("domain"):
            return True
        if item.get("url") and kind != "url":
            return True
        if item.get("value") is not None or (item.get("text") or "").strip():
            return True
    return False


def issue_has_required_fields(issue: dict[str, Any] | None) -> bool:
    """Issue crawl/index chỉ publish khi có severity, confidence, evidence, URL (hoặc domain), cách sửa."""
    if not isinstance(issue, dict):
        return False
    if issue.get("suppressed"):
        return False
    sev = str(issue.get("severity") or "").strip().lower()
    if sev not in ("high", "medium", "low", "critical", "warning"):
        return False
    try:
        conf = float(issue.get("confidence"))
    except (TypeError, ValueError):
        return False
    if conf <= 0:
        return False
    evidence = issue.get("evidence") or []
    if not evidence_is_technical(evidence):
        return False
    urls = [u for u in (issue.get("affected_urls") or []) if u and str(u).strip()]
    url = str(issue.get("url") or "").strip()
    if url:
        urls.append(url)
    has_domain = any(isinstance(e, dict) and e.get("domain") for e in evidence)
    if not urls and not has_domain:
        return False
    how = issue.get("how_to_fix")
    if isinstance(how, list):
        fix = " ".join(str(x) for x in how if x).strip()
    else:
        fix = str(how or "").strip()
    fix = (
        str(issue.get("remediation") or "").strip()
        or str(issue.get("suggested_fix") or "").strip()
        or fix
    )
    if not fix:
        itype = str(issue.get("type") or issue.get("rule_id") or "")
        fix = _CRAWL_INDEX_REMEDIATION.get(itype, "")
    return bool(fix)


def keep_evidenced_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lọc issue thiếu bằng chứng — không đưa vào score / API."""
    out: list[dict[str, Any]] = []
    for raw in issues:
        kept = ensure_crawl_index_contract(raw) if isinstance(raw, dict) else None
        if kept:
            out.append(kept)
    return out


def ensure_crawl_index_contract(issue: dict[str, Any]) -> dict[str, Any] | None:
    """Bổ sung affected_urls + cách sửa mặc định; None nếu vẫn thiếu evidence."""
    if not isinstance(issue, dict):
        return None
    out = dict(issue)
    url = str(out.get("url") or "").strip()
    affected = [str(u).strip() for u in (out.get("affected_urls") or []) if u and str(u).strip()]
    if url and url not in affected:
        affected = [url] + affected
    out["affected_urls"] = affected
    itype = str(out.get("type") or out.get("rule_id") or "")
    if not (out.get("remediation") or "").strip():
        how = out.get("how_to_fix")
        if isinstance(how, list) and how:
            out["remediation"] = "\n".join(str(x) for x in how if x)
        elif isinstance(how, str) and how.strip():
            out["remediation"] = how.strip()
        elif _CRAWL_INDEX_REMEDIATION.get(itype):
            out["remediation"] = _CRAWL_INDEX_REMEDIATION[itype]
    if out.get("confidence") is None:
        out["confidence"] = 0.72
    if not out.get("evidence"):
        return None
    return out if issue_has_required_fields(out) else None


def redirect_loop_slice(chain: list[Any] | None) -> list[str] | None:
    """Nếu chain lặp URL (loop), trả đoạn vòng; không thì None."""
    urls = [str(u).strip() for u in (chain or []) if u and str(u).strip()]
    if len(urls) < 2:
        return None
    seen: dict[str, int] = {}
    for i, u in enumerate(urls):
        key = _norm_url_key(u)
        if not key:
            continue
        if key in seen:
            return urls[seen[key] : i + 1]
        seen[key] = i
    return None


def redirect_hops(chain: list[Any] | None) -> int:
    urls = [str(u).strip() for u in (chain or []) if u and str(u).strip()]
    return max(0, len(urls) - 1)


def classify_http_issue_type(status: int, error_kind: str | None = None) -> tuple[str, str]:
    """(issue_type, severity) cho HTTP crawl / link check."""
    kind = str(error_kind or "")
    if kind == "redirect_loop":
        return "redirect_loop", "high"
    if kind == "timeout":
        return "crawl_timeout", "high"
    st = int(status or 0)
    if st == 0:
        if kind in ("dns_error", "ssl_error", "connection_error", "request_failed", "blocked"):
            return "crawl_connection_error", "high"
        return "crawl_timeout", "high"
    if 300 <= st < 400:
        return "crawl_http_3xx", "medium"
    if 400 <= st < 500:
        return "crawl_http_4xx", "high"
    if st >= 500:
        return "crawl_http_5xx", "high"
    return "crawl_page_non_200", "medium"


def build_crawled_url_robots_blocked_issues(
    *,
    pages: list[dict[str, Any]],
    robots: dict[str, Any],
) -> list[dict[str, Any]]:
    """URL đã crawl nhưng bị robots.txt Disallow với User-agent *."""
    body = str(robots.get("body_preview") or "")
    status = int(robots.get("status") or 0)
    robots_url = str(robots.get("url") or "")
    if status != 200 or not body.strip():
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        url = str(page.get("url") or "").strip()
        if not url:
            continue
        key = _norm_url_key(url)
        if key in seen:
            continue
        blocked = robots_url_blocked(url, body, robots_status=status)
        if blocked is not True:
            continue
        seen.add(key)
        issue = {
            "type": "crawled_url_robots_blocked",
            "severity": "high",
            "message": f"URL đã crawl nhưng robots.txt chặn Googlebot (Disallow): {url}",
            "url": url,
            "affected_urls": [url],
            "confidence": 0.9,
            "evidence": [
                {"kind": "url", "url": url},
                {"kind": "robots_blocked", "value": True},
                {"kind": "robots_txt", "url": robots_url},
            ],
            "source": "robots",
            "detected_from": ["crawler.url", "robots.txt Disallow"],
            "checklist_group": "Robots",
            "remediation": _CRAWL_INDEX_REMEDIATION["crawled_url_robots_blocked"],
        }
        kept = ensure_crawl_index_contract(issue)
        if kept:
            out.append(kept)
    return out
