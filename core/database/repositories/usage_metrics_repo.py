"""Repository for the `usage_metrics` table.

This is the primary data source for:

  * the cost panel (`execution.get` / a dedicated cost summary);
  * `BudgetManager`'s daily/monthly spend checks;
  * Stage 3's Reflection Engine (which model/agent/provider combination
    tends to succeed, how long it takes, how often it needs a retry).
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class UsageMetricsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        execution_id: str,
        step_id: str | None,
        agent_id: str | None,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        duration_seconds: float,
        success: bool,
        retries: int,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO usage_metrics
                (id, execution_id, step_id, agent_id, provider, model, input_tokens,
                 output_tokens, estimated_cost_usd, duration_seconds, success, retries,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("usage"), execution_id, step_id, agent_id, provider, model,
                input_tokens, output_tokens, estimated_cost_usd, duration_seconds,
                int(success), retries, utc_now().isoformat(),
            ),
        )

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM usage_metrics WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        return [dict(row) for row in rows]

    async def total_cost_for_execution(self, execution_id: str) -> float:
        row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total FROM usage_metrics "
            "WHERE execution_id = ?",
            (execution_id,),
        )
        return float(row["total"]) if row else 0.0

    async def total_cost_since(self, since_iso: str) -> float:
        row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total FROM usage_metrics "
            "WHERE created_at >= ?",
            (since_iso,),
        )
        return float(row["total"]) if row else 0.0
