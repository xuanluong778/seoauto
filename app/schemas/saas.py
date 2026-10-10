"""Pydantic schemas for SaaS Phase 1 (plans, subscriptions, entitlements)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UsageLimitResponse(BaseModel):
    id: int
    plan_id: int
    feature_key: str
    limit_value: int
    period: str
    is_hard_limit: bool

    model_config = {"from_attributes": True}


class PlanResponse(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    price_amount: int
    currency: str
    billing_cycle: str
    is_active: bool
    is_public: bool
    sort_order: int
    usage_limits: list[UsageLimitResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    id: int
    user_id: int
    plan_id: int
    status: str
    started_at: datetime
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    cancelled_at: datetime | None = None
    ended_at: datetime | None = None
    source: str
    notes: str | None = None
    plan_slug: str | None = None
    plan_name: str | None = None

    model_config = {"from_attributes": True}


class UserPlanSnapshot(BaseModel):
    user_id: int
    has_active_subscription: bool
    subscription: SubscriptionResponse | None = None
    plan: PlanResponse | None = None
    effective_plan_slug: str | None = None


class EntitlementResult(BaseModel):
    allowed: bool
    reason_code: str
    message: str
    plan_slug: str | None = None
    subscription_id: int | None = None
    quota_remaining: int | None = None
    feature_key: str


class GrantSubscriptionRequest(BaseModel):
    user_id: int
    plan_id: int
    months: int = Field(default=1, ge=1, le=36)
    status: str = Field(default="active", description="active | trialing")
    source: str = "manual"
    notes: str | None = None


class RecordUsageRequest(BaseModel):
    user_id: int
    feature_key: str
    quantity: int = Field(default=1, ge=1)
    subscription_id: int | None = None
    plan_id: int | None = None
    credits_used: int = Field(default=0, ge=0)
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None


class AdminGrantSubscriptionBody(BaseModel):
    plan_slug: str = Field(..., min_length=1, max_length=64)
    months: int = Field(default=1, ge=1, le=36)
    billing_cycle: str = Field(default="monthly", description="monthly | semi_annual | yearly")
    notes: str | None = None


class AdminGiftPlanBody(BaseModel):
    plan_slug: str = Field(..., min_length=1, max_length=64)
    duration_days: int | None = Field(default=None, ge=1, le=1095)
    duration_months: int | None = Field(default=None, ge=1, le=36)
    include_credit: bool = Field(default=False, description="Tặng kèm credit 1 tháng theo gói")
    notes: str | None = Field(default=None, max_length=500)


class AdminGiftUsageDaysBody(BaseModel):
    days: int = Field(..., ge=1, le=365)
    notes: str | None = Field(default=None, max_length=500)


class AdminGiftEligibilityResponse(BaseModel):
    user_id: int
    has_credit_purchase: bool
    has_active_subscription: bool
    can_gift_days: bool
    free_usage_days_remaining: int = 0
    message: str | None = None


class AdminGiftHistoryItem(BaseModel):
    id: int
    gift_type: str
    badge: str
    action: str
    admin_id: int | None = None
    plan_slug: str | None = None
    plan_name: str | None = None
    duration_days: int | None = None
    duration_months: int | None = None
    days_granted: int | None = None
    credits_granted: int = 0
    notes: str | None = None
    created_at: str


class AdminGiftHistoryResponse(BaseModel):
    items: list[AdminGiftHistoryItem] = Field(default_factory=list)
    total: int = 0


class AdminGiftPlanResponse(BaseModel):
    ok: bool = True
    gift_type: str = "plan"
    subscription_id: int
    subscription_action: str | None = None
    plan_slug: str
    plan_name: str | None = None
    duration_days: int | None = None
    duration_months: int | None = None
    credits_granted: int = 0
    include_credit: bool = False
    current_period_end: str | None = None
    notes: str | None = None


class AdminGiftUsageDaysResponse(BaseModel):
    ok: bool = True
    gift_type: str = "usage_days"
    subscription_id: int | None = None
    plan_slug: str | None = None
    plan_name: str | None = None
    days_granted: int
    previous_free_usage_expires_at: str | None = None
    free_usage_expires_at: str | None = None
    free_usage_days_remaining: int = 0
    notes: str | None = None
    admin_id: int | None = None
    user_id: int | None = None


class AdminTestRecordUsageBody(BaseModel):
    feature_key: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(default=1, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=128)


class AdminUserSubscriptionStatus(BaseModel):
    user_id: int
    subscription_id: int | None = None
    plan_slug: str | None = None
    plan_name: str | None = None
    status: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    notes: str | None = None
    message: str | None = None


class AdminTestRecordUsageResponse(BaseModel):
    ok: bool = True
    event_id: int
    idempotent_replay: bool = False
    feature_key: str
    quantity_used_month: int
    quota_remaining: int | None = None


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    total: int


class MonthlyUsageRow(BaseModel):
    feature_key: str
    quantity_used: int
    credits_used: int = 0
    limit_value: int | None = None
    quota_remaining: int | None = None
    period: str | None = None


class AdminUserUsageResponse(BaseModel):
    user_id: int
    usage_month: str
    plan_slug: str | None = None
    subscription_id: int | None = None
    items: list[MonthlyUsageRow] = Field(default_factory=list)
    message: str | None = None


class SaasQuotaItem(BaseModel):
    feature_key: str
    limit_value: int | None = None
    quantity_used: int = 0
    quota_remaining: int | None = None


class SaasMeResponse(BaseModel):
    user_id: int
    plan_slug: str | None = None
    plan_name: str | None = None
    subscription_status: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    usage_month: str
    quotas: list[SaasQuotaItem] = Field(default_factory=list)
    credit_balance: int = 0
    trial_status: str | None = None
    trial_message: str | None = None
    api_access_enabled: bool = False
    can_manage_api_keys: bool = False
    llm_source: str = "system"
    message: str | None = None
    byok_note: str | None = None
    trial_days: int | None = None
    standardized_quotas: dict[str, Any] | None = None
    free_usage_active: bool = False
    free_usage_days_remaining: int = 0
    free_usage_expires_at: datetime | None = None
    free_usage_banner: str | None = None
    needs_credit_for_features: bool = False
    free_usage_need_credit_message: str | None = None
    saas_trial_active: bool = False
    saas_trial_used: bool = False
    saas_trial_can_activate: bool = False
    saas_trial_days_remaining: int = 0
    saas_trial_credit_limit: int = 1000
    saas_trial_credit_used: int = 0
    saas_trial_credit_remaining: int = 0
    saas_trial_banner: str | None = None
    saas_trial_need_credit_message: str | None = None
    has_paid_plan: bool = False
    effective_plan_slug: str | None = None
    plan_source: str | None = None
    show_upgrade_banner: bool = False
    show_trial_expired_banner: bool = False
    ai_access_state: str | None = None
    ai_access_message: str | None = None
    can_use_ai: bool = False


class BillingAddonCredit(BaseModel):
    product_code: str
    price: int
    credits: int
    validity_months: int = 12


class BillingAddonArticle(BaseModel):
    product_code: str
    articles: int
    price: int | None = None
    price_label: str | None = None
    contact_sales: bool = False


class BillingPlanProductCodes(BaseModel):
    monthly: str
    yearly: str
    semi_annual: str | None = None


class BillingSaasProduct(BaseModel):
    product_code: str
    product_type: str = "saas_plan"
    name: str
    plan_slug: str
    billing_cycle: str
    price: int
    currency: str = "VND"
    period_days: int
    duration_months: int | None = None
    monthly_credit: int | None = None
    base_credit: int | None = None
    bonus_credit: int | None = None
    total_credit: int | None = None
    base_duration_months: int | None = None
    bonus_duration_months: int | None = None
    total_duration_months: int | None = None


class BillingPlanHighlight(BaseModel):
    label: str
    value: str
    emphasize: str | None = None
    free: str | None = None


class BillingCompareRow(BaseModel):
    key: str
    label: str


class BillingPlanCard(BaseModel):
    slug: str
    name: str
    fit: str = ""
    month_price: int = 0
    year_price: int = 0
    semi_annual_price: int = 0
    semi_annual_total_credit: int = 0
    semi_annual_bonus_credit: int = 0
    yearly_total_credit: int = 0
    yearly_bonus_credit: int = 0
    is_popular: bool = False
    badge: str = ""
    cta: str = "Nâng cấp gói"
    features: list[dict[str, Any]] = Field(default_factory=list)
    highlights: list[BillingPlanHighlight] = Field(default_factory=list)
    compare: dict[str, Any] = Field(default_factory=dict)
    tier: int = 0
    product_codes: BillingPlanProductCodes | None = None


class BillingCatalogResponse(BaseModel):
    plan_slugs: list[str] = Field(default_factory=list)
    plans: list[BillingPlanCard] = Field(default_factory=list)
    compare_rows: list[BillingCompareRow] = Field(default_factory=list)
    products: list[BillingSaasProduct] = Field(default_factory=list)
    credit_addons: list[BillingAddonCredit] = Field(default_factory=list)
    credit_addon_notes: list[str] = Field(default_factory=list)
    article_addons: list[BillingAddonArticle] = Field(default_factory=list)
    article_addon_notes: list[str] = Field(default_factory=list)
    catalog_revision: int | None = None


class PaymentOrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str = Field(..., min_length=2, max_length=64)


class CreatePaymentOrderResponse(BaseModel):
    success: bool = True
    contact_sales: bool = False
    order_code: str | None = None
    product_code: str
    product_name: str | None = None
    base_amount: int | None = None
    vat_amount: int | None = None
    vat_percent: int | None = None
    amount: int | None = None
    bank_code: str | None = None
    bank_account: str | None = None
    bank_holder: str | None = None
    transfer_content: str | None = None
    expired_at: datetime | None = None
    qr_url: str | None = None
    status: str | None = None
    message: str | None = None


class PaymentOrderResponse(BaseModel):
    id: int
    order_code: str
    product_code: str
    amount: int
    status: str
    bank_code: str
    bank_account: str
    bank_holder: str
    expired_at: datetime
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PaymentOrderListResponse(BaseModel):
    items: list[PaymentOrderResponse] = Field(default_factory=list)
    total: int = 0


class PaymentOrderStatusResponse(BaseModel):
    """Lightweight order status for payment polling UI."""

    order_code: str
    product_code: str
    product_name: str
    base_amount: int
    vat_amount: int
    vat_percent: int = 10
    amount: int
    status: str
    poll_status: str | None = None
    paid_at: datetime | None = None
    expired_at: datetime
    activation_status: str | None = None
    activation_error: str | None = None


class AdminPricingPlanItem(BaseModel):
    id: int
    slug: str
    name: str
    fit: str = ""
    month_price: int = 0
    year_price: int = 0
    credit_per_month: int = 0
    users: int = 0
    projects: int = 0
    ai_articles_per_month: int = 0
    bulk_writer_per_run: int = 0
    saved_articles_max: int = 0
    auto_update: int = 0
    rank_tracking: int = 0
    technical_audit: int = 0
    crawl_per_run: int = 0
    seo_score: int = 0
    social_auto: int = 0
    is_popular: bool = False
    is_active: bool = True


class AdminPricingPlanListResponse(BaseModel):
    items: list[AdminPricingPlanItem] = Field(default_factory=list)
    total: int = 0


class AdminPricingPlanUpdateBody(BaseModel):
    month_price: int = Field(ge=0)
    year_price: int = Field(ge=0)
    credit_per_month: int = Field(ge=0)
    users: int = Field(ge=0)
    projects: int = Field(ge=0)
    ai_articles_per_month: int = Field(ge=0)
    bulk_writer_per_run: int = Field(ge=0)
    saved_articles_max: int = Field(ge=0)
    auto_update: int = Field(ge=0)
    rank_tracking: int = Field(ge=0)
    technical_audit: int = Field(ge=0)
    crawl_per_run: int = Field(ge=0)
    seo_score: int = Field(ge=0)
    social_auto: int = Field(ge=0)
    is_popular: bool = False
    is_active: bool = True


class AdminPricingResetBody(BaseModel):
    slug: str | None = Field(default=None, description="Reset one plan; omit to reset all 4 plans")


class AdminPlanQuotaRow(BaseModel):
    quota_key: str
    feature_key: str
    label: str
    limit_value: int
    default_value: int
    period: str = "monthly"
    is_custom: bool = False


class AdminPlanQuotaPlan(BaseModel):
    plan_slug: str
    plan_name: str
    quotas: list[AdminPlanQuotaRow]
    features: dict[str, Any] = Field(default_factory=dict)


class AdminPlanQuotaListResponse(BaseModel):
    items: list[AdminPlanQuotaPlan]


class AdminPlanQuotaPatch(BaseModel):
    limit_value: int = Field(ge=0, le=10_000_000)


class ContentAiUsageItem(BaseModel):
    feature_key: str
    quantity_used: int = 0
    limit_value: int | None = None
    quota_remaining: int | None = None
    usage_percent: float | None = None
    is_unlimited: bool = False
    is_over_quota: bool = False
    is_warning: bool = False


class ContentAiUsageResponse(BaseModel):
    user_id: int
    usage_month: str
    plan_slug: str | None = None
    plan_name: str | None = None
    enforcement_enabled: bool = False
    bypass_entitlement: bool = False
    items: list[ContentAiUsageItem] = Field(default_factory=list)
    any_warning: bool = False
    any_over_quota: bool = False


class BillingAlertItem(BaseModel):
    level: str
    code: str
    message: str


class BillingExpiringCreditItem(BaseModel):
    amount: int
    source_type: str
    source_label: str
    expired_at: datetime
    days_left: int | None = None


class BillingModuleCreditItem(BaseModel):
    module: str
    label: str
    credits_used: int
    share_percent: float | None = None


class BillingQuotaUsageItem(BaseModel):
    key: str | None = None
    feature_key: str | None = None
    label: str
    limit: int
    used: int
    remaining: int
    percent_used: float = 0.0
    warning: bool = False


class BillingCreditHistoryItem(BaseModel):
    id: int
    delta: int
    credit_used: int
    balance_after: int
    module: str | None = None
    action: str | None = None
    label: str
    note: str | None = None
    created_at: datetime


class BillingPaymentHistoryItem(BaseModel):
    order_code: str | None = None
    product_code: str
    product_name: str
    amount: int
    status: str
    paid_at: datetime | None = None
    created_at: datetime
    activation_status: str | None = None


class BillingOverviewResponse(BaseModel):
    usage_month: str
    plan_slug: str | None = None
    plan_name: str | None = None
    subscription_status: str | None = None
    trial_status: str | None = None
    trial_message: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    byok_note: str | None = None
    credit_balance: int = 0
    available_credit: int = 0
    locked_credit: int = 0
    purchased_credit: int = 0
    renewal_grant_preview: dict[str, Any] | None = None
    locked_message: str | None = None
    has_active_subscription: bool = False
    credit_wallet: dict[str, Any] | None = None
    credit_expiring_soon: list[BillingExpiringCreditItem] = Field(default_factory=list)
    module_credit_usage: list[BillingModuleCreditItem] = Field(default_factory=list)
    top_credit_module: BillingModuleCreditItem | None = None
    quotas: list[BillingQuotaUsageItem] = Field(default_factory=list)
    credit_history: list[BillingCreditHistoryItem] = Field(default_factory=list)
    payment_history: list[BillingPaymentHistoryItem] = Field(default_factory=list)
    alerts: list[BillingAlertItem] = Field(default_factory=list)
    low_credit_threshold: int = 100
    free_usage_active: bool = False
    free_usage_days_remaining: int = 0
    free_usage_expires_at: datetime | None = None
    free_usage_banner: str | None = None
    needs_credit_for_features: bool = False
    free_usage_need_credit_message: str | None = None
