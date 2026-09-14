from __future__ import annotations

from pathlib import Path

import pytest
from core.agents.models import Agent, AgentCreate, AgentStatus, AgentUpdate
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.projects.models import ProjectCreate
from core.runtime.execution_backend import ExecutionBackendType
from core.utils.errors import NotFoundError


async def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "agents.db")
    await db.connect()
    return db


async def test_preferred_provider_and_fallback_providers_round_trip(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(
            id="agent_test_fallback", name="Test", provider="codex_cli",
            preferred_provider="codex_cli", fallback_providers=["claude_code_cli", "openai"],
        )
        await repo.upsert(agent)

        loaded = await repo.get("agent_test_fallback")
        assert loaded is not None
        assert loaded.preferred_provider == "codex_cli"
        assert loaded.fallback_providers == ["claude_code_cli", "openai"]
        assert loaded.effective_preferred_provider == "codex_cli"
    finally:
        await db.close()


async def test_agent_without_preferred_provider_falls_back_to_the_provider_field(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(id="agent_plain", name="Plain", provider="anthropic")
        await repo.upsert(agent)

        loaded = await repo.get("agent_plain")
        assert loaded is not None
        assert loaded.preferred_provider is None
        assert loaded.fallback_providers == []
        assert loaded.effective_preferred_provider == "anthropic"
    finally:
        await db.close()


async def test_presence_and_backend_fields_round_trip(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(
            id="agent_atlas", name="Atlas", provider="claude_code_cli", role="Software Architect",
            avatar="preset_architect", status=AgentStatus.WORKING,
            preferred_backend=ExecutionBackendType.SUBSCRIPTION,
            fallback_backend=ExecutionBackendType.API,
            memory_profile={"style": "concise"},
        )
        await repo.upsert(agent)

        loaded = await repo.get("agent_atlas")
        assert loaded is not None
        assert loaded.role == "Software Architect"
        assert loaded.avatar == "preset_architect"
        assert loaded.status == AgentStatus.WORKING
        assert loaded.preferred_backend == ExecutionBackendType.SUBSCRIPTION
        assert loaded.fallback_backend == ExecutionBackendType.API
        assert loaded.memory_profile == {"style": "concise"}
    finally:
        await db.close()


async def test_presence_and_backend_fields_default_sensibly(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(id="agent_plain", name="Plain", provider="anthropic")
        await repo.upsert(agent)

        loaded = await repo.get("agent_plain")
        assert loaded is not None
        assert loaded.role == ""
        assert loaded.avatar is None
        # Nothing computes real presence yet (Phase 8) -- IDLE is the inert
        # default, not a claimed live signal. See docs/refactor-v2-plan.md §4.
        assert loaded.status == AgentStatus.IDLE
        assert loaded.preferred_backend is None
        assert loaded.fallback_backend is None
        assert loaded.memory_profile == {}
    finally:
        await db.close()


# -- AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): project
# assignment, visual profile, and the new create/update repository
# methods. --------------------------------------------------------------


async def test_create_persists_a_real_agent_with_project_assignment(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        project = await ProjectsRepository(db).create(ProjectCreate(name="AgentMash"))
        repo = AgentsRepository(db)

        agent = await repo.create(
            AgentCreate(
                name="Atlas", role="Software Architect", project_id=project.id,
                visual_profile={"preset": "gemini_ceo"},
            )
        )
        assert agent.id  # a real, generated id -- never blank
        assert agent.project_id == project.id

        reloaded = await repo.get(agent.id)
        assert reloaded is not None
        assert reloaded.name == "Atlas"
        assert reloaded.role == "Software Architect"
        assert reloaded.project_id == project.id
        assert reloaded.visual_profile == {"preset": "gemini_ceo"}
    finally:
        await db.close()


async def test_create_without_a_project_leaves_it_unassigned(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = await repo.create(AgentCreate(name="Forge"))
        assert agent.project_id is None
    finally:
        await db.close()


async def test_update_can_reassign_an_agent_to_a_different_project(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        projects_repo = ProjectsRepository(db)
        project_a = await projects_repo.create(ProjectCreate(name="AgentMash"))
        project_b = await projects_repo.create(ProjectCreate(name="NerdVerso"))
        repo = AgentsRepository(db)
        agent = await repo.create(AgentCreate(name="Pixel", project_id=project_a.id))

        moved = await repo.update(agent.id, AgentUpdate(project_id=project_b.id))
        assert moved.project_id == project_b.id
    finally:
        await db.close()


async def test_update_can_unassign_an_agent_from_its_project(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        project = await ProjectsRepository(db).create(ProjectCreate(name="AgentMash"))
        repo = AgentsRepository(db)
        agent = await repo.create(AgentCreate(name="Nova", project_id=project.id))

        unassigned = await repo.update(agent.id, AgentUpdate(project_id=None))
        assert unassigned.project_id is None
    finally:
        await db.close()


async def test_update_only_touches_fields_the_caller_actually_set(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = await repo.create(AgentCreate(name="Sentinel", role="Security Engineer", provider="mock"))

        updated = await repo.update(agent.id, AgentUpdate(active=False))
        assert updated.active is False
        assert updated.name == "Sentinel"  # untouched
        assert updated.role == "Security Engineer"  # untouched
    finally:
        await db.close()


async def test_update_missing_agent_raises(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        with pytest.raises(NotFoundError):
            await repo.update("agent_does_not_exist", AgentUpdate(name="X"))
    finally:
        await db.close()


async def test_list_by_project_scopes_correctly_across_multiple_projects(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        projects_repo = ProjectsRepository(db)
        project_a = await projects_repo.create(ProjectCreate(name="Project A"))
        project_b = await projects_repo.create(ProjectCreate(name="Project B"))
        repo = AgentsRepository(db)

        agent_a1 = await repo.create(AgentCreate(name="Agent A1", project_id=project_a.id))
        agent_a2 = await repo.create(AgentCreate(name="Agent A2", project_id=project_a.id))
        agent_b1 = await repo.create(AgentCreate(name="Agent B1", project_id=project_b.id))
        await repo.create(AgentCreate(name="Unassigned"))  # no project -- must appear in neither

        assert {a.id for a in await repo.list_by_project(project_a.id)} == {agent_a1.id, agent_a2.id}
        assert {a.id for a in await repo.list_by_project(project_b.id)} == {agent_b1.id}
    finally:
        await db.close()


async def test_agent_project_assignment_survives_a_reconnect(tmp_path: Path) -> None:
    """Simulates closing and reopening AgentMash: a fresh `Database`/
    `AgentsRepository` against the same file must still see the real
    persisted assignment -- not anything held only in memory."""
    db_path = tmp_path / "persistence.db"
    db1 = Database(db_path)
    await db1.connect()
    project = await ProjectsRepository(db1).create(ProjectCreate(name="AgentMash"))
    agent = await AgentsRepository(db1).create(AgentCreate(name="Atlas", project_id=project.id))
    await db1.close()

    db2 = Database(db_path)
    await db2.connect()
    try:
        reloaded = await AgentsRepository(db2).get(agent.id)
        assert reloaded is not None
        assert reloaded.project_id == project.id
    finally:
        await db2.close()
