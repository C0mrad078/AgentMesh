"""Repository for `model_performance` -- Layer 5, "Model Performance Knowledge".

One row per (provider, model, agent_id, task_category, risk) dimension
tuple. Updated incrementally after every execution rather than recomputed
from raw `usage_metrics` on every Router call, so routing stays cheap. A
capped, most-recent-N sample of latencies is kept for p50/p95 -- exact
percentiles are not the point here, a reasonable estimate is.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now

_MAX_LATENCY_SAMPLES = 200


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["latency_samples"] = loads(item["latency_samples"], [])
    return item


class ModelPerformanceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(
        self, *, provider: str, model: str, agent_id: str, task_category: str, risk: str,
    ) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM model_performance WHERE provider = ? AND model = ? AND agent_id = ? "
            "AND task_category = ? AND risk = ?",
            (provider, model, agent_id, task_category, risk),
        )
        return _row_to_dict(row) if row else None

    async def record_outcome(
        self,
        *,
        provider: str,
        model: str,
        agent_id: str,
        task_category: str,
        risk: str,
        success: bool,
        verified_success: bool,
        retried: bool,
        review_rejected: bool,
        latency_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        iterations: int,
    ) -> dict[str, Any]:
        existing = await self.get(
            provider=provider, model=model, agent_id=agent_id, task_category=task_category, risk=risk,
        )
        now = utc_now().isoformat()
        if existing is None:
            row_id = new_id("modelperf")
            samples = [latency_seconds]
            await self._db.execute(
                """
                INSERT INTO model_performance
                    (id, provider, model, agent_id, task_category, risk, executions, successes,
                     verified_successes, failures, retries, review_rejections,
                     total_latency_seconds, total_input_tokens, total_output_tokens,
                     total_cost_usd, total_iterations, latency_samples, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id, provider, model, agent_id, task_category, risk,
                    1 if success else 0, 1 if verified_success else 0, 0 if success else 1,
                    1 if retried else 0, 1 if review_rejected else 0, latency_seconds,
                    input_tokens, output_tokens, cost_usd, iterations, dumps(samples), now,
                ),
            )
        else:
            samples = [*existing["latency_samples"], latency_seconds][-_MAX_LATENCY_SAMPLES:]
            await self._db.execute(
                """
                UPDATE model_performance
                SET executions = executions + 1,
                    successes = successes + ?,
                    verified_successes = verified_successes + ?,
                    failures = failures + ?,
                    retries = retries + ?,
                    review_rejections = review_rejections + ?,
                    total_latency_seconds = total_latency_seconds + ?,
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    total_cost_usd = total_cost_usd + ?,
                    total_iterations = total_iterations + ?,
                    latency_samples = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if success else 0, 1 if verified_success else 0, 0 if success else 1,
                    1 if retried else 0, 1 if review_rejected else 0, latency_seconds,
                    input_tokens, output_tokens, cost_usd, iterations, dumps(samples), now,
                    existing["id"],
                ),
            )
        row = await self.get(
            provider=provider, model=model, agent_id=agent_id, task_category=task_category, risk=risk,
        )
        assert row is not None
        return row

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM model_performance ORDER BY executions DESC")
        return [_row_to_dict(row) for row in rows]

    async def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM model_performance WHERE agent_id = ? ORDER BY executions DESC", (agent_id,)
        )
        return [_row_to_dict(row) for row in rows]
