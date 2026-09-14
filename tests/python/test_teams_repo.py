from __future__ import annotations

import pytest
from core.agents.models import Agent
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.teams_repo import TeamsRepository
from core.projects.models import ProjectCreate
from core.teams.models import TeamCreate, TeamUpdate
from core.utils.errors import NotFoundError


async def test_create_and_get_team(tmp_db: Database) -> None:
    repo = TeamsRepository(tmp_db)
    team = await repo.create(TeamCreate(name="AgentMash Core", description="The core team."))
    loaded = await repo.get(team.id)
    assert loaded is not None
    assert loaded.name == "AgentMash Core"
    assert loaded.project_id is None


async def test_team_scoped_to_a_project(tmp_db: Database) -> None:
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="AgentMash"))
    repo = TeamsRepository(tmp_db)
    team = await repo.create(TeamCreate(name="Core", project_id=project.id))

    all_teams = await repo.list()
    scoped_teams = await repo.list(project_id=project.id)
    assert team.id in [t.id for t in all_teams]
    assert [t.id for t in scoped_teams] == [team.id]


async def test_update_team(tmp_db: Database) -> None:
    repo = TeamsRepository(tmp_db)
    team = await repo.create(TeamCreate(name="Old Name"))
    updated = await repo.update(team.id, TeamUpdate(name="New Name"))
    assert updated.name == "New Name"


async def test_delete_team(tmp_db: Database) -> None:
    repo = TeamsRepository(tmp_db)
    team = await repo.create(TeamCreate(name="Temp"))
    await repo.delete(team.id)
    assert await repo.get(team.id) is None


async def test_get_missing_team_raises(tmp_db: Database) -> None:
    repo = TeamsRepository(tmp_db)
    with pytest.raises(NotFoundError):
        await repo.get_or_raise("team_missing")


async def test_agent_membership_is_many_to_many(tmp_db: Database) -> None:
    agents_repo = AgentsRepository(tmp_db)
    await agents_repo.upsert(Agent(id="agent_atlas", name="Atlas", provider="claude_code_cli"))
    await agents_repo.upsert(Agent(id="agent_forge", name="Forge", provider="codex_cli"))

    teams_repo = TeamsRepository(tmp_db)
    team_a = await teams_repo.create(TeamCreate(name="Team A"))
    team_b = await teams_repo.create(TeamCreate(name="Team B"))

    await teams_repo.add_agent(team_a.id, "agent_atlas")
    await teams_repo.add_agent(team_a.id, "agent_forge")
    await teams_repo.add_agent(team_b.id, "agent_atlas")

    assert set(await teams_repo.list_agent_ids(team_a.id)) == {"agent_atlas", "agent_forge"}
    assert set(await teams_repo.list_team_ids_for_agent("agent_atlas")) == {team_a.id, team_b.id}

    await teams_repo.remove_agent(team_a.id, "agent_forge")
    assert await teams_repo.list_agent_ids(team_a.id) == ["agent_atlas"]


async def test_adding_the_same_agent_twice_is_idempotent(tmp_db: Database) -> None:
    agents_repo = AgentsRepository(tmp_db)
    await agents_repo.upsert(Agent(id="agent_atlas", name="Atlas", provider="claude_code_cli"))
    teams_repo = TeamsRepository(tmp_db)
    team = await teams_repo.create(TeamCreate(name="Team A"))

    await teams_repo.add_agent(team.id, "agent_atlas")
    await teams_repo.add_agent(team.id, "agent_atlas")

    assert await teams_repo.list_agent_ids(team.id) == ["agent_atlas"]
