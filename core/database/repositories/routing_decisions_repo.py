"""Repository for the `routing_decisions` table.

Stores the Router's short justification for each step ("Claude Architect
selecionado porque a etapa envolve arquitetura e possui risco alto") -- a
summary of the decision, never a model's private reasoning.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.orchestrator.models import RoutingDecision
from core.utils.ids import new_id
from core.utils.time import utc_now


class RoutingDecisionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, execution_id: str, decision: RoutingDecision) -> None:
        await self._db.execute(
            """
            INSERT INTO routing_decisions
                (id, execution_id, step_id, agent_id, provider, model, score, reason,
                 alternatives, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("route"), execution_id, decision.step_id, decision.agent_id,
                decision.provider, decision.model, decision.score, decision.reason,
                dumps(list(decision.alternatives)), utc_now().isoformat(),
            ),
        )

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM routing_decisions WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        results = []
        for row in rows:
            item = dict(row)
            item["alternatives"] = loads(item["alternatives"], [])
            results.append(item)
        return results
