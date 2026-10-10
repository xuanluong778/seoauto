"""Index Control API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.saas_gate import build_job_id, saas_action_gate
from app.services.trial_access import require_active_trial
from app.services.index_control_check import URL_TYPE_LABELS, check_index_urls, normalize_url_type
from app.services.index_control_history_store import (
    delete_all_check_free_sessions,
    delete_all_history,
    delete_check_free_session,
    delete_history_item,
    export_check_free_rows_xlsx,
    export_check_free_session_xlsx,
    get_check_free_session_items,
    get_history_item,
    list_check_free_sessions,
    list_history_items,
    parse_date_param,
    save_check_history,
)
from app.services.index_control_overview_store import get_overview
from app.services.index_control_saas_service import (
    check_index_free_urls,
    get_saas_overview,
    get_submit_quota_snapshot,
    iter_check_free_stream,
    submit_indexing_urls,
)
from app.services.submit_project_store import (
    delete_all_submit_projects,
    delete_submit_project,
    export_submit_project_xlsx,
    get_submit_project,
    list_submit_projects,
    refresh_submit_project_index_status,
)
from app.services.index_control_results_store import (
    get_submit_result_detail,
    list_submit_results,
)
from app.services.index_control_social_service import check_social_urls
from app.services.index_control_web20_service import check_web20_urls
from app.services.index_control_service import check_website_urls, normalize_domain
from app.services.indexnow_log_store import list_indexnow_logs, save_indexnow_logs
from app.services.indexnow_service import (
    MAX_URLS_PER_SUBMIT,
    submit_indexnow,
    validate_indexnow_domain,
    validate_indexnow_key,
    validate_indexnow_urls,
)
from app.services.user_scope import is_admin_role

router = APIRouter(tags=["index-control"])

_WEBSITE_ALIASES = frozenset({"website", "main_site"})
_WEB20_ALIASES = frozenset({"web20", "web2"})
_SOCIAL_ALIASES = frozenset({"social_entity", "social"})


class IndexCheckRequest(BaseModel):
    domain: str | None = Field(default=None, max_length=253)
    website: str | None = Field(default=None, max_length=2000)
    url_type: str = "website"
    urls: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("urls")
    @classmethod
    def _cap_urls(cls, value: list[str]) -> list[str]:
        return value[:50]


def _resolve_url_type(raw: str | None) -> str:
    value = (raw or "website").strip().lower()
    if value in _WEBSITE_ALIASES:
        return "website"
    if value in _WEB20_ALIASES:
        return "web20"
    if value in _SOCIAL_ALIASES:
        return "social_entity"
    return normalize_url_type(value)


def _resolve_domain(body: IndexCheckRequest) -> str:
    if body.domain and body.domain.strip():
        return normalize_domain(body.domain)
    if body.website and body.website.strip():
        return normalize_domain(body.website)
    return ""


def _persist_check(
    db: Session,
    user: User,
    *,
    domain: str | None,
    url_type: str,
    items: list[dict],
) -> int | None:
    if not items:
        return None
    try:
        return save_check_history(
            db,
            user_id=user.id,
            domain=domain,
            url_type=url_type,
            items=items,
        )
    except Exception:
        db.rollback()
        return None


@router.post("/check")
def index_control_check(
    body: IndexCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Kiểm tra index URL — website, web20 & social_entity fetch thật."""
    urls = [u.strip() for u in body.urls if u and u.strip()]
    if not urls:
        return {"ok": False, "error": "empty_urls", "message": "Nhập ít nhất một URL."}

    url_type = _resolve_url_type(body.url_type)

    if url_type == "website":
        domain = _resolve_domain(body)
        if not domain:
            return {
                "ok": False,
                "error": "domain_required",
                "message": "Nhập domain hoặc chọn website khi kiểm tra Website chính.",
            }
        payload = check_website_urls(domain=domain, urls=urls)
        if not payload.get("ok"):
            return payload
        payload["url_type_label"] = URL_TYPE_LABELS.get("main_site", "Website chính")
        payload["authenticated"] = True
        payload["user_id"] = user.id
        check_id = _persist_check(db, user, domain=domain, url_type=url_type, items=payload.get("items") or [])
        if check_id:
            payload["history_check_id"] = check_id
        return payload

    if url_type == "web20":
        payload = check_web20_urls(urls=urls)
        if not payload.get("ok"):
            return payload
        payload["url_type_label"] = URL_TYPE_LABELS.get("web20", "Web 2.0")
        payload["authenticated"] = True
        payload["user_id"] = user.id
        domain = payload.get("domain") or _resolve_domain(body) or None
        check_id = _persist_check(db, user, domain=domain, url_type=url_type, items=payload.get("items") or [])
        if check_id:
            payload["history_check_id"] = check_id
        return payload

    if url_type == "social_entity":
        payload = check_social_urls(urls=urls)
        if not payload.get("ok"):
            return payload
        payload["url_type_label"] = URL_TYPE_LABELS.get("social_entity", "Social / Entity")
        payload["authenticated"] = True
        payload["user_id"] = user.id
        domain = payload.get("domain") or _resolve_domain(body) or None
        check_id = _persist_check(db, user, domain=domain, url_type=url_type, items=payload.get("items") or [])
        if check_id:
            payload["history_check_id"] = check_id
        return payload

    mock_type = url_type if url_type in URL_TYPE_LABELS else "web20"
    if mock_type == "main_site":
        mock_type = "web20"
    domain = _resolve_domain(body) or None
    payload = check_index_urls(
        url_type=mock_type,
        website=body.website or body.domain,
        urls=urls,
        max_urls=50,
    )
    items = payload.get("items") or []
    for it in items:
        it.setdefault("url_type", mock_type)
        if not it.get("indexability"):
            sc = it.get("status_class") or ""
            it["indexability"] = "indexable" if sc == "ok" else "warning" if sc == "warn" else "blocked"
        if not it.get("main_issue"):
            it["main_issue"] = it.get("primary_error") or "—"
        if not it.get("severity"):
            it["severity"] = it.get("severity_label", "low").lower() if it.get("severity_label") else "low"
        if not it.get("suggestion"):
            it["suggestion"] = it.get("hint") or ""
    payload["ok"] = True
    payload["authenticated"] = True
    payload["user_id"] = user.id
    check_id = _persist_check(db, user, domain=domain, url_type=mock_type, items=items)
    if check_id:
        payload["history_check_id"] = check_id
    return payload


