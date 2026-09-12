"""Repository for the `reflections` table -- one row per `ReflectionEngine.reflect()` call."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.learning.models import Finding, ImprovementCandidate, ReflectionResult
from core.utils.ids import new_id
from core.utils.time import utc_now

_JSON_LIST_FIELDS = (
    "findings", "successful_patterns", "problems", "improvement_candidates",
    "routing_feedback", "prompt_feedback", "cost_feedback", "context_feedback",
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    for field_name in _JSON_LIST_FIELDS:
        item[field_name] = loads(item[field_name], [])
    item["deterministic_evidence"] = loads(item["deterministic_evidence"], {})
    return item


class ReflectionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, result: ReflectionResult) -> str:
        reflection_id = new_id("reflection")
        await self._db.execute(
            """
            INSERT INTO reflections
                (id, execution_id, task_id, depth, overall_score, findings,
                 successful_patterns, problems, improvement_candidates, routing_feedback,
                 prompt_feedback, cost_feedback, context_feedback, deterministic_evidence,
                 ai_narrative, reflection_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reflection_id, result.execution_id, result.task_id, result.depth.value,
                result.overall_score,
                dumps([asdict(f) for f in result.findings]),
                dumps(list(result.successful_patterns)),
                dumps(list(result.problems)),
                dumps([asdict(c) for c in result.improvement_candidates]),
                dumps(list(result.routing_feedback)),
                dumps(list(result.prompt_feedback)),
                dumps(list(result.cost_feedback)),
                dumps(list(result.context_feedback)),
                dumps(result.deterministic_evidence),
                result.ai_narrative,
                result.reflection_cost_usd,
                utc_now().isoformat(),
            ),
        )
        return reflection_id

    async def get(self, reflection_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM reflections WHERE id = ?", (reflection_id,))
        return _row_to_dict(row) if row else None

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM reflections WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        return [_row_to_dict(row) for row in rows]

    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_dict(row) for row in rows]


__all__ = ["ReflectionsRepository", "Finding", "ImprovementCandidate"]
