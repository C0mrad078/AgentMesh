"""Repository for the `execution_steps` table.

Each row is either a fixed pipeline *phase* (intent analysis, planning,
routing, execution, verification, aggregation -- `kind="phase"`) or an
individual unit of *work* dispatched to an agent within the execution phase
(`kind="work"`). Both share the same table so the executions page can render
one linear timeline.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.orchestrator.models import StepStatus
from core.utils.ids import new_id
from core.utils.time import utc_now


class ExecutionStepRecord:
    def __init__(self, row: aiosqlite.Row) -> None:
        self.id: str = row["id"]
        self.execution_id: str = row["execution_id"]
        self.step_index: int = row["step_index"]
        self.name: str = row["name"]
        self.kind: str = row["kind"]
        self.agent_id: str | None = row["agent_id"]
        self.provider: str | None = row["provider"]
        self.status = StepStatus(row["status"])
        self.input: dict[str, Any] = loads(row["input"], {})
        self.output: dict[str, Any] | None = loads(row["output"], None) if row["output"] else None
        self.error: dict[str, Any] | None = loads(row["error"], None) if row["error"] else None
        self.attempt: int = row["attempt"]
        self.started_at: str | None = row["started_at"]
        self.completed_at: str | None = row["completed_at"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_index": self.step_index,
            "name": self.name,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "provider": self.provider,
            "status": self.status.value,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "attempt": self.attempt,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class ExecutionStepsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        execution_id: str,
        step_index: int,
        name: str,
        kind: str,
        agent_id: str | None = None,
        provider: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionStepRecord:
        step_id = new_id("estep")
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO execution_steps (id, execution_id, step_index, name, kind, agent_id,
                                          provider, status, input, output, error, attempt,
                                          started_at, completed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 1, ?, NULL, ?, ?)
            """,
            (
                step_id, execution_id, step_index, name, kind, agent_id, provider,
                StepStatus.RUNNING.value, dumps(input_data or {}), now, now, now,
            ),
        )
        return await self.get_or_raise(step_id)

    async def get(self, step_id: str) -> ExecutionStepRecord | None:
        row = await self._db.fetch_one("SELECT * FROM execution_steps WHERE id = ?", (step_id,))
        return ExecutionStepRecord(row) if row else None

    async def get_or_raise(self, step_id: str) -> ExecutionStepRecord:
        record = await self.get(step_id)
        if record is None:
            raise LookupError(f"Execution step '{step_id}' not found.")
        return record

    async def list_for_execution(self, execution_id: str) -> list[ExecutionStepRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM execution_steps WHERE execution_id = ? ORDER BY step_index ASC",
            (execution_id,),
        )
        return [ExecutionStepRecord(row) for row in rows]

    async def complete(
        self,
        step_id: str,
        status: StepStatus,
        *,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        attempt: int | None = None,
    ) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            UPDATE execution_steps
            SET status = ?, output = ?, error = ?, attempt = COALESCE(?, attempt),
                completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                dumps(output) if output is not None else None,
                dumps(error) if error is not None else None,
                attempt,
                now,
                now,
                step_id,
            ),
        )
