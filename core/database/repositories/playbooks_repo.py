"""Repository for `playbooks` and `playbook_versions` (Orchestration Playbook, Layer 2).

A playbook is keyed by `task_type` (an intent category) plus a list of
`conditions` (free-form tags such as `risk:high`, `stack:python`) that must
all be present for `PlaybookMatcher` to consider it a match. Each playbook
can have multiple versions -- the strategy itself can evolve -- with only
one active at a time, following the same append-only versioning pattern as
prompts.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _playbook_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["conditions"] = loads(item["conditions"], [])
    return item


def _version_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["strategy"] = loads(item["strategy"], [])
    item["active"] = bool(item["active"])
    return item


class PlaybooksRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_active(self, task_type: str | None = None) -> list[dict[str, Any]]:
        if task_type:
            rows = await self._db.fetch_all(
                "SELECT * FROM playbooks WHERE status = 'active' AND task_type = ?", (task_type,)
            )
        else:
            rows = await self._db.fetch_all("SELECT * FROM playbooks WHERE status = 'active'")
        return [_playbook_dict(row) for row in rows]

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM playbooks ORDER BY task_type")
        return [_playbook_dict(row) for row in rows]

    async def get(self, playbook_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM playbooks WHERE id = ?", (playbook_id,))
        return _playbook_dict(row) if row else None

    async def create(
        self, *, task_type: str, name: str, conditions: list[str], origin: str = "seed",
    ) -> dict[str, Any]:
        playbook_id = new_id("playbook")
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO playbooks (id, task_type, name, conditions, status, origin, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (playbook_id, task_type, name, dumps(conditions), origin, now, now),
        )
        row = await self.get(playbook_id)
        assert row is not None
        return row

    async def deprecate(self, playbook_id: str) -> None:
        await self._db.execute(
            "UPDATE playbooks SET status = 'deprecated', updated_at = ? WHERE id = ?",
            (utc_now().isoformat(), playbook_id),
        )


class PlaybookVersionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_active(self, playbook_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM playbook_versions WHERE playbook_id = ? AND active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (playbook_id,),
        )
        return _version_dict(row) if row else None

    async def list_for_playbook(self, playbook_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM playbook_versions WHERE playbook_id = ? ORDER BY version DESC",
            (playbook_id,),
        )
        return [_version_dict(row) for row in rows]

    async def create_version(
        self,
        playbook_id: str,
        *,
        strategy: list[dict[str, Any]],
        confidence: float,
        reason: str,
    ) -> dict[str, Any]:
        current = await self.get_active(playbook_id)
        next_version = (current["version"] + 1) if current else 1

        async with self._db.transaction() as conn:
            if current:
                await conn.execute(
                    "UPDATE playbook_versions SET active = 0 WHERE id = ?", (current["id"],)
                )
            version_id = new_id("pbver")
            await conn.execute(
                """
                INSERT INTO playbook_versions
                    (id, playbook_id, version, strategy, confidence, active, reason,
                     observations, successes, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, 0, 0, ?)
                """,
                (version_id, playbook_id, next_version, dumps(strategy), confidence, reason,
                 utc_now().isoformat()),
            )
        row = await self._db.fetch_one("SELECT * FROM playbook_versions WHERE id = ?", (version_id,))
        assert row is not None
        return _version_dict(row)

    async def record_outcome(self, version_id: str, *, success: bool) -> None:
        await self._db.execute(
            "UPDATE playbook_versions SET observations = observations + 1, "
            "successes = successes + ? WHERE id = ?",
            (1 if success else 0, version_id),
        )
