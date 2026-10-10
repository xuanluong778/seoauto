"""SEO Score API — AI fix từng trường."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.seo_score_ai_fix import SeoScoreAiFixRequest, SeoScoreAiFixResponse
from app.schemas.seo_score_apply_fix import SeoScoreApplyFixRequest, SeoScoreApplyFixResponse
from app.services.seo_score_ai_fix import (
    SeoScoreAiFixError,
    execute_seo_score_ai_fix_billed,
    normalize_page_field,
    validate_seo_score_ai_fix_input,
)
from app.services.seo_score_wp_apply import SeoScoreApplyError, apply_seo_score_fix_to_wordpress
from app.services.trial_access import require_active_trial
from app.services.url_safety import assert_public_http_url
from app.services.user_api_access import load_llm_config_for_request

router = APIRouter(tags=["seo-score"])
_LOG = logging.getLogger(__name__)


@router.post("/seo-score/ai-fix", response_model=SeoScoreAiFixResponse)
def api_seo_score_ai_fix(
    payload: SeoScoreAiFixRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> SeoScoreAiFixResponse:
    """
    Đề xuất sửa đúng một trường SEO (title, meta, heading, image alt, …).
    Billing: seo_score_ai_fix_billing_session (reserve → commit / release).
    """
    url = str(payload.url or "").strip()
    assert_public_http_url(url, label="URL")
    page_field = normalize_page_field(payload.page_field)
    if not page_field:
        raise HTTPException(status_code=400, detail="Thiếu page_field.")
    try:
        validate_seo_score_ai_fix_input(
            page_field=page_field,
            current_value=payload.current_value,
            evidence=payload.evidence,
            keyword=(payload.keyword or "").strip(),
        )
    except SeoScoreAiFixError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    llm_cfg = load_llm_config_for_request(db, current_user)
    try:
        result, credit_info = execute_seo_score_ai_fix_billed(
            db,
            current_user,
            url=url,
            keyword=(payload.keyword or "").strip(),
            group_key=(payload.group_key or "").strip(),
            issue_id=(payload.issue_id or "").strip(),
            page_field=page_field,
            current_value=payload.current_value,
            evidence=payload.evidence,
            llm_cfg=llm_cfg,
        )
    except SeoScoreAiFixError as exc:
        _LOG.info("seo_score_ai_fix failed user=%s field=%s: %s", current_user.id, page_field, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("seo_score_ai_fix unexpected error user=%s field=%s", current_user.id, page_field)
        raise HTTPException(status_code=502, detail="Không thể tạo đề xuất AI. Vui lòng thử lại.") from exc

    db.commit()

    return SeoScoreAiFixResponse(
        before=result.get("before"),
        after=result.get("after"),
        reason=str(result.get("reason") or ""),
        confidence=float(result.get("confidence") or 0.0),
        warnings=list(result.get("warnings") or []),
        credit=credit_info,
    )


@router.post("/seo-score/apply-fix", response_model=SeoScoreApplyFixResponse)
def api_seo_score_apply_fix(
    payload: SeoScoreApplyFixRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> SeoScoreApplyFixResponse:
    """Áp dụng bản tối ưu AI lên WordPress nếu URL thuộc project đã kết nối."""
    url = str(payload.url or "").strip()
    assert_public_http_url(url, label="URL")
    page_field = normalize_page_field(payload.page_field)
    if not page_field:
        raise HTTPException(status_code=400, detail="Thiếu page_field.")

    try:
        result = apply_seo_score_fix_to_wordpress(
            db,
            user_id=current_user.id,
            project_id=payload.project_id,
            url=url,
            page_field=page_field,
            before=payload.before,
            after=payload.after,
            issue_id=(payload.issue_id or "").strip(),
        )
        db.commit()
    except SeoScoreApplyError as exc:
        db.commit()
        if exc.manual_only:
            return SeoScoreApplyFixResponse(
                ok=True,
                applied=False,
                manual_only=True,
                message=str(exc),
                page_field=page_field,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("seo_score_apply_fix failed user=%s field=%s", current_user.id, page_field)
        raise HTTPException(status_code=502, detail="Không thể áp dụng lên WordPress. Vui lòng thử lại.") from exc

    return SeoScoreApplyFixResponse.model_validate(result)
