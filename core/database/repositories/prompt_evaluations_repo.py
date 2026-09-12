"""Repository for `prompt_evaluations` -- the record of a candidate prompt
version being run through `core.learning.prompt_regression` before it is
allowed to become active (see `core.learning.prompt_optimizer`)."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["regression_results"] = loads(item["regression_results"], [])
    item["regression_pass"] = bool(item["regression_pass"])
    return item


class PromptEvaluationsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        prompt_version_id: str,
        baseline_version_id: str | None,
        regression_pass: bool,
        regression_results: list[dict[str, Any]],
        verdict: str,
    ) -> dict[str, Any]:
        eval_id = new_id("prompteval")
        await self._db.execute(
            """
            INSERT INTO prompt_evaluations
                (id, prompt_version_id, baseline_version_id, regression_pass,
                 regression_results, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eval_id, prompt_version_id, baseline_version_id, 1 if regression_pass else 0,
                dumps(regression_results), verdict, utc_now().isoformat(),
            ),
        )
        row = await self._db.fetch_one("SELECT * FROM prompt_evaluations WHERE id = ?", (eval_id,))
        assert row is not None
        return _row_to_dict(row)

    async def list_for_prompt_version(self, prompt_version_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompt_evaluations WHERE prompt_version_id = ? ORDER BY created_at DESC",
            (prompt_version_id,),
        )
        return [_row_to_dict(row) for row in rows]
