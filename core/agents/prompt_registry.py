"""Prompt Registry: the single place agent system prompts are looked up.

Prompts are never hardcoded inline where an agent runs -- they are versioned
rows in `prompt_versions` (see
`core.database.repositories.prompt_versions_repo`), seeded from
`core.agents.default_prompts` on first startup. This indirection is what
Stage 3's prompt evolution/versioning/rollback will build on: a new prompt
version is a new row, the previous one is deactivated (not deleted), and
nothing about *how an agent gets its prompt* needs to change later.
"""

from __future__ import annotations

from core.agents.default_prompts import DEFAULT_PROMPTS
from core.database.repositories.prompt_versions_repo import PromptVersionsRepository
from core.utils.errors import NotFoundError


class PromptRegistry:
    def __init__(self, repository: PromptVersionsRepository) -> None:
        self._repository = repository

    async def seed_defaults(self, agent_ids: list[str]) -> None:
        for agent_id in agent_ids:
            content = DEFAULT_PROMPTS.get(agent_id)
            if content is None:
                continue
            await self._repository.seed_default(agent_id, name=f"{agent_id}_default", content=content)

    async def get_active_prompt(self, agent_id: str) -> str:
        active = await self._repository.get_active(agent_id)
        if active is None:
            raise NotFoundError(f"Agent '{agent_id}' has no active system prompt configured.")
        return active["content"]

    async def create_version(self, agent_id: str, name: str, content: str) -> dict:
        return await self._repository.create_version(agent_id, name, content)

    async def list_versions(self, agent_id: str) -> list[dict]:
        return await self._repository.list_for_agent(agent_id)
