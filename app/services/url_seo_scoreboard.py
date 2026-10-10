"""
Chấm điểm SEO 1 URL (0–100): 12 trụ cột — Intent ưu tiên cao nhất.
Output: total, sub-score, issues (priority P0–P3), gợi ý fix. An toàn khi thiếu dữ liệu.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from app.services.content_analysis import analyze_content
from app.services.crawler import LINK_CHECK_HEADERS, normalize_url
from app.services.keyword_difficulty import compute_keyword_difficulty
from app.services.keyword_opportunity import compute_keyword_opportunity
from app.services.parser import parse_page_seo_data
from app.services.schema_validator import validate_schemas
from app.services.search_intent import classify_search_intent
from app.services.editorial_seo_checklist import build_editorial_checklist_table
from app.services.seo_fifteen_pillars import build_fifteen_pillar_assessment
from app.services.serp_top10_crawl import crawl_serp_top_urls
from app.services.url_seo_optimization_report import (
    attach_evidence_to_scoreboard,
    build_url_seo_optimization_report,
)
from app.services.serp_competitor_analysis import analyze_serp_competitors
from app.services.seo_score_serp import fetch_seo_score_serp
from app.services.seo_score_ssot import SCORING_VERSION
from app.services.serp_intent_classifier import classify_serp_results
from app.services.url_seo_ten_group_scoring import (
    GROUP_LABELS,
    GROUP_WEIGHTS,
    analyze_page_links,
    build_ten_group_scoreboard,
    ensure_ten_groups_complete,
)

# Intent quan trọng nhất; các trụ còn lại cân bằng theo impact SEO phổ biến.
PILLAR_WEIGHTS: dict[str, float] = {
    "intent": 0.16,
    "eeat": 0.12,
    "helpful_content": 0.11,
    "structure": 0.10,
    "keyword_semantic": 0.10,
    "ux_readability": 0.09,
    "speed_mobile": 0.09,
    "links": 0.08,
    "schema": 0.06,
    "content_depth": 0.05,
    "freshness": 0.02,
    "ctr": 0.02,
}


def _pillar_from_severity(sev: str, issue_type: str) -> str:
    if issue_type in ("noindex_signal", "https_missing", "http_non_success") and sev == "high":
        return "P0"
    if sev == "high":
        return "P1"
    if sev == "medium":
        return "P2"
    return "P3"


def _issue(
    *,
    pillar: str,
    issue_type: str,
    severity: str,
    message: str,
    fix: str,
) -> dict[str, Any]:
    return {
        "pillar": pillar,
        "type": issue_type,
        "severity": severity,
        "priority": _pillar_from_severity(severity, issue_type),
        "message": message,
        "fix": fix,
    }


def _same_site(href: str, base_netloc: str) -> bool:
    try:
        p = urlparse(href)
        if p.scheme in ("mailto", "tel", "javascript", "data", ""):
            return False
        if not p.netloc:
            return True
        h = p.netloc.lower()
        if h.startswith("www."):
            h = h[4:]
        b = base_netloc.lower()
        if b.startswith("www."):
            b = b[4:]
        return h == b or h.endswith("." + b) or b.endswith("." + h)
    except Exception:
        return False


def _extract_ld_json_blocks(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not html:
        return out
    try:
        soup = BeautifulSoup(html[:800_000], "html.parser")
        for script in soup.find_all("script", type=lambda t: t and "ld+json" in str(t).lower()):
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    for item in data["@graph"]:
                        if isinstance(item, dict):
                            out.append(item)
                else:
                    out.append(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        out.append(item)
    except Exception:
        pass
    return out


def _ctr_curve(position: int | None) -> float:
    if position is None or position < 1:
        return 0.025
    table = {1: 0.27, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.06, 6: 0.045, 7: 0.035, 8: 0.03, 9: 0.026, 10: 0.023}
    if position in table:
        return table[position]
    if position <= 20:
        return 0.012
    return 0.006


def _safe_fetch(url: str) -> dict[str, Any]:
    notes: list[str] = []
    try:
        nu = normalize_url(url)
    except ValueError as e:
        return {
            "ok": False,
            "normalized_url": (url or "").strip(),
            "status": 0,
            "final_url": "",
            "html": "",
            "headers": {},
            "error": str(e),
            "notes": ["URL không hợp lệ hoặc không thể chuẩn hóa."],
        }
    try:
        from app.services.url_safety import safe_requests_get, validate_public_http_url

        blocked = validate_public_http_url(nu)
        if blocked:
            return {
                "ok": False,
                "normalized_url": nu,
                "status": 0,
                "final_url": nu,
                "html": "",
                "headers": {},
                "error": blocked,
                "notes": [f"URL bị chặn (SSRF): {blocked}"],
            }
        r = safe_requests_get(nu, timeout=18, headers=dict(LINK_CHECK_HEADERS))
    except ValueError as e:
        return {
            "ok": False,
            "normalized_url": nu,
            "status": 0,
            "final_url": nu,
            "html": "",
            "headers": {},
            "error": str(e),
            "notes": [f"URL bị chặn (SSRF): {e}"],
        }
    except requests.RequestException as e:
        return {
            "ok": False,
            "normalized_url": nu,
            "status": 0,
            "final_url": nu,
            "html": "",
            "headers": {},
            "error": e.__class__.__name__,
            "notes": [f"Không tải được trang: {e.__class__.__name__}"],
        }
    final = r.url or nu
    html = r.text if r.text else ""
    st = int(r.status_code or 0)
    if st != 200:
        notes.append(f"HTTP {st} — một số tín hiệu có thể không đầy đủ.")
    if not html.strip():
        notes.append("Thân HTML trống.")
    return {
        "ok": True,
        "normalized_url": nu,
        "status": st,
        "final_url": final,
        "html": html,
        "headers": {k: v for k, v in r.headers.items()},
        "error": None,
        "notes": notes,
    }


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup((html or "")[:600_000], "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")


def _pillar_intent(
    *,
    keyword: str | None,
    page_data: dict[str, Any],
    html: str,
    serp_intent_pkg: dict[str, Any] | None,
) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    title = str(page_data.get("title") or "")
    meta = str(page_data.get("meta_description") or "")
    blob = f"{title} {meta}".strip()
    page_intent = classify_search_intent(blob or "content")

    if not (keyword or "").strip():
        score = 55.0 + min(40.0, float(page_intent.get("confidence") or 0.5) * 40)
        signals.append("Chưa có keyword mục tiêu — Intent đánh giá theo title/meta (neutral).")
        return round(min(100.0, score), 1), {"page_intent": page_intent, "signals": signals}, issues

    kw = keyword.strip()
    page_i = str(page_intent.get("intent") or "informational")
    serp_i = str((serp_intent_pkg or {}).get("serp_intent") or "informational") if serp_intent_pkg else None
    kw_low = kw.lower()
    align = 0.55
    if kw_low in title.lower():
        align += 0.22
        signals.append("Keyword xuất hiện trong title — khớp intent tìm kiếm tốt hơn.")
    if kw_low in meta.lower():
        align += 0.12
    if serp_i and page_i == serp_i:
        align += 0.15
        signals.append(f"Intent trang ({page_i}) khớp dominant SERP ({serp_i}).")
    elif serp_i:
        align += 0.05
        signals.append(f"Intent trang {page_i} vs SERP {serp_i} — kiểm tra lại angle nội dung.")
        issues.append(
            _issue(
                pillar="intent",
                issue_type="intent_mismatch_serp",
                severity="medium",
                message=f"Gợi ý intent SERP: {serp_i}; trang đang thiên {page_i}.",
                fix="Điều chỉnh title/H1/intro để khớp intent người dùng trên SERP (informational vs commercial…).",
            )
        )

    score = round(max(0.0, min(100.0, align * 100)), 1)
    return score, {"keyword": kw, "page_intent": page_intent, "serp_intent": serp_i, "signals": signals}, issues


def _pillar_eeat(*, html: str, ld_blocks: list[dict[str, Any]]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    score_pts = 0.0
    max_pts = 0.0

    types = []
    for b in ld_blocks[:32]:
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
    type_set = {x.lower() for x in types}
    max_pts += 25
    if "person" in type_set or "organization" in type_set:
        score_pts += 25
        signals.append("JSON-LD có Person/Organization.")
    else:
        score_pts += 8
        issues.append(
            _issue(
                pillar="eeat",
                issue_type="missing_org_person_schema",
                severity="low",
                message="Chưa thấy Person/Organization trong JSON-LD.",
                fix="Thêm Organization + author (Person) khớp thực tế; tránh schema giả.",
            )
        )

    soup = _soup(html)
    max_pts += 20
    about_hit = False
    for a in soup.find_all("a", href=True, limit=400):
        lab = (a.get_text(" ", strip=True) or "").lower()
        href = str(a.get("href") or "").lower()
        if any(x in lab for x in ("about", "giới thiệu", "team", "liên hệ", "contact")) or any(
            x in href for x in ("/about", "/contact", "/team", "/gioi-thieu", "/lien-he")
        ):
            about_hit = True
            break
    if about_hit:
        score_pts += 20
        signals.append("Có liên kết About/Contact/Team — tín hiệu minh bạch.")
    else:
        score_pts += 6
        issues.append(
            _issue(
                pillar="eeat",
                issue_type="thin_trust_nav",
                severity="low",
                message="Không thấy About/Contact rõ ràng trong anchor đầu trang.",
                fix="Thêm trang Giới thiệu / Liên hệ / Đội ngũ và link từ header/footer.",
            )
        )

    max_pts += 20
    if re.search(r"\b(by|author|đăng bởi|biên tập|reviewed\s+by)\b", html[:200_000], re.I):
        score_pts += 20
        signals.append("Có dấu hiệu byline/author trong HTML.")
    else:
        score_pts += 8
        issues.append(
            _issue(
                pillar="eeat",
                issue_type="missing_byline",
                severity="low",
                message="Chưa thấy byline tác giả rõ (heuristic).",
                fix="Hiển thị tên tác giả, ngày, cập nhật; schema Article + author.",
            )
        )

    max_pts += 15
    if soup.find("meta", attrs={"property": "article:author"}) or soup.find("link", attrs={"rel": "author"}):
        score_pts += 15
        signals.append("Có article:author hoặc rel=author.")
    else:
        score_pts += 5

    max_pts += 20
    if any("aggregaterating" in json.dumps(b).lower() for b in ld_blocks[:16]):
        score_pts += 20
        signals.append("Có AggregateRating trong JSON-LD (nếu phù hợp loại trang).")
    else:
        score_pts += 10

    total = round(100.0 * score_pts / max_pts if max_pts else 50.0, 1)
    return total, {"types_found": sorted(type_set)[:12], "signals": signals}, issues


def _pillar_helpful_content(*, soup: BeautifulSoup, content_pkg: dict[str, Any]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    wc = int(content_pkg.get("word_count") or 0)
    lists = len(soup.find_all(["ul", "ol"]))
    tables = len(soup.find_all("table"))
    faq_h = sum(1 for hx in soup.find_all(["h2", "h3"]) if re.search(r"faq|câu hỏi|hỏi đáp", hx.get_text(" ", strip=True), re.I))

    score = 42.0
    if wc >= 800:
        score += 28.0
        signals.append(f"Độ dài {wc} từ — đủ để trả lời sâu.")
    elif wc >= 400:
        score += 18.0
        signals.append(f"{wc} từ — mức trung bình.")
    else:
        issues.append(
            _issue(
                pillar="helpful_content",
                issue_type="thin_helpful",
                severity="medium",
                message="Nội dung có thể chưa đủ ‘helpful’ so kỳ vọng Google.",
                fix="Bổ sung mục trả lời trực tiếp intent, ví dụ thực tế, checklist, FAQ ngắn.",
            )
        )
    if lists >= 2 or tables >= 1:
        score += 18.0
        signals.append("Có danh sách/bảng — dễ quét.")
    if faq_h:
        score += 12.0
        signals.append("Có heading dạng FAQ.")
    return round(min(100.0, score), 1), {"lists": lists, "tables": tables, "faq_headings": faq_h, "signals": signals}, issues


def _pillar_structure(*, page_data: dict[str, Any], html: str) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    title = str(page_data.get("title") or "").strip()
    meta = str(page_data.get("meta_description") or "").strip()
    h1c = int(page_data.get("h1_count") or 0)
    parts: list[float] = []

    if 28 <= len(title) <= 62:
        parts.append(100.0)
    elif title:
        parts.append(72.0)
        issues.append(
            _issue(
                pillar="structure",
                issue_type="title_length",
                severity="low",
                message=f"Title {len(title)} ký tự.",
                fix="Giữ ~30–55 ký tự, đặt keyword/brand rõ ở đầu.",
            )
        )
    else:
        parts.append(15.0)
        issues.append(
            _issue(
                pillar="structure",
                issue_type="missing_title",
                severity="high",
                message="Thiếu title.",
                fix="Thêm <title> duy nhất mô tả chính xác trang.",
            )
        )

    if 130 <= len(meta) <= 175:
        parts.append(100.0)
    elif meta:
        parts.append(70.0)
    else:
        parts.append(40.0)
        issues.append(
            _issue(
                pillar="structure",
                issue_type="missing_meta",
                severity="medium",
                message="Thiếu hoặc meta quá ngắn.",
                fix="Meta description ~140–160 ký tự, có CTA nhẹ.",
            )
        )

    if h1c == 1:
        parts.append(100.0)
    elif h1c == 0:
        parts.append(35.0)
        issues.append(
            _issue(
                pillar="structure",
                issue_type="missing_h1",
                severity="medium",
                message="Không có H1.",
                fix="Một H1 duy nhất trùng chủ đề chính.",
            )
        )
    else:
        parts.append(55.0)
        issues.append(
            _issue(
                pillar="structure",
                issue_type="multiple_h1",
                severity="low",
                message=f"Có {h1c} H1.",
                fix="Gộp thành 1 H1; dùng H2/H3 phân cấp.",
            )
        )

    soup = _soup(html)
    h2n = len(soup.find_all("h2"))
    parts.append(min(100.0, 40.0 + min(60.0, h2n * 8.0)))
    signals.append(f"H2: {h2n}.")

    return round(sum(parts) / len(parts), 1), {"h2_count": h2n, "signals": signals}, issues


def _pillar_keyword_semantic(*, keyword: str | None, page_data: dict[str, Any], html: str) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    if not (keyword or "").strip():
        return 50.0, {"signals": ["Chưa có keyword — điểm trung tính."]}, issues
    kw = keyword.strip().lower()
    tokens = [t for t in re.findall(r"[a-zà-ỹ0-9]{3,}", kw) if len(t) > 2][:6]
    title = (page_data.get("title") or "").lower()
    text_l = (html or "")[:120_000].lower()
    hits = sum(1 for t in tokens if t in title)
    body_hits = sum(1 for t in tokens if t in text_l)
    score = 35.0 + min(35.0, hits * 12.0) + min(30.0, body_hits * 6.0)
    if hits == 0:
        issues.append(
            _issue(
                pillar="keyword_semantic",
                issue_type="keyword_not_in_title",
                severity="medium",
                message="Keyword (token) chưa có trong title.",
                fix="Đưa cụm chính vào title tự nhiên; tránh nhồi.",
            )
        )
    signals.append(f"Token khớp title {hits}/{len(tokens) or 1}; trong body ~{body_hits}/{len(tokens) or 1}.")
    return round(min(100.0, score), 1), {"tokens_checked": tokens, "signals": signals}, issues


def _pillar_ux_readability(*, soup: BeautifulSoup, page_data: dict[str, Any]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    imgs = soup.find_all("img")
    missing = sum(1 for im in imgs if not str(im.get("alt") or "").strip())
    total = len(imgs) or 1
    alt_ratio = 1.0 - (missing / total)
    score = 55.0 + 30.0 * alt_ratio
    if alt_ratio < 0.6 and imgs:
        issues.append(
            _issue(
                pillar="ux_readability",
                issue_type="images_missing_alt",
                severity="medium",
                message=f"{missing}/{len(imgs)} ảnh thiếu alt.",
                fix="Alt mô tả ngắn, đúng ngữ cảnh; decorative dùng alt=\"\".",
            )
        )
    text = soup.get_text(" ", strip=True)
    words = re.findall(r"[\wà-ỹ]+", text, re.I)
    sents = max(1, len(re.split(r"[.!?]+", text)))
    asl = len(words) / sents if sents else 0
    if asl > 28:
        score -= 12
        issues.append(
            _issue(
                pillar="ux_readability",
                issue_type="long_sentences",
                severity="low",
                message="Câu trung bình khá dài — có thể khó đọc.",
                fix="Chia câu; dùng bullet; giữ 15–22 từ/câu trung bình khi có thể.",
            )
        )
    elif 10 <= asl <= 24:
        score += 10
    skip_el = soup.find(attrs={"id": re.compile(r"(skip|main-content|content)", re.I)})
    skip = bool(skip_el)
    if skip:
        score += 5
    signals = [f"ASL ~{round(asl, 1)} từ/câu", f"Alt ảnh hợp lệ ~{round(alt_ratio*100)}%"]
    return round(max(0.0, min(100.0, score)), 1), {"avg_sentence_length_words": round(asl, 2), "signals": signals}, issues


def _pillar_speed_mobile(*, fetch: dict[str, Any], html: str, headers: dict[str, Any]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    signals: list[str] = []
    parts: list[float] = []
    st = int(fetch.get("status") or 0)
    final = str(fetch.get("final_url") or "")
    try:
        https_ok = urlparse(final).scheme.lower() == "https"
    except Exception:
        https_ok = False
    parts.append(100.0 if https_ok else 35.0)
    if not https_ok:
        issues.append(
            _issue(
                pillar="speed_mobile",
                issue_type="https",
                severity="high",
                message="Không HTTPS.",
                fix="Bật SSL + redirect 301 về https.",
            )
        )
    parts.append(100.0 if 200 <= st < 300 else (70.0 if st in (301, 302, 308) else max(0.0, 50.0 - st / 15.0)))
    x_robots = (headers.get("X-Robots-Tag") or "").lower()
    meta_r = ""
    if html:
        m = _soup(html).find("meta", attrs={"name": "robots"})
        if m and m.get("content"):
            meta_r = str(m.get("content")).lower()
    if "noindex" in x_robots or "noindex" in meta_r:
        parts.append(20.0)
        issues.append(
            _issue(
                pillar="speed_mobile",
                issue_type="noindex",
                severity="high",
                message="noindex — không tính vào tốc độ nhưng chặn hiệu quả SEO.",
                fix="Gỡ noindex nếu URL cần index.",
            )
        )
    else:
        parts.append(90.0)
    vp = bool(html and re.search(r'name=["\']viewport["\']', html, re.I))
    parts.append(100.0 if vp else 52.0)
    if not vp and html.strip():
        issues.append(
            _issue(
                pillar="speed_mobile",
                issue_type="viewport",
                severity="medium",
                message="Thiếu viewport.",
                fix='Thêm <meta name="viewport" content="width=device-width, initial-scale=1">.',
            )
        )
    scripts = len(re.findall(r"<script\b", html or "", re.I))
    parts.append(78.0 if scripts < 70 else 52.0)
    signals.append(f"HTTP {st}; viewport={'ok' if vp else 'no'}; scripts≈{scripts} (proxy tải, không phải LCP/CLS lab).")
    return round(sum(parts) / len(parts), 1), {"signals": signals}, issues


def _pillar_links(html: str, base_url: str) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not html.strip():
        return 25.0, {"internal": 0, "external_hosts": 0, "signals": ["Không có HTML."]}, issues
    try:
        base_netloc = urlparse(base_url).netloc
        soup = _soup(html)
        internal = 0
        ext_hosts: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            abs_u = urljoin(base_url, href)
            if _same_site(abs_u, base_netloc):
                internal += 1
            else:
                try:
                    h = (urlparse(abs_u).hostname or "").lower()
                    if h:
                        ext_hosts.add(h)
                except Exception:
                    pass
        score = 40.0
        if internal >= 12:
            score += 35.0
        elif internal >= 5:
            score += 25.0
        elif internal >= 1:
            score += 12.0
        else:
            issues.append(
                _issue(
                    pillar="links",
                    issue_type="low_internal",
                    severity="medium",
                    message="Ít liên kết nội bộ.",
                    fix="Link tới pillar liên quan; anchor mô tả.",
                )
            )
        score += min(25.0, len(ext_hosts) * 2.5)
        return round(min(100.0, score), 1), {"internal": internal, "external_hosts": len(ext_hosts), "signals": []}, issues
    except Exception as e:
        return 40.0, {"error": str(e)}, issues


def _pillar_schema(ld_blocks: list[dict[str, Any]]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not ld_blocks:
        return 35.0, {"present": False, "signals": ["Không có JSON-LD."]}, issues + [
            _issue(
                pillar="schema",
                issue_type="no_ld_json",
                severity="low",
                message="Không có JSON-LD.",
                fix="Thêm schema phù hợp (Article/Product/FAQ…) và kiểm Rich Results Test.",
            )
        ]
    val = validate_schemas(ld_blocks[:24])
    valid = bool(val.get("valid"))
    errs = list(val.get("errors") or [])
    score = 72.0 if valid else 50.0
    if len(ld_blocks) > 1:
        score = min(100.0, score + 6.0)
    if errs:
        score = max(28.0, score - min(24.0, 4.0 * len(errs)))
        issues.append(
            _issue(
                pillar="schema",
                issue_type="schema_errors",
                severity="medium",
                message="; ".join(errs[:3]),
                fix="Sửa JSON-LD theo schema.org.",
            )
        )
    return round(score, 1), {"present": True, "valid": valid, "blocks": len(ld_blocks)}, issues


def _pillar_content_depth(content_pkg: dict[str, Any]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    wc = int(content_pkg.get("word_count") or 0)
    depth = str(content_pkg.get("content_depth") or "thin")
    h = float(content_pkg.get("heading_structure_score") or 0.0)
    score = 30.0
    if wc >= 1200:
        score += 40.0
    elif wc >= 600:
        score += 28.0
    elif wc >= 300:
        score += 16.0
    else:
        issues.append(
            _issue(
                pillar="content_depth",
                issue_type="thin",
                severity="medium",
                message=f"Chỉ ~{wc} từ.",
                fix="Mở rộng phần giải thích, ví dụ, dữ liệu — theo intent.",
            )
        )
    score += 30.0 * h
    return round(min(100.0, score), 1), {"word_count": wc, "depth_bucket": depth, "heading_structure_score": h}, issues


def _pillar_freshness(headers: dict[str, Any], html: str, ld_blocks: list[dict[str, Any]]) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    lm = headers.get("Last-Modified") or headers.get("Date")
    soup = _soup(html)
    pub = soup.find("meta", attrs={"property": "article:published_time"})
    pub_v = str(pub.get("content")) if pub and pub.get("content") else ""
    json_blob = json.dumps(ld_blocks[:8])[:40_000].lower()
    has_date = bool(pub_v or lm or "datepublished" in json_blob or "datemodified" in json_blob)
    score = 58.0 if has_date else 42.0
    if not has_date:
        issues.append(
            _issue(
                pillar="freshness",
                issue_type="no_visible_date",
                severity="low",
                message="Không thấy ngày published/modified rõ.",
                fix="Hiển thị ngày cập nhật + schema datePublished/dateModified trung thực.",
            )
        )
    return round(score, 1), {"last_modified_header": bool(lm), "article_published_meta": bool(pub_v), "ld_date_hints": has_date}, issues


def _pillar_ctr(
    *,
    page_data: dict[str, Any],
    keyword: str | None,
    current_serp_position: int | None,
    serp_position_snapshot: int | None,
) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    title = str(page_data.get("title") or "")
    meta = str(page_data.get("meta_description") or "")
    tl, ml = len(title), len(meta)
    score = 55.0
    if 32 <= tl <= 58:
        score += 18.0
    if 135 <= ml <= 168:
        score += 14.0
    if keyword and keyword.strip().lower() in title.lower():
        score += 12.0
    pos = current_serp_position if current_serp_position is not None else serp_position_snapshot
    ctr = _ctr_curve(pos)
    score += min(15.0, ctr * 45.0)
    if pos and pos > 10:
        issues.append(
            _issue(
                pillar="ctr",
                issue_type="low_position",
                severity="low",
                message=f"Vị trí ~{pos} — CTR thấp hơn top 3.",
                fix="Cải thiện title/meta theo intent; thêm structured data phù hợp; tăng độ liên quan nội dung.",
            )
        )
    return round(min(100.0, score), 1), {"title_len": tl, "meta_len": ml, "position_used": pos, "ctr_proxy": round(ctr, 4)}, issues


def _parse_secondary_keywords(raw: list[str] | str | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]
    return [str(p).strip() for p in raw if p and str(p).strip()]


def build_url_seo_scoreboard(
    url: str,
    *,
    keyword: str | None = None,
    secondary_keywords: list[str] | str | None = None,
    page_type: str | None = None,
    search_volume: int | None = None,
    current_serp_position: int | None = None,
) -> dict[str, Any]:
    fetch = _safe_fetch(url)
    nu = str(fetch.get("normalized_url") or "").strip()
    html = str(fetch.get("html") or "")
    headers = dict(fetch.get("headers") or {})
    final_u = str(fetch.get("final_url") or nu)
    page_data = parse_page_seo_data(html or "", base_url=final_u or nu)
    content_pkg = analyze_content(html) if html else {"word_count": 0, "content_depth": "thin", "heading_structure_score": 0.0, "keyword_density_estimate": {}}
    soup = _soup(html)
    link_profile = analyze_page_links(
        html or "",
        final_u or nu,
        soup=soup,
        parsed_links=list(page_data.get("links") or []),
    )
    page_data["link_profile"] = link_profile
    if link_profile.get("links"):
        page_data["links"] = link_profile["links"]
    ld_blocks = _extract_ld_json_blocks(html)
    schema_validation = validate_schemas(ld_blocks) if ld_blocks else {"valid": False, "errors": ["no_ld_json"], "warnings": []}

    serp_intent_pkg: dict[str, Any] | None = None
    serp_pos_snap: int | None = None
    serp_rows: list[dict[str, Any]] = []
    serp_fetch_meta: dict[str, Any] = {}
    serp_analysis_full: dict[str, Any] | None = None
    if (keyword or "").strip():
        serp_stats: dict[str, Any] = {}
        serp_fetch_meta = fetch_seo_score_serp(keyword.strip(), stats=serp_stats)
        serp_rows = list(serp_fetch_meta.get("rows") or [])
        serp_fetch_meta["stats"] = serp_stats
        serp_intent_pkg = classify_serp_results(serp_rows) if serp_rows else None
        norm = nu.rstrip("/").lower()
        for i, row in enumerate(serp_rows, start=1):
            u = str(row.get("url") or row.get("link") or "").strip().rstrip("/").lower()
            if u and (u == norm or norm in u or u in norm):
                serp_pos_snap = i
                break

    pillars: dict[str, tuple[float, dict[str, Any], list[dict[str, Any]]]] = {
        "intent": _pillar_intent(keyword=keyword, page_data=page_data, html=html, serp_intent_pkg=serp_intent_pkg),
        "eeat": _pillar_eeat(html=html, ld_blocks=ld_blocks),
        "helpful_content": _pillar_helpful_content(soup=soup, content_pkg=content_pkg),
        "structure": _pillar_structure(page_data=page_data, html=html),
        "keyword_semantic": _pillar_keyword_semantic(keyword=keyword, page_data=page_data, html=html),
        "ux_readability": _pillar_ux_readability(soup=soup, page_data=page_data),
        "speed_mobile": _pillar_speed_mobile(fetch=fetch, html=html, headers=headers),
        "links": _pillar_links(html, final_u or nu),
        "schema": _pillar_schema(ld_blocks),
        "content_depth": _pillar_content_depth(content_pkg),
        "freshness": _pillar_freshness(headers, html, ld_blocks),
        "ctr": _pillar_ctr(
            page_data=page_data,
            keyword=keyword,
            current_serp_position=current_serp_position,
            serp_position_snapshot=serp_pos_snap,
        ),
    }

    all_issues: list[dict[str, Any]] = []
    components: dict[str, float] = {}
    breakdown: dict[str, Any] = {}
    for name, (sc, meta, iss) in pillars.items():
        components[name] = round(float(sc), 1)
        breakdown[name] = {"score": components[name], **meta}
        all_issues.extend(iss)

    w = {k: round(v / sum(PILLAR_WEIGHTS.values()), 4) for k, v in PILLAR_WEIGHTS.items()}
    legacy_total = round(sum(components[k] * w[k] for k in w), 1)
    legacy_total = max(0.0, min(100.0, legacy_total))

    all_issues.sort(key=lambda x: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(str(x.get("priority")), 9))

    serp_top10_crawl: dict[str, Any] = {"enabled": False, "pages": [], "stats": {}, "note": "no_keyword_or_disabled"}
    if (keyword or "").strip() and os.getenv("SERP_TOP10_CRAWL_ENABLED", "1").lower() in ("1", "true", "yes"):
        try:
            serp_top10_crawl = crawl_serp_top_urls(
                serp_rows,
                exclude_url=final_u or nu,
                keyword=(keyword or "").strip(),
                max_pages=10,
            )
        except Exception as e:
            serp_top10_crawl = {
                "enabled": True,
                "pages": [],
                "stats": {},
                "note": f"crawl_error:{e.__class__.__name__}",
                "total_elapsed_ms": 0,
            }

    try:
        fifteen_pkg = build_fifteen_pillar_assessment(
            components=components,
            breakdown=breakdown,
            all_issues=all_issues,
            serp_rows=serp_rows,
            serp_analysis=serp_analysis_full,
            keyword=(keyword or "").strip() or None,
            html=html,
            page_data=page_data,
            normalized_url=nu,
            our_word_count=int(content_pkg.get("word_count") or page_data.get("word_count") or 0),
            serp_top10_crawl=serp_top10_crawl,
        )
    except Exception:
        fifteen_pkg = {
            "items": [],
            "weights": {},
            "weighted_raw": 0.0,
            "total_capped": 0.0,
            "intent_hard_gate": {},
            "checklist_table_rows": [],
            "top_priority_by_impact": [],
            "top_fixes": [],
        }

    opportunity: dict[str, Any] | None = None
    serp_pkg: dict[str, Any] | None = None
    if (keyword or "").strip():
        try:
            serp_analysis_full = analyze_serp_competitors(
                serp_rows,
                {nu: {"pagerank_score": 0.22, "word_count": int(content_pkg.get("word_count") or 0)}},
                keyword=keyword.strip(),
            )
            kd_pkg = compute_keyword_difficulty(serp_analysis_full)
        except Exception:
            serp_analysis_full = None
            kd_pkg = {"difficulty_score": 50.0, "difficulty_level": "medium", "reasoning": []}
        opp = compute_keyword_opportunity(
            keyword.strip(),
            search_volume=search_volume,
            difficulty=kd_pkg,
            your_ranking_score=float(legacy_total),
            topical_authority_score=None,
        )
        vol = int(search_volume) if search_volume is not None else None
        pos_use = current_serp_position if current_serp_position is not None else serp_pos_snap
        ctr_now = _ctr_curve(pos_use)
        ctr_potential = _ctr_curve(max(1, (pos_use or 12) - 2)) if pos_use else _ctr_curve(5)
        gain = max(0.0, (vol or 800) * (ctr_potential - ctr_now))
        opportunity = {
            **opp,
            "priority_hint": "high" if float(opp.get("opportunity_score") or 0) >= 60 and legacy_total < 72 else "medium",
            "estimated_monthly_visits_gain": {
                "current_ctr_assumed": round(ctr_now, 4),
                "target_ctr_assumed": round(ctr_potential, 4),
                "position_used": pos_use,
                "monthly_visits_delta_approx": int(round(gain)),
                "explain": "Ước lượng thô; cần volume & rank thật (GSC) để thu hẹp sai số.",
            },
            "keyword_difficulty": kd_pkg,
        }
        serp_pkg = {
            "keyword": keyword.strip(),
            "your_position_snapshot": serp_pos_snap,
            "serp_intent": (serp_intent_pkg or {}).get("serp_intent"),
            "intent_distribution": (serp_intent_pkg or {}).get("intent_distribution"),
            "cache_hit": bool(serp_fetch_meta.get("cache_hit")),
            "provider_called": bool(serp_fetch_meta.get("provider_called")),
            "source": serp_fetch_meta.get("source"),
        }

    page_snapshot = {
        "title": str(page_data.get("title") or ""),
        "meta_description": str(page_data.get("meta_description") or ""),
        "h1_count": int(page_data.get("h1_count") or 0),
        "h2_count": int(page_data.get("h2_count") or 0),
        "canonical": str(page_data.get("canonical") or ""),
        "headings": page_data.get("headings") or {},
        "intro": page_data.get("intro") or content_pkg.get("intro") or {},
        "intro_text": str(page_data.get("intro_text") or content_pkg.get("intro_text") or ""),
        "content_sections": list(page_data.get("content_sections") or content_pkg.get("content_sections") or []),
        "images": page_data.get("images") or [],
        "links": page_data.get("links") or [],
        "link_profile": page_data.get("link_profile") or {},
        "images_total": int(page_data.get("images_total") or 0),
        "images_missing_alt": int(page_data.get("images_missing_alt") or 0),
        "images_missing_size": int(page_data.get("images_missing_size") or 0),
        "visible_text": str(page_data.get("visible_text") or "")[:4000],
    }

    try:
        editorial_checklist = build_editorial_checklist_table(
            normalized_url=nu,
            final_url=final_u or nu,
            html=html,
            page_data=page_data,
            keyword=(keyword or "").strip() or None,
            serp_intent_pkg=serp_intent_pkg,
            ld_blocks=ld_blocks,
            body_word_count=int(content_pkg.get("word_count") or page_data.get("word_count") or 0),
        )
    except Exception:
        editorial_checklist = {"rows": [], "items": [], "average_score": 0.0, "checklist_version": "error"}

    out: dict[str, Any] = {
        "url": (url or "").strip(),
        "normalized_url": nu,
        "fetch": {
            "ok": fetch.get("ok"),
            "status": fetch.get("status"),
            "final_url": final_u,
            "error": fetch.get("error"),
            "notes": list(fetch.get("notes") or []),
        },
        "scores": {
            "total": legacy_total,
            "legacy_total": legacy_total,
            "legacy_12_pillar_total": legacy_total,
            "components": components,
            "weights_applied": w,
            "editorial_checklist_average": round(float(editorial_checklist.get("average_score") or 0.0), 1),
            "checklist_15_total": round(float(fifteen_pkg.get("total_capped") or 0.0), 1),
            "checklist_15_weighted_raw": round(float(fifteen_pkg.get("weighted_raw") or 0.0), 2),
            "checklist_15_subscores": {str(x.get("id")): float(x.get("score") or 0) for x in (fifteen_pkg.get("items") or [])},
        },
        "breakdown": breakdown,
        "issues": all_issues,
        "serp": serp_pkg,
        "opportunity": opportunity,
        "weights": w,
        "pillar_definitions": {
            "intent": "Khớp intent trang vs keyword & SERP (quan trọng nhất).",
            "eeat": "Tín hiệu Experience, Expertise, Authoritativeness, Trustworthiness (heuristic).",
            "helpful_content": "Độ đầy đủ, định dạng dễ đọc, FAQ-style.",
            "structure": "Title, meta, H1/H2.",
            "keyword_semantic": "Keyword + token liên quan trong title/body.",
            "ux_readability": "Alt ảnh, độ dài câu, skip link.",
            "speed_mobile": "HTTPS, HTTP, viewport, proxy độ nặng HTML (không LCP/CLS lab).",
            "links": "Nội bộ + đa dạng host ngoài.",
            "schema": "JSON-LD + validate.",
            "content_depth": "Word count + heading structure score.",
            "freshness": "Ngày/header/schema date hints.",
            "ctr": "Title/meta length + keyword + vị trí & CTR heuristic.",
        },
        "page_snapshot": page_snapshot,
        "_content_pkg": content_pkg,
        "_ld_blocks": ld_blocks,
        "_schema_validation": schema_validation,
        "editorial_checklist": editorial_checklist,
        "fifteen_pillar_assessment": fifteen_pkg,
        "serp_top10_crawl": serp_top10_crawl,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        out["optimization_report"] = build_url_seo_optimization_report(out)
    except Exception:
        out["optimization_report"] = {
            "error": "Không tạo được báo cáo tối ưu (fallback).",
            "checklist": ["Thử chấm điểm lại; kiểm tra log server."],
        }

    sec_kw = _parse_secondary_keywords(secondary_keywords)
    try:
        out["ten_group_scoreboard"] = build_ten_group_scoreboard(
            url=(url or "").strip(),
            normalized_url=nu,
            fetch=fetch,
            page_data=page_data,
            content_pkg=content_pkg,
            html=html,
            headers=headers,
            ld_blocks=ld_blocks,
            soup=soup,
            primary_keyword=(keyword or "").strip() or None,
            secondary_keywords=sec_kw,
            page_type=(page_type or "").strip() or None,
            breakdown=breakdown,
            legacy_issues=all_issues,
            serp_intent_pkg=serp_intent_pkg,
            link_profile=link_profile,
            serp_rows=serp_rows,
            schema_validation=schema_validation,
        )
        tg = out["ten_group_scoreboard"]
        ssot_total = float(tg.get("total_score") or legacy_total)
        out["scores"]["total"] = ssot_total
        out["scores"]["ten_group_total"] = ssot_total
        out["scores"]["scoring_version"] = str(tg.get("scoring_version") or SCORING_VERSION)
        out["scores"]["ssot"] = tg.get("ssot") or {}
    except Exception:
        out["ten_group_scoreboard"] = {
            "total_score": round(legacy_total, 1),
            "group_scores": {gid: 0.0 for gid in GROUP_WEIGHTS},
            "groups": ensure_ten_groups_complete([]),
            "strengths": [],
            "weaknesses": [],
            "priority_fixes": [],
            "ai_suggestions": ["Không tạo được báo cáo 10 nhóm — thử lại."],
            "penalties_applied": [],
            "weights": GROUP_WEIGHTS,
            "group_labels": GROUP_LABELS,
        }

    try:
        attach_evidence_to_scoreboard(out)
        out["optimization_report"] = build_url_seo_optimization_report(out)
    except Exception:
        pass

    return out
