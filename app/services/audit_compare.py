"""Compare two technical audit runs — score delta and issue diff."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse


def _safe_list(val: object) -> list:
    return val if isinstance(val, list) else []


def _safe_dict(val: object) -> dict:
    return val if isinstance(val, dict) else {}


def _norm_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u if "://" in u else f"https://{u}")
        host = (p.netloc or p.path or "").lower().rstrip("/")
        path = (p.path or "/").rstrip("/") or "/"
        if not p.netloc and host:
            path = f"/{host}{path}" if not path.startswith("/") else path
            host = ""
        return f"{host}{path}".lower()
    except Exception:
        return u.lower().rstrip("/")


def audit_health_score(audit: dict[str, Any]) -> float | None:
    dash = _safe_dict(audit.get("technical_dashboard_v2"))
    if dash.get("technical_health_score") is not None:
        try:
            return round(float(dash["technical_health_score"]), 1)
        except (TypeError, ValueError):
            pass
    ts = _safe_dict(audit.get("technical_summary"))
    if ts.get("health_score") is not None:
        try:
            return round(float(ts["health_score"]), 1)
        except (TypeError, ValueError):
            pass
    return None


def collect_audit_issues(audit: dict[str, Any]) -> list[dict[str, Any]]:
    dash = _safe_dict(audit.get("technical_dashboard_v2"))
    issues = _safe_list(dash.get("issues"))
    if issues:
        return [i for i in issues if isinstance(i, dict)]
    norm = _safe_list(audit.get("normalized_issues"))
    if norm:
        return [i for i in norm if isinstance(i, dict)]
    legacy = _safe_list(audit.get("issues"))
    return [i for i in legacy if isinstance(i, dict)]


def issue_identity(issue: dict[str, Any]) -> str:
    """Stable fingerprint — dedupe by issue type + affected URL scope."""
    itype = str(
        issue.get("issue_type")
        or issue.get("_issue_type")
        or issue.get("type")
        or issue.get("id")
        or "issue"
    ).lower()
    urls: list[str] = []
    for raw in _safe_list(issue.get("affected_urls")) + _safe_list(issue.get("sample_urls")):
        n = _norm_url(str(raw))
        if n:
            urls.append(n)
    u0 = issue.get("url")
    if u0:
        n0 = _norm_url(str(u0))
        if n0:
            urls.append(n0)
    urls = sorted(set(urls))
    if len(urls) == 1:
        return f"{itype}|{urls[0]}"
    if not urls:
        return f"{itype}|__site__"
    blob = "|".join(urls)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{itype}|multi|{digest}"


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    urls = _safe_list(issue.get("affected_urls")) or _safe_list(issue.get("sample_urls"))
    if issue.get("url") and not urls:
        urls = [issue.get("url")]
    return {
        "issue_id": issue.get("issue_id") or issue.get("id"),
        "issue_type": issue.get("issue_type") or issue.get("type") or issue.get("id"),
        "title": issue.get("title") or issue.get("message") or issue.get("issue_type") or "—",
        "severity": issue.get("severity"),
        "priority_score": issue.get("priority_score"),
        "priority_tier": issue.get("priority_tier"),
        "affected_urls": urls[:5],
        "affected_url_count": len(urls) or int(issue.get("count") or 1),
    }


def compare_technical_audits(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """
    Compare older/base audit to newer/target audit.

    fixed — present in base, absent in target
    new — present in target, absent in base
    remaining — present in both
    """
    base_map: dict[str, dict[str, Any]] = {}
    for issue in collect_audit_issues(base):
        base_map[issue_identity(issue)] = issue
    target_map: dict[str, dict[str, Any]] = {}
    for issue in collect_audit_issues(target):
        target_map[issue_identity(issue)] = issue

    base_keys = set(base_map)
    target_keys = set(target_map)

    fixed_keys = base_keys - target_keys
    new_keys = target_keys - base_keys
    remaining_keys = base_keys & target_keys

    score_before = audit_health_score(base)
    score_after = audit_health_score(target)
    score_delta = None
    if score_before is not None and score_after is not None:
        score_delta = round(score_after - score_before, 1)

    return {
        "base_id": base.get("id") or base.get("audit_id"),
        "target_id": target.get("id") or target.get("audit_id"),
        "base_at": base.get("at"),
        "target_at": target.get("at"),
        "domain": target.get("domain") or base.get("domain"),
        "score_before": score_before,
        "score_after": score_after,
        "score_delta": score_delta,
        "fixed": [_issue_summary(base_map[k]) for k in sorted(fixed_keys)],
        "new": [_issue_summary(target_map[k]) for k in sorted(new_keys)],
        "remaining": [_issue_summary(target_map[k]) for k in sorted(remaining_keys)],
        "counts": {
            "fixed": len(fixed_keys),
            "new": len(new_keys),
            "remaining": len(remaining_keys),
            "base_total": len(base_keys),
            "target_total": len(target_keys),
        },
    }
