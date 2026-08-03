import logging

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
from app.services.auth import get_current_user
from app.services.trial_access import require_active_trial
from app.services.credits import consume_credits, cost_analyze_project, cost_technical_analyze, cost_url_seo_scoreboard, credits_enforced
from app.services.cost_control import CostGateRequest, ExternalApiProvider, cost_gate_session
from app.services.plan_quota_registry import feature_key_for
from app.services.plan_quota_service import record_quota_usage
from app.services.crawler import CrawlRequestError, CrawlStatusError, CrawlTimeoutError
from app.services.url_safety import assert_public_http_url
from app.services.url_seo_scoreboard import build_url_seo_scoreboard

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
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="analyze_project",
        credit_cost=credit_cost,
        feature_key=feature_key_for("seo_score"),
        quota_units=1,
        single_flight_key=f"analyze_project:{current_user.id}",
    )
    try:
        with cost_gate_session(gate_req):
            result = analyze_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CrawlTimeoutError as exc:
        raise HTTPException(status_code=408, detail="Request timeout while crawling URL.") from exc
    except CrawlStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Target URL returned non-200 status: {exc.status_code}",
        ) from exc
    except CrawlRequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch target URL.") from exc

    seo_score = max(0, 100 - (result.summary.high * 30 + result.summary.medium * 15 + result.summary.low * 5))
    scan = Scan(project_id=project.id, seo_score=seo_score, total_pages=len(result.pages))
    db.add(scan)
    db.flush()

    for page_result in result.pages:
        page_score = seo_score
        page = Page(
            scan_id=scan.id,
            url=page_result.url,
            status=200,
            title=page_result.title,
            page_score=page_score,
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

    if credits_enforced():
        c = cost_analyze_project()
        if c > 0:
            consume_credits(
                db,
                user_id=current_user.id,
                amount=c,
                reason="analyze_project",
                note=f"project_id={project.id}",
            )
    record_quota_usage(db, current_user.id, feature_key_for("seo_score"), quantity=1, credits_used=credit_cost)
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
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="technical_analyze",
        credit_cost=credit_cost,
        feature_key=feature_key_for("technical_audit"),
        quota_units=1,
        single_flight_key=f"technical_analyze:{current_user.id}",
    )
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result_dict = result.model_dump()
    try:
        from app.services.technical_output_normalizer import build_saas_api_extensions

        saas_ext = build_saas_api_extensions(result_dict)
        result_dict.update(saas_ext)
    except Exception as exc:
        _LOG.warning("SaaS normalizer failed (audit continues with legacy fields): %s", exc, exc_info=True)
        from app.services.technical_output_normalizer import empty_saas_api_extensions

        result_dict.update(empty_saas_api_extensions())

    audit_id = save_technical_audit(
        user_id=current_user.id,
        source_url=payload.url,
        result=result_dict,
    )
    if credits_enforced():
        c = cost_technical_analyze()
        if c > 0:
            consume_credits(db, user_id=current_user.id, amount=c, reason="technical_analyze", note=payload.url[:500])
    record_quota_usage(
        db,
        current_user.id,
        feature_key_for("technical_audit"),
        quantity=1,
        credits_used=credit_cost,
    )
    db.commit()
    result_dict["audit_id"] = audit_id
    return TechnicalAnalyzeResponse.model_validate(result_dict)


@router.post("/analyze/url-seo-scoreboard", response_model=UrlSeoScoreboardResponse)
def analyze_url_seo_scoreboard(
    payload: UrlSeoScoreboardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> UrlSeoScoreboardResponse:
    """
    Chấm điểm SEO 1 URL (technical, on-page, content, internal link, schema, SERP fit, opportunity).
    Không lưu DB; an toàn khi thiếu dữ liệu (mock SERP / không có backlink API).
    """
    assert_public_http_url(payload.url, label="URL")
    credit_cost = cost_url_seo_scoreboard() if credits_enforced() else 0
    gate_req = CostGateRequest(
        db=db,
        user=current_user,
        provider=ExternalApiProvider.CRAWL,
        action="url_seo_scoreboard",
        credit_cost=credit_cost,
        feature_key=feature_key_for("seo_score"),
        quota_units=1,
        single_flight_key=f"url_seo_scoreboard:{current_user.id}",
    )
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
        _LOG.exception("url_seo_scoreboard failed for %s", payload.url)
        raise HTTPException(status_code=500, detail="Không thể chấm điểm URL. Vui lòng thử lại sau.") from exc
    if credits_enforced():
        c = cost_url_seo_scoreboard()
        if c > 0:
            consume_credits(db, user_id=current_user.id, amount=c, reason="url_seo_scoreboard", note=payload.url[:500])
    record_quota_usage(
        db,
        current_user.id,
        feature_key_for("seo_score"),
        quantity=1,
        credits_used=credit_cost,
    )
    db.commit()
    return UrlSeoScoreboardResponse.model_validate(raw)
