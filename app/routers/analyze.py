"""Analyze / technical / SEO score routes — wired through central SaaS gate."""
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import ensure_db_alive, get_db, release_db_before_long_io
from app.models.seo import Page, Project, Scan, ScanIssue
from app.models.user import User
from app.schemas import TechnicalAnalyzeRequest, TechnicalAnalyzeResponse
from app.schemas.project import AnalyzeProjectRequest, AnalyzeProjectResponse
from app.schemas.url_scoreboard import UrlSeoScoreboardRequest, UrlSeoScoreboardResponse
from app.services.analyzer import analyze_technical_seo, analyze_url
from app.services.audit_store import get_audit_by_idempotency, save_technical_audit
from app.services.idempotency_guard import build_idempotency_key, url_seo_scoreboard_fingerprint
from app.services.trial_access import require_active_trial
from app.services.credits import cost_analyze_project, cost_technical_analyze, cost_url_seo_scoreboard, credits_enforced
from app.services.cost_control import CostGateRequest, ExternalApiProvider, cost_gate_session
from app.services.plan_quota_registry import feature_key_for
from app.services.plan_quota_service import record_quota_usage
from app.services.crawler import CrawlRequestError, CrawlStatusError, CrawlTimeoutError
from app.services.url_safety import assert_public_http_url
from app.services.url_seo_scoreboard import build_url_seo_scoreboard
from app.services.saas_gate import saas_action_gate
from sqlalchemy.exc import OperationalError

router = APIRouter(tags=["analyze"])
_LOG = logging.getLogger(__name__)


def _resolve_url_seo_scoreboard_idempotency_key(
    user_id: int,
    payload: UrlSeoScoreboardRequest,
    header_key: str | None,
) -> str:
    raw = str(header_key or "").strip()
    if raw:
        return build_idempotency_key("url_seo_scoreboard", user_id, raw[:64])
    fp = url_seo_scoreboard_fingerprint(payload.model_dump())
    return build_idempotency_key("url_seo_scoreboard", user_id, fp)


def _resolve_technical_idempotency_key(
    user_id: int,
    payload: TechnicalAnalyzeRequest,
    header_key: str | None,
) -> str | None:
    raw = str(payload.idempotency_key or header_key or "").strip()
    if not raw:
        return None
    return build_idempotency_key("technical_analyze", user_id, raw[:64])


def _technical_response_from_audit(audit: dict) -> TechnicalAnalyzeResponse:
    snap = audit.get("result_snapshot")
    if isinstance(snap, dict) and snap.get("domain"):
        out = dict(snap)
        out["audit_id"] = audit.get("audit_id") or audit.get("id")
        return TechnicalAnalyzeResponse.model_validate(out)
    raise HTTPException(
        status_code=409,
        detail="Audit đã lưu nhưng không có snapshot phản hồi — mở lại từ Lịch sử.",
    )


