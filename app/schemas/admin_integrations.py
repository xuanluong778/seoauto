"""Admin integration configuration schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SinbyteSaveRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)


class SinbyteStatusResponse(BaseModel):
    ok: bool = True
    provider: str
    provider_label: str
    configured: bool
    connected: bool
    source: str = ""
    api_key_masked: str = ""
    updated_at: str | None = None
    last_test_at: str | None = None
    last_test_ok: bool | None = None
    last_test_message: str = ""


class SinbyteActionResponse(BaseModel):
    ok: bool
    message: str = ""
    connected: bool | None = None
    api_key_masked: str = ""
    status: SinbyteStatusResponse | None = None
