"""Repository for the `prompt_versions` table.

Stage 1/2 used this table for one thing: an agent's system prompt, keyed by
`agent_id`, at most one active version at a time. Stage 3 generalizes the
same table to hold every mutable prompt type (`PromptType`: core, agent,
planner, router, verifier, reflection, synthesizer) keyed by a generic
`owner_key` (equal to `agent_id` for agent prompts, a fixed string like
"planner" or "core" for the others) -- the original agent-keyed methods
(`get_active`, `list_for_agent`, `create_version`, `seed_default`) are kept
working unchanged for backward compatibility; new `*_by_key` methods are
the Stage 3 generalization.

Creating a new version deactivates the previous one (in the same
transaction) rather than deleting it -- history is kept so execution
outcomes can be correlated with which prompt version was live, and so a
prompt can be rolled back. A `prompt_type=="core"` row can only be created
with `origin="user"` -- see `core.learning.core_prompt` for why.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.learning.models import PROTECTED_PROMPT_TYPES, PromptType
from core.utils.errors import ImmutablePolicyError, NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = loads(item["metadata"], {})
    item["active"] = bool(item["active"])
    item["protected"] = bool(item.get("protected", 0))
    return item


class PromptVersionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- Stage 1/2 agent-keyed API (unchanged) --------------------------

    async def get_active(self, agent_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompt_versions WHERE agent_id = ? AND active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (agent_id,),
        )
        return _row_to_dict(row) if row else None

    async def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompt_versions WHERE agent_id = ? ORDER BY version DESC",
            (agent_id,),
        )
        return [_row_to_dict(row) for row in rows]

    async def create_version(
        self, agent_id: str, name: str, content: str, *, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self.create_version_by_key(
            owner_key=agent_id, name=name, content=content, agent_id=agent_id,
            prompt_type=PromptType.AGENT.value, metadata=metadata,
        )

    async def seed_default(self, agent_id: str, name: str, content: str) -> None:
        """Create the initial version for an agent only if it has none yet."""
        existing = await self.get_active(agent_id)
        if existing is not None:
            return
        await self.create_version(agent_id, name, content)

    # -- Stage 3 generic (owner_key-keyed) API --------------------------

    async def get_active_by_key(self, owner_key: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompt_versions WHERE owner_key = ? AND active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (owner_key,),
        )
        return _row_to_dict(row) if row else None

    async def list_by_key(self, owner_key: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompt_versions WHERE owner_key = ? ORDER BY version DESC",
            (owner_key,),
        )
        return [_row_to_dict(row) for row in rows]

    async def get(self, prompt_version_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompt_versions WHERE id = ?", (prompt_version_id,)
        )
        return _row_to_dict(row) if row else None

    async def create_version_by_key(
        self,
        *,
        owner_key: str,
        name: str,
        content: str,
        prompt_type: str = PromptType.AGENT.value,
        agent_id: str | None = None,
        author: str = "system",
        origin: str = "seed",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = await self.get_active_by_key(owner_key)

        # A protected prompt (the Core Prompt) may be *created* once, at
        # first-run seeding (`current is None`) -- but once it exists, only
        # an explicit user/administrative action may replace it with a new
        # version. This is what "não evolui automaticamente" means in
        # practice: initialization is not the same thing as mutation.
        if (
            current is not None
            and prompt_type in {t.value for t in PROTECTED_PROMPT_TYPES}
            and origin != "user"
        ):
            raise ImmutablePolicyError(
                f"Prompt type '{prompt_type}' is protected: a new version can only be "
                "created by an explicit user/administrative action (origin='user'), "
                f"not by '{origin}'.",
            )

        next_version = (current["version"] + 1) if current else 1

        async with self._db.transaction() as conn:
            if current:
                await conn.execute(
                    "UPDATE prompt_versions SET active = 0 WHERE id = ?", (current["id"],)
                )
            prompt_id = new_id("prompt")
            await conn.execute(
                """
                INSERT INTO prompt_versions (id, agent_id, name, version, content, metadata,
                                              created_at, active, prompt_type, owner_key,
                                              author, origin, reason, previous_version_id,
                                              protected)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt_id, agent_id, name, next_version, content, dumps(metadata or {}),
                    utc_now().isoformat(), prompt_type, owner_key, author, origin, reason,
                    current["id"] if current else None,
                    1 if prompt_type in {t.value for t in PROTECTED_PROMPT_TYPES} else 0,
                ),
            )

        row = await self._db.fetch_one("SELECT * FROM prompt_versions WHERE id = ?", (prompt_id,))
        assert row is not None
        return _row_to_dict(row)

    async def seed_by_key(
        self, owner_key: str, *, name: str, content: str, prompt_type: str, agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create the initial version for a key only if it has none yet."""
        existing = await self.get_active_by_key(owner_key)
        if existing is not None:
            return existing
        return await self.create_version_by_key(
            owner_key=owner_key, name=name, content=content, prompt_type=prompt_type,
            agent_id=agent_id, author="system", origin="seed", reason="initial seed",
        )

    async def rollback_to(self, owner_key: str, target_version_id: str, *, reason: str) -> dict[str, Any]:
        """Activate a previous version again, recorded as a new version so
        history stays append-only (rollback never rewrites the past)."""
        target = await self.get(target_version_id)
        if target is None or target["owner_key"] != owner_key:
            raise NotFoundError(f"Prompt version '{target_version_id}' not found for '{owner_key}'.")
        return await self.create_version_by_key(
            owner_key=owner_key, name=target["name"], content=target["content"],
            prompt_type=target["prompt_type"], agent_id=target["agent_id"],
            author="user", origin="rollback", reason=reason,
        )

    async def list_all_active(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM prompt_versions WHERE active = 1")
        return [_row_to_dict(row) for row in rows]
