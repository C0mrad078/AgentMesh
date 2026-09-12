"""Repository for `rule_evidence` -- the audit trail of *why* a rule's
confidence changed: which execution supported or contradicted it."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class RuleEvidenceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        rule_id: str,
        *,
        execution_id: str | None,
        project_id: str | None,
        outcome: str,
        detail: str = "",
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO rule_evidence (id, rule_id, execution_id, project_id, outcome, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("evidence"), rule_id, execution_id, project_id, outcome, detail, utc_now().isoformat()),
        )

    async def list_for_rule(self, rule_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM rule_evidence WHERE rule_id = ? ORDER BY created_at DESC", (rule_id,)
        )
        return [dict(row) for row in rows]