@router.get("/saas-overview")
def index_control_saas_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    return get_saas_overview(db, user_id=user.id, role=role)


@router.get("/submit-quota")
def index_control_submit_quota(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    return {"ok": True, "quota": get_submit_quota_snapshot(db, user_id=user.id, role=role)}


class SubmitIndexingRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    url_meta: dict[str, dict[str, Any]] = Field(default_factory=dict)
    project_name: str | None = Field(default=None, max_length=255)

    @field_validator("urls")
    @classmethod
    def _cap(cls, value: list[str]) -> list[str]:
        return value[:110]


class CheckFreeRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    project_name: str | None = Field(default=None, max_length=255)

    @field_validator("urls")
    @classmethod
    def _cap(cls, value: list[str]) -> list[str]:
        return value[:120]


class CheckFreeStreamRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    phase: str = Field(default="index")
    project_name: str | None = Field(default=None, max_length=255)
    check_id: int | None = Field(default=None, description="Resume paused check session")
    resume: bool = False

    @field_validator("urls")
    @classmethod
    def _cap(cls, value: list[str]) -> list[str]:
        return value[:120]

    @field_validator("phase")
    @classmethod
    def _phase(cls, value: str) -> str:
        p = (value or "index").strip().lower()
        return p if p in ("index", "response") else "index"

class CheckFreeExportRow(BaseModel):
    url: str = ""
    query: str | None = None
    status: str | None = None
    index_status: str | None = None
    status_label: str | None = None
    http_status: str | None = None
    indexability: str | None = None
    indexability_status: str | None = None
    matched_url: str | None = None
    title: str | None = None
    page_title: str | None = None
    reason: str | None = None
    message: str | None = None
    checked_at: str | None = None
    retry_count: int | None = None


class CheckFreeExportRequest(BaseModel):
    check_id: int | None = None
    rows: list[CheckFreeExportRow] = Field(default_factory=list)

    @field_validator("rows")
    @classmethod
    def _cap_rows(cls, value: list[CheckFreeExportRow]) -> list[CheckFreeExportRow]:
        return value[:25]


@router.post("/submit-indexing")
def index_control_submit_indexing(
    body: SubmitIndexingRequest,
    user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> dict:
    # Trial-blocked feature: never call SinByte/Index provider without SaaS gate
    units = max(1, len(body.urls or []))
    job_id = build_job_id("index_control_submit", user.id, units)
    from app.services.credits import cost_index_submit, credits_enforced

    credit_cost = cost_index_submit(units, provider="google", db=db) if credits_enforced() else 0
    with saas_action_gate(
        db,
        user,
        feature_code="index_control_submit",
        credit_cost=credit_cost,
        quota_units=units,
        job_id=job_id,
        idempotency_key=job_id,
        charge_mode="reserve",
        auto_commit_on_success=True,
    ) as sgate:
        role = getattr(user, "role", None)
        out = submit_indexing_urls(
            db,
            user_id=user.id,
            role=role,
            urls=body.urls,
            url_meta=body.url_meta,
            project_name=body.project_name,
        )
        sgate.record_usage(metadata={"url_count": units, "credits": credit_cost})
        return out


@router.get("/submit-indexing/projects")
def index_control_submit_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    role = getattr(user, "role", None)
    return list_submit_projects(db, user_id=user.id, role=role, limit=limit, offset=offset)


@router.get("/results")
def index_control_results_list(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    q: str | None = Query(default=None),
    submit_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Tab Kết quả — danh sách batch submit index (theo user)."""
    role = getattr(user, "role", None)
    return list_submit_results(
        db,
        user_id=user.id,
        role=role,
        date_from=date_from,
        date_to=date_to,
        q=q,
        submit_status=submit_status,
        limit=limit,
        offset=offset,
    )


@router.get("/results/{project_id}")
def index_control_results_detail(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    data = get_submit_result_detail(
        db, project_id=project_id, user_id=user.id, role=role
    )
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return data


@router.delete("/submit-indexing/projects")
def index_control_submit_projects_delete_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    deleted = delete_all_submit_projects(db, user_id=user.id, role=role)
    return {"ok": True, "deleted": deleted}


@router.get("/submit-indexing/projects/{project_id}")
def index_control_submit_project_detail(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    data = get_submit_project(db, project_id=project_id, user_id=user.id, role=role)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return data


@router.post("/submit-indexing/projects/{project_id}/check-index")
def index_control_submit_project_check_index(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Kiểm tra index tất cả URL trong dự án submit — trả Index/No."""
    role = getattr(user, "role", None)
    data = refresh_submit_project_index_status(
        db, project_id=project_id, user_id=user.id, role=role
    )
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return data


@router.delete("/submit-indexing/projects/{project_id}")
def index_control_submit_project_delete(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    ok = delete_submit_project(db, project_id=project_id, user_id=user.id, role=role)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return {"ok": True}


@router.get("/submit-indexing/projects/{project_id}/export")
def index_control_submit_project_export(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    role = getattr(user, "role", None)
    blob = export_submit_project_xlsx(
        db, project_id=project_id, user_id=user.id, role=role
    )
    if not blob:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    filename = f"submit-project-{project_id}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/check-free")
def index_control_check_free(
    body: CheckFreeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return check_index_free_urls(db, user_id=user.id, urls=body.urls, project_name=body.project_name)


@router.post("/check-free/stream")
def index_control_check_free_stream(
    body: CheckFreeStreamRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    def _sse():
        for event in iter_check_free_stream(
            db,
            user_id=user.id,
            urls=body.urls,
            phase=body.phase,
            project_name=body.project_name,
            check_id=body.check_id,
            resume=bool(body.resume),
        ):
            evt = str(event.get("event") or "message")
            payload = json.dumps(event.get("data") or {}, ensure_ascii=False)
            yield f"event:{evt}\ndata:{payload}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/check-free/paused")
def index_control_check_free_paused(
    check_id: int | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    from app.services.index_check_job_store import get_latest_paused_job, get_paused_job

    job = None
    if check_id is not None:
        job = get_paused_job(user_id=user.id, check_id=int(check_id))
    else:
        job = get_latest_paused_job(user_id=user.id)
    if not job:
        return {"ok": True, "paused": False, "job": None}
    return {"ok": True, "paused": True, "job": job}


@router.post("/check-free/export")
def index_control_check_free_export(
    body: CheckFreeExportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    role = getattr(user, "role", None)
    blob: bytes | None = None
    filename = "check-index-ket-qua.xlsx"

    if body.rows:
        blob = export_check_free_rows_xlsx(
            [r.model_dump(exclude_none=True) for r in body.rows]
        )
    elif body.check_id:
        blob = export_check_free_session_xlsx(
            db, check_id=body.check_id, user_id=user.id, role=role
        )
        filename = f"check-index-{body.check_id}.xlsx"
    else:
        sessions = list_check_free_sessions(db, user_id=user.id, role=role, limit=1)
        latest = (sessions.get("sessions") or [None])[0]
        if latest and latest.get("check_id"):
            cid = int(latest["check_id"])
            blob = export_check_free_session_xlsx(
                db, check_id=cid, user_id=user.id, role=role
            )
            filename = f"check-index-{cid}.xlsx"

    if not blob:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no_data",
        )

    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/check-free/sessions")
def index_control_check_free_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    role = getattr(user, "role", None)
    return list_check_free_sessions(
        db, user_id=user.id, role=role, limit=limit, offset=offset
    )


@router.delete("/check-free/sessions")
def index_control_check_free_sessions_delete_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    deleted = delete_all_check_free_sessions(db, user_id=user.id, role=role)
    return {"ok": True, "deleted": deleted}


@router.get("/check-free/sessions/{check_id}")
def index_control_check_free_session_detail(
    check_id: int,
    items_page: int | None = Query(default=None, ge=1),
    items_page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.api_payload_optimizer import shape_check_free_session

    role = getattr(user, "role", None)
    data = get_check_free_session_items(
        db, check_id=check_id, user_id=user.id, role=role
    )
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return shape_check_free_session(
        data,
        items_page=items_page,
        items_page_size=items_page_size,
    )


@router.delete("/check-free/sessions/{check_id}")
def index_control_check_free_session_delete(
    check_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    ok = delete_check_free_session(
        db, check_id=check_id, user_id=user.id, role=role
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return {"ok": True}


@router.get("/check-free/sessions/{check_id}/export")
def index_control_check_free_session_export(
    check_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    role = getattr(user, "role", None)
    blob = export_check_free_session_xlsx(
        db, check_id=check_id, user_id=user.id, role=role
    )
    if not blob:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    filename = f"check-index-{check_id}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overview")
def index_control_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    domain: str | None = Query(default=None),
    url_type: str | None = Query(default=None),
    urgent_limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    role = getattr(user, "role", None)
    return get_overview(
        db,
        user_id=user.id,
        role=role,
        domain=normalize_domain(domain) if domain else None,
        url_type=_resolve_url_type(url_type) if url_type else None,
        urgent_limit=urgent_limit,
    )


@router.get("/history")
def index_control_history_list(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    domain: str | None = Query(default=None),
    url_type: str | None = Query(default=None),
    indexability: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    role = getattr(user, "role", None)
    return list_history_items(
        db,
        user_id=user.id,
        role=role,
        domain=normalize_domain(domain) if domain else None,
        url_type=_resolve_url_type(url_type) if url_type else None,
        indexability=indexability,
        severity=severity,
        date_from=parse_date_param(date_from),
        date_to=parse_date_param(date_to, end_of_day=True),
        limit=limit,
        offset=offset,
    )


@router.get("/history/{item_id}")
def index_control_history_detail(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    item = get_history_item(db, item_id=item_id, user_id=user.id, role=role)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi.")
    return item


@router.delete("/history/{item_id}")
def index_control_history_delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    role = getattr(user, "role", None)
    ok = delete_history_item(db, item_id=item_id, user_id=user.id, role=role)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi.")
    return {"ok": True, "deleted_id": item_id}


@router.delete("/history")
def index_control_history_clear(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    user_id: int | None = Query(default=None, description="Admin: xóa lịch sử user khác"),
) -> dict:
    role = getattr(user, "role", None)
    if user_id is not None and not is_admin_role(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ admin mới xóa lịch sử user khác.")
    n = delete_all_history(db, user_id=user.id, role=role, target_user_id=user_id)
    return {"ok": True, "deleted_count": n}


class IndexNowSubmitRequest(BaseModel):
    domain: str = Field(..., max_length=253)
    key: str = Field(..., max_length=128)
    urls: list[str] = Field(default_factory=list)

    @field_validator("urls")
    @classmethod
    def _cap_urls(cls, value: list[str]) -> list[str]:
        return value[:MAX_URLS_PER_SUBMIT + 10]


@router.post("/indexnow-submit")
def index_control_indexnow_submit(
    body: IndexNowSubmitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Gửi URL tới IndexNow API và lưu log (không lưu key)."""
    domain, domain_err = validate_indexnow_domain(body.domain)
    if domain_err:
        return {"ok": False, "error": "invalid_domain", "message": domain_err}

    key, key_err = validate_indexnow_key(body.key)
    if key_err:
        return {"ok": False, "error": "invalid_key", "message": key_err}

    raw_urls = [u.strip() for u in body.urls if u and u.strip()]
    if not raw_urls:
        return {"ok": False, "error": "empty_urls", "message": "Nhập ít nhất một URL."}
    if len(raw_urls) > MAX_URLS_PER_SUBMIT:
        return {
            "ok": False,
            "error": "too_many_urls",
            "message": f"Tối đa {MAX_URLS_PER_SUBMIT} URL mỗi lần gửi.",
        }

    valid_urls, invalid_entries = validate_indexnow_urls(raw_urls, domain=domain)
    log_items: list[dict] = []

    for inv in invalid_entries:
        log_items.append({
            "url": inv.get("url") or "",
            "send_status": "validation_error",
            "http_status": None,
            "note": inv.get("note") or "URL không hợp lệ.",
        })

    api_result: dict | None = None
    if valid_urls:
        from app.services.credits import cost_index_submit, credits_enforced
        from app.services.saas_gate import build_job_id, saas_action_gate

        units = max(1, len(valid_urls))
        job_id = build_job_id("indexnow_submit", user.id, units)
        credit_cost = cost_index_submit(units, provider="indexnow", db=db) if credits_enforced() else 0
        with saas_action_gate(
            db,
            user,
            feature_code="index_control_submit",
            credit_cost=credit_cost,
            quota_units=units,
            job_id=job_id,
            idempotency_key=job_id,
            charge_mode="reserve",
            auto_commit_on_success=True,
        ) as sgate:
            api_result = submit_indexnow(domain=domain, key=key, urls=valid_urls)
            if not api_result.get("ok"):
                sgate.release(reason="indexnow_failed")
            else:
                sgate.record_usage(metadata={"url_count": units, "provider": "indexnow"})
        send_status = "sent" if api_result.get("ok") else "failed"
        batch_note = api_result.get("message")
        http_status = api_result.get("http_status")
        for url in valid_urls:
            log_items.append({
                "url": url,
                "send_status": send_status,
                "http_status": http_status,
                "note": batch_note,
            })
    else:
        api_result = {"ok": False, "error": "no_valid_urls", "message": "Không có URL hợp lệ.", "http_status": None}

    submit_status = "success" if api_result and api_result.get("ok") else "failed"
    if valid_urls and invalid_entries:
        submit_status = "partial"
    if not valid_urls:
        submit_status = "validation_only"

    submit_id = None
    try:
        submit_id = save_indexnow_logs(
            db,
            user_id=user.id,
            domain=domain,
            api_http_status=api_result.get("http_status") if api_result else None,
            submit_status=submit_status,
            batch_note=api_result.get("message") if api_result else None,
            items=log_items,
        )
    except Exception:
        db.rollback()

    return {
        "ok": bool(api_result and api_result.get("ok")),
        "error": api_result.get("error") if api_result else "no_valid_urls",
        "message": api_result.get("message") if api_result else "Không có URL hợp lệ.",
        "http_status": api_result.get("http_status") if api_result else None,
        "submit_id": submit_id,
        "url_count": len(valid_urls),
        "invalid_count": len(invalid_entries),
        "logged_count": len(log_items),
    }


@router.get("/indexnow-logs")
def index_control_indexnow_logs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    domain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    role = getattr(user, "role", None)
    return list_indexnow_logs(
        db,
        user_id=user.id,
        role=role,
        domain=normalize_domain(domain) if domain else None,
        limit=limit,
        offset=offset,
    )
