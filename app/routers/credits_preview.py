"""User credit preview before billable actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.credit_preview import CreditPreviewRequest, CreditPreviewResponse
from app.services.auth import get_current_user
from app.services.credit_preview_service import build_credit_preview

router = APIRouter(prefix="/credits", tags=["credits"])


@router.post("/preview", response_model=CreditPreviewResponse)
def credit_action_preview(
    payload: CreditPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreditPreviewResponse:
  """Ước tính credit/quota — không gọi API bên ngoài."""
  data = build_credit_preview(
      db,
      current_user,
      module=payload.module,
      action=payload.action,
      quantity=payload.quantity,
      from_cache=payload.from_cache,
      quota_key=payload.quota_key,
      word_count=payload.word_count,
      label=payload.label,
      lead_mode=payload.lead_mode,
      lead_limit=payload.lead_limit,
  )
  return CreditPreviewResponse.model_validate(data)
