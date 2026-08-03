from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.password_policy import validate_password_strength


class AdminUserSummary(BaseModel):
    id: int
    email: str
    role: str
    status: str
    credit_balance: int = 0
    chatbot_cskh_bonus_credits: int = 0
    has_password: bool = True
    api_access_enabled: bool = False
    use_admin_api_pool: bool = False
    allow_custom_api_key: bool = False
    llm_source: str = "system"
    created_at: datetime | None = None
    account_activated: bool = False
    trial_status: str = "none"
    trial_started_at: str | None = None
    trial_ends_at: str | None = None
    trial_days_remaining: int = 0
    trial_is_active: bool = False
    trial_never_used: bool = True
    trial_message: str = ""

    model_config = {"from_attributes": True}


class AdminUserListResponse(BaseModel):
    items: list[AdminUserSummary]
    total: int


class AdminUserRoleUpdate(BaseModel):
    role: str = Field(..., description="admin | user | editor | viewer")


class AdminUserStatusUpdate(BaseModel):
    status: str = Field(..., description="active | inactive | banned")


class AdminUserApiAccessUpdate(BaseModel):
    api_access_enabled: bool | None = None
    use_admin_api_pool: bool | None = None
    allow_custom_api_key: bool | None = None


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user", description="admin | user | editor | viewer")
    status: str = Field(default="active", description="active | inactive | banned")
    api_access_enabled: bool = False
    use_admin_api_pool: bool = False
    initial_credits: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class AdminUserCreateResponse(BaseModel):
    ok: bool = True
    user: AdminUserSummary


class AdminUserDetailResponse(BaseModel):
    user: AdminUserSummary
    seo_projects: list[dict[str, Any]]
    content_ai_projects: list[dict[str, Any]]
    knowledge_bases: list[dict[str, Any]]
    bulk_jobs: list[dict[str, Any]]
    api_keys: list[dict[str, Any]]
    publishing_sites: list[dict[str, Any]]
    trial: dict[str, Any]
    audit_logs: list[dict[str, Any]]
    credit_history: list["AdminCreditHistoryRow"] = Field(default_factory=list)


class AdminGrantCreditsRequest(BaseModel):
    credit_type: str = Field(..., description="plan_monthly | purchased | admin_adjustment | refund")
    amount: int = Field(..., gt=0, le=1_000_000)
    reason: str = Field(..., min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("credit_type")
    @classmethod
    def validate_credit_type(cls, v: str) -> str:
        from app.models.credit_ledger_entry import CREDIT_SOURCE_TYPES

        key = str(v or "").strip().lower()
        if key not in CREDIT_SOURCE_TYPES:
            raise ValueError("Loại credit không hợp lệ.")
        return key

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if int(v) <= 0:
            raise ValueError("Số credit không hợp lệ.")
        return int(v)


class AdminGrantCreditsResponse(BaseModel):
    ok: bool = True
    message: str = "Đã tặng credit thành công."
    user: AdminUserSummary
    new_balance: int


class AdminCreditHistoryRow(BaseModel):
    id: int
    created_at: datetime | None = None
    credit_type: str | None = None
    amount: int
    transaction_type: str
    grant_reason: str | None = None
    internal_note: str | None = None
    source_label: str
    admin_id: int | None = None
    admin_email: str | None = None
    balance_after: int


class AdminGrantChatbotCreditsRequest(BaseModel):
    amount: int = Field(..., gt=0, le=1_000_000)
    operation: str = Field(default="add", description="add | subtract")
    reason: str = Field(..., min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, v: str) -> str:
        key = str(v or "add").strip().lower()
        if key not in ("add", "subtract"):
            raise ValueError("Thao tác không hợp lệ.")
        return key


class AdminGrantChatbotCreditsResponse(BaseModel):
    ok: bool = True
    message: str = "Đã cập nhật credit chatbot thành công."
    user: AdminUserSummary
    new_balance: int


class AdminAuditLogRow(BaseModel):
    id: int
    user_id: int | None
    action: str
    resource_type: str
    resource_id: str
    detail_json: str
    ip_address: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminAuditListResponse(BaseModel):
    items: list[AdminAuditLogRow]


class AdminCreditCostRow(BaseModel):
    module: str
    action: str
    credit_cost: int
    cache_discount_percent: int = 80
    cache_zero_cost: bool = False
    label: str | None = None
    description: str | None = None
    is_default: bool = True


class AdminCreditCostListResponse(BaseModel):
    items: list[AdminCreditCostRow]


class AdminCreditCostPatch(BaseModel):
    credit_cost: int | None = Field(default=None, ge=0)
    cache_discount_percent: int | None = Field(default=None, ge=0, le=100)
    cache_zero_cost: bool | None = None
    label: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
