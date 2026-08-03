"""Admin billing / payment order schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminSepayTransactionRow(BaseModel):
    id: int
    sepay_transaction_id: str
    order_code: str | None = None
    account_number: str | None = None
    transfer_amount: int = 0
    transfer_type: str | None = None
    content: str | None = None
    raw_payload: Any = None
    created_at: datetime


class AdminPaymentOrderRow(BaseModel):
    id: int
    user_id: int
    user_email: str
    order_code: str | None = None
    product_code: str
    product_name: str
    amount: int
    status: str
    activation_status: str | None = None
    activation_error: str | None = None
    created_at: datetime
    paid_at: datetime | None = None
    expired_at: datetime
    sepay_transaction_count: int = 0


class AdminPaymentOrderDetail(AdminPaymentOrderRow):
    activation_result_json: str | None = None
    activated_at: datetime | None = None
    bank_code: str
    bank_account: str
    bank_holder: str
    sepay_transactions: list[AdminSepayTransactionRow] = Field(default_factory=list)


class AdminPaymentOrderListResponse(BaseModel):
    items: list[AdminPaymentOrderRow] = Field(default_factory=list)
    total: int = 0
    limit: int = 0
    offset: int = 0


class AdminBillingActionResponse(BaseModel):
    ok: bool = True
    message: str = ""
    order: AdminPaymentOrderRow | None = None
    activation: dict[str, Any] | None = None
