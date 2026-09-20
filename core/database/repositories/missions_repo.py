"""Mission persistence. Trigger-written events are atomic with each entity mutation.

Events are immutable invalidations of durable materialized entities. A snapshot is
read under one SQLite SELECT transaction boundary and ordered by the event cursor.
"""
from __future__ import annotations

import asyncio
import builtins
import json
from typing import TypeVar

from pydantic import BaseModel

from core.database.connection import Database
from core.database.repositories.sessions_repo import SessionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.missions.models import (
    AgentMessage,
    Artifact,
    Assignment,
    Instruction,
    Mission,
    MissionCommand,
    MissionEvent,
    MissionPlan,
    MissionSnapshot,
    Review,
)
from core.utils.errors import NotFoundError, ValidationError

T = TypeVar('T', bound=BaseModel)
TABLES: dict[type[BaseModel], str] = {
    Mission: 'missions', MissionPlan: 'mission_plans', Assignment: 'mission_assignments',
    AgentMessage: 'agent_messages', Artifact: 'mission_artifacts', Review: 'mission_reviews',
    Instruction: 'mission_instructions',
}
COLUMNS: dict[type[BaseModel], tuple[str, ...]] = {
    Mission: ('project_id',), MissionPlan: ('mission_id', 'leader_session_id', 'version'),
    Assignment: ('mission_id', 'task_id', 'agent_id', 'session_id'),
    AgentMessage: ('mission_id', 'task_id', 'from_session_id', 'to_session_id', 'reply_to'),
    Artifact: ('mission_id', 'task_id', 'session_id'),
    Review: ('mission_id', 'task_id', 'reviewer_session_id', 'worker_session_id'),
    Instruction: ('mission_id',),
}


class MissionsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.lock = asyncio.Lock()
        self.sessions = SessionsRepository(db)
        self.tasks = TasksRepository(db)

    async def put(self, value: Mission | MissionPlan | Assignment | AgentMessage | Artifact | Review | Instruction, *, command_id: str | None = None) -> None:
        cls = type(value)
        table = TABLES[cls]
        columns = ('id', *COLUMNS[cls], 'data')
        params = [getattr(value, c) for c in columns[:-1]] + [value.model_dump_json()]
        if cls is Mission and command_id is not None:
            columns += ('command_id',)
            params.append(command_id)
        if cls is Mission and command_id is None:
            await self.db.execute('UPDATE missions SET data=? WHERE id=?',
                                  (value.model_dump_json(), value.id))
            return
        placeholders = ','.join('?' for _ in columns)
        await self.db.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
            'ON CONFLICT(id) DO UPDATE SET data=excluded.data', tuple(params),
        )

    async def get(self, cls: type[T], entity_id: str) -> T:
        row = await self.db.fetch_one(f'SELECT data FROM {TABLES[cls]} WHERE id=?', (entity_id,))
        if row is None:
            raise NotFoundError(f'{cls.__name__} not found: {entity_id}')
        return cls.model_validate_json(row['data'])

    async def list(self, cls: type[T], mission_id: str) -> builtins.list[T]:
        rows = await self.db.fetch_all(
            f'SELECT data FROM {TABLES[cls]} WHERE mission_id=? ORDER BY rowid', (mission_id,))
        return [cls.model_validate_json(row['data']) for row in rows]

    async def missions(self, project_id: str | None = None) -> builtins.list[Mission]:
        rows = await self.db.fetch_all(
            'SELECT data FROM missions WHERE (? IS NULL OR project_id=?) ORDER BY rowid DESC',
            (project_id, project_id))
        return [Mission.model_validate_json(row['data']) for row in rows]

    async def by_command(self, command_id: str) -> Mission | None:
        row = await self.db.fetch_one('SELECT data FROM missions WHERE command_id=?', (command_id,))
        return Mission.model_validate_json(row['data']) if row else None

    async def claim_command(self, command: MissionCommand) -> bool:
        row = await self.db.fetch_one('SELECT data FROM mission_commands WHERE id=?', (command.command_id,))
        if row:
            if row['data'] != command.model_dump_json():
                raise ValidationError('Command id already used for different input')
            return False
        await self.db.execute('INSERT INTO mission_commands(id,mission_id,data) VALUES(?,?,?)',
                              (command.command_id, command.mission_id, command.model_dump_json()))
        return True

    async def finish_command(self, command_id: str, *, failed: bool = False) -> None:
        await self.db.execute('UPDATE mission_commands SET status=? WHERE id=?',
                              ('failed' if failed else 'completed', command_id))

    async def link(self, kind: str, mission_id: str, entity_id: str) -> None:
        if kind not in ('task', 'session'):
            raise ValueError('Unsupported link')
        await self.db.execute(
            f'INSERT INTO mission_{kind}_links({kind}_id,mission_id) VALUES(?,?)',
            (entity_id, mission_id))

    async def belongs(self, kind: str, mission_id: str, entity_id: str) -> None:
        if kind not in ('task', 'session'):
            raise ValueError('Unsupported link')
        row = await self.db.fetch_one(
            f'SELECT mission_id FROM mission_{kind}_links WHERE {kind}_id=?', (entity_id,))
        if not row or row['mission_id'] != mission_id:
            raise ValidationError(f'{kind} does not belong to this mission')

    async def events(self, mission_id: str, after: int = 0) -> builtins.list[MissionEvent]:
        rows = await self.db.fetch_all(
            'SELECT * FROM mission_events WHERE mission_id=? AND sequence>? ORDER BY sequence',
            (mission_id, after))
        return [MissionEvent.model_validate({**dict(row), 'record': json.loads(row['record'])}) for row in rows]

    async def snapshot(self, mission_id: str) -> MissionSnapshot:
        # Retry if a writer advanced the cursor while we assembled the materialization.
        while True:
            events = await self.events(mission_id)
            mission = await self.get(Mission, mission_id)
            task_rows = await self.db.fetch_all(
                'SELECT task_id FROM mission_task_links WHERE mission_id=? ORDER BY rowid', (mission_id,))
            session_rows = await self.db.fetch_all(
                'SELECT session_id FROM mission_session_links WHERE mission_id=? ORDER BY rowid', (mission_id,))
            snapshot = MissionSnapshot(
                mission=mission, plans=await self.list(MissionPlan, mission_id),
                tasks=[await self.tasks.get_or_raise(r['task_id']) for r in task_rows],
                sessions=[await self.sessions.get_or_raise(r['session_id']) for r in session_rows],
                assignments=await self.list(Assignment, mission_id),
                messages=await self.list(AgentMessage, mission_id),
                artifacts=await self.list(Artifact, mission_id), reviews=await self.list(Review, mission_id),
                instructions=await self.list(Instruction, mission_id), events=events)
            from core.database.repositories.parallel_repo import ParallelRepository
            parallel = ParallelRepository(self.db)
            snapshot = snapshot.model_copy(update={
                "worktrees": await parallel.list_worktrees(mission_id),
                "forecasts": await parallel.forecasts(mission_id),
                "integrations": await parallel.integrations(mission_id),
                "quality_gates": await parallel.gates(mission_id),
                "approvals": await parallel.approvals(mission_id),
            })
            latest = await self.events(mission_id, events[-1].sequence if events else 0)
            if not latest:
                return snapshot

    async def lease(self, path: str, mission_id: str) -> bool:
        async with self.lock:
            return await self._lease(path, mission_id)

    async def _lease(self, path: str, mission_id: str) -> bool:
        import os
        path = os.path.normcase(path).rstrip('/\\')
        rows = await self.db.fetch_all('SELECT path,mission_id FROM mission_workspace_leases')
        from pathlib import Path
        for row in rows:
            if row['mission_id'] != mission_id and (
                    Path(path).is_relative_to(row['path']) or Path(row['path']).is_relative_to(path)):
                return False
        await self.db.execute(
            'INSERT OR IGNORE INTO mission_workspace_leases(path,mission_id) VALUES(?,?)', (path, mission_id))
        lease_row = await self.db.fetch_one('SELECT mission_id FROM mission_workspace_leases WHERE path=?', (path,))
        return bool(lease_row and lease_row['mission_id'] == mission_id)

    async def release(self, mission_id: str) -> None:
        await self.db.execute('DELETE FROM mission_workspace_leases WHERE mission_id=?', (mission_id,))

    async def workspace_busy(self, path: str) -> bool:
        from pathlib import Path
        rows = await self.db.fetch_all('SELECT path FROM mission_workspace_leases')
        return any(Path(path).is_relative_to(r['path']) or Path(r['path']).is_relative_to(path) for r in rows)
