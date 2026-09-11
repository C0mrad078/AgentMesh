"""Memory domain models.

`MemoryRecord` is intentionally generic: the same shape backs project
memory, execution memory, and agent memory (distinguished by `kind` and the
`project_id` it is attached to). This stage only implements simple
key/value fact storage; ranking, decay, and retrieval-by-relevance are left
for the learning stage, but nothing here needs to change shape for that to
be added -- `importance` and `kind` already exist for that purpose.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryKind(str, Enum):
    FACT = "fact"
    EXECUTION_SUMMARY = "execution_summary"
    AGENT_NOTE = "agent_note"
    PREFERENCE = "preference"


class MemoryRecord(BaseModel):
    id: str
    project_id: str
    kind: MemoryKind = MemoryKind.FACT
    key: str
    value: dict[str, Any] = Field(default_factory=dict)
    importance: float = 0.5
    created_at: datetime
    updated_at: datetime


class MemoryWrite(BaseModel):
    project_id: str
    kind: MemoryKind = MemoryKind.FACT
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
