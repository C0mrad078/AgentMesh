"""Repository for the `agents` table.

Stage 1's routing decisions are made against the in-memory
`core.agents.registry.AgentRegistry`, but agents are also persisted here so
the desktop agent panel has a durable source to read from and so a future
stage can manage agents (create/edit/disable) without another schema
change.
"""

from __future__ import annotations

import aiosqlite

from core.agents.models import Agent, AgentPermissions
from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.time import utc_now


def _row_to_agent(row: aiosqlite.Row) -> Agent:
    return Agent(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        provider=row["provider"],
        model=row["model"],
        system_prompt=row["system_prompt"],
        capabilities=loads(row["capabilities"], []),
        tools=loads(row["tools"], []),
        permissions=AgentPermissions(**loads(row["permissions"], {})),
        config=loads(row["config"], {}),
        active=bool(row["active"]),
    )


class AgentsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, agent: Agent) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO agents (id, name, description, provider, model, system_prompt,
                                 capabilities, tools, permissions, config, active,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, description = excluded.description,
                provider = excluded.provider, model = excluded.model,
                system_prompt = excluded.system_prompt, capabilities = excluded.capabilities,
                tools = excluded.tools, permissions = excluded.permissions,
                config = excluded.config, active = excluded.active, updated_at = excluded.updated_at
            """,
            (
                agent.id, agent.name, agent.description, agent.provider, agent.model,
                agent.system_prompt, dumps([c.model_dump() for c in agent.capabilities]),
                dumps(agent.tools), dumps(agent.permissions.model_dump()), dumps(agent.config),
                int(agent.active), now, now,
            ),
        )

    async def seed_defaults(self, agents: list[Agent]) -> None:
        for agent in agents:
            await self.upsert(agent)

    async def list(self, *, only_active: bool = True) -> list[Agent]:
        if only_active:
            rows = await self._db.fetch_all("SELECT * FROM agents WHERE active = 1 ORDER BY name")
        else:
            rows = await self._db.fetch_all("SELECT * FROM agents ORDER BY name")
        return [_row_to_agent(row) for row in rows]

    async def get(self, agent_id: str) -> Agent | None:
        row = await self._db.fetch_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
        return _row_to_agent(row) if row else None
