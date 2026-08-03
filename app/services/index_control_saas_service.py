"""Index Control SaaS — quota, submit indexing, check free."""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from random import uniform
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexNowSubmitLog
from app.services.index_check_providers import (
    INDEX_STATUS_CAPTCHA_REQUIRED,
    INDEX_STATUS_ERROR,
    INDEX_STATUS_INDEX,
    INDEX_STATUS_NO_INDEX,
    INDEX_STATUS_PENDING_RETRY,
    INDEX_STATUS_UNKNOWN,
    GoogleSiteSearchProvider,
)
from app.services.index_control_history_store import (
    append_check_session_item,
    create_check_session,
    save_check_history,
)
from app.services.index_control_service import _DomainCache, check_website_url, normalize_domain
from app.services.indexnow_log_store import save_indexnow_logs
from app.services.index_status_checker import check_url_response_details
from app.services.sinbyte_service import resolve_api_key, submit_urls as sinbyte_submit_urls
from app.services.url_safety import assert_public_http_url
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.user_scope import is_admin_role
from app.services.submit_project_store import make_project_name, normalize_project_name
from app.services.crawler import normalize_url

logger = logging.getLogger(__name__)

FEATURE_SUBMIT = "index_control_submit"
DEFAULT_MONTHLY_LIMIT = int(os.getenv("INDEX_CONTROL_SUBMIT_MONTHLY_DEFAULT", "50") or "50")
MAX_CHECK_FREE_URLS = int(os.getenv("INDEX_CONTROL_CHECK_FREE_MAX_URLS", "100") or "100")
MAX_SUBMIT_URLS = 100

CHECK_FREE_DISCLAIMER = (
    "Kết quả check miễn phí có tính tham khảo. "
    "Website đã kết nối Google Search Console sẽ có độ chính xác cao hơn."
)

_CHECK_UI_STATUS = {
    INDEX_STATUS_INDEX: ("indexed", "Index"),
    INDEX_STATUS_NO_INDEX: ("not_indexed", "No"),
    INDEX_STATUS_UNKNOWN: ("unknown", "Unknown"),
    INDEX_STATUS_ERROR: ("error", "Error"),
    INDEX_STATUS_CAPTCHA_REQUIRED: ("captcha_required", "Captcha"),
    INDEX_STATUS_PENDING_RETRY: ("pending_retry", "Retry"),
}

_CHECK_HISTORY_INDEXABILITY = {
    INDEX_STATUS_INDEX: "indexable",
    INDEX_STATUS_NO_INDEX: "warning",
    INDEX_STATUS_UNKNOWN: "error",
    INDEX_STATUS_ERROR: "error",
    INDEX_STATUS_CAPTCHA_REQUIRED: "warning",
    INDEX_STATUS_PENDING_RETRY: "warning",
}

CHECK_DELAY_MIN_SECONDS = float(os.getenv("INDEX_CONTROL_CHECK_DELAY_MIN_SECONDS", "0.4") or "0.4")
CHECK_DELAY_MAX_SECONDS = float(os.getenv("INDEX_CONTROL_CHECK_DELAY_MAX_SECONDS", "1.2") or "1.2")
CHECK_PAUSE_EVERY = int(os.getenv("INDEX_CONTROL_CHECK_PAUSE_EVERY", "10") or "10")
CHECK_PAUSE_SECONDS = float(os.getenv("INDEX_CONTROL_CHECK_PAUSE_SECONDS", "8") or "8")
CHECK_CAPTCHA_PAUSE_SECONDS = float(os.getenv("INDEX_CONTROL_CHECK_CAPTCHA_PAUSE_SECONDS", "20") or "20")
CHECK_RETRY_LIMIT = int(os.getenv("INDEX_CONTROL_CHECK_RETRY_LIMIT", "1") or "1")
CHECK_PARALLEL_WORKERS = int(os.getenv("INDEX_CONTROL_CHECK_PARALLEL_WORKERS", "3") or "3")

MSG_SUCCESS = "Submit thành công."
MSG_FAILURE = "Submit thất bại, vui lòng thử lại sau."
MSG_UNAVAILABLE = "Hệ thống submit hiện chưa sẵn sàng, vui lòng thử lại sau."
MSG_QUOTA = "Bạn đã hết link submit trong gói hiện tại."

