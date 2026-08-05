"""Analyze / technical / SEO score routes — wired through central SaaS gate."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.seo import Page, Project, Scan, ScanIssue
from app.models.user import User
from app.schemas import TechnicalAnalyzeRequest, TechnicalAnalyzeResponse
from app.schemas.project import AnalyzeProjectRequest, AnalyzeProjectResponse
from app.schemas.url_scoreboard import UrlSeoScoreboardRequest, UrlSeoScoreboardResponse
from app.services.analyzer import analyze_technical_seo, analyze_url
from app.services.audit_store import save_technical_audit
from app.services.trial_access import require_active_trial
from app.services.credits import cost_analyze_project, cost_technical_analyze, cost_url_seo_scoreboard, credits_enforced
from app.services.cost_control import CostGateRequest, ExternalApiProvider, cost_gate_session
from app.services.plan_quota_registry import feature_key_for
from app.services.plan_quota_service import record_quota_usage
from app.services.crawler import CrawlRequestError, CrawlStatusError, CrawlTimeoutError
from app.services.url_safety import assert_public_http_url
from app.services.url_seo_scoreboard import build_url_seo_scoreboard
from app.services.saas_gate import saas_action_gate

router = APIRouter(tags=["analyze"])
_LOG = logging.getLogger(__name__)


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
) -> TechnicalAnalyzeResponse:
    assert_public_http_url(payload.url, label="URL")
    credit_cost = cost_technical_analyze() if credits_enforced() else 0
    feature = feature_key_for("technical_audit")
    job_id = f"technical:{current_user.id}:{uuid.uuid4().hex[:12]}"
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
        try:
            with cost_gate_session(gate_req):
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
                )
        except ValueError as exc:
            sgate.release(reason="bad_request")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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

        audit_id = save_technical_audit(
            user_id=current_user.id,
            source_url=payload.url,
            result=result_dict,
        )
        sgate.commit()
        sgate.record_usage(metadata={"url": payload.url[:200]})
        record_quota_usage(db, current_user.id, feature, quantity=1, credits_used=credit_cost)
        db.commit()
        result_dict["audit_id"] = audit_id
        return TechnicalAnalyzeResponse.model_validate(result_dict)


@router.post("/analyze/url-seo-scoreboard", response_model=UrlSeoScoreboardResponse)
def analyze_url_seo_scoreboard(
    payload: UrlSeoScoreboardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> UrlSeoScoreboardResponse:
    assert_public_http_url(payload.url, label="URL")
    credit_cost = cost_url_seo_scoreboard() if credits_enforced() else 0
    feature = feature_key_for("seo_score")
    job_id = f"url_seo_scoreboard:{current_user.id}:{uuid.uuid4().hex[:12]}"
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="url_seo_scoreboard",
        credit_cost=0,
        feature_key=feature,
        quota_units=1,
        skip_credit_check=True,
        single_flight_key=f"url_seo_scoreboard:{current_user.id}",
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
