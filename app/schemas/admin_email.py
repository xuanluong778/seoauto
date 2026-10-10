from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator


class EmailAutomationTemplateSave(BaseModel):
    email_type: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    name: str = Field(default="Automation Template")
    subject_template: str = Field(default="")
    preheader_template: Optional[str] = None
    html_body_template: str = Field(default="")
    text_body_template: Optional[str] = None


class EmailMarketingCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=255)
    preheader: Optional[str] = Field(default=None, max_length=180)
    html_body: str = Field(min_length=1)
    text_body: Optional[str] = None

    cta_label: str = Field(default="Mở ngay", max_length=120)
    cta_url: str = Field(default="https://seoauto.vn/account-billing", min_length=1)

    discount_code: Optional[str] = None

    segment_kind: Literal["all", "trial", "active", "expired", "low_credit", "by_plan"] = "all"
    segment_plan_id: Optional[int] = None
    # Optional: only these users receive the campaign (shown/selected in admin UI).
    recipient_user_ids: Optional[list[int]] = None

    send_mode: Literal["now", "scheduled", "draft"] = "now"
    scheduled_at: Optional[datetime] = None
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)

    @field_validator("cta_url", mode="before")
    @classmethod
    def _default_cta_url(cls, v):
        s = str(v or "").strip()
        return s or "https://seoauto.vn/account-billing"

    @field_validator("cta_label", mode="before")
    @classmethod
    def _default_cta_label(cls, v):
        s = str(v or "").strip()
        return s or "Mở ngay"

    @field_validator("name", "subject", "html_body", mode="before")
    @classmethod
    def _strip_required(cls, v):
        return str(v or "").strip()


class EmailCampaignSendAction(BaseModel):
    noop: bool = False


class EmailAiComposeRequest(BaseModel):
    action: Literal["generate", "rewrite", "shorter", "professional", "sales"] = "generate"
    goal: str = ""
    segment: str = "active"
    tone: str = "professional"
    offer: str = ""
    cta_label: str = "Mở ngay"
    cta_url: str = ""
    current_subject: str = ""
    current_html: str = ""


class EmailPreviewRequest(BaseModel):
    subject: str = ""
    preheader: str = ""
    html_body: str = ""
    text_body: Optional[str] = None
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None
    name: str = "Nguyễn Văn A"
    plan: str = "Pro"
    expiry_date: str = "2026-12-31"
    credit_balance: str = "120"


class EmailTestSendRequest(BaseModel):
    to: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    preheader: str = ""
    html_body: str = Field(min_length=1)
    text_body: Optional[str] = None
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None
