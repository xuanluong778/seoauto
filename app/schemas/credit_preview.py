"""Credit action preview — cost, quota, cache hint before user confirms."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreditPreviewRequest(BaseModel):
    module: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    quantity: int = Field(default=1, ge=1, le=10_000)
    from_cache: bool = False
    quota_key: str | None = Field(default=None, max_length=64)
    word_count: int | None = Field(default=None, ge=0, le=50_000)
    label: str | None = Field(default=None, max_length=200)
    # Lead scanner quote params (internal preview only — no external API)
    lead_mode: str | None = None
    lead_limit: int | None = Field(default=None, ge=1, le=500)


class CreditPreviewResponse(BaseModel):
    credits_enabled: bool
    module: str
    action: str
    label: str
    credit_cost: int
    credit_balance: int
    sufficient_credits: bool
    quota_key: str | None = None
    quota_label: str | None = None
    quota_remaining: int | None = None
    quota_limit: int | None = None
    quota_exceeded: bool = False
    data_source: str  # cache | api
    data_source_label: str
    high_cost_warning: bool = False
    high_cost_threshold: int = 0
    can_proceed: bool
    breakdown: dict[str, Any] | None = None
