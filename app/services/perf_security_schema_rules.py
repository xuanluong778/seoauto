"""
Performance (CWV), security (HTTPS/mixed/HSTS), schema, and mobile-basics
checks for Technical Analysis (/tool).

Core Web Vitals issues are emitted only when real field/lab metrics exist
(CrUX / page payload). Missing PSI/CrUX is not an issue.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.services.index_crawl_rules import ensure_crawl_index_contract
from app.services.schema_validator import extract_jsonld_from_html, validate_schemas

_LOG = logging.getLogger(__name__)

LCP_GOOD_MS = 2500
LCP_POOR_MS = 4000
INP_GOOD_MS = 200
INP_POOR_MS = 500
CLS_GOOD = 0.1
CLS_POOR = 0.25

_SKIP_HTTP_HOSTS = frozenset(
    {
        "schema.org",
        "www.schema.org",
        "www.w3.org",
        "w3.org",
        "ogp.me",
        "www.ogp.me",
    }
)

_REMEDIATION: dict[str, str] = {
    "cwv_lcp_poor": "Giảm LCP: tối ưu ảnh hero (AVIF/WebP), preload, TTFB, tránh lazy-load LCP image.",
    "cwv_inp_poor": "Giảm INP: tách JS dài, giảm listener nặng, trì hoãn script không cần thiết.",
    "cwv_cls_poor": "Giảm CLS: luôn set width/height ảnh, reserve slot ads/font, tránh inject DOM muộn.",
    "mixed_content": "Đổi URL tài nguyên http:// sang https:// (hoặc protocol-relative) trên trang HTTPS.",
    "http_internal_links": "Sửa href nội bộ sang https:// cùng host; 301 HTTP→HTTPS nếu còn URL cũ.",
    "missing_hsts": "Thêm header Strict-Transport-Security (ví dụ max-age=31536000; includeSubDomains).",
    "jsonld_parse_error": "Sửa JSON-LD cho parse được (dấu phẩy, quotes). Kiểm tra Rich Results Test.",
    "schema_missing_type": "Thêm @type hợp lệ (Article, Product, FAQPage, Organization, …).",
    "schema_missing_required_field": "Bổ sung trường bắt buộc theo loại schema (headline, offers, mainEntity, …).",
    "missing_charset": "Khai báo <meta charset=\"utf-8\"> sớm trong <head>.",
    "viewport_no_scale": "Bỏ user-scalable=no / maximum-scale=1 cứng — cho phép zoom trên mobile.",
}


def _url_host_key(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _header_get(headers: dict[str, Any] | None, name: str) -> str:
    if not isinstance(headers, dict):
        return ""
    want = name.lower()
    for k, v in headers.items():
        if str(k).lower() == want:
            return str(v or "").strip()
    return ""


def _wrap(issue: dict[str, Any]) -> dict[str, Any] | None:
    itype = str(issue.get("type") or "")
    if not (issue.get("remediation") or "").strip() and _REMEDIATION.get(itype):
        issue["remediation"] = _REMEDIATION[itype]
    issue.setdefault("source", "crawl")
    return ensure_crawl_index_contract(issue)


def _cwv_tier(value: float, good: float, poor: float) -> str | None:
    if value <= good:
        return None
    if value <= poor:
        return "needs_improvement"
    return "poor"


def build_cwv_issues_from_metrics(
    *,
    url: str,
    lcp_ms: float | None = None,
    inp_ms: float | None = None,
    cls: float | None = None,
    source: str = "crux",
    form_factor: str = "",
) -> list[dict[str, Any]]:
    """Emit LCP/INP/CLS issues only when numeric field/lab values are present."""
    out: list[dict[str, Any]] = []
    page = str(url or "").strip()
    if not page:
        return out

    def _emit(itype: str, metric: str, value: float, unit: str, tier: str, good: float, poor: float) -> None:
        sev = "high" if tier == "poor" else "medium"
        issue = {
            "type": itype,
            "severity": sev,
            "message": f"{metric} {tier.replace('_', ' ')}: {value}{unit} (ngưỡng tốt ≤ {good}{unit}) — {page}",
            "url": page,
            "affected_urls": [page],
            "confidence": 0.9 if source == "crux" else 0.82,
            "evidence": [
                {"kind": "url", "url": page},
                {"kind": "cwv_metric", "value": metric},
                {"kind": "cwv_p75", "value": value},
                {"kind": "cwv_tier", "value": tier},
                {"kind": "cwv_good_threshold", "value": good},
                {"kind": "cwv_poor_threshold", "value": poor},
                *([{"kind": "form_factor", "value": form_factor}] if form_factor else []),
            ],
            "source": source,
            "detected_from": [f"{source}.{metric}"],
            "checklist_group": "Speed",
            "remediation": _REMEDIATION[itype],
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)

    if lcp_ms is not None:
        tier = _cwv_tier(float(lcp_ms), LCP_GOOD_MS, LCP_POOR_MS)
        if tier:
            _emit("cwv_lcp_poor", "LCP", float(lcp_ms), "ms", tier, LCP_GOOD_MS, LCP_POOR_MS)
    if inp_ms is not None:
        tier = _cwv_tier(float(inp_ms), INP_GOOD_MS, INP_POOR_MS)
        if tier:
            _emit("cwv_inp_poor", "INP", float(inp_ms), "ms", tier, INP_GOOD_MS, INP_POOR_MS)
    if cls is not None:
        tier = _cwv_tier(float(cls), CLS_GOOD, CLS_POOR)
        if tier:
            _emit("cwv_cls_poor", "CLS", float(cls), "", tier, CLS_GOOD, CLS_POOR)
    return out


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def metrics_from_page(page: dict[str, Any]) -> dict[str, float | None]:
    cwv = page.get("core_web_vitals") or page.get("crux") or page.get("pagespeed") or {}
    if not isinstance(cwv, dict):
        cwv = {}
    lcp = _num(page.get("lcp_ms") or cwv.get("lcp_ms") or cwv.get("lcp") or cwv.get("largest_contentful_paint"))
    inp = _num(page.get("inp_ms") or cwv.get("inp_ms") or cwv.get("inp") or cwv.get("interaction_to_next_paint"))
    cls = _num(page.get("cls") or cwv.get("cls") or cwv.get("cumulative_layout_shift"))
    return {"lcp_ms": lcp, "inp_ms": inp, "cls": cls}


def parse_crux_record(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize CrUX queryRecord JSON → origin + p75 LCP/INP/CLS."""
    if not isinstance(payload, dict):
        return None
    rec = payload.get("record") or payload
    metrics = rec.get("metrics") if isinstance(rec, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        return None
    key = rec.get("key") if isinstance(rec, dict) else {}
    origin = str((key or {}).get("origin") or payload.get("origin") or "").strip()

    def p75(name: str) -> float | None:
        block = metrics.get(name) or {}
        pct = block.get("percentiles") or {}
        return _num(pct.get("p75"))

    lcp = p75("largest_contentful_paint")
    inp = p75("interaction_to_next_paint")
    cls = p75("cumulative_layout_shift")
    if lcp is None and inp is None and cls is None:
        return None
    return {
        "origin": origin,
        "lcp_ms": lcp,
        "inp_ms": inp,
        "cls": cls,
        "form_factor": str((key or {}).get("formFactor") or ""),
    }


def fetch_crux_origin(origin: str, *, timeout: float = 8.0) -> dict[str, Any] | None:
    """CrUX origin query. Never raises — None when no key, 404, timeout, or error."""
    key = (
        (os.getenv("CRUX_API_KEY") or "").strip()
        or (os.getenv("PAGESPEED_API_KEY") or "").strip()
        or (os.getenv("GOOGLE_API_KEY") or "").strip()
        or (os.getenv("GOOGLE_CSE_API_KEY") or "").strip()
    )
    origin = (origin or "").strip().rstrip("/")
    if not key or not origin.startswith("http"):
        return None
    url = f"https://chromeuxreport.googleapis.com/v1/records:queryRecord?key={key}"
    try:
        resp = requests.post(url, json={"origin": origin, "formFactor": "PHONE"}, timeout=timeout)
        if resp.status_code != 200:
            _LOG.debug("CrUX skip status=%s origin=%s", resp.status_code, origin)
            return None
        return parse_crux_record(resp.json())
    except Exception as exc:
        _LOG.debug("CrUX fetch failed origin=%s: %s", origin, exc)
        return None


def _mixed_content_urls(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html if isinstance(html, str) else "", "html.parser")
    found: list[str] = []
    attrs = (
        ("img", "src"),
        ("script", "src"),
        ("iframe", "src"),
        ("source", "src"),
        ("video", "src"),
        ("audio", "src"),
        ("link", "href"),
        ("form", "action"),
    )
    for tag, attr in attrs:
        for el in soup.find_all(tag):
            raw = str(el.get(attr) or "").strip()
            if not raw.lower().startswith("http://"):
                continue
            host = _url_host_key(raw)
            if host in _SKIP_HTTP_HOSTS:
                continue
            found.append(raw)
            if len(found) >= 12:
                return found
    return found


def _http_internal_hrefs(html: str, page_url: str) -> list[str]:
    page_host = _url_host_key(page_url)
    if not page_host:
        return []
    soup = BeautifulSoup(html if isinstance(html, str) else "", "html.parser")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href.lower().startswith("http://"):
            continue
        if _url_host_key(href) != page_host:
            continue
        out.append(href)
        if len(out) >= 12:
            break
    return out


def _has_charset(html: str) -> bool:
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("meta", charset=True):
        return True
    equiv = soup.find("meta", attrs={"http-equiv": re.compile(r"content-type", re.I)})
    if equiv and "charset" in str(equiv.get("content") or "").lower():
        return True
    return False


def _viewport_blocks_zoom(viewport: str) -> bool:
    t = (viewport or "").lower()
    if not t:
        return False
    if "user-scalable=no" in t or "user-scalable=0" in t:
        return True
    m = re.search(r"maximum-scale\s*=\s*([0-9.]+)", t)
    if m:
        try:
            return float(m.group(1)) <= 1.0
        except ValueError:
            return False
    return False


def build_perf_security_schema_issues(
    pages: list[dict[str, Any]],
    *,
    start_url: str = "",
    crux: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    https_pages_with_headers = 0
    hsts_seen = False
    hsts_checked_url = ""

    for page in pages:
        url = str(page.get("url") or "").strip()
        if not url:
            continue
        status = int(page.get("status") or 0)
        html = page.get("html") if isinstance(page.get("html"), str) else ""
        scheme = (urlparse(url).scheme or "").lower()

        m = metrics_from_page(page)
        src = "pagespeed" if page.get("pagespeed") else ("crux" if page.get("crux") else "crawl")
        if m["lcp_ms"] is not None or m["inp_ms"] is not None or m["cls"] is not None:
            out.extend(
                build_cwv_issues_from_metrics(
                    url=url,
                    lcp_ms=m["lcp_ms"],
                    inp_ms=m["inp_ms"],
                    cls=m["cls"],
                    source=src if src in ("crux", "pagespeed") else "crux",
                )
            )

        if status == 200 and html.strip():
            if scheme == "https":
                mixed = _mixed_content_urls(html, url)
                if mixed:
                    issue = {
                        "type": "mixed_content",
                        "severity": "high",
                        "message": f"Trang HTTPS nạp {len(mixed)} tài nguyên HTTP (mixed content): {url}",
                        "url": url,
                        "affected_urls": [url],
                        "confidence": 0.92,
                        "evidence": [
                            {"kind": "url", "url": url},
                            {"kind": "mixed_content_urls", "urls": mixed[:8]},
                            {"kind": "mixed_content_count", "value": len(mixed)},
                        ],
                        "source": "crawl",
                        "detected_from": ["html.http_resources"],
                        "checklist_group": "Security",
                    }
                    kept = _wrap(issue)
                    if kept:
                        out.append(kept)

                http_hrefs = _http_internal_hrefs(html, url)
                if http_hrefs:
                    issue = {
                        "type": "http_internal_links",
                        "severity": "medium",
                        "message": f"Trang HTTPS chứa {len(http_hrefs)} internal link HTTP: {url}",
                        "url": url,
                        "affected_urls": [url, *http_hrefs[:8]],
                        "confidence": 0.9,
                        "evidence": [
                            {"kind": "url", "url": url},
                            {"kind": "http_internal_hrefs", "urls": http_hrefs[:8]},
                            {"kind": "http_internal_count", "value": len(http_hrefs)},
                        ],
                        "source": "crawl",
                        "detected_from": ["html.a[href=http]"],
                        "checklist_group": "Security",
                    }
                    kept = _wrap(issue)
                    if kept:
                        out.append(kept)

            if not _has_charset(html):
                issue = {
                    "type": "missing_charset",
                    "severity": "low",
                    "message": f"Thiếu meta charset trên {url}",
                    "url": url,
                    "affected_urls": [url],
                    "confidence": 0.88,
                    "evidence": [{"kind": "url", "url": url}, {"kind": "charset", "value": ""}],
                    "source": "crawl",
                    "detected_from": ["html.meta[charset]"],
                    "checklist_group": "Onpage",
                }
                kept = _wrap(issue)
                if kept:
                    out.append(kept)

            soup = BeautifulSoup(html, "html.parser")
            vp_el = soup.find("meta", attrs={"name": "viewport"})
            vp = str((vp_el.get("content") if vp_el else "") or "")
            if _viewport_blocks_zoom(vp):
                issue = {
                    "type": "viewport_no_scale",
                    "severity": "medium",
                    "message": f"Viewport chặn zoom (user-scalable/maximum-scale): {url}",
                    "url": url,
                    "affected_urls": [url],
                    "confidence": 0.9,
                    "evidence": [
                        {"kind": "url", "url": url},
                        {"kind": "viewport", "value": vp[:180]},
                    ],
                    "source": "crawl",
                    "detected_from": ["html.meta[viewport]"],
                    "checklist_group": "Onpage",
                }
                kept = _wrap(issue)
                if kept:
                    out.append(kept)

            nodes, parse_errs = extract_jsonld_from_html(html)
            if parse_errs:
                issue = {
                    "type": "jsonld_parse_error",
                    "severity": "high",
                    "message": f"JSON-LD không parse được trên {url}: {parse_errs[0]}",
                    "url": url,
                    "affected_urls": [url],
                    "confidence": 0.95,
                    "evidence": [
                        {"kind": "url", "url": url},
                        {"kind": "jsonld_parse_errors", "value": parse_errs[:6]},
                    ],
                    "source": "crawl",
                    "detected_from": ["script[type=application/ld+json]"],
                    "checklist_group": "Schema",
                }
                kept = _wrap(issue)
                if kept:
                    out.append(kept)
            elif nodes:
                result = validate_schemas(nodes)
                missing_type = [e for e in result["errors"] if "missing @type" in e]
                missing_req = [e for e in result["errors"] if "missing recommended field" in e or "mainEntity empty" in e]
                types = []
                for n in nodes:
                    t = n.get("@type")
                    if isinstance(t, list):
                        types.extend(str(x) for x in t)
                    elif t:
                        types.append(str(t))
                if missing_type:
                    issue = {
                        "type": "schema_missing_type",
                        "severity": "medium",
                        "message": f"JSON-LD thiếu @type trên {url}",
                        "url": url,
                        "affected_urls": [url],
                        "confidence": 0.9,
                        "evidence": [
                            {"kind": "url", "url": url},
                            {"kind": "schema_errors", "value": missing_type[:6]},
                            {"kind": "schema_types", "value": types[:8]},
                        ],
                        "source": "crawl",
                        "detected_from": ["jsonld.@type"],
                        "checklist_group": "Schema",
                    }
                    kept = _wrap(issue)
                    if kept:
                        out.append(kept)
                if missing_req:
                    issue = {
                        "type": "schema_missing_required_field",
                        "severity": "medium",
                        "message": f"Schema thiếu trường bắt buộc trên {url}: {missing_req[0]}",
                        "url": url,
                        "affected_urls": [url],
                        "confidence": 0.86,
                        "evidence": [
                            {"kind": "url", "url": url},
                            {"kind": "schema_errors", "value": missing_req[:8]},
                            {"kind": "schema_types", "value": types[:8]},
                        ],
                        "source": "crawl",
                        "detected_from": ["jsonld.required_fields"],
                        "checklist_group": "Schema",
                    }
                    kept = _wrap(issue)
                    if kept:
                        out.append(kept)

        headers = page.get("response_headers") or page.get("raw_response_headers") or {}
        if status == 200 and scheme == "https" and isinstance(headers, dict) and headers:
            https_pages_with_headers += 1
            if not hsts_checked_url:
                hsts_checked_url = url
            if _header_get(headers, "strict-transport-security"):
                hsts_seen = True

    if https_pages_with_headers and not hsts_seen and hsts_checked_url:
        issue = {
            "type": "missing_hsts",
            "severity": "medium",
            "message": f"HTTPS nhưng không thấy header Strict-Transport-Security (HSTS) — {hsts_checked_url}",
            "url": hsts_checked_url,
            "affected_urls": [hsts_checked_url],
            "confidence": 0.84,
            "evidence": [
                {"kind": "url", "url": hsts_checked_url},
                {"kind": "hsts_header", "value": ""},
                {"kind": "https_pages_with_headers", "value": https_pages_with_headers},
            ],
            "source": "crawl",
            "detected_from": ["response_headers.strict-transport-security"],
            "checklist_group": "Security",
        }
        kept = _wrap(issue)
        if kept:
            out.append(kept)

    if crux:
        origin = str(crux.get("origin") or start_url or "").strip()
        out.extend(
            build_cwv_issues_from_metrics(
                url=origin,
                lcp_ms=_num(crux.get("lcp_ms")),
                inp_ms=_num(crux.get("inp_ms")),
                cls=_num(crux.get("cls")),
                source="crux",
                form_factor=str(crux.get("form_factor") or ""),
            )
        )
    return out
