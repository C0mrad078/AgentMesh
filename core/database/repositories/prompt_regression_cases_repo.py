"""Repository for `prompt_regression_cases` -- the fixed set of behaviors a
candidate prompt/rule must not break (see `core.learning.prompt_regression`)."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class PromptRegressionCasesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def seed(self, target: str, name: str, description: str) -> None:
        existing = await self._db.fetch_one(
            "SELECT id FROM prompt_regression_cases WHERE target = ? AND name = ?", (target, name)
        )
        if existing:
            return
        await self._db.execute(
            """
            INSERT INTO prompt_regression_cases (id, target, name, description, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (new_id("regcase"), target, name, description, utc_now().isoformat()),
        )

    async def list_active(self, target: str | None = None) -> list[dict[str, Any]]:
        if target:
            rows = await self._db.fetch_all(
                "SELECT * FROM prompt_regression_cases WHERE active = 1 AND target = ?", (target,)
            )
        else:
            rows = await self._db.fetch_all("SELECT * FROM prompt_regression_cases WHERE active = 1")
        return [dict(row) for row in rows]
