"""Admin SaaS economics API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EconomicsProviderRow(BaseModel):
    provider: str
    label: str
    credits: int
    estimated_cost_vnd: int


class EconomicsModuleRow(BaseModel):
    module: str
    credits: int


class EconomicsActionRow(BaseModel):
    module: str
    action: str
    credits: int


class EconomicsUserBurnRow(BaseModel):
    user_id: int
    email: str
    credits: int


class EconomicsRevenueBucket(BaseModel):
    subscription_gross_vnd: int
    subscription_base_vnd: int
    credit_pack_gross_vnd: int
    credit_pack_base_vnd: int
    total_gross_vnd: int
    total_base_vnd: int


class EconomicsAtRiskUser(BaseModel):
    user_id: int
    email: str
    credits_burned: int
    estimated_cost_vnd: int
    revenue_base_vnd: int
    risk_score: float


class EconomicsAlert(BaseModel):
    level: str
    period: str
    message: str
    estimated_cost_vnd: int | None = None
    threshold_vnd: int | None = None
    blocked_at: str | None = None


class EconomicsSettings(BaseModel):
    daily_cost_threshold_vnd: int = Field(ge=0)
    monthly_cost_threshold_vnd: int = Field(ge=0)
    usd_to_vnd: int = Field(ge=1)
    vnd_per_credit: dict[str, int]
    auto_block_expensive_api: bool = True
    alert_cooldown_hours: int = Field(ge=1, le=168)
    at_risk_burn_credits: int = Field(ge=0)
    at_risk_cost_revenue_ratio: float = Field(ge=0.1)


class EconomicsSettingsPatch(BaseModel):
    daily_cost_threshold_vnd: int | None = Field(default=None, ge=0)
    monthly_cost_threshold_vnd: int | None = Field(default=None, ge=0)
    usd_to_vnd: int | None = Field(default=None, ge=1)
    vnd_per_credit: dict[str, int] | None = None
    auto_block_expensive_api: bool | None = None
    alert_cooldown_hours: int | None = Field(default=None, ge=1, le=168)
    at_risk_burn_credits: int | None = Field(default=None, ge=0)
    at_risk_cost_revenue_ratio: float | None = Field(default=None, ge=0.1)


class EconomicsDashboardResponse(BaseModel):
    generated_at: str
    period: dict[str, str]
    settings: dict[str, Any]
    expensive_api_blocked: bool
    block_reason: str | None = None
    blocked_at: str | None = None
    credit_burn: dict[str, int]
    estimated_cost_vnd: dict[str, int]
    by_provider: dict[str, list[EconomicsProviderRow]]
    by_module: dict[str, list[EconomicsModuleRow]]
    by_action: dict[str, list[EconomicsActionRow]]
    by_user: dict[str, list[EconomicsUserBurnRow]]
    revenue: dict[str, EconomicsRevenueBucket]
    profit_vnd: dict[str, int]
    at_risk_users: list[EconomicsAtRiskUser]
    alerts: list[EconomicsAlert]
    dataforseo_usage: dict[str, Any] | None = None


class EconomicsUnblockResponse(BaseModel):
    ok: bool = True
    expensive_api_blocked: bool
    message: str
