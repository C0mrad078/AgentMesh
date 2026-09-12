"""Repository for `learning_candidates` -- observations that have not yet
earned enough evidence to become an active `learned_rules` row.

A single execution's finding ("Gemini was unnecessary here") is recorded as
`observations=1, confidence=~0.3` and never jumps straight to an active
rule (see `core.learning.learning_engine`, which is the only writer that
should call `record_observation`/`promote`/`reject`). Matching by
`normalized_key` is how the Learning Engine deduplicates near-identical
candidates instead of piling up near-duplicate rows for the same insight.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["distinct_projects"] = loads(item["distinct_projects"], [])
    return item


class LearningCandidatesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def find_by_normalized_key(self, normalized_key: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM learning_candidates WHERE normalized_key = ? "
            "AND status IN ('candidate', 'observing') ORDER BY created_at DESC LIMIT 1",
            (normalized_key,),
        )
        return _row_to_dict(row) if row else None

    async def find_promoted_by_normalized_key(self, normalized_key: str) -> dict[str, Any] | None:
        """A key that already graduated into an active rule -- further
        observations of the same insight should feed `record_rule_outcome`
        on that rule, not spawn a duplicate candidate."""
        row = await self._db.fetch_one(
            "SELECT * FROM learning_candidates WHERE normalized_key = ? "
            "AND status = 'promoted' AND promoted_rule_id IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 1",
            (normalized_key,),
        )
        return _row_to_dict(row) if row else None

    async def create(
        self,
        *,
        category: str,
        title: str,
        rule_text: str,
        scope_type: str,
        scope_value: str | None,
        normalized_key: str,
        source_reflection_id: str | None,
        confidence: float,
        project_id: str | None,
    ) -> dict[str, Any]:
        candidate_id = new_id("candidate")
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO learning_candidates
                (id, category, title, rule_text, scope_type, scope_value, normalized_key,
                 source_reflection_id, observations, successes, failures, distinct_projects,
                 confidence, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0, ?, ?, 'candidate', ?, ?)
            """,
            (
                candidate_id, category, title, rule_text, scope_type, scope_value,
                normalized_key, source_reflection_id, dumps([project_id] if project_id else []),
                confidence, now, now,
            ),
        )
        row = await self._db.fetch_one("SELECT * FROM learning_candidates WHERE id = ?", (candidate_id,))
        assert row is not None
        return _row_to_dict(row)

    async def record_observation(
        self, candidate_id: str, *, success: bool, confidence: float, project_id: str | None,
    ) -> dict[str, Any]:
        current = await self.get(candidate_id)
        assert current is not None
        projects = set(current["distinct_projects"])
        if project_id:
            projects.add(project_id)
        await self._db.execute(
            """
            UPDATE learning_candidates
            SET observations = observations + 1,
                successes = successes + ?,
                failures = failures + ?,
                distinct_projects = ?,
                confidence = ?,
                status = CASE WHEN status = 'candidate' THEN 'observing' ELSE status END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                1 if success else 0, 0 if success else 1, dumps(list(projects)), confidence,
                utc_now().isoformat(), candidate_id,
            ),
        )
        row = await self.get(candidate_id)
        assert row is not None
        return row

    async def get(self, candidate_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM learning_candidates WHERE id = ?", (candidate_id,))
        return _row_to_dict(row) if row else None

    async def mark_promoted(self, candidate_id: str, rule_id: str) -> None:
        await self._db.execute(
            "UPDATE learning_candidates SET status = 'promoted', promoted_rule_id = ?, "
            "updated_at = ? WHERE id = ?",
            (rule_id, utc_now().isoformat(), candidate_id),
        )

    async def mark_rejected(self, candidate_id: str, *, reason: str) -> None:
        await self._db.execute(
            "UPDATE learning_candidates SET status = 'rejected', rejection_reason = ?, "
            "updated_at = ? WHERE id = ?",
            (reason, utc_now().isoformat(), candidate_id),
        )

    async def list_pending(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM learning_candidates WHERE status IN ('candidate', 'observing') "
            "ORDER BY confidence DESC",
        )
        return [_row_to_dict(row) for row in rows]

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM learning_candidates ORDER BY created_at DESC")
        return [_row_to_dict(row) for row in rows]