_PROVIDER_LEAK_RE = re.compile(r"sinbyte", re.I)


def _sanitize_user_text(text: str, *, fallback: str = "") -> str:
    s = str(text or "").strip()
    if not s or _PROVIDER_LEAK_RE.search(s):
        return fallback
    return s[:500]


def _admin_batch_note(api_result: dict[str, Any]) -> str:
    parts = [
        f"provider=third_party",
        f"http={api_result.get('http_status')}",
        f"code={api_result.get('error') or 'ok'}",
    ]
    raw = _sanitize_user_text(str(api_result.get("message") or ""), fallback="")
    if raw:
        parts.append(f"detail={raw[:200]}")
    return "; ".join(parts)[:1000]


def _sleep_between_urls(index: int, total: int) -> None:
    if index >= total:
        return
    if CHECK_DELAY_MAX_SECONDS > 0 and CHECK_DELAY_MAX_SECONDS >= CHECK_DELAY_MIN_SECONDS:
        time.sleep(uniform(CHECK_DELAY_MIN_SECONDS, CHECK_DELAY_MAX_SECONDS))
    if CHECK_PAUSE_EVERY > 0 and index % CHECK_PAUSE_EVERY == 0:
        time.sleep(CHECK_PAUSE_SECONDS)


def _indexability_status(technical: dict[str, Any]) -> str:
    checks = technical.get("checks") or {}
    if checks.get("meta_noindex") == "fail" or checks.get("x_robots_noindex") == "fail":
        return "NOINDEX"
    if checks.get("robots_txt") == "fail":
        return "ROBOTS_BLOCKED"
    if checks.get("canonical") == "fail":
        return "CANONICAL_MISMATCH"
    state = str(technical.get("indexability") or "").lower()
    if state == "indexable":
        return "INDEXABLE"
    if state == "blocked":
        return "BLOCKED"
    if state == "warning":
        return "WARNING"
    return "UNKNOWN"


def _build_index_check_row(url: str, provider_row: dict[str, Any], technical: dict[str, Any]) -> dict[str, Any]:
    title = provider_row.get("title") or technical.get("page_title") or ""
    reason = str(provider_row.get("reason") or technical.get("suggestion") or technical.get("main_issue") or "").strip()
    return {
        "url": url,
        "query": provider_row.get("query") or f"site:{url}",
        "index_status": provider_row.get("index_status") or INDEX_STATUS_UNKNOWN,
        "matched_url": provider_row.get("matched_url") or None,
        "title": title or None,
        "page_title": title or None,
        "reason": reason,
        "message": reason,
        "http_status": str(technical.get("status_code")) if technical.get("status_code") is not None else "—",
        "status_code": technical.get("status_code"),
        "indexability": technical.get("indexability") or "error",
        "indexability_status": _indexability_status(technical),
        "checked_at": provider_row.get("checked_at") or datetime.now(timezone.utc).isoformat(),
        "retry_count": int(provider_row.get("retry_count") or 0),
        "final_url": technical.get("final_url") or provider_row.get("matched_url"),
        "checks": technical.get("checks") or {},
        "main_issue": technical.get("main_issue") or reason or "HTTP error",
        "severity": technical.get("severity") or ("low" if provider_row.get("index_status") == INDEX_STATUS_INDEX else "medium"),
        "suggestion": technical.get("suggestion") or reason,
        "source": "google_site_search",
        "evidence": provider_row.get("evidence"),
        "target_url_normalized": provider_row.get("target_url_normalized"),
        "candidate_urls": provider_row.get("candidate_urls"),
        "match_type": provider_row.get("match_type"),
    }


def _provider_check_with_retry(
    provider: GoogleSiteSearchProvider,
    normalized: str,
    *,
    query_url: str | None = None,
) -> dict[str, Any]:
    provider_row = provider.check_url(normalized, retry_count=0, query_url=query_url)
    if provider_row.get("index_status") == INDEX_STATUS_PENDING_RETRY and CHECK_RETRY_LIMIT > 0:
        provider_row = provider.check_url(normalized, retry_count=1, query_url=query_url)
    return provider_row