@router.post("/analyze", response_model=AnalyzeProjectResponse)
def analyze(
    payload: AnalyzeProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> AnalyzeProjectResponse:
    project = db.query(Project).filter(Project.id == payload.project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(
            status_code=404,
            detail="Không có project này trong tài khoản của bạn. Hãy đăng nhập đúng email, tạo project ở Bước 2, rồi chọn project trong danh sách (không dùng ID của tài khoản khác).",
        )

    assert_public_http_url(payload.url, label="URL")
    credit_cost = cost_analyze_project() if credits_enforced() else 0
    feature = feature_key_for("seo_score")
    job_id = f"analyze_project:{current_user.id}:{project.id}:{uuid.uuid4().hex[:12]}"
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="analyze_project",
        credit_cost=0,  # reserved by saas_action_gate
        feature_key=feature,
        quota_units=1,
        skip_credit_check=True,
        single_flight_key=f"analyze_project:{current_user.id}",
    )
    with saas_action_gate(
        db,
        current_user,
        feature_code=feature,
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            with cost_gate_session(gate_req):
                result = analyze_url(payload.url)
        except ValueError as exc:
            sgate.release(reason="bad_request")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except CrawlTimeoutError as exc:
            sgate.release(reason="timeout")
            raise HTTPException(status_code=408, detail="Request timeout while crawling URL.") from exc
        except CrawlStatusError as exc:
            sgate.release(reason="crawl_status")
            raise HTTPException(
                status_code=502,
                detail=f"Target URL returned non-200 status: {exc.status_code}",
            ) from exc
        except CrawlRequestError as exc:
            sgate.release(reason="crawl_request")
            raise HTTPException(status_code=502, detail="Failed to fetch target URL.") from exc
        except Exception:
            sgate.release(reason="job_failed")
            raise

        seo_score = max(0, 100 - (result.summary.high * 30 + result.summary.medium * 15 + result.summary.low * 5))
        scan = Scan(project_id=project.id, seo_score=seo_score, total_pages=len(result.pages))
        db.add(scan)
        db.flush()

        for page_result in result.pages:
            page = Page(
                scan_id=scan.id,
                url=page_result.url,
                status=200,
                title=page_result.title,
                page_score=seo_score,
            )
            db.add(page)
            db.flush()
            for issue in result.issues:
                if issue.url != page_result.url:
                    continue
                db.add(
                    ScanIssue(
                        page_id=page.id,
                        type=issue.type,
                        severity=issue.severity,
                        message=issue.message,
                    )
                )

        sgate.commit()
        sgate.record_usage(metadata={"project_id": project.id})
        record_quota_usage(db, current_user.id, feature, quantity=1, credits_used=credit_cost)
        db.commit()
        return AnalyzeProjectResponse(scan_id=scan.id, seo_score=seo_score)


@router.post("/analyze/technical", response_model=TechnicalAnalyzeResponse)
def analyze_technical(
    payload: TechnicalAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> TechnicalAnalyzeResponse:
    assert_public_http_url(payload.url, label="URL")
    idem_key = _resolve_technical_idempotency_key(current_user.id, payload, x_idempotency_key)
    if idem_key:
        cached = get_audit_by_idempotency(current_user.id, idem_key)
        if cached:
            return _technical_response_from_audit(cached)

    credit_cost = cost_technical_analyze() if credits_enforced() else 0
    feature = feature_key_for("technical_audit")
    job_id = idem_key or f"technical:{current_user.id}:{uuid.uuid4().hex[:12]}"
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="technical_analyze",
        credit_cost=0,
        feature_key=feature,
        quota_units=1,
        skip_credit_check=True,
        single_flight_key=f"technical_analyze:{current_user.id}",
    )
    with saas_action_gate(
        db,
        current_user,
        feature_code=feature,
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        charge_mode="reserve",
    ) as sgate:
        if sgate.committed and idem_key:
            cached = get_audit_by_idempotency(current_user.id, idem_key)
            if cached:
                return _technical_response_from_audit(cached)

        try:
            with cost_gate_session(gate_req):
                sync_budget = int(os.getenv("TECHNICAL_SCAN_SYNC_BUDGET_SECONDS", "80") or 80)
                sync_budget = max(45, min(480, sync_budget))
                release_db_before_long_io(db)
                result = analyze_technical_seo(
                    payload.url,
                    max_pages=payload.max_pages,
                    user_id=current_user.id,
                    use_gsc=payload.use_gsc,
                    gsc_property=payload.gsc_property,
                    gsc_date_range=payload.gsc_date_range,
                    gsc_start_date=payload.gsc_start_date,
                    gsc_end_date=payload.gsc_end_date,
                    url_inspection_limit=payload.url_inspection_limit,
                    deadline_monotonic=time.monotonic() + sync_budget,
                )
        except ValueError as exc:
            sgate.release(reason="bad_request")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except CrawlTimeoutError as exc:
            sgate.release(reason="timeout")
            raise HTTPException(status_code=408, detail="Request timeout while crawling URL.") from exc
        except CrawlStatusError as exc:
            sgate.release(reason="crawl_status")
            raise HTTPException(
                status_code=502,
                detail=f"Target URL returned non-200 status: {exc.status_code}",
            ) from exc
        except CrawlRequestError as exc:
            sgate.release(reason="crawl_request")
            raise HTTPException(status_code=502, detail="Failed to fetch target URL.") from exc
        except Exception:
            sgate.release(reason="job_failed")
            raise

        result_dict = result.model_dump()
        try:
            from app.services.technical_output_normalizer import build_saas_api_extensions

            result_dict.update(build_saas_api_extensions(result_dict))
        except Exception as exc:
            _LOG.warning("SaaS normalizer failed (audit continues with legacy fields): %s", exc, exc_info=True)
            from app.services.technical_output_normalizer import empty_saas_api_extensions

            result_dict.update(empty_saas_api_extensions())

        def _persist_sync() -> int:
            ensure_db_alive(db)
            audit_id_local = save_technical_audit(
                user_id=current_user.id,
                source_url=payload.url,
                result=result_dict,
                idempotency_key=idem_key,
            )
            sgate.commit()
            sgate.record_usage(metadata={"url": payload.url[:200]})
            record_quota_usage(db, current_user.id, feature, quantity=1, credits_used=credit_cost)
            db.commit()
            return audit_id_local

        try:
            audit_id = _persist_sync()
        except OperationalError:
            try:
                ensure_db_alive(db)
                audit_id = _persist_sync()
            except Exception as exc:
                sgate.release(reason="db_persist_failed")
                raise HTTPException(
                    status_code=503,
                    detail="Kết nối dữ liệu tạm thời gián đoạn sau khi crawl. Vui lòng thử lại.",
                ) from exc
        result_dict["audit_id"] = audit_id
        return TechnicalAnalyzeResponse.model_validate(result_dict)


@router.post("/analyze/technical/jobs")
def analyze_technical_job_start(
    payload: TechnicalAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> JSONResponse:
    """Start technical scan in background — poll GET /analyze/technical/jobs/{job_id}."""
    from app.services.job_store import create_job, ensure_job_schema
    from app.services.technical_scan_job import (
        JOB_TYPE,
        find_technical_job_by_idempotency,
        start_technical_scan_thread,
    )

    assert_public_http_url(payload.url, label="URL")
    ensure_job_schema()
    idem_key = _resolve_technical_idempotency_key(current_user.id, payload, x_idempotency_key)

    if idem_key:
        cached = get_audit_by_idempotency(current_user.id, idem_key)
        if cached:
            try:
                result = _technical_response_from_audit(cached).model_dump()
                return JSONResponse(
                    content={
                        "job_id": cached.get("id") or cached.get("audit_id"),
                        "state": "SUCCESS",
                        "progress": 100,
                        "message": "Lấy lại kết quả quét gần đây (không trừ credit lần nữa).",
                        "cached": True,
                        "poll_url": None,
                        "result": result,
                    }
                )
            except HTTPException:
                pass
        existing = find_technical_job_by_idempotency(current_user.id, idem_key)
        if existing:
            out: dict = {
                "job_id": existing.job_id,
                "state": existing.state,
                "progress": existing.progress,
                "message": existing.message,
                "poll_url": f"/analyze/technical/jobs/{existing.job_id}",
                "cached": True,
            }
            if existing.state == "SUCCESS" and existing.result is not None:
                out["result"] = existing.result
            return JSONResponse(content=out)

    credit_cost = cost_technical_analyze() if credits_enforced() else 0
    feature = feature_key_for("technical_audit")
    gate_job_id = idem_key or f"technical:{current_user.id}:{uuid.uuid4().hex[:12]}"

    with saas_action_gate(
        db,
        current_user,
        feature_code=feature,
        credit_cost=credit_cost,
        quota_units=1,
        job_id=gate_job_id,
        idempotency_key=gate_job_id,
        charge_mode="reserve",
        auto_commit_on_success=False,
    ) as sgate:
        if sgate.committed and idem_key:
            cached = get_audit_by_idempotency(current_user.id, idem_key)
            if cached:
                try:
                    result = _technical_response_from_audit(cached).model_dump()
                    return JSONResponse(
                        content={
                            "job_id": cached.get("id") or cached.get("audit_id"),
                            "state": "SUCCESS",
                            "progress": 100,
                            "cached": True,
                            "result": result,
                        }
                    )
                except HTTPException:
                    pass
        job_payload = {
            "user_id": current_user.id,
            "url": payload.url,
            "max_pages": payload.max_pages,
            "use_gsc": payload.use_gsc,
            "gsc_property": payload.gsc_property,
            "gsc_date_range": payload.gsc_date_range,
            "gsc_start_date": payload.gsc_start_date,
            "gsc_end_date": payload.gsc_end_date,
            "url_inspection_limit": payload.url_inspection_limit,
            "idempotency_key": idem_key,
            "reservation_id": sgate.reservation_id,
            "reserved_amount": sgate.reserved_amount or credit_cost,
            "feature_key": feature,
        }
        try:
            job = create_job(
                job_type=JOB_TYPE,
                message="Đã xếp hàng — bắt đầu crawl",
                payload=job_payload,
                user_id=int(current_user.id),
            )
        except Exception:
            sgate.release(reason="job_create_failed")
            raise
        db.commit()
        start_technical_scan_thread(job.job_id, job_payload)
        return JSONResponse(
            content={
                "job_id": job.job_id,
                "state": job.state,
                "progress": job.progress,
                "message": job.message,
                "poll_url": f"/analyze/technical/jobs/{job.job_id}",
            }
        )


@router.get("/analyze/technical/jobs/{job_id}")
def analyze_technical_job_poll(
    job_id: str,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    from app.services.job_store import ensure_job_schema
    from app.services.technical_scan_job import poll_technical_job

    ensure_job_schema()
    st = poll_technical_job(job_id, current_user.id)
    if not st:
        raise HTTPException(status_code=404, detail="Không tìm thấy job quét technical.")
    return JSONResponse(content=st)


@router.post("/analyze/url-seo-scoreboard", response_model=UrlSeoScoreboardResponse)
def analyze_url_seo_scoreboard(
    payload: UrlSeoScoreboardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> UrlSeoScoreboardResponse:
    assert_public_http_url(payload.url, label="URL")
    credit_cost = cost_url_seo_scoreboard() if credits_enforced() else 0
    feature = feature_key_for("seo_score")
    idem_key = _resolve_url_seo_scoreboard_idempotency_key(current_user.id, payload, x_idempotency_key)
    job_id = idem_key
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="url_seo_scoreboard",
        credit_cost=0,
        feature_key=feature,
        quota_units=1,
        skip_credit_check=True,
        single_flight_key=f"url_seo_scoreboard:{current_user.id}:{url_seo_scoreboard_fingerprint(payload.model_dump())}",
    )
    with saas_action_gate(
        db,
        current_user,
        feature_code=feature,
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            with cost_gate_session(gate_req):
                raw = build_url_seo_scoreboard(
                    payload.url,
                    keyword=(payload.keyword or "").strip() or None,
                    secondary_keywords=payload.secondary_keywords,
                    page_type=(payload.page_type or "").strip() or None,
                    search_volume=payload.search_volume,
                    current_serp_position=payload.current_serp_position,
                )
        except Exception as exc:
            sgate.release(reason="job_failed")
            _LOG.exception("url_seo_scoreboard failed for %s", payload.url)
            raise HTTPException(status_code=500, detail="Không thể chấm điểm URL. Vui lòng thử lại sau.") from exc

        sgate.commit()
        sgate.record_usage(metadata={"url": payload.url[:200]})
        record_quota_usage(db, current_user.id, feature, quantity=1, credits_used=credit_cost)
        db.commit()
        return UrlSeoScoreboardResponse.model_validate(raw)
