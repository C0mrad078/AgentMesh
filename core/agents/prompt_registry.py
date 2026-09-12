"""Prompt Registry: the single place every prompt in the system is looked up.

Stage 2 covered agent system prompts. Stage 3 generalizes this to every
`PromptType` (core/agent/planner/router/verifier/reflection/synthesizer),
still versioned, still never hardcoded inline where it runs. A new version
deactivates (never deletes) the previous one, and the Core Prompt can only
ever get a new version through an explicit user action -- see
`core.learning.core_prompt` and `PromptVersionsRepository`.
"""

from __future__ import annotations

from core.agents.default_prompts import DEFAULT_PROMPTS
from core.database.repositories.prompt_versions_repo import PromptVersionsRepository
from core.learning.core_prompt import CORE_PROMPT_OWNER_KEY, CORE_PROMPT_TEXT
from core.learning.models import PromptType
from core.utils.errors import NotFoundError

_DEFAULT_ORCHESTRATOR_PROMPTS: dict[str, str] = {
    "planner": (
        "You plan how to accomplish the user's goal as a small set of "
        "concrete steps. Prefer the fewest steps that fully address the "
        "goal; never add a step that does not contribute to it."
    ),
    "router": (
        "You are choosing which agent handles a step. Match capability "
        "first; only use history and cost as tie-breakers, never as a "
        "reason to pick an agent that cannot do the work."
    ),
    "verifier": (
        "You judge whether a result actually satisfies its goal using "
        "objective evidence. Deterministic checks (tests, builds, exit "
        "codes) always outweigh a model's own claim of success."
    ),
    "reflection": (
        "You analyze a completed execution using the objective evidence "
        "provided (costs, retries, tool calls, verification results) and "
        "answer the reflection questions concisely. Do not speculate "
        "beyond what the evidence supports."
    ),
    "synthesizer": (
        "You are given multiple independent candidate answers to the same "
        "goal. Pick the best one or synthesize a better one, and explain "
        "why in one or two sentences."
    ),
}


class PromptRegistry:
    def __init__(self, repository: PromptVersionsRepository) -> None:
        self._repository = repository

    async def seed_defaults(self, agent_ids: list[str]) -> None:
        for agent_id in agent_ids:
            content = DEFAULT_PROMPTS.get(agent_id)
            if content is None:
                continue
            await self._repository.seed_default(agent_id, name=f"{agent_id}_default", content=content)

    async def seed_core_and_orchestrator_prompts(self) -> None:
        await self._repository.seed_by_key(
            CORE_PROMPT_OWNER_KEY, name="core_prompt", content=CORE_PROMPT_TEXT,
            prompt_type=PromptType.CORE.value,
        )
        for key, content in _DEFAULT_ORCHESTRATOR_PROMPTS.items():
            await self._repository.seed_by_key(
                key, name=f"{key}_default", content=content, prompt_type=key,
            )

    async def get_active_prompt(self, agent_id: str) -> str:
        active = await self._repository.get_active(agent_id)
        if active is None:
            raise NotFoundError(f"Agent '{agent_id}' has no active system prompt configured.")
        return active["content"]

    async def get_by_key(self, owner_key: str) -> str:
        active = await self._repository.get_active_by_key(owner_key)
        if active is None:
            raise NotFoundError(f"'{owner_key}' has no active prompt configured.")
        return active["content"]

    async def create_version(self, agent_id: str, name: str, content: str) -> dict:
        return await self._repository.create_version(agent_id, name, content)

    async def list_versions(self, agent_id: str) -> list[dict]:
        return await self._repository.list_for_agent(agent_id)

    async def list_versions_by_key(self, owner_key: str) -> list[dict]:
        return await self._repository.list_by_key(owner_key)

    async def create_version_by_key(
        self,
        owner_key: str,
        *,
        name: str,
        content: str,
        prompt_type: str,
        agent_id: str | None = None,
        author: str,
        origin: str,
        reason: str,
    ) -> dict:
        return await self._repository.create_version_by_key(
            owner_key=owner_key, name=name, content=content, prompt_type=prompt_type,
            agent_id=agent_id, author=author, origin=origin, reason=reason,
        )

    async def rollback(self, owner_key: str, target_version_id: str, *, reason: str) -> dict:
        return await self._repository.rollback_to(owner_key, target_version_id, reason=reason)
