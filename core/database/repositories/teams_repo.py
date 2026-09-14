"""Repository for the `teams` and `team_agents` tables."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.teams.models import Team, TeamCreate, TeamUpdate
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_team(row: aiosqlite.Row) -> Team:
    return Team(
        id=row["id"],
        name=row["name"],
        project_id=row["project_id"],
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class TeamsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: TeamCreate) -> Team:
        now = utc_now().isoformat()
        team_id = new_id("team")
        await self._db.execute(
            """
            INSERT INTO teams (id, name, project_id, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (team_id, data.name, data.project_id, data.description, now, now),
        )
        created = await self.get(team_id)
        if created is None:
            raise RuntimeError("Team vanished immediately after creation.")
        return created

    async def get(self, team_id: str) -> Team | None:
        row = await self._db.fetch_one("SELECT * FROM teams WHERE id = ?", (team_id,))
        return _row_to_team(row) if row else None

    async def get_or_raise(self, team_id: str) -> Team:
        team = await self.get(team_id)
        if team is None:
            raise NotFoundError(f"Team '{team_id}' not found.")
        return team

    async def update(self, team_id: str, data: TeamUpdate) -> Team:
        current = await self.get_or_raise(team_id)
        name = data.name if data.name is not None else current.name
        project_id = data.project_id if data.project_id is not None else current.project_id
        description = data.description if data.description is not None else current.description
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE teams SET name = ?, project_id = ?, description = ?, updated_at = ? WHERE id = ?",
            (name, project_id, description, now, team_id),
        )
        return await self.get_or_raise(team_id)

    async def delete(self, team_id: str) -> None:
        await self.get_or_raise(team_id)
        await self._db.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    async def add_agent(self, team_id: str, agent_id: str) -> None:
        await self.get_or_raise(team_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "INSERT INTO team_agents (team_id, agent_id, added_at) VALUES (?, ?, ?) "
            "ON CONFLICT(team_id, agent_id) DO NOTHING",
            (team_id, agent_id, now),
        )

    async def remove_agent(self, team_id: str, agent_id: str) -> None:
        await self._db.execute(
            "DELETE FROM team_agents WHERE team_id = ? AND agent_id = ?", (team_id, agent_id)
        )

    async def list_agent_ids(self, team_id: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT agent_id FROM team_agents WHERE team_id = ? ORDER BY added_at", (team_id,)
        )
        return [row["agent_id"] for row in rows]

    async def list_team_ids_for_agent(self, agent_id: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT team_id FROM team_agents WHERE agent_id = ? ORDER BY added_at", (agent_id,)
        )
        return [row["team_id"] for row in rows]

    async def list(self, *, project_id: str | None = None) -> list[Team]:
        if project_id is not None:
            rows = await self._db.fetch_all(
                "SELECT * FROM teams WHERE project_id = ? ORDER BY name", (project_id,)
            )
        else:
            rows = await self._db.fetch_all("SELECT * FROM teams ORDER BY name")
        return [_row_to_team(row) for row in rows]
