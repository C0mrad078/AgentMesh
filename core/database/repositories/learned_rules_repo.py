"""Repository for `learned_rules` -- the Stage 1 placeholder table, extended
(never replaced) into the full Stage 3 rule lifecycle:

    candidate -> observing -> active -> deprecated
                           \\-> rejected
    (any non-terminal state) -> archived

`origin` distinguishes a rule the Learning Engine promoted from one the
user wrote by hand (`core.learning.rule_resolver.RuleResolver` treats user
rules and pinned rules with higher precedence -- see the module docstring
there for the full hierarchy).
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["condition"] = loads(item["condition"], {})
    item["action"] = loads(item["action"], {})
    item["distinct_projects"] = loads(item["distinct_projects"], [])
    item["active"] = bool(item["active"])
    item["pinned"] = bool(item["pinned"])
    return item


class LearnedRulesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        title: str,
        category: str,
        rule_text: str,
        scope_type: str,
        scope_value: str | None,
        priority: str,
        confidence: float,
        observations: int,
        successes: int,
        failures: int,
        distinct_projects: list[str],
        status: str,
        origin: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        rule_id = new_id("rule")
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO learned_rules
                (id, project_id, rule_type, condition, action, confidence, source, active,
                 created_at, updated_at, title, category, scope_type, scope_value, priority,
                 status, observations, successes, failures, distinct_projects, pinned,
                 last_observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                rule_id, project_id, category, dumps({}), dumps({"text": rule_text}), confidence,
                origin, 1 if status == "active" else 0, now, now, title, category, scope_type,
                scope_value, priority, status, observations, successes, failures,
                dumps(distinct_projects), now,
            ),
        )
        row = await self.get(rule_id)
        assert row is not None
        return row

    async def get(self, rule_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM learned_rules WHERE id = ?", (rule_id,))
        return _row_to_dict(row) if row else None

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM learned_rules WHERE status = ? ORDER BY confidence DESC", (status,)
        )
        return [_row_to_dict(row) for row in rows]

    async def list_active_and_pinned(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM learned_rules WHERE status = 'active' OR pinned = 1 "
            "ORDER BY confidence DESC",
        )
        return [_row_to_dict(row) for row in rows]

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM learned_rules ORDER BY updated_at DESC")
        return [_row_to_dict(row) for row in rows]

    async def update_status(self, rule_id: str, status: str) -> None:
        await self._db.execute(
            "UPDATE learned_rules SET status = ?, active = ?, updated_at = ? WHERE id = ?",
            (status, 1 if status == "active" else 0, utc_now().isoformat(), rule_id),
        )

    async def update_confidence(
        self, rule_id: str, *, confidence: float, observations: int, successes: int, failures: int,
    ) -> None:
        await self._db.execute(
            """
            UPDATE learned_rules
            SET confidence = ?, observations = ?, successes = ?, failures = ?,
                last_observed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (confidence, observations, successes, failures, utc_now().isoformat(),
             utc_now().isoformat(), rule_id),
        )

    async def update_action(self, rule_id: str, action: dict[str, Any]) -> None:
        """Overwrite the structured routing effect (see
        `core.learning.rule_resolver`) -- `create()` seeds `action` with a
        plain `{"text": rule_text}` placeholder; the Learning Engine calls
        this once it has inferred the real effect for a promoted rule."""
        await self._db.execute(
            "UPDATE learned_rules SET action = ?, updated_at = ? WHERE id = ?",
            (dumps(action), utc_now().isoformat(), rule_id),
        )

    async def set_pinned(self, rule_id: str, pinned: bool) -> None:
        await self._db.execute(
            "UPDATE learned_rules SET pinned = ?, updated_at = ? WHERE id = ?",
            (1 if pinned else 0, utc_now().isoformat(), rule_id),
        )

    async def create_user_rule(
        self,
        *,
        title: str,
        category: str,
        rule_text: str,
        scope_type: str,
        scope_value: str | None,
        priority: str,
    ) -> dict[str, Any]:
        return await self.create(
            title=title, category=category, rule_text=rule_text, scope_type=scope_type,
            scope_value=scope_value, priority=priority, confidence=1.0, observations=0,
            successes=0, failures=0, distinct_projects=[], status="active", origin="user",
        )