def _run_real_index_check(
    raw_url: str,
    *,
    cache: _DomainCache,
    provider: GoogleSiteSearchProvider,
    query_url: str | None = None,
) -> dict[str, Any]:
    safe = assert_public_http_url(raw_url, label="URL")
    normalized = normalize_url(safe)
    domain = normalize_domain(urlparse(normalized).hostname or "")
    qurl = query_url or safe

    with ThreadPoolExecutor(max_workers=2) as pool:
        tech_future = pool.submit(check_website_url, normalized, domain=domain, cache=cache)
        prov_future = pool.submit(_provider_check_with_retry, provider, normalized, query_url=qurl)
        technical = tech_future.result()
        provider_row = prov_future.result()

    if provider_row.get("index_status") == INDEX_STATUS_CAPTCHA_REQUIRED:
        # Short pause only — batch stop/resume is handled by the stream.
        time.sleep(min(max(CHECK_CAPTCHA_PAUSE_SECONDS, 0.0), 3.0))
    return _build_index_check_row(normalized, provider_row, technical)


def _error_index_row(raw_url: str, *, exc: Exception | None = None) -> dict[str, Any]:
    reason = f"Lỗi xử lý URL: {type(exc).__name__}" if exc else "Lỗi xử lý URL."
    return {
        "url": raw_url,
        "query": f"site:{raw_url}",
        "index_status": INDEX_STATUS_ERROR,
        "reason": reason,
        "http_status": "—",
        "indexability": "error",
        "indexability_status": "UNKNOWN",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "retry_count": 0,
        "checks": {},
        "main_issue": "Processing error",
        "severity": "high",
        "suggestion": "Thử lại sau.",
        "source": "google_site_search",
    }


def _run_index_checks_parallel(
    urls: list[str],
    *,
    on_result=None,
) -> list[dict[str, Any]]:
    """Check URLs with limited parallelism; optional callback per finished URL."""
    if not urls:
        return []

    workers = max(1, min(CHECK_PARALLEL_WORKERS, len(urls)))
    ordered: dict[str, dict[str, Any]] = {}
    completed = 0

    def _work(target_url: str) -> dict[str, Any]:
        cache = _DomainCache()
        provider = GoogleSiteSearchProvider()
        try:
            return _run_real_index_check(target_url, cache=cache, provider=provider)
        except Exception as exc:
            logger.warning("check_free_url_failed url=%s err=%s", target_url, type(exc).__name__)
            return _error_index_row(target_url, exc=exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_work, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = _error_index_row(url, exc=exc)
            ordered[url] = row
            completed += 1
            if on_result is not None:
                on_result(row, completed, len(urls))
            if completed < len(urls):
                _sleep_between_urls(completed, len(urls))

    return [ordered[u] for u in urls if u in ordered]


def get_submit_quota_snapshot(db: Session, *, user_id: int, role: str | None) -> dict[str, Any]:
    if is_admin_role(role):
        return {
            "used": usage_tracking_service.get_monthly_usage(db, user_id, FEATURE_SUBMIT),
            "limit": None,
            "remaining": None,
            "is_unlimited": True,
        }

    sub = subscription_service.get_active_subscription(db, user_id)
    plan_id = sub.plan_id if sub else None
    used = usage_tracking_service.get_monthly_usage(db, user_id, FEATURE_SUBMIT)
    remaining = usage_tracking_service.get_quota_remaining(db, user_id, FEATURE_SUBMIT, plan_id=plan_id)

    limit: int | None = None
    is_unlimited = False
    if remaining is None:
        limit_row = plan_service.get_limit_for_feature(db, plan_id, FEATURE_SUBMIT) if plan_id else None
        if limit_row is None or int(limit_row.limit_value) == -1:
            if DEFAULT_MONTHLY_LIMIT <= 0:
                is_unlimited = True
                limit = None
                remaining = None
            else:
                limit = DEFAULT_MONTHLY_LIMIT
                remaining = max(0, limit - used)
        else:
            limit = int(limit_row.limit_value)
            is_unlimited = False
    else:
        limit_row = plan_service.get_limit_for_feature(db, plan_id, FEATURE_SUBMIT) if plan_id else None
        if limit_row is not None:
            limit = int(limit_row.limit_value)
            if limit == -1:
                is_unlimited = True
                limit = None
                remaining = None

    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "is_unlimited": is_unlimited,
    }


