"""Persisted provider catalog domain models (Refactor V2, Phase 1).

Distinct from everything else already in `core/providers/`:

  * `core.providers.base.ProviderAdapter` and friends are the *runtime*
    interface (`execute`/`stream`/`health_check`) -- unchanged by this
    module.
  * `core.providers.registry.ModelRegistry`/`ModelInfo` is the catalog of
    *models* a provider exposes -- unchanged.
  * This module is the catalog of *providers themselves* as durable rows
    (`Provider`), the *accounts* a provider may have more than one of
    (`ProviderAccount`, e.g. two Google accounts), and the *execution
    backends* configured for a provider (`ProviderBackend` -- the
    persisted half of "is Subscription/Session/API set up and connected
    for Claude", see `core.runtime.execution_backend.ExecutionBackendType`).

Nothing in this module talks to a real CLI or API -- see
`core.providers.provider_manager.ProviderManager` for the live discovery
that a `ProviderBackend` row's `status`/`detail` is meant to be refreshed
from, once a later phase wires that update path in.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.runtime.execution_backend import ExecutionBackendType


class ProviderAccountStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class ProviderBackendStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


class Provider(BaseModel):
    id: str
    name: str
    display_name: str
    created_at: datetime
    updated_at: datetime


class ProviderAccount(BaseModel):
    id: str
    provider_id: str
    label: str
    external_identifier: str | None = None
    status: ProviderAccountStatus = ProviderAccountStatus.DISCONNECTED
    created_at: datetime
    updated_at: datetime


class ProviderAccountCreate(BaseModel):
    provider_id: str
    label: str = Field(min_length=1, max_length=200)
    external_identifier: str | None = None


class ProviderBackend(BaseModel):
    id: str
    provider_id: str
    backend_type: ExecutionBackendType
    status: ProviderBackendStatus = ProviderBackendStatus.NOT_INSTALLED
    detail: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProviderBackendUpsert(BaseModel):
    provider_id: str
    backend_type: ExecutionBackendType
    status: ProviderBackendStatus = ProviderBackendStatus.NOT_INSTALLED
    detail: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
