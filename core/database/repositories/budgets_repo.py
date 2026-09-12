"""Repository for the `budgets` table. Stage 2 only has a single "global"
scope row; per-project budgets are a natural, additive extension the schema
already leaves room for (`scope` is a free column, not an enum column)."""

from __future__ import annotations

from core.database.connection import Database
from core.orchestrator.budget import BudgetLimits
from core.utils.ids import new_id
from core.utils.time import utc_now

_GLOBAL_SCOPE = "global"


class BudgetsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_global_limits(self) -> BudgetLimits:
        row = await self._db.fetch_one("SELECT * FROM budgets WHERE scope = ?", (_GLOBAL_SCOPE,))
        if row is None:
            return BudgetLimits()
        return BudgetLimits(
            max_per_execution_usd=row["max_per_execution_usd"],
            daily_limit_usd=row["daily_limit_usd"],
            monthly_limit_usd=row["monthly_limit_usd"],
            soft_limit_ratio=row["soft_limit_ratio"],
        )

    async def set_global_limits(self, limits: BudgetLimits) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO budgets
                (id, scope, max_per_execution_usd, daily_limit_usd, monthly_limit_usd,
                 soft_limit_ratio, currency, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'USD', ?)
            ON CONFLICT(scope) DO UPDATE SET
                max_per_execution_usd = excluded.max_per_execution_usd,
                daily_limit_usd = excluded.daily_limit_usd,
                monthly_limit_usd = excluded.monthly_limit_usd,
                soft_limit_ratio = excluded.soft_limit_ratio,
                updated_at = excluded.updated_at
            """,
            (
                new_id("budget"), _GLOBAL_SCOPE, limits.max_per_execution_usd,
                limits.daily_limit_usd, limits.monthly_limit_usd, limits.soft_limit_ratio, now,
            ),
        )
