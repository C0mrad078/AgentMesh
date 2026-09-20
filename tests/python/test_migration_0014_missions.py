from __future__ import annotations

import aiosqlite
import pytest
from core.agents.models import Agent
from core.database.connection import Database
from core.database.migrations import runner
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.missions_repo import MissionsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.missions.models import Mission
from core.projects.models import ProjectCreate
from core.utils.time import utc_now


@pytest.mark.parametrize('upgrade', [False, True])
async def test_mission_migration_empty_and_existing(tmp_path, monkeypatch, upgrade):
    path = tmp_path / 'upgrade.db'
    original = runner.discover_migrations
    if upgrade:
        monkeypatch.setattr(runner, 'discover_migrations', lambda: [m for m in original() if m[0] <= 13])
        old = Database(path)
        await old.connect()
        project = await ProjectsRepository(old).create(ProjectCreate(name='preserved'))
        await AgentsRepository(old).upsert(Agent(id='existing', name='User persona', provider='codex_cli', system_prompt='User instructions'))
        await old.close()
        monkeypatch.setattr(runner, 'discover_migrations', original)
    db = Database(path)
    await db.connect()
    try:
        if upgrade:
            assert (await ProjectsRepository(db).get(project.id)).name == 'preserved'
            assert (await AgentsRepository(db).get('existing')).system_prompt == 'User instructions'
        else:
            project = await ProjectsRepository(db).create(ProjectCreate(name='new'))
        assert not await db.fetch_all('PRAGMA foreign_key_check')
        assert 14 in await runner.applied_versions(db.connection)
        assert 15 in await runner.applied_versions(db.connection)
        assert 16 in await runner.applied_versions(db.connection)
        repo = MissionsRepository(db)
        mission = Mission(id='mission', project_id=project.id, request='test', created_at=utc_now(), updated_at=utc_now())
        await repo.put(mission, command_id='first')
        await repo.put(mission.model_copy(update={'status': 'analyzing'}))
        events = await repo.events(mission.id)
        assert events[0].record.status == 'draft'
        assert events[1].record.status == 'analyzing'
        assert await runner.run_migrations(db.connection) == []
    finally:
        await db.close()


async def test_failed_migration_rolls_back_ddl(tmp_path, monkeypatch):
    bad = tmp_path / '0099_bad.sql'
    bad.write_text('CREATE TABLE should_not_survive(id TEXT);\nINVALID SQL;')
    db = Database(tmp_path / 'atomic.db')
    await db.connect()
    try:
        monkeypatch.setattr(runner, 'discover_migrations', lambda: [(99, bad)])
        with pytest.raises(aiosqlite.OperationalError):
            await runner.run_migrations(db.connection)
        assert await db.fetch_one("SELECT name FROM sqlite_master WHERE name='should_not_survive'") is None
        assert 99 not in await runner.applied_versions(db.connection)
    finally:
        await db.close()
