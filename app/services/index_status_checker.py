"""Index status checker — GSC URL Inspection, SERP API, then technical fallback."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.services.gsc_client import (
    GscClient,
    GscClientError,
    GscNotConnectedError,
    GscPermissionError,
    GscQuotaError,
)
from app.services.index_control_service import _DomainCache, check_website_url, normalize_domain
from app.services.serp_fetcher import fetch_serp_for_keyword, normalize_serp_url
from app.services.url_safety import assert_public_http_url
from app.services.crawler import normalize_url

logger = logging.getLogger(__name__)

INDEX_STATUS_INDEXED = "indexed"
INDEX_STATUS_NOT_FOUND = "not_found"
INDEX_STATUS_UNKNOWN = "unknown"

SOURCE_GSC = "gsc"
SOURCE_SERP = "serp"
SOURCE_TECHNICAL = "technical"

_SOCIAL_HOSTS = frozenset(
    {
        "facebook.com",
        "fb.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "linkedin.com",
        "pinterest.com",
        "medium.com",
        "reddit.com",
    }
)

_PROVIDER_LEAK_RE = re.compile(r"sinbyte", re.I)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_message(text: str) -> str:
    s = str(text or "").strip()
    if _PROVIDER_LEAK_RE.search(s):
        return ""
    return s[:500]


def _is_social_url(url: str) -> bool:
    host = normalize_domain(urlparse(url).hostname or "")
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _SOCIAL_HOSTS)


def _url_matches_gsc_property(url: str, site_url: str) -> bool:
    site = (site_url or "").strip()
    if not site:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if site.startswith("sc-domain:"):
        dom = site[len("sc-domain:") :].strip().lower()
        if not dom or not host:
            return False
        return host == dom or host == f"www.{dom}" or host.endswith(f".{dom}")
    site_base = site.rstrip("/").lower()
    url_lower = url.split("#")[0].rstrip("/").lower()
    if url_lower.startswith(site_base):
        return True
    if site_base.startswith("https://www."):
        alt = "https://" + site_base[len("https://www.") :]
        if url_lower.startswith(alt.rstrip("/")):
            return True
    if site_base.startswith("https://") and not site_base.startswith("https://www."):
        alt = site_base.replace("https://", "https://www.", 1)
        if url_lower.startswith(alt.rstrip("/")):
            return True
    return False


def _list_gsc_properties(client: GscClient) -> list[str]:
    data = client.list_sites()
    entries = data.get("siteEntry") or []
    out: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        su = str(entry.get("siteUrl") or "").strip()
        if su:
            out.append(su)
    return out


def resolve_gsc_property_for_url(
    client: GscClient,
    url: str,
    *,
    properties: list[str] | None = None,
) -> str | None:
    props = properties if properties is not None else _list_gsc_properties(client)
    matches = [p for p in props if _url_matches_gsc_property(url, p)]
    if not matches:
        return None
    matches.sort(key=len, reverse=True)
    return matches[0]


def _interpret_gsc_indexed(inspection: dict[str, Any]) -> bool | None:
    verdict = str(inspection.get("index_verdict") or "").upper()
    coverage = str(inspection.get("coverage_state") or "").lower()
    if verdict == "PASS":
        if "indexed" in coverage and "not indexed" not in coverage:
            return True
        if "submitted and indexed" in coverage:
            return True
    if verdict in ("FAIL", "PARTIAL"):
        return False
    if "not indexed" in coverage or "not on google" in coverage or "excluded" in coverage:
        return False
    if verdict == "NEUTRAL":
        return None
    return None


def _gsc_indexed_message() -> str:
    return "Đã tìm thấy URL trên Google Search Console."


def _gsc_not_indexed_message(inspection: dict[str, Any]) -> str:
    coverage = str(inspection.get("coverage_state") or "").strip()
    if coverage:
        cov = coverage.lower()
        if "noindex" in cov:
            return "URL có thể bị noindex."
        if "robots" in cov:
            return "Website có thể chặn bot bằng robots.txt."
        if "canonical" in cov:
            return "URL canonical sang trang khác."
        if "redirect" in cov:
            return "URL chuyển hướng sang trang khác."
    return "Chưa thấy URL xuất hiện trong kết quả tìm kiếm."


def _serp_url_in_results(target_url: str, snap: dict[str, Any]) -> bool:
    target_norm = normalize_serp_url(target_url)
    for u in snap.get("serp_urls") or []:
        if normalize_serp_url(str(u)) == target_norm:
            return True
    return False


def _check_serp_indexed(url: str) -> tuple[bool | None, str]:
    """
    Return (found, meta).
    found: True indexed in SERP, False not in SERP, None SERP unavailable/error.
    """
    parsed = urlparse(url)
    domain = normalize_domain(parsed.hostname or "")

    queries: list[str] = []
    if domain:
        queries.append(f"site:{domain}")
    queries.append(f'"{url}"')

    saw_success = False
    last_source = ""
    for q in queries[:2]:
        try:
            snap = fetch_serp_for_keyword(q, top_n=30, use_cache=True)
        except Exception as exc:
            logger.warning("index_serp_fetch_error: %s", type(exc).__name__)
            continue

        source = str(snap.get("source") or "")
        last_source = source or last_source
        if source in ("disabled", "empty", "none"):
            continue

        urls = snap.get("serp_urls") or []
        if urls:
            saw_success = True
        if _serp_url_in_results(url, snap):
            return True, source or SOURCE_SERP

    if saw_success:
        return False, last_source or SOURCE_SERP
    return None, last_source or ""


def _technical_message(row: dict[str, Any], *, url: str) -> str:
    suggestion = _sanitize_message(str(row.get("suggestion") or ""))
    main_issue = str(row.get("main_issue") or "").lower()

    if _is_social_url(url):
        idx = str(row.get("indexability") or "")
        if idx == "error":
            return "Social/entity có thể chặn bot hoặc không cho index."
        if idx in ("blocked", "warning"):
            return "Social/entity có thể chặn bot hoặc không cho index."

    if "meta noindex" in main_issue or row.get("checks", {}).get("meta_noindex") == "fail":
        return "URL có thể bị noindex."
    if "x-robots" in main_issue or row.get("checks", {}).get("x_robots_noindex") == "fail":
        return "URL có thể bị noindex."
    if "robots" in main_issue or row.get("checks", {}).get("robots_txt") == "fail":
        return "Website có thể chặn bot bằng robots.txt."
    if "canonical" in main_issue or row.get("checks", {}).get("canonical") == "fail":
        return "URL canonical sang trang khác."

    if suggestion:
        low = suggestion.lower()
        if "noindex" in low:
            return "URL có thể bị noindex."
        if "robots" in low:
            return "Website có thể chặn bot bằng robots.txt."
        if "canonical" in low:
            return "URL canonical sang trang khác."
        if "timeout" in low or "không truy cập" in low:
            return "Không kiểm tra được URL — thử lại sau."

    indexability = str(row.get("indexability") or "")
    if indexability == "error":
        return "Không kiểm tra được URL — thử lại sau."
    return "Chưa thấy URL xuất hiện trong kết quả tìm kiếm."


def _technical_check(url: str, *, domain: str, cache: _DomainCache) -> dict[str, Any]:
    try:
        return check_website_url(url, domain=domain, cache=cache)
    except Exception:
        return {"indexability": "error", "main_issue": "HTTP error", "suggestion": ""}


def _result(
    *,
    url: str,
    index_status: str,
    message: str,
    source: str,
    checked_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "url": url,
        "index_status": index_status,
        "message": _sanitize_message(message) or message,
        "source": source,
        "checked_at": checked_at or _utc_now_iso(),
    }
    if extra:
        out.update(extra)
    return out


def check_url_index_status(
    db: Session,
    *,
    url: str,
    user_id: int,
    cache: _DomainCache | None = None,
    gsc_client: GscClient | None = None,
    gsc_properties: list[str] | None = None,
    skip_technical: bool = False,
) -> dict[str, Any]:
    """Check one URL — GSC first, then SERP, optional technical signals."""
    del db  # reserved for future per-user settings
    checked_at = _utc_now_iso()
    domain_cache = cache or _DomainCache()

    try:
        safe = assert_public_http_url(url, label="URL")
        normalized = normalize_url(safe)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return _result(
            url=url,
            index_status=INDEX_STATUS_UNKNOWN,
            message=_sanitize_message(str(detail)) or "URL không hợp lệ.",
            source=SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    domain = normalize_domain(urlparse(normalized).hostname or "")

    client = gsc_client
    if client is None:
        client = GscClient.for_user(user_id)

    if client is not None:
        prop = resolve_gsc_property_for_url(client, normalized, properties=gsc_properties)
        if prop:
            try:
                insp = client.inspect_url(site_url=prop, inspection_url=normalized)
                indexed = _interpret_gsc_indexed(insp)
                if indexed is True:
                    return _result(
                        url=normalized,
                        index_status=INDEX_STATUS_INDEXED,
                        message=_gsc_indexed_message(),
                        source=SOURCE_GSC,
                        checked_at=checked_at,
                    )
                if indexed is False:
                    return _result(
                        url=normalized,
                        index_status=INDEX_STATUS_NOT_FOUND,
                        message=_gsc_not_indexed_message(insp),
                        source=SOURCE_GSC,
                        checked_at=checked_at,
                    )
            except GscQuotaError:
                logger.info("index_check_gsc_quota user_id=%s", user_id)
            except (GscPermissionError, GscClientError) as exc:
                logger.info("index_check_gsc_error user_id=%s code=%s", user_id, getattr(exc, "code", ""))
            except Exception:
                logger.warning("index_check_gsc_unexpected user_id=%s", user_id)

    serp_found, serp_meta = _check_serp_indexed(normalized)
    if serp_found is True:
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_INDEXED,
            message="Đã tìm thấy URL trên công cụ tìm kiếm.",
            source=SOURCE_SERP,
            checked_at=checked_at,
        )

    if skip_technical:
        if serp_found is False:
            return _result(
                url=normalized,
                index_status=INDEX_STATUS_NOT_FOUND,
                message="Chưa thấy URL trong kết quả tìm kiếm.",
                source=SOURCE_SERP,
                checked_at=checked_at,
            )
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_UNKNOWN,
            message="Không kiểm tra được lúc này — thử lại sau.",
            source=SOURCE_SERP if serp_meta else SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    tech = _technical_check(normalized, domain=domain, cache=domain_cache)

    if serp_found is False:
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_NOT_FOUND,
            message=_technical_message(tech, url=normalized),
            source=SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    if str(tech.get("indexability") or "") == "error":
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_UNKNOWN,
            message=_technical_message(tech, url=normalized),
            source=SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    if _is_social_url(normalized) and str(tech.get("indexability") or "") in ("blocked", "error", "warning"):
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_UNKNOWN,
            message="Social/entity có thể chặn bot hoặc không cho index.",
            source=SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    if serp_meta in ("disabled", "") and str(tech.get("indexability") or "") != "indexable":
        return _result(
            url=normalized,
            index_status=INDEX_STATUS_UNKNOWN,
            message=_technical_message(tech, url=normalized),
            source=SOURCE_TECHNICAL,
            checked_at=checked_at,
        )

    return _result(
        url=normalized,
        index_status=INDEX_STATUS_NOT_FOUND,
        message=_technical_message(tech, url=normalized),
        source=SOURCE_TECHNICAL,
        checked_at=checked_at,
    )


def check_urls_index_status(
    db: Session,
    *,
    user_id: int,
    urls: list[str],
) -> list[dict[str, Any]]:
    cache = _DomainCache()
    gsc_client = GscClient.for_user(user_id)
    out: list[dict[str, Any]] = []
    for raw in urls:
        text = (raw or "").strip()
        if not text:
            continue
        out.append(
            check_url_index_status(
                db,
                url=text,
                user_id=user_id,
                cache=cache,
                gsc_client=gsc_client,
            )
        )
    return out


def format_http_status_label(row: dict[str, Any]) -> str:
    status_code = row.get("status_code")
    indexability = str(row.get("indexability") or "")
    main_issue = str(row.get("main_issue") or "").lower()

    if indexability == "error" or status_code is None:
        if "timeout" in main_issue:
            return "Timeout"
        return "Lỗi"

    label = str(status_code)
    if row.get("redirected"):
        label += " → redirect"
    return label


def format_indexability_label(row: dict[str, Any]) -> str:
    checks = row.get("checks") or {}
    if checks.get("meta_noindex") == "fail" or checks.get("x_robots_noindex") == "fail":
        return "Noindex"
    if checks.get("robots_txt") == "fail":
        return "Robots chặn"
    if checks.get("canonical") == "fail":
        return "Canonical khác"

    indexability = str(row.get("indexability") or "")
    if indexability == "indexable":
        return "Có thể index"
    if indexability == "blocked":
        return "Bị chặn index"
    if indexability == "error":
        return "—"
    return "Cần theo dõi"


def check_url_response_details(
    url: str,
    *,
    cache: _DomainCache | None = None,
) -> dict[str, Any]:
    """HTTP status, redirect, noindex, robots, canonical, title."""
    domain_cache = cache or _DomainCache()
    checked_at = _utc_now_iso()

    try:
        safe = assert_public_http_url(url, label="URL")
        normalized = normalize_url(safe)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return {
            "url": url,
            "http_status": "Lỗi",
            "indexability": "—",
            "page_title": "—",
            "message": _sanitize_message(str(detail)) or "URL không hợp lệ.",
            "checked_at": checked_at,
        }

    domain = normalize_domain(urlparse(normalized).hostname or "")
    tech = _technical_check(normalized, domain=domain, cache=domain_cache)
    suggestion = _sanitize_message(str(tech.get("suggestion") or ""))
    main_issue = str(tech.get("main_issue") or "")

    return {
        "url": normalized,
        "http_status": format_http_status_label(tech),
        "indexability": format_indexability_label(tech),
        "page_title": str(tech.get("page_title") or "").strip() or "—",
        "message": suggestion or main_issue or "",
        "final_url": tech.get("final_url"),
        "redirected": bool(tech.get("redirected")),
        "checked_at": checked_at,
    }
