from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AffiliateApiResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Any = None
    error: str | None = None


class AffiliateRegisterBody(BaseModel):
    pass


class AffiliateTrackClickBody(BaseModel):
    referral_code: str = Field(..., min_length=4, max_length=32)
    landing_page: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None


class AffiliatePayoutInfoBody(BaseModel):
    bank_name: str = Field(..., min_length=2, max_length=128)
    bank_account_name: str = Field(..., min_length=2, max_length=128)
    bank_account_number: str = Field(..., min_length=6, max_length=64)
    payout_method: str = Field(default="bank", max_length=32)


class AffiliatePayoutRequestBody(BaseModel):
    amount: int | None = Field(default=None, ge=1000)


class AffiliateRejectBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class AffiliatePayoutPaidBody(BaseModel):
    transaction_ref: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=500)


class AffiliateSettingsBody(BaseModel):
    default_commission_rate: int = Field(default=30, ge=0, le=100)
    cookie_days: int = Field(default=60, ge=1, le=365)
    min_payout_amount: int = Field(default=200000, ge=0)
    commission_hold_days: int = Field(default=7, ge=0, le=90)
    auto_approve_commissions: bool = False
