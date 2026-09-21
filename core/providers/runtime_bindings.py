from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RuntimeBinding(BaseModel):
    id: str
    provider_id: str
    account_id: str | None = None
    label: str
    configured_capacity: int = Field(default=1, ge=1, le=32)
    observed_capacity: int = Field(default=1, ge=0, le=32)
    reserved_slots: int = Field(default=0, ge=0)
    health: str = "unknown"
    backoff_until: datetime | None = None
    enabled: bool = True
    last_diagnostic: str = ""
    last_reconciled_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RuntimeBindingCreate(BaseModel):
    provider_id: str
    account_id: str | None = None
    label: str = Field(min_length=1, max_length=200)
    configured_capacity: int = Field(default=1, ge=1, le=32)
