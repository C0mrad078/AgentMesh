from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.utils.time import utc_now


class BackupManifest(BaseModel):
    """Immutable metadata accompanying a consistent SQLite snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str
    schema_version: int = Field(ge=0)
    app_version: str = "0.1.0-rc.1"
    created_at: datetime = Field(default_factory=utc_now)
    db_size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_path: str
    tables_count: int = Field(ge=0)
    records_summary: dict[str, int] = Field(default_factory=dict)
    protected: bool = False


class BackupInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: BackupManifest
    database_path: str
    manifest_path: str


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backup_id: str
    restored_path: str
    safety_snapshot_path: str
    schema_version: int


class RecoveryIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
