"""Repository for the `agents` table.

Stage 1's routing decisions are made against the in-memory
`core.agents.registry.AgentRegistry`, but agents are also persisted here so
the desktop agent panel has a durable source to read from and so a future
stage can manage agents (create/edit/disable) without another schema
change.
"""

from __future__ import annotations

import aiosqlite

from core.agents.models import Agent, AgentCreate, AgentPermissions, AgentStatus, AgentUpdate
from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.runtime.execution_backend import ExecutionBackendType
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
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
        preferred_provider=row["preferred_provider"],
        fallback_providers=loads(row["fallback_providers"], []),
        role=row["role"],
        avatar=row["avatar"],
        status=AgentStatus(row["status"]),
        preferred_backend=ExecutionBackendType(row["preferred_backend"]) if row["preferred_backend"] else None,
        fallback_backend=ExecutionBackendType(row["fallback_backend"]) if row["fallback_backend"] else None,
        memory_profile=loads(row["memory_profile"], {}),
        project_id=row["project_id"],
        visual_profile=loads(row["visual_profile"], {}),
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
                                 preferred_provider, fallback_providers,
                                 role, avatar, status, preferred_backend, fallback_backend, memory_profile,
                                 project_id, visual_profile,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, description = excluded.description,
                provider = excluded.provider, model = excluded.model,
                system_prompt = excluded.system_prompt, capabilities = excluded.capabilities,
                tools = excluded.tools, permissions = excluded.permissions,
                config = excluded.config, active = excluded.active,
                preferred_provider = excluded.preferred_provider,
                fallback_providers = excluded.fallback_providers,
                role = excluded.role, avatar = excluded.avatar, status = excluded.status,
                preferred_backend = excluded.preferred_backend, fallback_backend = excluded.fallback_backend,
                memory_profile = excluded.memory_profile, project_id = excluded.project_id,
                visual_profile = excluded.visual_profile, updated_at = excluded.updated_at
            """,
            (
                agent.id, agent.name, agent.description, agent.provider, agent.model,
                agent.system_prompt, dumps([c.model_dump() for c in agent.capabilities]),
                dumps(agent.tools), dumps(agent.permissions.model_dump()), dumps(agent.config),
                int(agent.active), agent.preferred_provider, dumps(agent.fallback_providers),
                agent.role, agent.avatar, agent.status.value,
                agent.preferred_backend.value if agent.preferred_backend else None,
                agent.fallback_backend.value if agent.fallback_backend else None,
                dumps(agent.memory_profile), agent.project_id, dumps(agent.visual_profile), now, now,
            ),
        )

    async def seed_defaults(self, agents: list[Agent]) -> None:
        for agent in agents:
            if await self.get(agent.id) is None:
                await self.upsert(agent)

    async def create(self, data: AgentCreate) -> Agent:
        agent = Agent(
            id=new_id("agent"), name=data.name, role=data.role, description=data.description,
            provider=data.provider, model=data.model, capabilities=data.capabilities,
            preferred_backend=data.preferred_backend, fallback_backend=data.fallback_backend,
            project_id=data.project_id, visual_profile=data.visual_profile,
        )
        await self.upsert(agent)
        return await self.get_or_raise(agent.id)

    async def update(self, agent_id: str, data: AgentUpdate) -> Agent:
        current = await self.get_or_raise(agent_id)
        updated = current.model_copy(
            update={
                k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None
                or k in {"project_id"}  # project_id: None is a real, meaningful "unassign" value
            }
        )
        await self.upsert(updated)
        return await self.get_or_raise(agent_id)

    async def list_by_project(self, project_id: str) -> list[Agent]:
        rows = await self._db.fetch_all(
            "SELECT * FROM agents WHERE project_id = ? ORDER BY name", (project_id,)
        )
        return [_row_to_agent(row) for row in rows]

    async def get(self, agent_id: str) -> Agent | None:
        row = await self._db.fetch_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
        return _row_to_agent(row) if row else None

    async def get_or_raise(self, agent_id: str) -> Agent:
        agent = await self.get(agent_id)
        if agent is None:
            raise NotFoundError(f"Agent '{agent_id}' not found.")
        return agent

    # `list` is defined last in the class body so its name never shadows
    # the builtin `list[...]` used in this file's other method
    # annotations under `from __future__ import annotations` -- see the
    # identical fix in `TeamsRepository`.
    async def list(self, *, only_active: bool = True) -> list[Agent]:
        if only_active:
            rows = await self._db.fetch_all("SELECT * FROM agents WHERE active = 1 ORDER BY name")
        else:
            rows = await self._db.fetch_all("SELECT * FROM agents ORDER BY name")
        return [_row_to_agent(row) for row in rows]
