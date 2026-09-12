"""Repository for `user_feedback` (thumbs up/down + optional type/comment).

An important signal, but never one that overrides deterministic evidence by
itself -- see `core.learning.reflection_engine`, which reads this alongside
verification results rather than instead of them.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class UserFeedbackRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, execution_id: str, *, rating: str, feedback_type: str | None, comment: str | None,
    ) -> dict[str, Any]:
        feedback_id = new_id("feedback")
        await self._db.execute(
            """
            INSERT INTO user_feedback (id, execution_id, rating, feedback_type, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, execution_id, rating, feedback_type, comment, utc_now().isoformat()),
        )
        row = await self._db.fetch_one("SELECT * FROM user_feedback WHERE id = ?", (feedback_id,))
        assert row is not None
        return dict(row)

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM user_feedback WHERE execution_id = ? ORDER BY created_at DESC",
            (execution_id,),
        )
        return [dict(row) for row in rows]
