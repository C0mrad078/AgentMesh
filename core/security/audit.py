"""Audit logging facade used by services to record security-relevant actions.

Audit entries never carry secrets: callers pass a `context` dict that is
persisted as-is, so any call site touching credentials must redact before
calling `log()`. Sensitive-looking keys are additionally redacted here as a
defense-in-depth safety net (see `core.utils.logging.redact`).
"""

from __future__ import annotations

from typing import Any

from core.database.repositories.audit_logs_repo import AuditLogsRepository
from core.utils.logging import redact


class AuditLogger:
    def __init__(self, repository: AuditLogsRepository, *, actor: str = "system") -> None:
        self._repository = repository
        self._actor = actor

    async def log(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        await self._repository.insert(
            actor=self._actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            context=redact(context or {}),
        )
