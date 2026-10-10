from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.password_policy import validate_password_strength


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    otp: str = Field(min_length=4, max_length=12)

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_otp(cls, v: object) -> str:
        if v is None:
            return ""
        if not isinstance(v, str):
            v = str(v)
        return v.strip().replace(" ", "")

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    otp: str | None = Field(default=None, min_length=4, max_length=12)

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_otp(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            v = str(v)
        s = v.strip().replace(" ", "")
        return s if s else None

    @model_validator(mode="after")
    def password_strength_when_otp(self) -> "UserLogin":
        if self.otp:
            validate_password_strength(self.password)
        return self


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None


class UserResponse(BaseModel):
    id: int
    # Response must not 500 on legacy/test addresses already stored in DB.
    email: str
    created_at: datetime
    credit_balance: int = 0
    role: str = "user"
    status: str = "active"
    api_access_enabled: bool = False
    use_admin_api_pool: bool = False
    show_admin_nav: bool = False

    model_config = {"from_attributes": True}


class CreditGrantRequest(BaseModel):
    email: EmailStr
    amount: int = Field(gt=0, le=1_000_000)


class CreditsConfigResponse(BaseModel):
    enabled: bool


class CreditPackagePublic(BaseModel):
    id: str
    name: str
    credits: int = 0
    description: str = ""
    price_hint: str | None = None


class CreditPackagesResponse(BaseModel):
    credits_system_enabled: bool
    your_balance: int | None = None
    packages: list[CreditPackagePublic]
    footnote: str = ""


class CreditLedgerRow(BaseModel):
    id: int
    source_type: str
    amount: int
    remaining_amount: int
    expired_at: datetime | None = None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreditTransactionRow(BaseModel):
    """Legacy consumption/grant audit log."""

    id: int
    delta: int
    balance_after: int
    reason: str
    note: str | None
    module: str | None = None
    action: str | None = None
    credit_used: int | None = None
    request_id: str | None = None
    source: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreditGrantResult(BaseModel):
    ok: bool = True
    email: EmailStr
    new_balance: int


class CreditLedgerListResponse(BaseModel):
    items: list[CreditLedgerRow]
    balance: int = 0


class CreditTransactionListResponse(BaseModel):
    items: list[CreditTransactionRow]
    balance: int = 0


class CreditCostCatalogItem(BaseModel):
    module: str
    action: str
    credit_cost: int
    cache_discount_percent: int = 80
    cache_zero_cost: bool = False
    label: str | None = None
    description: str | None = None


class CreditCostCatalogResponse(BaseModel):
    items: list[CreditCostCatalogItem]
    credits_enabled: bool = False


class MessageResponse(BaseModel):
    message: str


class OtpSendRequest(BaseModel):
    email: EmailStr


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=4, max_length=12)