def _existing_sent_urls(db: Session, *, user_id: int, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    rows = db.scalars(
        select(IndexNowSubmitLog.url)
        .where(IndexNowSubmitLog.user_id == int(user_id))
        .where(IndexNowSubmitLog.send_status == "sent")
        .where(IndexNowSubmitLog.url.in_(urls))
    ).all()
    return {str(u) for u in rows}


def get_saas_overview(db: Session, *, user_id: int, role: str | None) -> dict[str, Any]:
    quota = get_submit_quota_snapshot(db, user_id=user_id, role=role)

    q = (
        select(IndexNowSubmitLog)
        .where(IndexNowSubmitLog.send_status == "sent")
        .order_by(desc(IndexNowSubmitLog.created_at))
        .limit(5)
    )
    if not is_admin_role(role):
        q = q.where(IndexNowSubmitLog.user_id == int(user_id))

    recent = [
        {
            "url": r.url,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in db.scalars(q).all()
    ]

    lifetime_sent = db.scalar(
        select(func.count(IndexNowSubmitLog.id))
        .where(IndexNowSubmitLog.user_id == int(user_id))
        .where(IndexNowSubmitLog.send_status == "sent")
    ) or 0

    return {
        "ok": True,
        "quota": quota,
        "lifetime_submitted": int(lifetime_sent),
        "recent_submits": recent,
        "is_admin": is_admin_role(role),
    }


def _parse_unique_urls(raw_urls: list[str], *, max_urls: int) -> tuple[list[str], list[dict[str, Any]]]:
    seen: set[str] = set()
    valid: list[str] = []
    errors: list[dict[str, Any]] = []

    for raw in raw_urls:
        text = (raw or "").strip()
        if not text:
            continue
        try:
            safe = assert_public_http_url(text, label="URL")
            normalized = normalize_url(safe)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            errors.append({"url": text[:2000], "status": "error", "message": str(detail)[:500]})
            continue
        if normalized in seen:
            errors.append({"url": normalized, "status": "duplicate", "message": "URL trùng trong danh sách."})
            continue
        seen.add(normalized)
        valid.append(safe)
        if len(valid) >= max_urls:
            break

    return valid, errors


def _submit_payload_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    status = str(meta.get("status") or meta.get("index_status") or "").lower()
    indexed = str(meta.get("indexed") or meta.get("status_label") or "").strip()
    if not indexed:
        if status == "indexed":
            indexed = "Index"
        elif status:
            indexed = "No"
    if indexed not in ("Index", "No"):
        indexed = ""

    http_status = meta.get("http_status") or meta.get("status_code") or ""
    indexability = meta.get("indexability") or ""
    redirect_url = meta.get("redirect_url") or meta.get("final_url") or ""
    broken = str(meta.get("broken") or "").strip()
    if not broken and not indexed:
        broken = "not check indexed"

    return {
        "indexed": indexed,
        "index_status": status,
        "status_code": http_status,
        "http_status": http_status,
        "indexability": indexability,
        "redirect_url": redirect_url,
        "final_url": redirect_url,
        "broken": broken,
        "message": meta.get("message") or "",
    }


def submit_indexing_urls(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    urls: list[str],
    url_meta: dict[str, dict[str, Any]] | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    if not resolve_api_key(db):
        return {
            "ok": False,
            "error": "service_unavailable",
            "message": MSG_UNAVAILABLE,
        }

    valid, parse_errors = _parse_unique_urls(urls, max_urls=MAX_SUBMIT_URLS)
    if not valid and not parse_errors:
        return {"ok": False, "error": "empty_urls", "message": "Nhập ít nhất một URL."}

    quota = get_submit_quota_snapshot(db, user_id=user_id, role=role)
    results: list[dict[str, Any]] = [
        {
            "url": e["url"],
            "status": e["status"],
            **({"message": e["message"]} if e.get("message") else {}),
        }
        for e in parse_errors
    ]

    already = _existing_sent_urls(db, user_id=user_id, urls=valid)
    to_submit: list[str] = []
    for url in valid:
        if url in already:
            results.append({"url": url, "status": "duplicate", "message": "URL đã được gửi trước đó."})
        else:
            to_submit.append(url)

    if not is_admin_role(role) and not quota.get("is_unlimited"):
        remaining = quota.get("remaining")
        if remaining is not None and len(to_submit) > remaining:
            return {
                "ok": False,
                "error": "quota_exceeded",
                "message": MSG_QUOTA,
                "quota": quota,
                "would_use": len(to_submit),
            }

    if not to_submit:
        sent_n = sum(1 for r in results if r.get("status") == "sent")
        dup_n = sum(1 for r in results if r.get("status") == "duplicate")
        err_n = sum(1 for r in results if r.get("status") == "error")
        return {
            "ok": dup_n > 0 and err_n == 0,
            "message": MSG_SUCCESS if sent_n > 0 else (MSG_FAILURE if err_n else ""),
            "items": results,
            "summary": {"sent": sent_n, "duplicate": dup_n, "error": err_n},
            "quota": quota,
        }

    primary_domain = normalize_domain(urlparse(to_submit[0]).hostname or "") or "batch"
    api_result = sinbyte_submit_urls(
        db,
        urls=to_submit,
        name=f"SEOAuto user {user_id}",
    )

    send_status = "sent" if api_result.get("ok") else "failed"
    meta_map = url_meta or {}
    log_items = [
        {
            "url": u,
            "send_status": send_status,
            "http_status": api_result.get("http_status"),
            "note": _admin_batch_note(api_result),
            "payload": _submit_payload_from_meta(meta_map.get(u) or {}),
        }
        for u in to_submit
    ]
    project_id: int | None = None
    try:
        project_id = save_indexnow_logs(
            db,
            user_id=user_id,
            domain=primary_domain[:253],
            api_http_status=api_result.get("http_status"),
            submit_status="success" if send_status == "sent" else "failed",
            batch_note=_admin_batch_note(api_result),
            items=log_items,
            project_name=normalize_project_name(project_name, len(log_items)),
        )
    except Exception:
        logger.exception("submit_indexing_log_failed user_id=%s", user_id)
        db.rollback()

    if send_status == "sent":
        for u in to_submit:
            results.append({"url": u, "status": "sent"})
            if not is_admin_role(role):
                try:
                    usage_tracking_service.record_successful_usage(
                        db,
                        user_id,
                        FEATURE_SUBMIT,
                        quantity=1,
                        metadata={"url": u, "domain": primary_domain},
                    )
                except Exception:
                    logger.warning("submit_indexing_usage_failed user_id=%s", user_id)
                    db.rollback()
        top_message = MSG_SUCCESS
        ok = True
    else:
        for u in to_submit:
            results.append({"url": u, "status": "error"})
        top_message = MSG_FAILURE
        ok = False

    sent_n = sum(1 for r in results if r.get("status") == "sent")
    dup_n = sum(1 for r in results if r.get("status") == "duplicate")
    err_n = sum(1 for r in results if r.get("status") == "error")

    return {
        "ok": ok,
        "message": top_message,
        "items": results,
        "summary": {"sent": sent_n, "duplicate": dup_n, "error": err_n},
        "quota": get_submit_quota_snapshot(db, user_id=user_id, role=role),
        "project_id": project_id,
    }


def _check_result_to_item(row: dict[str, Any]) -> dict[str, Any]:
    index_status = str(row.get("index_status") or INDEX_STATUS_UNKNOWN)
    ui_status, ui_label = _CHECK_UI_STATUS.get(index_status, ("cannot_check", "Không kiểm tra được"))
    return {
        "url": row.get("url") or "",
        "query": row.get("query") or f"site:{row.get('url') or ''}",
        "index_status": index_status,
        "status": ui_status,
        "status_label": ui_label,
        "message": row.get("message") or row.get("reason") or ui_label,
        "reason": row.get("reason") or row.get("message") or ui_label,
        "matched_url": row.get("matched_url"),
        "title": row.get("title") or row.get("page_title"),
        "page_title": row.get("title") or row.get("page_title"),
        "http_status": row.get("http_status") or "—",
        "indexability": row.get("indexability_status") or row.get("indexability") or "—",
        "retry_count": int(row.get("retry_count") or 0),
        "source": row.get("source") or "",
        "evidence": row.get("evidence"),
        "checked_at": row.get("checked_at"),
    }


def _check_result_to_history(row: dict[str, Any]) -> dict[str, Any]:
    index_status = str(row.get("index_status") or INDEX_STATUS_UNKNOWN)
    return {
        "url": row.get("url") or "",
        "domain": normalize_domain(urlparse(str(row.get("url") or "")).hostname or ""),
        "indexability": _CHECK_HISTORY_INDEXABILITY.get(index_status, "error"),
        "main_issue": str(row.get("reason") or row.get("message") or "")[:128],
        "severity": "low" if index_status == INDEX_STATUS_INDEX else "medium",
        "suggestion": row.get("reason") or row.get("message"),
        "checks": row.get("checks") or {"source": row.get("source")},
        "index_status": index_status,
        "query": row.get("query"),
        "matched_url": row.get("matched_url"),
        "title": row.get("title") or row.get("page_title"),
        "reason": row.get("reason") or row.get("message"),
        "http_status": row.get("status_code"),
        "status_code": row.get("status_code"),
        "indexability_status": row.get("indexability_status"),
        "retry_count": row.get("retry_count"),
        "final_url": row.get("final_url"),
        "source": row.get("source"),
        "checked_at": row.get("checked_at"),
    }


def check_index_free_urls(
    db: Session,
    *,
    user_id: int,
    urls: list[str],
    project_name: str | None = None,
) -> dict[str, Any]:
    valid, parse_errors = _parse_unique_urls(urls, max_urls=MAX_CHECK_FREE_URLS)
    items: list[dict[str, Any]] = []

    for err in parse_errors:
        items.append(_check_result_to_item({
            "url": err["url"],
            "query": f"site:{err['url']}",
            "index_status": INDEX_STATUS_ERROR,
            "reason": err.get("message") or "URL không hợp lệ.",
            "http_status": "—",
            "indexability_status": "UNKNOWN",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "source": "validation",
        }))

    if valid:
        checked = _run_index_checks_parallel(valid)
        items.extend(_check_result_to_item(r) for r in checked)
        try:
            primary_domain = normalize_domain(urlparse(valid[0]).hostname or "") or None
            save_check_history(
                db,
                user_id=user_id,
                domain=primary_domain,
                url_type="check_free",
                items=checked,
                project_name=project_name,
            )
        except Exception:
            logger.warning("check_free_history_failed user_id=%s", user_id)
            db.rollback()

    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "disclaimer": CHECK_FREE_DISCLAIMER,
    }


def iter_check_free_stream(
    db: Session,
    *,
    user_id: int,
    urls: list[str],
    phase: str,
    project_name: str | None = None,
    check_id: int | None = None,
    resume: bool = False,
):
    """Yield SSE event dicts for check-free index or response phase."""
    from app.services.index_check_job_store import (
        clear_paused_job,
        get_paused_job,
        save_paused_job,
    )

    resume_job = None
    if resume and check_id:
        resume_job = get_paused_job(user_id=user_id, check_id=int(check_id))
        if not resume_job or not resume_job.get("pending_urls"):
            yield {
                "event": "error",
                "data": {
                    "message": "Không tìm thấy phiên đang tạm dừng hoặc đã hết URL chờ.",
                    "check_id": check_id,
                },
            }
            return
        urls = list(resume_job.get("pending_urls") or [])
        project_name = project_name or resume_job.get("project_name")

    valid, parse_errors = _parse_unique_urls(urls, max_urls=MAX_CHECK_FREE_URLS)
    total = len(valid)
    prior_done = int((resume_job or {}).get("done_count") or 0) if resume_job else 0
    grand_total = int((resume_job or {}).get("total") or 0) or (prior_done + total)

    yield {
        "event": "init",
        "data": {
            "phase": phase,
            "total": grand_total if resume else total,
            "batch_total": total,
            "valid_count": len(valid),
            "invalid_count": len(parse_errors),
            "max_urls": MAX_CHECK_FREE_URLS,
            "urls": valid,
            "errors": parse_errors,
            "resume": bool(resume_job),
            "check_id": int(check_id) if check_id else None,
            "done_count": prior_done,
        },
    }

    if phase == "index":
        saved_check_id: int | None = int(check_id) if (resume and check_id) else None
        done = prior_done
        history_domain = normalize_domain(urlparse(valid[0]).hostname or "") or None if valid else None

        if valid and saved_check_id is None:
            try:
                saved_check_id = create_check_session(
                    db,
                    user_id=user_id,
                    domain=history_domain,
                    url_type="check_free",
                    project_name=project_name,
                )
            except Exception:
                logger.warning("check_free_stream_session_create_failed user_id=%s", user_id)
                db.rollback()

        for err in parse_errors:
            raw = {
                "url": err.get("url") or "",
                "query": f"site:{err.get('url') or ''}",
                "index_status": INDEX_STATUS_ERROR,
                "reason": err.get("message") or "URL không hợp lệ.",
                "http_status": "—",
                "indexability": "error",
                "indexability_status": "UNKNOWN",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0,
                "checks": {},
                "main_issue": "Validation error",
                "severity": "high",
                "suggestion": err.get("message") or "URL không hợp lệ.",
                "source": "validation",
            }
            if saved_check_id is not None:
                try:
                    append_check_session_item(
                        db,
                        check_id=saved_check_id,
                        user_id=user_id,
                        domain=history_domain,
                        url_type="check_free",
                        item=raw,
                    )
                except Exception:
                    logger.warning("check_free_stream_session_append_failed user_id=%s", user_id)
                    db.rollback()
            item = _check_result_to_item(raw)
            yield {"event": "row", "data": {"phase": "index", "item": item}}

        # Sequential shared provider — stop immediately on CAPTCHA; never mark waiting as No Index.
        cache = _DomainCache()
        provider = GoogleSiteSearchProvider()
        paused = False

        for idx, raw_url in enumerate(valid):
            try:
                result = _run_real_index_check(raw_url, cache=cache, provider=provider)
            except Exception as exc:
                logger.warning("check_free_stream_url_failed url=%s err=%s", raw_url, type(exc).__name__)
                result = _error_index_row(raw_url, exc=exc)

            if saved_check_id is not None:
                try:
                    append_check_session_item(
                        db,
                        check_id=saved_check_id,
                        user_id=user_id,
                        domain=history_domain,
                        url_type="check_free",
                        item=result,
                    )
                except Exception:
                    logger.warning("check_free_stream_session_append_failed user_id=%s", user_id)
                    db.rollback()

            item = _check_result_to_item(result)
            done += 1
            yield {"event": "row", "data": {"phase": "index", "item": item}}
            yield {
                "event": "progress",
                "data": {
                    "done": done,
                    "total": grand_total if resume else total,
                    "phase": "index",
                },
            }

            status = str(result.get("index_status") or "")
            if status == INDEX_STATUS_CAPTCHA_REQUIRED:
                pending = valid[idx + 1 :]
                if saved_check_id is not None:
                    save_paused_job(
                        user_id=user_id,
                        check_id=int(saved_check_id),
                        pending_urls=pending,
                        done_count=done,
                        total=grand_total if resume else total,
                        project_name=project_name,
                        captcha_url=raw_url,
                        reason=str(result.get("reason") or ""),
                    )
                yield {
                    "event": "captcha_required",
                    "data": {
                        "phase": "index",
                        "check_id": saved_check_id,
                        "url": raw_url,
                        "reason": result.get("reason")
                        or "Google yêu cầu xác minh (CAPTCHA / unusual traffic).",
                        "pending_urls": pending,
                        "pending_count": len(pending),
                        "done": done,
                        "total": grand_total if resume else total,
                        "message": (
                            "Google yêu cầu xác minh. Kết quả đã check được giữ nguyên. "
                            "Bấm «Tiếp tục kiểm tra» sau khi xác minh / chờ cooldown."
                        ),
                    },
                }
                paused = True
                break

            remaining = total - (idx + 1)
            if remaining > 0:
                _sleep_between_urls(idx + 1, total)

        if not paused:
            if saved_check_id is not None:
                clear_paused_job(user_id=user_id, check_id=int(saved_check_id))
            yield {
                "event": "done",
                "data": {
                    "phase": phase,
                    "total": grand_total if resume else total,
                    "check_id": saved_check_id,
                    "disclaimer": CHECK_FREE_DISCLAIMER,
                    "max_urls": MAX_CHECK_FREE_URLS,
                },
            }
        return

    elif phase == "response":
        cache = _DomainCache()
        done = 0
        for raw_url in valid:
            resp = check_url_response_details(raw_url, cache=cache)
            done += 1
            yield {"event": "row", "data": {"phase": "response", "item": resp}}
            yield {
                "event": "progress",
                "data": {"done": done, "total": total, "phase": "response"},
            }

    yield {
        "event": "done",
        "data": {
            "phase": phase,
            "total": total,
            "disclaimer": CHECK_FREE_DISCLAIMER,
        },
    }
