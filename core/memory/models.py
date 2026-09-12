"""Memory domain models.

`MemoryRecord` is intentionally generic: the same shape backs project
memory, execution memory, and agent memory (distinguished by `kind` and the
`project_id` it is attached to). `kind` is the coarse Stage 1 classification
(fact/execution_summary/agent_note/preference); `category` (Stage 3) is a
finer, project-memory-specific taxonomy (architecture/stack/decisions/
constraints/known_issues/preferences/commands/deployment/integrations) used
by the Learning Page and by agents deciding what to read back.

Every memory has provenance (`source_execution_id`/`source_file`/
`source_user_input`) and a `confidence` distinct from a learned rule's
confidence: a fact the user typed explicitly is `confidence=1.0` and never
auto-superseded by an inferred one; a fact inferred by an agent starts
lower. `valid_until`/`superseded_by` implement supersession (see
`core.memory.store.SqliteMemoryStore.remember`): a *new*, contradicting
value for the same key never overwrites the old row in place -- the old
row is marked superseded and a new row is inserted, so history stays
auditable ("não apagar histórico") while `recall`/`recall_all` only ever
return the currently-valid facts.
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


class MemoryCategory(str, Enum):
    ARCHITECTURE = "architecture"
    STACK = "stack"
    DECISIONS = "decisions"
    CONSTRAINTS = "constraints"
    KNOWN_ISSUES = "known_issues"
    PREFERENCES = "preferences"
    COMMANDS = "commands"
    DEPLOYMENT = "deployment"
    INTEGRATIONS = "integrations"
    OTHER = "other"


class MemoryProvenance(BaseModel):
    source_execution_id: str | None = None
    source_file: str | None = None
    source_user_input: bool = False


class MemoryRecord(BaseModel):
    id: str
    project_id: str
    kind: MemoryKind = MemoryKind.FACT
    category: MemoryCategory = MemoryCategory.OTHER
    key: str
    value: dict[str, Any] = Field(default_factory=dict)
    importance: float = 0.5
    confidence: float = 0.7
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    superseded_by: str | None = None
    created_at: datetime
    updated_at: datetime


class MemoryWrite(BaseModel):
    project_id: str
    kind: MemoryKind = MemoryKind.FACT
    category: MemoryCategory = MemoryCategory.OTHER
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
