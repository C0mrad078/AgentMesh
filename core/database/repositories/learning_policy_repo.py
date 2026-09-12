"""Repository for the single-row `learning_policy` table -- the central
configuration the Learning Engine reads before applying any change (mode,
thresholds, rate limit). See `core.learning.models.LearningPolicySettings`.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.time import utc_now

_ROW_ID = "global"


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["auto_apply_categories"] = loads(item["auto_apply_categories"], [])
    item["requires_approval_categories"] = loads(item["requires_approval_categories"], [])
    return item


class LearningPolicyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self) -> dict[str, Any]:
        row = await self._db.fetch_one("SELECT * FROM learning_policy WHERE id = ?", (_ROW_ID,))
        if row is None:
            await self._db.execute(
                "INSERT INTO learning_policy (id, updated_at) VALUES (?, ?)",
                (_ROW_ID, utc_now().isoformat()),
            )
            row = await self._db.fetch_one("SELECT * FROM learning_policy WHERE id = ?", (_ROW_ID,))
        assert row is not None
        return _row_to_dict(row)

    async def update(
        self,
        *,
        mode: str | None = None,
        minimum_observations_for_activation: int | None = None,
        minimum_confidence: float | None = None,
        auto_apply_categories: list[str] | None = None,
        requires_approval_categories: list[str] | None = None,
        max_changes_per_day: int | None = None,
        rollback_threshold: float | None = None,
    ) -> dict[str, Any]:
        current = await self.get()
        updated = {
            "mode": mode if mode is not None else current["mode"],
            "minimum_observations_for_activation": (
                minimum_observations_for_activation
                if minimum_observations_for_activation is not None
                else current["minimum_observations_for_activation"]
            ),
            "minimum_confidence": (
                minimum_confidence if minimum_confidence is not None else current["minimum_confidence"]
            ),
            "auto_apply_categories": (
                auto_apply_categories
                if auto_apply_categories is not None
                else current["auto_apply_categories"]
            ),
            "requires_approval_categories": (
                requires_approval_categories
                if requires_approval_categories is not None
                else current["requires_approval_categories"]
            ),
            "max_changes_per_day": (
                max_changes_per_day if max_changes_per_day is not None else current["max_changes_per_day"]
            ),
            "rollback_threshold": (
                rollback_threshold if rollback_threshold is not None else current["rollback_threshold"]
            ),
        }
        await self._db.execute(
            """
            UPDATE learning_policy
            SET mode = ?, minimum_observations_for_activation = ?, minimum_confidence = ?,
                auto_apply_categories = ?, requires_approval_categories = ?,
                max_changes_per_day = ?, rollback_threshold = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated["mode"], updated["minimum_observations_for_activation"],
                updated["minimum_confidence"], dumps(updated["auto_apply_categories"]),
                dumps(updated["requires_approval_categories"]), updated["max_changes_per_day"],
                updated["rollback_threshold"], utc_now().isoformat(), _ROW_ID,
            ),
        )
        return await self.get()
