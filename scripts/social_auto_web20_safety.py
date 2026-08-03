"""Safety Score cho bài Web 2.0 / WordPress vệ tinh."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from app.services.social_auto_web20_store import count_account_posts_today, get_settings, list_posts
from app.services.social_auto_web20_wp import count_links_to_host

_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_ANCHOR_TEXT_RE = re.compile(r"<a[^>]*>([^<]{1,120})</a>", re.I | re.S)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip().lower()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _count_links(html: str) -> int:
    return len(_LINK_RE.findall(html or ""))


def _anchor_stuffing(html: str) -> dict[str, Any]:
    anchors = [a.strip().lower() for a in _ANCHOR_TEXT_RE.findall(html or "") if a.strip()]
    if len(anchors) <= 3:
        return {"ok": True, "code": "anchor_stuffing", "level": "passed", "message": "Anchor ổn.", "score_delta": 0}
    from collections import Counter

    counts = Counter(anchors)
    worst, n = counts.most_common(1)[0]
    if n >= 3:
        return {
            "ok": False,
            "code": "anchor_stuffing",
            "level": "error",
            "message": f"Anchor «{worst[:40]}» lặp {n} lần — có thể bị coi là spam.",
            "score_delta": -25,
        }
    if n == 2 and len(anchors) >= 5:
        return {
            "ok": True,
            "code": "anchor_stuffing",
            "level": "warning",
            "message": "Nhiều anchor tương tự — nên đa dạng hóa.",
            "score_delta": -8,
        }
    return {"ok": True, "code": "anchor_stuffing", "level": "passed", "message": "Anchor ổn.", "score_delta": 0}


def _link_stuffing(html: str) -> dict[str, Any]:
    n = _count_links(html)
    if n > 8:
        return {
            "ok": False,
            "code": "link_stuffing",
            "level": "error",
            "message": f"Quá nhiều link ({n}) — tối đa khuyến nghị 6–8.",
            "score_delta": -20,
        }
    if n > 5:
        return {
            "ok": True,
            "code": "link_stuffing",
            "level": "warning",
            "message": f"Có {n} link — cân nhắc giảm bớt.",
            "score_delta": -10,
        }
    return {"ok": True, "code": "link_stuffing", "level": "passed", "message": f"Số link ({n}) hợp lý.", "score_delta": 0}


def _main_site_links(html: str, main_site_url: str) -> dict[str, Any]:
    if not main_site_url:
        return {
            "ok": True,
            "code": "main_site_links",
            "level": "passed",
            "message": "Chưa cấu hình URL website chính.",
            "score_delta": 0,
            "count": 0,
        }
    n = count_links_to_host(html, main_site_url)
    if n > 3:
        return {
            "ok": False,
            "code": "main_site_links",
            "level": "error",
            "message": f"Có {n} link về website chính — tối đa 2–3 link.",
            "score_delta": -30,
            "count": n,
        }
    if n == 3:
        return {
            "ok": True,
            "code": "main_site_links",
            "level": "warning",
            "message": "Đang dùng tối đa 3 link về site chính.",
            "score_delta": -5,
            "count": n,
        }
    return {
        "ok": True,
        "code": "main_site_links",
        "level": "passed",
        "message": f"{n} link về site chính (≤3).",
        "score_delta": 0,
        "count": n,
    }


def _duplicate_content(user_id: int, html: str, *, exclude_post_id: str | None = None) -> dict[str, Any]:
    for p in list_posts(user_id):
        if exclude_post_id and str(p.get("id")) == str(exclude_post_id):
            continue
        other = str(p.get("html_content") or "")
        sim = _similarity(html, other)
        if sim >= 0.92:
            return {
                "ok": False,
                "code": "duplicate_content",
                "level": "error",
                "message": f"Trùng ~{int(sim * 100)}% với bài «{p.get('title') or p.get('id')}».",
                "score_delta": -35,
            }
    return {"ok": True, "code": "duplicate_content", "level": "passed", "message": "Không trùng bài khác.", "score_delta": 0}


def _copy_source(html: str, source_content: str) -> dict[str, Any]:
    if not source_content:
        return {"ok": True, "code": "copy_source", "level": "passed", "message": "—", "score_delta": 0}
    sim = _similarity(html, source_content)
    if sim >= 0.88:
        return {
            "ok": False,
            "code": "copy_source",
            "level": "error",
            "message": f"Gần như copy bài gốc (~{int(sim * 100)}%). Cần viết lại Web 2.0.",
            "score_delta": -40,
        }
    if sim >= 0.72:
        return {
            "ok": True,
            "code": "copy_source",
            "level": "warning",
            "message": f"Giống bài gốc ~{int(sim * 100)}% — nên spin thêm.",
            "score_delta": -15,
        }
    return {"ok": True, "code": "copy_source", "level": "passed", "message": "Đã viết lại, không copy 100%.", "score_delta": 0}


def _required_fields(title: str, html: str, account_id: str) -> dict[str, Any]:
    missing = []
    if not str(title or "").strip():
        missing.append("title")
    if len(_norm(html)) < 80:
        missing.append("content")
    if not str(account_id or "").strip():
        missing.append("account")
    if missing:
        return {
            "ok": False,
            "code": "required_fields",
            "level": "error",
            "message": "Thiếu: " + ", ".join(missing),
            "score_delta": -50,
        }
    return {"ok": True, "code": "required_fields", "level": "passed", "message": "Đủ title, content, account.", "score_delta": 0}


def _daily_quota(user_id: int, account_id: str) -> dict[str, Any]:
    if not str(account_id or "").strip():
        return {"ok": True, "code": "daily_quota", "level": "passed", "message": "—", "score_delta": 0, "count": 0}
    settings = get_settings(user_id)
    limit = int(settings.get("max_posts_per_account_per_day") or 3)
    n = count_account_posts_today(account_id, user_id)
    if n >= limit:
        return {
            "ok": False,
            "code": "daily_quota",
            "level": "error",
            "message": f"Site đã đăng {n}/{limit} bài hôm nay — tối đa {limit} bài/ngày/site.",
            "score_delta": -50,
            "count": n,
            "limit": limit,
        }
    if n == limit - 1:
        return {
            "ok": True,
            "code": "daily_quota",
            "level": "warning",
            "message": f"Sắp đạt giới hạn ({n + 1}/{limit} bài/ngày).",
            "score_delta": -5,
            "count": n,
            "limit": limit,
        }
    return {
        "ok": True,
        "code": "daily_quota",
        "level": "passed",
        "message": f"{n}/{limit} bài hôm nay trên site này.",
        "score_delta": 0,
        "count": n,
        "limit": limit,
    }


def run_web20_safety_checks(
    user_id: int,
    *,
    title: str,
    html_content: str,
    account_id: str,
    main_site_url: str = "",
    source_content: str = "",
    exclude_post_id: str | None = None,
) -> dict[str, Any]:
    checks = [
        _required_fields(title, html_content, account_id),
        _daily_quota(user_id, account_id),
        _duplicate_content(user_id, html_content, exclude_post_id=exclude_post_id),
        _copy_source(html_content, source_content),
        _link_stuffing(html_content),
        _anchor_stuffing(html_content),
        _main_site_links(html_content, main_site_url),
    ]
    score = 100
    for c in checks:
        score += int(c.get("score_delta") or 0)
    score = max(0, min(100, score))
    errors = [c for c in checks if not c.get("ok")]
    warnings = [c for c in checks if c.get("ok") and c.get("level") == "warning"]
    passed = len(errors) == 0 and score >= 60
    return {
        "score": score,
        "passed": passed,
        "can_publish": passed and score >= 70,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
